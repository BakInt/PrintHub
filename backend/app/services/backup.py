import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from ..config import Settings, get_settings
from ..database import connect, init_db


BACKUP_DATA_VERSION = "cloud-print-backup-v1"
BACKUP_MANIFEST = "manifest.json"
BACKUP_FORMATS = {"zip", "tar.gz"}
BACKUP_CONFIG_FILES = [
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.local-test.yml",
    "docker-compose.cups.yml",
    "docker-compose.print-service.yml",
    "docker-compose.print-service.hostnet.yml",
]
# 唯一配置文件（config.json）存在 config 目录里、不在仓库根，单独归档成这个固定名字，
# 恢复时再写回 `settings.config_file`，这样换一台机器也能恢复出同样的 app_secret 与端口配置。
BACKUP_SETTINGS_FILE = "config.json"


def _copy_settings_file(config_dir: Path, content: dict, settings: Settings) -> None:
    """把 config 目录里的 config.json 一并归档（含 app_secret / 管理员密码）。"""

    config_file = settings.config_file
    if not config_file.exists() or not config_file.is_file():
        return
    shutil.copy2(config_file, config_dir / BACKUP_SETTINGS_FILE)
    content["config_files"].append(BACKUP_SETTINGS_FILE)

_maintenance_lock = threading.RLock()
_maintenance_reason: str | None = None
_scheduler_started = False
_scheduler_lock = threading.Lock()


def backup_root() -> Path:
    root = get_settings().backup_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_root() -> Path:
    return get_settings().log_dir.resolve()


def is_maintenance_locked() -> bool:
    return _maintenance_reason is not None


def maintenance_reason() -> str:
    return _maintenance_reason or ""


@contextmanager
def maintenance_lock(reason: str):
    global _maintenance_reason
    with _maintenance_lock:
        if _maintenance_reason:
            raise HTTPException(status_code=423, detail=f"系统正在{_maintenance_reason}，请稍后再试")
        _maintenance_reason = reason
        try:
            yield
        finally:
            _maintenance_reason = None


def backup_policy(db: sqlite3.Connection) -> dict:
    settings = {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings").fetchall()}
    return {
        "enabled": _bool_setting(settings.get("backup_auto_enabled"), False),
        "frequency": settings.get("backup_auto_frequency") or "daily",
        "time": settings.get("backup_auto_time") or "03:00",
        "weekday": int(settings.get("backup_auto_weekday") or 0),
        "retention_count": int(settings.get("backup_retention_count") or 7),
        "last_run_at": settings.get("backup_auto_last_run_at") or "",
    }


def update_backup_policy(db: sqlite3.Connection, payload) -> dict:
    data = payload.model_dump()
    stored = {
        "backup_auto_enabled": "true" if data["enabled"] else "false",
        "backup_auto_frequency": data["frequency"],
        "backup_auto_time": data["time"],
        "backup_auto_weekday": str(data["weekday"]),
        "backup_retention_count": str(data["retention_count"]),
    }
    for key, value in stored.items():
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    db.commit()
    cleanup_old_backups(data["retention_count"])
    return backup_policy(db)


def create_backup(archive_format: str = "zip", created_by: str = "manual") -> dict:
    if archive_format not in BACKUP_FORMATS:
        raise HTTPException(status_code=422, detail="备份格式仅支持 zip 或 tar.gz")
    with maintenance_lock("备份数据"):
        return _create_backup_unlocked(archive_format, created_by)


def _create_backup_unlocked(archive_format: str, created_by: str) -> dict:
    settings = get_settings()
    root = backup_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "tar.gz" if archive_format == "tar.gz" else "zip"
    filename = f"backup_{timestamp}.{suffix}"
    archive_path = root / filename
    with tempfile.TemporaryDirectory(prefix="cloud-print-backup-") as tmp:
        staging = Path(tmp) / "payload"
        staging.mkdir(parents=True)
        manifest = _build_staging(staging, archive_format, created_by)
        if archive_format == "zip":
            _write_zip(staging, archive_path)
        else:
            _write_tar_gz(staging, archive_path)
    cleanup_old_backups(_current_retention_count())
    return _backup_file_info(archive_path, manifest)


def _build_staging(staging: Path, archive_format: str, created_by: str) -> dict:
    settings = get_settings()
    repo_root = Path.cwd().resolve()
    database_dir = staging / "database"
    database_dir.mkdir()
    _copy_sqlite_database(settings.database_path, database_dir / settings.database_path.name)

    content: dict[str, bool | list[str]] = {
        "database": True,
        "uploads": False,
        "logs": False,
        "config_files": [],
    }
    upload_dir = settings.upload_dir.resolve()
    if upload_dir.exists():
        shutil.copytree(upload_dir, staging / "uploads", symlinks=False)
        content["uploads"] = True
    logs = log_root()
    if logs.exists():
        shutil.copytree(logs, staging / "logs", symlinks=False)
        content["logs"] = True
    config_dir = staging / "config"
    config_dir.mkdir()
    for relative in BACKUP_CONFIG_FILES:
        source = repo_root / relative
        if source.exists() and source.is_file():
            target = config_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            content["config_files"].append(relative)
    _copy_settings_file(config_dir, content, settings)

    manifest = {
        "data_version": BACKUP_DATA_VERSION,
        "backup_time": datetime.utcnow().isoformat(),
        "created_by": created_by,
        "archive_format": archive_format,
        "app_name": settings.app_name,
        "database_file": f"database/{settings.database_path.name}",
        "content": content,
    }
    (staging / BACKUP_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _copy_sqlite_database(source_path: Path, target_path: Path) -> None:
    source_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_path)
    try:
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def list_backups() -> list[dict]:
    root = backup_root()
    rows = []
    for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or not _is_backup_archive(path):
            continue
        rows.append(_backup_file_info(path))
    return rows


def delete_backup(filename: str) -> dict:
    path = backup_file_path(filename)
    path.unlink(missing_ok=True)
    return {"success": True}


def backup_file_path(filename: str) -> Path:
    if Path(filename).name != filename or not _is_backup_archive(Path(filename)):
        raise HTTPException(status_code=400, detail="备份文件名无效")
    path = (backup_root() / filename).resolve()
    try:
        path.relative_to(backup_root())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="备份文件名无效") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return path


async def inspect_uploaded_backup(file: UploadFile) -> dict:
    upload_path = await _save_upload_to_temp(file)
    try:
        return inspect_backup_archive(upload_path)
    finally:
        upload_path.unlink(missing_ok=True)


async def restore_uploaded_backup(file: UploadFile, source: str = "admin") -> dict:
    upload_path = await _save_upload_to_temp(file)
    try:
        with maintenance_lock("恢复数据"):
            return _restore_backup_unlocked(upload_path, source)
    finally:
        upload_path.unlink(missing_ok=True)


def inspect_backup_archive(path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="cloud-print-restore-inspect-") as tmp:
        extracted = Path(tmp) / "payload"
        _extract_archive(path, extracted)
        manifest = _read_and_validate_manifest(extracted)
        db_path = extracted / manifest["database_file"]
        if not db_path.exists():
            raise HTTPException(status_code=422, detail="备份缺少数据库文件")
        return _manifest_response(manifest, path)


def _restore_backup_unlocked(path: Path, source: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="cloud-print-restore-") as tmp:
        base = Path(tmp)
        extracted = base / "payload"
        rollback = base / "rollback"
        _extract_archive(path, extracted)
        manifest = _read_and_validate_manifest(extracted)
        _validate_restore_payload(extracted, manifest)
        _snapshot_current_state(rollback)
        try:
            _apply_restore_payload(extracted, manifest)
            init_db()
        except Exception:
            _apply_restore_payload(rollback, _rollback_manifest(rollback))
            init_db()
            raise
    return {"success": True, "restored_from": source, "backup": _manifest_response(manifest, path)}


def is_initial_restore_available() -> bool:
    try:
        with connect() as db:
            users = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            admins = db.execute("SELECT COUNT(*) AS count FROM users WHERE is_admin = 1").fetchone()["count"]
            files = db.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"]
            orders = db.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
            payments = db.execute("SELECT COUNT(*) AS count FROM payments").fetchone()["count"]
        return users == 0 and admins == 0 and files == 0 and orders == 0 and payments == 0
    except sqlite3.Error:
        return False


async def inspect_initial_restore(file: UploadFile) -> dict:
    if not is_initial_restore_available():
        raise HTTPException(status_code=403, detail="当前系统已初始化，请登录管理员后台执行恢复")
    return await inspect_uploaded_backup(file)


async def restore_initial_backup(file: UploadFile) -> dict:
    if not is_initial_restore_available():
        raise HTTPException(status_code=403, detail="当前系统已初始化，请登录管理员后台执行恢复")
    return await restore_uploaded_backup(file, "initial-setup")


def start_auto_backup_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    thread = threading.Thread(target=_auto_backup_loop, name="cloud-print-auto-backup", daemon=True)
    thread.start()


def cleanup_old_backups(retention_count: int) -> None:
    if retention_count <= 0:
        return
    backups = list_backups()
    for item in backups[retention_count:]:
        try:
            backup_file_path(item["filename"]).unlink(missing_ok=True)
        except HTTPException:
            continue


def _auto_backup_loop() -> None:
    while True:
        try:
            with connect() as db:
                policy = backup_policy(db)
                if _auto_backup_due(policy):
                    result = create_backup("zip", "auto")
                    db.execute(
                        "INSERT INTO settings (key, value) VALUES ('backup_auto_last_run_at', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (result["backup_time"],),
                    )
                    db.commit()
        except Exception:
            pass
        time.sleep(60)


def _auto_backup_due(policy: dict) -> bool:
    if not policy["enabled"]:
        return False
    now = datetime.now()
    try:
        hour, minute = [int(item) for item in policy["time"].split(":", 1)]
    except ValueError:
        hour, minute = 3, 0
    if (now.hour, now.minute) < (hour, minute):
        return False
    last_run_at = policy.get("last_run_at")
    last = None
    if last_run_at:
        try:
            last = datetime.fromisoformat(last_run_at)
        except ValueError:
            last = None
    if policy["frequency"] == "weekly":
        if now.weekday() != int(policy.get("weekday") or 0):
            return False
        return last is None or last.isocalendar()[:2] != now.isocalendar()[:2]
    return last is None or last.date() != now.date()


def _current_retention_count() -> int:
    try:
        with connect() as db:
            return backup_policy(db)["retention_count"]
    except sqlite3.Error:
        return 7


async def _save_upload_to_temp(file: UploadFile) -> Path:
    filename = file.filename or ""
    if not filename.endswith((".zip", ".tar.gz", ".tgz")):
        raise HTTPException(status_code=422, detail="仅支持上传 zip 或 tar.gz 备份文件")
    suffix = ".tar.gz" if filename.endswith((".tar.gz", ".tgz")) else ".zip"
    fd, temp_name = tempfile.mkstemp(prefix="cloud-print-backup-upload-", suffix=suffix)
    path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                target.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _write_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in source.rglob("*"):
            if child.is_file():
                archive.write(child, child.relative_to(source).as_posix())


def _write_tar_gz(source: Path, target: Path) -> None:
    with tarfile.open(target, "w:gz") as archive:
        for child in source.iterdir():
            archive.add(child, arcname=child.name)


def _extract_archive(path: Path, target: Path) -> None:
    target.mkdir(parents=True)
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            _validate_zip_members(archive)
            archive.extractall(target)
    elif path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            _validate_tar_members(archive)
            archive.extractall(target)
    else:
        raise HTTPException(status_code=422, detail="备份文件格式不受支持")


def _validate_zip_members(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        _validate_archive_member(member.filename)


def _validate_tar_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        _validate_archive_member(member.name)
        if member.issym() or member.islnk():
            raise HTTPException(status_code=422, detail="备份文件包含不安全的链接")


def _validate_archive_member(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=422, detail="备份文件包含不安全路径")


def _read_and_validate_manifest(extracted: Path) -> dict:
    manifest_path = extracted / BACKUP_MANIFEST
    if not manifest_path.exists():
        raise HTTPException(status_code=422, detail="备份缺少 manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="备份 manifest 格式错误") from exc
    if manifest.get("data_version") != BACKUP_DATA_VERSION:
        raise HTTPException(status_code=422, detail="备份数据版本不兼容")
    database_file = manifest.get("database_file")
    if not isinstance(database_file, str) or Path(database_file).is_absolute() or ".." in Path(database_file).parts:
        raise HTTPException(status_code=422, detail="备份数据库路径无效")
    return manifest


def _validate_restore_payload(extracted: Path, manifest: dict) -> None:
    database_path = extracted / manifest["database_file"]
    try:
        connection = sqlite3.connect(database_path)
        expected_tables = {"users", "files", "orders", "settings"}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not expected_tables.issubset(tables):
            raise HTTPException(status_code=422, detail="备份数据库缺少必要数据表")
    except sqlite3.Error as exc:
        raise HTTPException(status_code=422, detail="备份数据库无法读取") from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass


def _snapshot_current_state(target: Path) -> None:
    target.mkdir(parents=True)
    settings = get_settings()
    manifest: dict[str, object] = {
        "database_file": f"database/{settings.database_path.name}",
        "content": {
            "database": settings.database_path.exists(),
            "uploads": settings.upload_dir.resolve().exists(),
            "logs": log_root().exists(),
            "config_files": [],
        },
    }
    if settings.database_path.exists():
        database_dir = target / "database"
        database_dir.mkdir()
        _copy_sqlite_database(settings.database_path, database_dir / settings.database_path.name)
    upload_dir = settings.upload_dir.resolve()
    if upload_dir.exists():
        shutil.copytree(upload_dir, target / "uploads", symlinks=False)
    logs = log_root()
    if logs.exists():
        shutil.copytree(logs, target / "logs", symlinks=False)
    config_dir = target / "config"
    config_dir.mkdir()
    repo_root = Path.cwd().resolve()
    for relative in BACKUP_CONFIG_FILES:
        source = repo_root / relative
        if source.exists() and source.is_file():
            destination = config_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest["content"]["config_files"].append(relative)
    _copy_settings_file(config_dir, manifest["content"], settings)
    (target / BACKUP_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _rollback_manifest(rollback: Path) -> dict:
    return json.loads((rollback / BACKUP_MANIFEST).read_text(encoding="utf-8"))


def _apply_restore_payload(source: Path, manifest: dict) -> None:
    settings = get_settings()
    database_source = source / manifest["database_file"]
    content = manifest.get("content") or {}
    if database_source.exists():
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database_source, settings.database_path)
    elif not content.get("database") and settings.database_path.exists():
        settings.database_path.unlink()

    _replace_directory(source / "uploads", settings.upload_dir.resolve(), bool(content.get("uploads")))
    _replace_directory(source / "logs", log_root(), bool(content.get("logs")))
    _restore_config_files(source / "config")


def _replace_directory(source: Path, target: Path, should_exist: bool = True) -> None:
    if source.exists():
        target.mkdir(parents=True, exist_ok=True)
        _clear_directory_contents(target)
        for child in source.iterdir():
            destination = target / child.name
            if child.is_dir():
                shutil.copytree(child, destination, symlinks=False)
            else:
                shutil.copy2(child, destination)
        return
    if target.exists():
        _clear_directory_contents(target)
        if not should_exist:
            try:
                target.rmdir()
            except OSError:
                pass
    elif should_exist:
        target.mkdir(parents=True, exist_ok=True)


def _clear_directory_contents(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _restore_config_files(config_source: Path) -> None:
    if not config_source.exists():
        return
    settings = get_settings()
    repo_root = Path.cwd().resolve()
    for source in config_source.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(config_source)
        name = relative.as_posix()
        if name == BACKUP_SETTINGS_FILE:
            # config.json 写回它当前所在位置（config 目录），并且触发热加载
            target = settings.config_file
        elif name in BACKUP_CONFIG_FILES:
            target = repo_root / relative
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _backup_file_info(path: Path, manifest: dict | None = None) -> dict:
    manifest = manifest or _read_archive_manifest_safe(path)
    stat = path.stat()
    backup_time = manifest.get("backup_time") if manifest else ""
    return {
        "filename": path.name,
        "backup_time": backup_time or datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "data_version": manifest.get("data_version", "unknown") if manifest else "unknown",
        "archive_format": manifest.get("archive_format", "zip" if path.name.endswith(".zip") else "tar.gz") if manifest else "",
        "created_by": manifest.get("created_by", "") if manifest else "",
        "content": manifest.get("content", {}) if manifest else {},
        "download_url": f"/api/admin/backups/{path.name}/download",
    }


def _read_archive_manifest_safe(path: Path) -> dict | None:
    try:
        if path.name.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                with archive.open(BACKUP_MANIFEST) as manifest:
                    return json.loads(manifest.read().decode("utf-8"))
        if path.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(path, "r:gz") as archive:
                member = archive.getmember(BACKUP_MANIFEST)
                stream = archive.extractfile(member)
                if stream:
                    return json.loads(stream.read().decode("utf-8"))
    except Exception:
        return None
    return None


def _manifest_response(manifest: dict, path: Path) -> dict:
    return {
        "filename": path.name,
        "backup_time": manifest.get("backup_time", ""),
        "data_version": manifest.get("data_version", ""),
        "archive_format": manifest.get("archive_format", ""),
        "created_by": manifest.get("created_by", ""),
        "content": manifest.get("content", {}),
    }


def _is_backup_archive(path: Path) -> bool:
    return path.name.endswith((".zip", ".tar.gz", ".tgz")) and path.name.startswith("backup_")


def _bool_setting(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}
