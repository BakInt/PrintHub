import io
import secrets
import sqlite3
import string
import time
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from PIL import Image, ImageDraw, ImageFont

from ..config import get_settings


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
    settings = get_settings()
    row = db.execute(
        "SELECT locked_until FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, failure_key(username)),
    ).fetchone()
    if row and float(row["locked_until"] or 0) > now_ts():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR)


def record_login_failure(db: sqlite3.Connection, ip_address: str, username: str) -> None:
    settings = get_settings()
    key = failure_key(username)
    row = db.execute(
        "SELECT id, failed_count FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, key),
    ).fetchone()
    failed_count = int(row["failed_count"]) + 1 if row else 1
    locked_until = now_ts() + settings.login_lock_seconds if failed_count >= settings.login_lock_threshold else 0
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


def clear_login_failures(db: sqlite3.Connection, ip_address: str, username: str) -> None:
    db.execute(
        "DELETE FROM login_failures WHERE ip_address = ? AND username = ?",
        (ip_address, failure_key(username)),
    )
    db.commit()
