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
    },
    "payments": {
        "status": "TEXT DEFAULT 'pending'",
        "raw_payload": "TEXT",
    },
    "order_items": {
        "is_double_sided": "INTEGER DEFAULT 0",
    },
    "printers": {
        "accepting_jobs": "INTEGER DEFAULT 1",
        "last_test_at": "TEXT",
        "last_test_success": "INTEGER",
        "last_test_note": "TEXT",
        "last_error": "TEXT",
        "hidden": "INTEGER DEFAULT 0",
    },
}


def ensure_columns(connection: sqlite3.Connection) -> None:
    for table, columns in SCHEMA_MIGRATIONS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
