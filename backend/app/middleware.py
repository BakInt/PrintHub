import sqlite3
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status

from .config import Settings
from .database import connect
from .services.auth_session import require_csrf
from .services.backup import is_maintenance_locked, maintenance_reason


class RateLimitMiddleware:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.limit = settings.rate_limit_requests
        self.window = settings.rate_limit_window_seconds
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        path = scope.get("path", "")
        key = f"{client[0] if client else 'unknown'}:{path}"
        now = time.monotonic()
        entries = self.requests[key]
        while entries and now - entries[0] > self.window:
            entries.popleft()
        if len(entries) >= self.limit:
            response = Response("请求过于频繁，请稍后再试", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
            await response(scope, receive, send)
            return
        entries.append(now)
        await self.app(scope, receive, send)


async def security_headers_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


async def maintenance_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    safe_methods = {"GET", "HEAD", "OPTIONS", "TRACE"}
    if (
        request.method not in safe_methods
        and is_maintenance_locked()
        and not request.url.path.startswith("/api/admin/backups")
    ):
        return Response(f"系统正在{maintenance_reason()}，请稍后再试", status_code=status.HTTP_423_LOCKED)
    return await call_next(request)


async def csrf_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    try:
        with connect() as db:
            require_csrf(request, db)
    except RuntimeError:
        raise
    except sqlite3.OperationalError as exc:
        if "auth_sessions" not in str(exc):
            raise
    return await call_next(request)


def validate_production_config(settings: Settings) -> None:
    if not settings.is_production:
        return
    problems: list[str] = []
    if settings.app_secret == "change-me-in-production" or "replace-" in settings.app_secret or len(settings.app_secret) < 32:
        problems.append("config.json 的 app_secret 必须替换为至少 32 位随机字符串")
    if settings.admin_password in {"admin123456", "change-this-admin-password"} or "replace-" in settings.admin_password or len(settings.admin_password) < 12:
        problems.append("config.json 的 admin_password 必须替换为至少 12 位强密码")
    if "*" in settings.cors_origin_list:
        problems.append("生产环境不允许 config.json 的 cors_origins 使用通配符")
    if (
        "your-" in settings.epay_pid
        or "replace-" in settings.epay_pid
        or "your-" in settings.epay_key
        or "replace-" in settings.epay_key
        or "example.com" in settings.epay_gateway
        or "your-" in settings.epay_gateway
    ):
        problems.append("生产环境必须配置真实易支付商户 ID、商户密钥和网关")
    if (
        "example.com" in settings.public_base_url
        or "example.com" in settings.frontend_base_url
        or settings.public_base_url.startswith(("http://localhost", "http://127.0.0.1"))
        or settings.frontend_base_url.startswith(("http://localhost", "http://127.0.0.1"))
    ):
        problems.append("生产环境必须配置真实公网回调地址和前端返回地址")
    if problems:
        raise RuntimeError("；".join(problems))
