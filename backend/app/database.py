import sqlite3
import json
from collections.abc import Generator
from pathlib import Path

from .config import get_settings
from .utils.security import hash_password


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    real_name TEXT,
    email TEXT,
    phone TEXT UNIQUE,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    pdf_path TEXT,
    page_count INTEGER DEFAULT 0,
    file_size REAL DEFAULT 0,
    black_coverage REAL DEFAULT 0,
    page_coverages TEXT,
    is_safe INTEGER DEFAULT 1,
    status TEXT DEFAULT 'uploaded',
    error_message TEXT,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    order_type TEXT DEFAULT 'print',
    total_amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    is_double_sided INTEGER DEFAULT 0,
    -- 【新增功能】彩色打印：用户下单时是否选择彩色（NULL=旧数据/旧前端未指定，1=彩色，0=黑白）
    use_color INTEGER,
    copies INTEGER DEFAULT 1,
    payment_method TEXT DEFAULT 'wxpay',
    printer_name TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    print_job_id TEXT,
    print_error TEXT,
    sheet_count INTEGER DEFAULT 0,
    base_amount REAL,
    discount_amount REAL DEFAULT 0,
    pricing_detail TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    paid_at TEXT,
    balance_applied_at TEXT,
    printed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    is_double_sided INTEGER DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    epay_trade_no TEXT,
    amount REAL NOT NULL,
    payment_method TEXT,
    status TEXT DEFAULT 'pending',
    paid_at TEXT,
    raw_payload TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    file_id TEXT,
    order_id TEXT,
    level TEXT DEFAULT 'warning',
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    handled_at TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS printers (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    uri TEXT,
    driver TEXT DEFAULT 'everywhere',
    location TEXT,
    description TEXT,
    is_default INTEGER DEFAULT 0,
    is_enabled INTEGER DEFAULT 1,
    accepting_jobs INTEGER DEFAULT 1,
    -- 【新增功能】打印机属性：是否支持彩色打印 / 是否支持自动双面打印（后台配置，驱动前端是否展示对应选项）
    is_support_color INTEGER DEFAULT 0,
    is_support_auto_duplex INTEGER DEFAULT 1,
    last_status TEXT,
    last_checked_at TEXT,
    last_test_at TEXT,
    last_test_success INTEGER,
    last_test_note TEXT,
    last_error TEXT,
    hidden INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    csrf_token TEXT NOT NULL,
    captcha_answer TEXT,
    captcha_expires_at REAL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS login_failures (
    id TEXT PRIMARY KEY,
    ip_address TEXT NOT NULL,
    username TEXT NOT NULL,
    failed_count INTEGER DEFAULT 0,
    locked_until REAL DEFAULT 0,
    updated_at REAL NOT NULL,
    UNIQUE(ip_address, username)
);

-- 【新增功能】兑换码：后台生成，用户在个人中心「兑换码充值」输入兑换额度。
-- 一个兑换码最多可被兑换 usable_count 次（默认 1），每次成功兑换给对应用户加 balance。
-- per_user_max_times=0（默认）表示关闭「每个用户最大兑换次数」限制，完全按 usable_count 总次数逻辑；
-- per_user_max_times=N>0 时开启双重校验：既受 usable_count 总次数约束，同一 user_id 又最多兑换 N 次
-- （该用户已兑换次数统计 redemption_logs）。
-- 历史列 per_user_once（每个用户仅可使用一次）已被 per_user_max_times 取代，不再读写；
-- 旧库由 migrate_redemption_per_user_limit() 做一次等价换算 per_user_once=1 → per_user_max_times=1。
-- expires_at 是过期判断的唯一权威字段，两种互斥的有效期方式都只体现在它上面：
-- 「按天数」由 valid_days 算出（valid_days=0 表示永久有效、expires_at 为 NULL）；
-- 「指定到期日期」由管理员用日期控件直接指定，归一化为当天 23:59:59 后写入并把 valid_days 记为 0。
-- 因此 (valid_days, expires_at) 组合可唯一定位方式，无需为到期日期新增列。
CREATE TABLE IF NOT EXISTS redemption_codes (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    amount REAL NOT NULL,
    usable_count INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0,
    per_user_max_times INTEGER DEFAULT 0,
    valid_days INTEGER DEFAULT 0,
    expires_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code)
);

-- 兑换日志：每次成功兑换记录一条（兑换用户 id + 时间 + 到账金额）。
CREATE TABLE IF NOT EXISTS redemption_logs (
    id TEXT PRIMARY KEY,
    code_id TEXT NOT NULL,
    user_id TEXT,
    amount REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (code_id) REFERENCES redemption_codes(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


DEFAULT_SETTINGS = {
    "pricing_mode": "standard",
    "single_price": "0.50",
    "duplex_price": "0.30",
    "coverage_single_base_price": "0.10",
    "coverage_duplex_base_price": "0.08",
    "bulk_discount_enabled": "true",
    "bulk_discount_rules": json.dumps(
        [
            {"min_sheets": 10, "discount": 0.95},
            {"min_sheets": 100, "discount": 0.90},
            {"min_sheets": 200, "discount": 0.80},
        ]
    ),
    "daily_limited_offer_enabled": "false",
    "daily_limited_offer_all_day": "false",
    "daily_limited_offer_start_time": "",
    "daily_limited_offer_end_time": "",
    "daily_limited_offer_sheet_quota": "0",
    "daily_limited_offer_discount": "1.0",
    "daily_limited_offer_free": "false",
    "min_balance": "1.00",
    "safety_coverage_limit": "40",
    "max_file_size_mb": "50",
    "max_pages": "100",
    "backup_auto_enabled": "false",
    "backup_auto_frequency": "daily",
    "backup_auto_time": "03:00",
    "backup_auto_weekday": "0",
    "backup_retention_count": "7",
    "backup_auto_last_run_at": "",
    "cups_server": "192.168.1.100:631",
    "cups_user": "",
    "cups_password": "",
}


SCHEMA_MIGRATIONS = {
    "users": {
        "real_name": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
    },
    "files": {
        "page_coverages": "TEXT",
        "status": "TEXT DEFAULT 'uploaded'",
        "error_message": "TEXT",
    },
    "orders": {
        "order_type": "TEXT DEFAULT 'print'",
        "payment_method": "TEXT DEFAULT 'wxpay'",
        "printer_name": "TEXT",
        "contact_name": "TEXT",
        "contact_phone": "TEXT",
        "print_job_id": "TEXT",
        "print_error": "TEXT",
        "printed_at": "TEXT",
        "sheet_count": "INTEGER DEFAULT 0",
        "base_amount": "REAL",
        "discount_amount": "REAL DEFAULT 0",
        "pricing_detail": "TEXT",
        "balance_applied_at": "TEXT",
        # 【新增功能】旧库补列：彩色打印标记。故意不给 DEFAULT：老订单补列后为 NULL
        # （NULL = 未指定，打印时完全沿用原有逻辑，历史订单/旧前端行为不变）。
        "use_color": "INTEGER",
    },
    "payments": {
        "status": "TEXT DEFAULT 'pending'",
        "raw_payload": "TEXT",
    },
    "order_items": {
        "is_double_sided": "INTEGER DEFAULT 0",
    },
    "redemption_codes": {
        # 【新增功能】旧库补列：每个用户最大兑换次数。0 = 关闭该限制（保持原有
        # 「按总可用次数」逻辑不变）；N > 0 = 同一用户最多兑换 N 次，且仍受总次数约束。
        # 取代历史上的 per_user_once（每个用户仅可使用一次），旧值由
        # migrate_redemption_per_user_limit() 换算过来。
        "per_user_max_times": "INTEGER DEFAULT 0",
    },
    "printers": {
        "accepting_jobs": "INTEGER DEFAULT 1",
        "last_test_at": "TEXT",
        "last_test_success": "INTEGER",
        "last_test_note": "TEXT",
        "last_error": "TEXT",
        "hidden": "INTEGER DEFAULT 0",
        # 【新增功能】旧库补列：打印机是否支持彩色 / 自动双面。
        # 彩色默认 0（旧版没有彩色能力，保持"不展示彩色选项"）；
        # 自动双面默认 1（旧版所有打印机都可选双面，升级后保持原行为不变）。
        "is_support_color": "INTEGER DEFAULT 0",
        "is_support_auto_duplex": "INTEGER DEFAULT 1",
    },
}


def ensure_columns(connection: sqlite3.Connection) -> None:
    for table, columns in SCHEMA_MIGRATIONS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_redemption_per_user_limit(connection: sqlite3.Connection) -> None:
    """一次性数据换算：旧库的 per_user_once=1 等价于 per_user_max_times=1。

    `per_user_once`（每个用户仅可使用一次）已被 `per_user_max_times`（每个用户最大
    兑换次数，0=不限制）取代，代码不再读写旧列。升级后旧库里勾选过「每个用户仅可
    使用一次」的兑换码必须继续保持原来的限制，因此这里做一次等价换算。
    幂等：只处理「per_user_max_times 仍为 0 且 per_user_once=1」的行，重复执行无副作用；
    新库没有 per_user_once 列，直接跳过（什么都不用换算）。
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(redemption_codes)").fetchall()}
    if "per_user_once" not in columns or "per_user_max_times" not in columns:
        return
    connection.execute(
        """
        UPDATE redemption_codes
           SET per_user_max_times = 1
         WHERE per_user_once = 1
           AND per_user_max_times = 0
        """
    )


def connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.executescript(SCHEMA)
        ensure_columns(connection)
        # 补列之后再换算旧数据：老库里 per_user_once=1 的兑换码要变成「每用户最多 1 次」。
        migrate_redemption_per_user_limit(connection)
        defaults = {
            **DEFAULT_SETTINGS,
            "epay_gateway": settings.epay_gateway,
            "epay_pid": settings.epay_pid,
            "epay_key": settings.epay_key,
            "public_base_url": settings.public_base_url,
            "frontend_base_url": settings.frontend_base_url,
            "default_printer": settings.default_printer,
            "cups_server": settings.cups_server,
            "cups_user": settings.cups_user,
            "cups_password": settings.cups_password,
            "cups_allow_external_printers": str(settings.cups_allow_external_printers).lower(),
            "cups_connection_mode": settings.cups_connection_mode,
            "cups_network_interface": settings.cups_network_interface,
            "cups_static_route_gateway": settings.cups_static_route_gateway,
            "cups_driver_dir": str(settings.cups_driver_dir),
        }
        # 建库播种：只在键不存在时写入（INSERT OR IGNORE）。已有数据库里后台保存过的
        # 值不会被 config.json 覆盖，「配置只存在 config/ 目录」以数据库为准。
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        connection.execute(
            "UPDATE settings SET value = ? WHERE key = 'epay_gateway' AND value = ?",
            (settings.epay_gateway, "https://legacy-epay-gateway.example.com/api/pay/submit"),
        )
        # 已移除「打印模式」配置：真实打印由运行平台决定（Windows 走 SumatraPDF/PrintTo，
        # 其余平台走 CUPS），不再存在可配置的 cups/system 切换项。这里清掉旧库遗留的键，
        # 避免已删除的设置在后台设置接口里继续回显。
        connection.execute("DELETE FROM settings WHERE key = 'print_mode'")
        admin = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (settings.admin_username,),
        ).fetchone()
        if admin is None:
            from uuid import uuid4

            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, is_admin, balance)
                VALUES (?, ?, ?, 1, 0)
                """,
                (str(uuid4()), settings.admin_username, hash_password(settings.admin_password)),
            )
        elif settings.reset_admin_password:
            # 一次性引导：忘记管理员密码时把 config.json 的 reset_admin_password 置 true，
            # 重启后按 admin_password 重置一次，随即把开关写回 false，避免每次启动覆盖后台密码。
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(settings.admin_password), admin["id"]),
            )
            settings.reset_admin_password = False
            config_file = settings.config_file
            if config_file.exists():
                try:
                    payload = json.loads(config_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
                if isinstance(payload, dict) and payload.get("reset_admin_password") is not False:
                    payload["reset_admin_password"] = False
                    config_file.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        connection.commit()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()
