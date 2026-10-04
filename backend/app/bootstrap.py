"""首次部署引导：生成唯一配置文件（config.json）并确保数据目录存在。

由 `docker/entrypoint.sh` 以 app 用户身份调用：`cd /app && python3 -m app.bootstrap`，
也在 `app.main` 导入时兜底调用一次（非容器部署直接跑 uvicorn 也能用）。

这里只做两件事：
1. 确保 ``<CONFIG_ROOT>/config.json`` 存在（缺失时用默认值生成、含随机 app_secret，
   只补齐缺失的键，绝不覆盖用户已改的值）；
2. 确保数据库/上传/备份/日志/CUPS 驱动目录存在。

业务配置（计价、促销、支付商户密钥、CUPS、默认打印机、备份策略）不在这里，
它们由 `init_db()` 在首次建库时播种进 SQLite，之后以后台页面保存的值为准。
"""

from __future__ import annotations

from pathlib import Path

from .config import ensure_config_file, get_settings


def ensure_data_dirs() -> list[Path]:
    """创建全部持久化目录（相对路径已按 config 目录归一）。"""

    settings = get_settings()
    directories = [
        settings.config_root,
        settings.database_path.parent,
        settings.upload_dir,
        settings.backup_dir,
        settings.log_dir,
        settings.cups_driver_dir,
    ]
    created: list[Path] = []
    for directory in directories:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(directory)
    return created


def bootstrap() -> dict[str, object]:
    """生成配置文件 + 数据目录，返回可直接打印进容器日志的结果。"""

    config_file = ensure_config_file()
    created = ensure_data_dirs()
    settings = get_settings()
    return {
        "config_file": str(config_file),
        "config_root": str(settings.config_root),
        "database": str(settings.database_path),
        "created_dirs": [str(item) for item in created],
    }


def main() -> None:
    result = bootstrap()
    print("[cloud-print] 启动引导完成", flush=True)
    print(f"[cloud-print]   配置目录：{result['config_root']}", flush=True)
    print(f"[cloud-print]   配置文件：{result['config_file']}", flush=True)
    print(f"[cloud-print]   数据库：  {result['database']}", flush=True)
    for item in result["created_dirs"]:
        print(f"[cloud-print]   新建目录：{item}", flush=True)


if __name__ == "__main__":
    main()
