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
    """IP + 路径维度的固定窗口限流。

    全局默认 settings.rate_limit_requests 次 / rate_limit_window_seconds；
    敏感路径（安全修复 V-04）叠加更严的专项限额（次/分钟/IP，由
    settings.sensitive_rate_limit_per_minute 配置，0 = 关闭），防止爆破登录与匿名灌文件。
    """

    # 专项限速的路径前缀（精确匹配或以其开头）；/api/cert/generate 为证照打印隔离钩子（预算表内）。
    SENSITIVE_PATH_PREFIXES: tuple[str, ...] = (
        "/api/auth/login",
        "/api/auth/register",
        "/api/upload",
        "/api/cert/generate",
    )

    def __init__(self, app, settings: Settings):
        self.app = app
        self.limit = settings.rate_limit_requests
        self.window = settings.rate_limit_window_seconds
        self.sensitive_limit = settings.sensitive_rate_limit_per_minute
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    def _limit_for_path(self, path: str) -> int:
        if self.sensitive_limit <= 0:
            return self.limit
        for prefix in self.SENSITIVE_PATH_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                # 专项限额按「次/分钟」归一到当前窗口长度，保持同一套滑动清理逻辑。
                return max(1, round(self.sensitive_limit * self.window / 60))
        return self.limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        path = scope.get("path", "")
        key = f"{client[0] if client else 'unknown'}:{path}"
        allowed = self._limit_for_path(path)
        now = time.monotonic()
        entries = self.requests[key]
        while entries and now - entries[0] > self.window:
            entries.popleft()
        if len(entries) >= allowed:
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
