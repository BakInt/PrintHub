import sqlite3

from fastapi import Depends, Header, HTTPException, Request, status

from ..database import get_db
from ..config import get_settings
from ..services.auth_session import get_session
from ..utils.security import decode_token


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    settings = get_settings()
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        payload = decode_token(authorization.removeprefix("Bearer ").strip())
        user_id = payload.get("sub")
    if user_id is None:
        session = get_session(db, request.cookies.get(settings.session_cookie_name))
        user_id = session["user_id"] if session and session["user_id"] else None
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or not bool(user["is_active"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row | None:
    settings = get_settings()
    if authorization:
        return current_user(request, authorization, db)
    session = get_session(db, request.cookies.get(settings.session_cookie_name))
    if session and session["user_id"]:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if user is not None and bool(user["is_active"]):
            return user
    return None


def admin_user(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无效请求")
    return user
