import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import Response as FastAPIResponse

from ..database import get_db
from ..models.schemas import USERNAME_PATTERN, AuthRequest, AuthResponse, UserOut
from ..services.auth_session import (
    LOGIN_ERROR,
    assert_not_locked,
    clear_login_failures,
    clear_session_cookies,
    destroy_session,
    generate_captcha,
    get_session,
    ensure_guest_session,
    make_session,
    record_login_failure,
    set_session_cookies,
    verify_captcha,
)
from ..config import get_settings
from ..utils.security import create_token, hash_password, password_needs_rehash, verify_password
from .deps import current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def row_to_user(row: sqlite3.Row) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        real_name=row["real_name"],
        email=row["email"],
        phone=row["phone"],
        balance=row["balance"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def login_failure(db: sqlite3.Connection, ip_address: str, username: str) -> None:
    record_login_failure(db, ip_address, username)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR)


def validate_login_payload(raw_payload: dict) -> tuple[str, str, str]:
    username = str(raw_payload.get("username") or "").strip()
    password = str(raw_payload.get("password") or "")
    captcha = str(raw_payload.get("captcha") or "").strip()
    if not USERNAME_PATTERN.fullmatch(username) or not 8 <= len(password) <= 64 or not captcha:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR)
    return username, password, captcha


def login_response(response: Response, db: sqlite3.Connection, user: sqlite3.Row, old_session_id: str | None) -> AuthResponse:
    destroy_session(db, old_session_id)
    session = make_session(db, user["id"])
    set_session_cookies(response, session)
    return AuthResponse(token=create_token({"sub": user["id"]}), user=row_to_user(user))


@router.get("/csrf")
def csrf(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    session = ensure_guest_session(request, response, db)
    return {"csrf_token": session["csrf_token"]}


@router.get("/captcha")
def captcha(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    image = generate_captcha(request, response, db)
    captcha_response = FastAPIResponse(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})
    for header in response.raw_headers:
        if header[0].lower() == b"set-cookie":
            captcha_response.raw_headers.append(header)
    return captcha_response


@router.post("/register", response_model=AuthResponse)
def register(payload: AuthRequest, request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    settings = get_settings()
    settings_session = get_session(db, request.cookies.get(settings.session_cookie_name))
    if not verify_captcha(db, settings_session, payload.captcha):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
    user_id = str(uuid4())
    try:
        db.execute(
            """
            INSERT INTO users (id, username, password_hash, email, phone, balance)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (user_id, payload.username, hash_password(payload.password), payload.email, payload.phone),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或手机号已存在") from exc
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return login_response(response, db, user, request.cookies.get(settings.session_cookie_name))


@router.post("/login", response_model=AuthResponse)
async def login(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    try:
        raw_payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR) from exc
    if not isinstance(raw_payload, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR)
    username, password, captcha_answer = validate_login_payload(raw_payload)
    ip_address = client_ip(request)
    assert_not_locked(db, ip_address, username)
    settings = get_settings()
    old_session_id = request.cookies.get(settings.session_cookie_name)
    session = get_session(db, old_session_id)
    if not verify_captcha(db, session, captcha_answer):
        login_failure(db, ip_address, username)
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        login_failure(db, ip_address, username)
    if not bool(user["is_active"]):
        login_failure(db, ip_address, username)
    if password_needs_rehash(user["password_hash"]):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user["id"]))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    clear_login_failures(db, ip_address, username)
    return login_response(response, db, user, old_session_id)


@router.post("/logout")
def logout(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    settings = get_settings()
    destroy_session(db, request.cookies.get(settings.session_cookie_name))
    clear_session_cookies(response)
    return {"success": True}


@router.get("/me", response_model=UserOut)
def me(user: sqlite3.Row = Depends(current_user)):
    return row_to_user(user)
