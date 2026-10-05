import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .bootstrap import bootstrap
from .config import get_settings
from .database import init_db
from .middleware import RateLimitMiddleware, maintenance_middleware, security_headers_middleware, validate_production_config
from .routers import admin, auth, files, orders, public, user
from .services.backup import start_auto_backup_scheduler
from .services.print_monitor import start_print_status_monitor

logger = logging.getLogger(__name__)

# 首次部署（config 目录还是空的）时自动生成唯一配置文件 config.json（含随机 app_secret）
# 并建好数据目录；之后所有配置只改这个文件或后台页面，不再使用 .env。
bootstrap()

settings = get_settings()

print(
    "[cloud-print] 配置目录: {root} | 配置文件: {cfg} | 数据库: {db}".format(
        root=settings.config_root,
        cfg=settings.config_file,
        db=settings.database_path,
    ),
    flush=True,
)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, settings=settings)
if settings.trusted_host_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.middleware("http")(security_headers_middleware)
app.middleware("http")(maintenance_middleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理：任何未捕获异常都记录堆栈并返回标准 JSON 错误。

    FastAPI 默认对未捕获异常只返回纯文本 500 "Internal Server Error"，前端拿不到
    可读信息（历史 bug：兑换码接口因此只显示 "Internal Server Error"）。这里统一
    转成 `{"detail": "..."}` 中文提示，真实原因进日志。
    """
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


def _warn_data_outside_config_root() -> None:
    """容器部署下数据必须落在 config 目录（唯一持久化挂载点），否则提醒用户。

    容器里 CONFIG_ROOT 必定由 entrypoint 设置；本地开发不受影响、不打印噪音。
    """

    import os

    config_root = settings.config_root
    watched = {
        "数据库": settings.database_path,
        "上传目录": settings.upload_dir,
        "备份目录": settings.backup_dir,
        "日志目录": settings.log_dir,
        "CUPS 驱动目录": settings.cups_driver_dir,
    }
    outside = {name: path for name, path in watched.items() if config_root not in path.parents and path != config_root}
    if not outside:
        return
    if os.environ.get("CONFIG_ROOT") or Path("/.dockerenv").exists():
        for name, path in outside.items():
            print(
                f"[cloud-print] 警告：{name} 不在配置目录 {config_root} 内（当前 {path}），"
                "容器重建后这些数据会丢失；请在 config/config.json 里改回配置目录下的相对路径。",
                flush=True,
            )


@app.on_event("startup")
def startup() -> None:
    _warn_data_outside_config_root()
    validate_production_config(settings)
    init_db()
    start_print_status_monitor()
    start_auto_backup_scheduler()


app.include_router(public.router)
app.include_router(auth.router)
app.include_router(files.router)
app.include_router(orders.router)
app.include_router(admin.router)
app.include_router(admin.setup_router)
app.include_router(user.router)

FRONTEND_DIST = Path(__file__).parent.parent / "frontend-dist"
if FRONTEND_DIST.exists() and FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists() and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    static_dir = FRONTEND_DIST / "static"
    if static_dir.exists() and static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))