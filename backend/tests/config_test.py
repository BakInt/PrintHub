"""配置系统专项测试：JSON 配置文件生成、热加载、环境变量优先级、管理员密码一次性重置。

相对 `smoke_test.py` 完全不依赖 pycups / CUPS / 网络，可单独在开发机上跑：

    python backend/tests/config_test.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ensure_config_file, get_settings, reload_settings
from app.database import connect, init_db


def test_generate_and_load() -> None:
    """首次部署没有配置文件时必须生成完整、可直接编辑且不依赖 .env 的 JSON。"""

    root = Path(tempfile.mkdtemp(prefix="cloud-print-config-"))
    config_path = root / "config.json"
    assert ensure_config_file(config_path) == config_path
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["database_path"] == "cloud_print.db", "默认值应是相对 config 目录的路径，便于整目录搬家"
    assert raw["upload_dir"] == "uploads"
    assert len(raw["app_secret"]) == 64, "生成时必须写入随机 app_secret，不能用 change-me 占位值"
    assert raw["reset_admin_password"] is False
    assert "print_mode" not in raw, "已移除的打印模式配置不应再出现在配置文件中"
    assert "cups_job_timeout_seconds" in raw and "print_confirm_timeout_seconds" in raw
    assert raw["sumatra_pdf_path"] == "" and raw["windows_pdf_print_command"] == "", "Windows 打印命令应可在配置文件里直接填写"

    # 已存在的配置文件绝不能被覆盖（用户在文件里的编辑必须保留）；
    # 只补齐版本升级后新增的键，方便用户看到新配置项。
    raw["cups_server"] = "10.0.0.9:631"
    raw.pop("print_confirm_timeout_seconds")
    config_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    ensure_config_file(config_path)
    merged = json.loads(config_path.read_text(encoding="utf-8"))
    assert merged["cups_server"] == "10.0.0.9:631", "用户改过的值不得被覆盖"
    assert merged["print_confirm_timeout_seconds"] == 600, "缺失的新键应被补齐"
    assert merged["app_secret"] == raw["app_secret"], "app_secret 不得被重新生成"


def test_hot_reload_and_env_priority() -> None:
    root = Path(tempfile.mkdtemp(prefix="cloud-print-config-"))
    config_path = root / "config.json"
    ensure_config_file(config_path)
    original = os.environ.get("CONFIG_CONFIG_FILE")
    original_root = os.environ.get("CONFIG_ROOT")
    original_db = os.environ.get("DATABASE_PATH")
    try:
        os.environ["CONFIG_CONFIG_FILE"] = str(config_path)
        os.environ["CONFIG_ROOT"] = str(root)
        os.environ.pop("DATABASE_PATH", None)
        settings = reload_settings()
        assert settings.config_file == config_path
        assert settings.database_path == root / "cloud_print.db", settings.database_path
        assert settings.upload_dir == root / "uploads", settings.upload_dir
        assert settings.cups_driver_dir == root / "cups-drivers", settings.cups_driver_dir

        # 改完 config.json 不需要重启：get_settings() 依据 mtime/大小自动重载。
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        raw["rate_limit_requests"] = 999
        config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        assert get_settings().rate_limit_requests == 999

        # 环境变量优先级最高（本地测试与特殊部署依赖这一点）。
        env_db = str(root / "from-env.db")
        os.environ["DATABASE_PATH"] = env_db
        assert str(reload_settings().database_path) == env_db

        # 配置文件损坏时不能崩：退化为全部默认值。
        config_path.write_text("{ broken json", encoding="utf-8")
        assert reload_settings().rate_limit_requests == 120
    finally:
        if original is None:
            os.environ.pop("CONFIG_CONFIG_FILE", None)
        else:
            os.environ["CONFIG_CONFIG_FILE"] = original
        if original_db is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = original_db
        reload_settings()


def test_admin_password_reset_once() -> None:
    """忘记管理员密码：config.json 置 reset_admin_password=true，重启后重置一次并写回 false。"""

    root = Path(tempfile.mkdtemp(prefix="cloud-print-reset-"))
    config_path = root / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database_path": str(root / "reset.db"),
                "admin_username": "resetadmin",
                "admin_password": "temp-password-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original = os.environ.get("CONFIG_CONFIG_FILE")
    original_root = os.environ.get("CONFIG_ROOT")
    original_db = os.environ.get("DATABASE_PATH")
    try:
        os.environ["CONFIG_CONFIG_FILE"] = str(config_path)
        os.environ["CONFIG_ROOT"] = str(root)
        os.environ.pop("DATABASE_PATH", None)
        reload_settings()
        init_db()
        with connect() as db:
            first = db.execute("SELECT id, password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert first is not None, "init_db 必须按 config.json 里的管理员账号建号"

        # 建库播种：config.json 里的 CUPS/ePay 值应写进 settings 表，且不覆盖已保存的值。
        with connect() as db:
            seeded = db.execute("SELECT value FROM settings WHERE key = 'cups_server'").fetchone()
            assert seeded is not None, "settings 表必须被播种"
            db.execute("UPDATE settings SET value = 'kept.example.com:631' WHERE key = 'cups_server'")
            db.commit()
        init_db()
        with connect() as db:
            kept = db.execute("SELECT value FROM settings WHERE key = 'cups_server'").fetchone()
        assert kept["value"] == "kept.example.com:631", "已有数据库里的值不得被 config.json 覆盖"

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        raw["admin_password"] = "temp-password-2"
        raw["reset_admin_password"] = True
        config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        reload_settings()
        init_db()
        with connect() as db:
            second = db.execute("SELECT password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert second["password_hash"] != first["password_hash"], "reset_admin_password=true 时必须重置管理员密码"
        assert json.loads(config_path.read_text(encoding="utf-8"))["reset_admin_password"] is False, (
            "重置成功后必须把开关写回 false，避免每次启动覆盖后台改过的密码"
        )

        # 再启动一次不再重置：后台改过的密码必须保留。
        reload_settings()
        init_db()
        with connect() as db:
            third = db.execute("SELECT password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert third["password_hash"] == second["password_hash"], "开关写回 false 后不得再次重置"
    finally:
        if original is None:
            os.environ.pop("CONFIG_CONFIG_FILE", None)
        else:
            os.environ["CONFIG_CONFIG_FILE"] = original
        if original_root is None:
            os.environ.pop("CONFIG_ROOT", None)
        else:
            os.environ["CONFIG_ROOT"] = original_root
        if original_db is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = original_db
        reload_settings()


def main() -> None:
    test_generate_and_load()
    test_hot_reload_and_env_priority()
    test_admin_password_reset_once()
    print("config tests passed")


if __name__ == "__main__":
    main()
