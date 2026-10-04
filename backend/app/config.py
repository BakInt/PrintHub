"""应用配置：唯一配置文件 + 环境变量兜底。

配置约定（重要）：

1. 部署级配置只存在 ``<CONFIG_ROOT>/config.json`` 一个文件里，首次启动时自动生成，
   含全部键和默认值；不再读取、也不要求存在 ``.env`` 文件。
2. 业务/运行配置（计价、促销、支付商户、CUPS、默认打印机、备份策略等）由
   ``init_db()`` 在首次建库时写入 SQLite ``settings`` 表，之后一律以后台页面
   保存的数据库值为准；``config.json`` 里的同名键只作为建库种子。
3. 优先级：进程环境变量 > ``config.json`` > 代码内建默认值。保留环境变量优先是为了
   本地测试（如 ``backend/tests/smoke_test.py`` 用 ``DATABASE_PATH`` 指向临时目录）
   和特殊部署场景；日常使用无需设置任何环境变量。
4. 相对路径按 ``CONFIG_ROOT`` 归一为绝对路径，默认值里就写着 ``cloud_print.db``、
   ``uploads`` 这类以 ``config`` 目录为基准的相对路径，因此整个 ``config`` 目录搬家
   后配置依然成立。

Docker 里由 ``docker/entrypoint.sh`` 设 ``CONFIG_ROOT=/app/config``（对应宿主机
``./config`` 绑定挂载），容器内所有持久化数据都落在这个目录。
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, JsonConfigSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

CONFIG_FILE_NAME = "config.json"
CONFIG_ROOT_ENV = "CONFIG_ROOT"
CONFIG_FILE_ENV = "CONFIG_CONFIG_FILE"

# 首次生成配置文件时写出的键（顺序即文件中的顺序，便于人工阅读）。
# 只放部署级配置；计价/促销/支付密钥/CUPS 等运行配置保存在数据库 settings 表。
GENERATED_CONFIG_KEYS: tuple[str, ...] = (
    "environment",
    "app_secret",
    "database_path",
    "upload_dir",
    "backup_dir",
    "log_dir",
    "cups_driver_dir",
    "trusted_hosts",
    "cors_origins",
    "session_cookie_secure",
    "rate_limit_requests",
    "rate_limit_window_seconds",
    "access_token_expire_seconds",
    "session_expire_seconds",
    "captcha_expire_seconds",
    "login_lock_threshold",
    "login_lock_seconds",
    "admin_username",
    "admin_password",
    "reset_admin_password",
    "cups_job_timeout_seconds",
    "printer_probe_timeout_seconds",
    "print_status_check_interval_seconds",
    "print_confirm_timeout_seconds",
    # 仅在 Windows 上直接跑后端（非容器）时才会用到，容器部署可留空。
    "sumatra_pdf_path",
    "windows_pdf_print_command",
)

CONFIG_FILE_HEADER = "云打印系统唯一配置文件：与 cloud_print.db 同在 config 目录，备份时请整体复制。"


def config_root() -> Path:
    """配置目录：容器内由 CONFIG_ROOT 指定（默认 /app/config），本地开发回退当前目录。"""

    raw = (os.environ.get(CONFIG_ROOT_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def config_file_path() -> Path:
    """配置文件路径：CONFIG_CONFIG_FILE 可覆盖，否则为 ``<CONFIG_ROOT>/config.json``。"""

    raw = (os.environ.get(CONFIG_FILE_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (config_root() / CONFIG_FILE_NAME).resolve()


def _resolve_against_root(raw: Path) -> Path:
    """把配置里的相对路径按配置目录归一；绝对路径原样保留。"""

    if raw.is_absolute():
        return raw.resolve()
    return (config_root() / raw).resolve()


def config_file_exists() -> bool:
    path = config_file_path()
    return path.exists() and path.is_file()


def _relative_to_root(path: Path) -> str:
    """写进配置文件时尽量转成相对配置目录的写法，保持可移植。"""

    try:
        return path.resolve().relative_to(config_root()).as_posix()
    except ValueError:
        return str(path)


def _generate_config_secret() -> str:
    return secrets.token_hex(32)


def ensure_config_file(path: Path | None = None) -> Path:
    """确保配置文件存在；不存在时用内建默认值生成一份（含随机 app_secret）。

    已存在则原样保留用户修改，只在缺少相应键时补齐（便于后续版本新增配置项）。
    返回值是配置文件路径。
    """

    target = (path or config_file_path()).resolve()
    defaults = Settings()
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        payload: dict[str, Any] = loaded if isinstance(loaded, dict) else {"_comment": CONFIG_FILE_HEADER}
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"_comment": CONFIG_FILE_HEADER}
    if "app_secret" not in payload:
        payload["app_secret"] = _generate_config_secret()
    for key in GENERATED_CONFIG_KEYS:
        if key in payload:
            continue
        value = getattr(defaults, key)
        if isinstance(value, Path):
            value = _relative_to_root(value)
        payload[key] = value
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


class TextJsonConfigSettingsSource(JsonConfigSettingsSource):
    """强制 UTF-8 读取，并在文件损坏/不可读时安全降级为空配置。

    Windows 默认编码是 GBK，配置文件必须显式按 UTF-8 读取（文件里含中文注释）；
    损坏的配置文件不应该让整个服务起不来，出错时退化为「全部使用默认值」。
    """

    def _read_file(self, file_path: Path) -> dict[str, Any]:
        try:
            with open(file_path, encoding="utf-8") as json_file:
                return json.load(json_file)
        except (OSError, ValueError):
            return {}


class Settings(BaseSettings):
    app_name: str = "云打印系统"
    environment: str = "development"
    app_secret: str = "change-me-in-production"
    access_token_expire_seconds: int = 60 * 60 * 24 * 7
    session_expire_seconds: int = 60 * 60 * 24 * 7
    captcha_expire_seconds: int = 60 * 5
    login_lock_threshold: int = 5
    login_lock_seconds: int = 60 * 15
    session_cookie_name: str = "cloud_print_session"
    csrf_cookie_name: str = "cloud_print_csrf"
    session_cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    # 相对路径以 config 目录为基准（见 doc/AGENTS.md「存储」一节）。
    database_path: Path = Path("cloud_print.db")
    upload_dir: Path = Path("uploads")
    backup_dir: Path = Path("backups")
    log_dir: Path = Path("logs")
    max_file_size_mb: int = 50
    max_pages: int = 100
    safety_coverage_limit: float = 40.0
    default_single_price: float = 0.5
    default_duplex_price: float = 0.3
    min_balance: float = 1.0
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    # 一次性引导开关：为 true 时启动用它重置管理员密码，成功后写回 false。
    reset_admin_password: bool = False
    epay_gateway: str = "https://your-epay-gateway.example.com/submit.php"
    epay_pid: str = "your-epay-pid"
    epay_key: str = "your-epay-key"
    public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"
    default_printer: str = ""
    cups_server: str = "192.168.1.100:631"
    cups_user: str = ""
    cups_password: str = ""
    cups_driver_dir: Path = Path("cups-drivers")
    cups_allow_external_printers: bool = True
    cups_connection_mode: str = "bridge"
    cups_network_interface: str = ""
    cups_static_route_gateway: str = ""
    cups_job_timeout_seconds: int = 60
    printer_probe_timeout_seconds: float = 3.0
    print_status_check_interval_seconds: int = 30
    print_confirm_timeout_seconds: int = 600
    # Windows 真实打印 PDF 命令（一般指向 SumatraPDF）；空则回退系统 PrintTo。
    sumatra_pdf_path: str = ""
    windows_pdf_print_command: str = ""

    # 配置文件是唯一持久化配置来源：这里不再声明 env_file，.env 不再被读取。
    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("database_path", "upload_dir", "backup_dir", "log_dir", "cups_driver_dir", mode="after")
    @classmethod
    def _normalize_path(cls, value: Path) -> Path:
        if isinstance(value, Path) and not value.is_absolute():
            return _resolve_against_root(value)
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            TextJsonConfigSettingsSource(settings_cls, json_file=config_file_path(), json_file_encoding="utf-8"),
            file_secret_settings,
        )

    @property
    def config_file(self) -> Path:
        return config_file_path()

    @property
    def config_root(self) -> Path:
        return config_root()

    @property
    def cups_driver_upload_dir(self) -> Path:
        return self.cups_driver_dir

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


_settings_cache: Settings | None = None
_settings_fingerprint: tuple[str, int, int] | None = None


def _config_fingerprint() -> tuple[str, int, int]:
    """(路径, mtime_ns, 大小)：配置文件被编辑后自动重新加载。"""

    path = config_file_path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def get_settings() -> Settings:
    """读取当前生效配置；配置文件变化（mtime/大小）后自动重载。"""

    global _settings_cache, _settings_fingerprint
    fingerprint = _config_fingerprint()
    if _settings_cache is None or fingerprint != _settings_fingerprint:
        _settings_cache = Settings()
        _settings_fingerprint = fingerprint
    return _settings_cache


def reload_settings() -> Settings:
    """强制丢弃缓存并重新读取配置（改完 config.json 后可立即生效）。"""

    global _settings_cache, _settings_fingerprint
    _settings_cache = None
    _settings_fingerprint = None
    return get_settings()
