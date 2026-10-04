import base64
import hashlib
import hmac
import json
import time
from typing import Any

import bcrypt
from fastapi import HTTPException, status

from ..config import get_settings


def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    return f"bcrypt${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("bcrypt$"):
        digest = stored_hash.removeprefix("bcrypt$").encode("utf-8")
        try:
            return bcrypt.checkpw(password.encode("utf-8"), digest)
        except ValueError:
            return False
    try:
        algorithm, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(candidate, digest)


def password_needs_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith("bcrypt$")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(payload: dict[str, Any], expires_in: int | None = None) -> str:
    settings = get_settings()
    token_ttl = expires_in if expires_in is not None else settings.access_token_expire_seconds
    body = {**payload, "exp": int(time.time()) + token_ttl}
    encoded = _b64url(json.dumps(body, separators=(",", ":")).encode())
    signature = hmac.new(settings.app_secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64url(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    expected = _b64url(hmac.new(settings.app_secret.encode(), encoded.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    payload = json.loads(_b64url_decode(encoded))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    return payload
