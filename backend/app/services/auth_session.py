import io
import math
import secrets
import sqlite3
import string
import time
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from PIL import Image, ImageDraw, ImageFont

from ..config import get_settings
from .site_settings import login_lock_seconds_of, login_lock_threshold_of


SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_EXEMPT_PATHS = {"/api/payment/notify"}
LOGIN_ERROR = "用户名或密码错误"


def now_ts() -> float:
    return time.time()


def make_session(db: sqlite3.Connection, user_id: str | None = None) -> sqlite3.Row:
    settings = get_settings()
    session_id = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = now_ts()
    db.execute(
        """
        INSERT INTO auth_sessions (id, user_id, csrf_token, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, user_id, csrf_token, now, now + settings.session_expire_seconds),
    )
    db.commit()
    return get_session(db, session_id)


def destroy_session(db: sqlite3.Connection, session_id: str | None) -> None:
    if not session_id:
        return
    db.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
    db.commit()


def get_session(db: sqlite3.Connection, session_id: str | None) -> sqlite3.Row | None:
    if not session_id:
        return None
    row = db.execute("SELECT * FROM auth_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    if float(row["expires_at"]) < now_ts():
        destroy_session(db, session_id)
        return None
    return row


def ensure_guest_session(request: Request, response: Response, db: sqlite3.Connection) -> sqlite3.Row:
    settings = get_settings()
    session = get_session(db, request.cookies.get(settings.session_cookie_name))
    if session is None:
        session = make_session(db)
    set_session_cookies(response, session)
    return session


def set_session_cookies(response: Response, session: sqlite3.Row) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        session["id"],
        httponly=True,
        # HTTP 生产部署必须允许显式关闭 Secure；否则浏览器不会回传会话 Cookie，
        # 验证码与登录会永远被判定为失败。HTTPS 时部署脚本会自动写入 true。
        secure=settings.session_cookie_secure,
        samesite="strict",
        max_age=settings.session_expire_seconds,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        session["csrf_token"],
        httponly=False,
        # HTTP 生产部署必须允许显式关闭 Secure；否则浏览器不会回传会话 Cookie，
        # 验证码与登录会永远被判定为失败。HTTPS 时部署脚本会自动写入 true。
        secure=settings.session_cookie_secure,
        samesite="strict",
        max_age=settings.session_expire_seconds,
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def require_csrf(request: Request, db: sqlite3.Connection) -> None:
    if request.method.upper() in SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
        return
    settings = get_settings()
    session = get_session(db, request.cookies.get(settings.session_cookie_name))
    submitted = request.headers.get("x-csrf-token")
    if session is None or not submitted or not secrets.compare_digest(submitted, session["csrf_token"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无效请求")


def generate_captcha(request: Request, response: Response, db: sqlite3.Connection) -> bytes:
    settings = get_settings()
    session = ensure_guest_session(request, response, db)
    answer = "".join(secrets.choice(string.digits) for _ in range(5))
    db.execute(
        """
        UPDATE auth_sessions
        SET captcha_answer = ?, captcha_expires_at = ?
        WHERE id = ?
        """,
        (answer, now_ts() + settings.captcha_expire_seconds, session["id"]),
    )
    db.commit()
    return render_captcha(answer)


def verify_captcha(db: sqlite3.Connection, session: sqlite3.Row | None, answer: str) -> bool:
    if session is None:
        return False
    try:
        expires_at = float(session["captcha_expires_at"] or 0)
    except (TypeError, ValueError):
        expires_at = 0
    expected = str(session["captcha_answer"] or "")
    db.execute(
        "UPDATE auth_sessions SET captcha_answer = NULL, captcha_expires_at = NULL WHERE id = ?",
        (session["id"],),
    )
    db.commit()
    return bool(expected) and expires_at >= now_ts() and secrets.compare_digest(answer.strip(), expected)


def render_captcha(answer: str) -> bytes:
    image = Image.new("RGB", (148, 48), "#f8fafc")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for _ in range(80):
        x = secrets.randbelow(image.width)
        y = secrets.randbelow(image.height)
        shade = 160 + secrets.randbelow(70)
        draw.point((x, y), fill=(shade, shade, shade))
    for index, char in enumerate(answer):
        x = 18 + index * 24 + secrets.randbelow(5)
        y = 12 + secrets.randbelow(9)
        color = (20 + secrets.randbelow(60), 60 + secrets.randbelow(80), 120 + secrets.randbelow(80))
        draw.text((x, y), char, fill=color, font=font)
    for _ in range(4):
        color = (80 + secrets.randbelow(80), 100 + secrets.randbelow(80), 130 + secrets.randbelow(80))
        draw.line(
            (
                secrets.randbelow(image.width),
                secrets.randbelow(image.height),
                secrets.randbelow(image.width),
                secrets.randbelow(image.height),
            ),
            fill=color,
            width=1,
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def failure_key(username: str) -> str:
    return username.strip().lower()


def assert_not_locked(db: sqlite3.Connection, ip_address: str, username: str) -> None:
    row = db.execute(
        "SELECT locked_until FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, failure_key(username)),
    ).fetchone()
    if row and float(row["locked_until"] or 0) > now_ts():
        # 安全修复（V-04）：锁定中返回 429 与明确的退避提示（锁定由连续失败触发，
        # 不存在「通过响应差异枚举账号」的问题），并区分于普通的密码错误 401。
        # 结构化 detail 让前端展示「账号已锁定，请 N 分钟后重试」（锁定分钟数由后端给出）。
        minutes = max(1, math.ceil((float(row["locked_until"]) - now_ts()) / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": f"账号已锁定，请 {minutes} 分钟后重试", "locked": True, "retry_after_minutes": minutes},
        )


def record_login_failure(db: sqlite3.Connection, ip_address: str, username: str) -> dict:
    """记录一次登录失败，返回 {"failed_count", "locked_until", "locked", "remaining"}。

    阈值/时长来自站点设置（数据库 `login_lock_threshold` / `login_lock_minutes`，
    后台「站点设置」页可改；缺键回退 config.json 部署级键），本次失败刚好达到阈值
    时立即写入 locked_until（触发锁定），由调用方把锁定提示返回给前端。
    """
    threshold = login_lock_threshold_of(db)
    key = failure_key(username)
    row = db.execute(
        "SELECT id, failed_count FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, key),
    ).fetchone()
    failed_count = int(row["failed_count"]) + 1 if row else 1
    locked = failed_count >= threshold
    locked_until = now_ts() + login_lock_seconds_of(db) if locked else 0
    if row:
        db.execute(
            """
            UPDATE login_failures
            SET failed_count = ?, locked_until = ?, updated_at = ?
            WHERE id = ?
            """,
            (failed_count, locked_until, now_ts(), row["id"]),
        )
    else:
        db.execute(
            """
            INSERT INTO login_failures (id, ip_address, username, failed_count, locked_until, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), ip_address, key, failed_count, locked_until, now_ts()),
        )
    db.commit()
    return {
        "failed_count": failed_count,
        "locked_until": locked_until,
        "locked": locked,
        "remaining": max(0, threshold - failed_count),
    }


def clear_login_failures(db: sqlite3.Connection, ip_address: str, username: str) -> None:
    db.execute(
        "DELETE FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, failure_key(username)),
    )
    db.commit()
