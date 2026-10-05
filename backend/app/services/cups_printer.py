import gzip
import io
import os
import re
import socket
import tarfile
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..config import get_settings
from ..utils.cups_utils import (
    create_cups_connection,
    cups_call,
    cups_error_message,
    is_cups_permission_error,
    get_cups_config,
)

_scan_cache = {}
_scan_cache_lock = threading.Lock()
_SCAN_CACHE_TTL = 30

try:
    import cups
except ImportError:  # pragma: no cover - depends on system libcups
    cups = None


ALLOWED_URI_SCHEMES = {"ipp", "ipps", "socket", "lpd", "usb", "dnssd"}
DRIVERLESS_ID = "everywhere"
DRIVERLESS_PROTOCOLS = {"ipp", "ipps", "dnssd"}
LEGACY_PROTOCOLS = {"socket", "lpd", "usb"}
GENERIC_DRIVER_WORDS = {"generic"}
DRIVER_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
PPD_FILE_MAX_BYTES = 10 * 1024 * 1024
PPD_TEXT_SCAN_BYTES = 512 * 1024
DRIVER_ARCHIVE_MAX_PPDS = 100

BRAND_PROFILES = {
    "hp": {
        "label": "HP",
        "aliases": ["hp", "hewlett packard", "hewlett-packard", "laserjet", "deskjet", "officejet", "pagewide", "photosmart"],
        "preferred": ["hplip", "hpijs", "laserjet", "deskjet", "officejet", "pcl", "postscript", "foomatic"],
    },
    "huawei": {
        "label": "HUAWEI",
        "aliases": ["huawei", "pixlab", "cv81", "x1", "v1", "b5"],
        "preferred": ["airprint", "driverless", "everywhere", "mopria", "ipp"],
    },
    "canon": {
        "label": "Canon",
        "aliases": ["canon", "pixma", "imageclass", "imagerunner", "lbp"],
        "preferred": ["canon", "cnij", "ufr", "gutenprint", "postscript", "pcl"],
    },
    "epson": {
        "label": "Epson",
        "aliases": ["epson", "stylus", "ecotank", "workforce"],
        "preferred": ["epson", "escpr", "gutenprint", "ijs", "postscript"],
    },
    "brother": {
        "label": "Brother",
        "aliases": ["brother", "hl-", "dcp", "mfc"],
        "preferred": ["brother", "brlaser", "gutenprint", "postscript", "pcl"],
    },
    "samsung": {
        "label": "Samsung",
        "aliases": ["samsung", "xpress"],
        "preferred": ["samsung", "splix", "postscript", "pcl"],
    },
    "ricoh": {
        "label": "Ricoh",
        "aliases": ["ricoh", "aficio", "savin", "lanier", "gestetner"],
        "preferred": ["ricoh", "postscript", "pcl", "pxlmono"],
    },
    "xerox": {
        "label": "Xerox",
        "aliases": ["xerox", "fuji xerox", "fujifilm", "docuprint", "docucentre"],
        "preferred": ["xerox", "fuji", "postscript", "pcl"],
    },
    "kyocera": {
        "label": "Kyocera",
        "aliases": ["kyocera", "ecosys"],
        "preferred": ["kyocera", "postscript", "pcl"],
    },
    "lenovo": {
        "label": "Lenovo",
        "aliases": ["lenovo", "联想"],
        "preferred": ["lenovo", "postscript", "pcl", "gutenprint"],
    },
    "pantum": {
        "label": "Pantum",
        "aliases": ["pantum", "奔图"],
        "preferred": ["pantum", "postscript", "pcl"],
    },
    "lexmark": {
        "label": "Lexmark",
        "aliases": ["lexmark"],
        "preferred": ["lexmark", "postscript", "pcl"],
    },
    "oki": {
        "label": "OKI",
        "aliases": ["oki", "okidata"],
        "preferred": ["oki", "postscript", "pcl"],
    },
    "sharp": {
        "label": "Sharp",
        "aliases": ["sharp"],
        "preferred": ["sharp", "postscript", "pcl"],
    },
    "konica": {
        "label": "Konica Minolta",
        "aliases": ["konica", "minolta", "bizhub"],
        "preferred": ["konica", "minolta", "postscript", "pcl"],
    },
    "toshiba": {
        "label": "Toshiba",
        "aliases": ["toshiba", "e-studio", "estudio"],
        "preferred": ["toshiba", "postscript", "pcl"],
    },
    "zebra": {
        "label": "Zebra",
        "aliases": ["zebra", "zpl"],
        "preferred": ["zebra", "zpl", "driverless"],
    },
    "dymo": {
        "label": "DYMO",
        "aliases": ["dymo", "labelwriter"],
        "preferred": ["dymo", "labelwriter", "driverless"],
    },
}

BRAND_DRIVER_HINTS = {
    "hp": {
        "packages": ["hplip", "printer-driver-hpcups", "printer-driver-hpijs"],
        "hint": "HP LaserJet/DeskJet/OfficeJet 传统 USB、Socket、LPD 队列建议安装 HPLIP；新款 AirPrint/Mopria 机型优先用 IPP Everywhere。",
    },
    "huawei": {
        "packages": [],
        "hint": "HUAWEI PixLab X1/X1 Pro/V1 系列必须使用 IPP Everywhere/AirPrint/Mopria 免驱模式，连接 URI 建议使用 ipp://<IP>/ipp/print。请确保 CUPS 容器已安装 cups-browsed、libcupsfilters1、libqpdf1，且过滤器权限正确（chmod 755 /usr/lib/cups/filter/*）。若出现 'Filter failed' 错误，请检查 CUPS 日志确认缺少哪些依赖库。",
    },
    "canon": {
        "packages": ["printer-driver-gutenprint", "cnijfilter2", "ufr2"],
        "hint": "Canon PIXMA 通常可用 Gutenprint/厂商 cnijfilter，imageCLASS/imageRUNNER 常见 UFR II、PCL 或 PostScript 驱动。",
    },
    "epson": {
        "packages": ["printer-driver-escpr", "printer-driver-gutenprint"],
        "hint": "Epson EcoTank/WorkForce 优先安装 ESC/P-R 驱动；老款喷墨可用 Gutenprint。",
    },
    "brother": {
        "packages": ["printer-driver-brlaser", "printer-driver-ptouch", "brother-lpr-drivers"],
        "hint": "Brother HL/DCP/MFC 激光机可先安装 brlaser；标签机查看 ptouch；部分机型需要 Brother 官方 LPR/CUPS 包。",
    },
    "samsung": {
        "packages": ["printer-driver-splix"],
        "hint": "Samsung/Xpress 老款激光机常用 SPLIX；支持 AirPrint/Mopria 的新队列优先用 IPP Everywhere。",
    },
    "ricoh": {
        "packages": ["printer-driver-postscript-hp", "printer-driver-pxljr"],
        "hint": "Ricoh/Aficio 多功能机优先尝试 PostScript 或 PCL/PXL；如果后台选项缺失，请安装厂商 PPD。",
    },
    "xerox": {
        "packages": ["printer-driver-postscript-hp", "printer-driver-foo2zjs"],
        "hint": "Xerox/Fuji Xerox/Fujifilm 多数办公机优先尝试 PostScript/PCL；DocuPrint 老机型可能需要厂商 PPD。",
    },
    "kyocera": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "Kyocera ECOSYS 通常支持 PostScript/PCL；高级装订/纸盒选项建议导入 Kyocera PPD。",
    },
    "lenovo": {
        "packages": ["printer-driver-brlaser", "printer-driver-gutenprint"],
        "hint": "Lenovo 打印机常见 Brother/Pantum/OEM 兼容方案；优先尝试 IPP Everywhere、brlaser 或厂商 PPD。",
    },
    "pantum": {
        "packages": ["pantum-driver"],
        "hint": "Pantum/奔图许多机型需要厂商 CUPS 驱动或 PPD；若支持 IPP/AirPrint，优先使用免驱。",
    },
    "lexmark": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "Lexmark 办公机多支持 PostScript/PCL；高级功能建议导入 Lexmark PPD。",
    },
    "oki": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "OKI/OKIDATA 优先尝试 PostScript/PCL；标签或特殊纸张配置建议使用厂商 PPD。",
    },
    "sharp": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "Sharp 复合机通常用 PostScript/PCL；双面、纸盒、装订选项建议导入厂商 PPD。",
    },
    "konica": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "Konica Minolta bizhub 通常支持 PostScript/PCL；高级分页/装订建议使用厂商 PPD。",
    },
    "toshiba": {
        "packages": ["printer-driver-postscript-hp"],
        "hint": "Toshiba e-STUDIO 通常支持 PostScript/PCL；企业功能建议导入 Toshiba PPD。",
    },
    "zebra": {
        "packages": ["printer-driver-zebra", "printer-driver-cups-pdf"],
        "hint": "Zebra 标签机优先确认 ZPL/EPL 模式；普通办公 PDF 打印和标签打印的驱动不能混用。",
    },
    "dymo": {
        "packages": ["printer-driver-dymo"],
        "hint": "DYMO LabelWriter 建议安装 DYMO CUPS 驱动，并按标签纸尺寸配置默认介质。",
    },
}


def _diagnostic(source: str, ok: bool, message: str, hint: str = "") -> dict[str, object]:
    return {"source": source, "ok": ok, "message": message, "hint": hint}


def _metadata_fallback_diagnostics(detail: dict[str, object] | None, message: str, hint: str = "") -> list[dict[str, object]]:
    diagnostics = []
    if isinstance(detail, dict):
        for item in detail.get("diagnostics") or []:
            if not isinstance(item, dict):
                continue
            item_message = str(item.get("message") or "")
            item_hint = str(item.get("hint") or "")
            if "打印机不存在" in item_message or "打印机不存在" in item_hint:
                continue
            diagnostics.append(item)
    diagnostics.append(_diagnostic("cups-metadata-fallback", False, message, hint))
    return diagnostics


def _cups_server() -> str:
    config = get_cups_config()
    return config["server"]


def _configured_path(setting_name: str, fallback: Path) -> Path:
    """驱动目录只来自 config/config.json（cups_driver_dir / cups-driver 目录）。"""

    value = getattr(get_settings(), setting_name, fallback)
    return Path(value).expanduser()


def _driver_upload_dir() -> Path:
    return _configured_path("cups_driver_upload_dir", Path("storage/cups-drivers"))


def _driver_search_dirs() -> list[Path]:
    candidates = [
        _driver_upload_dir(),
        _configured_path("cups_driver_dir", Path("storage/cups-drivers")),
    ]
    rows = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key and key not in seen:
            rows.append(path)
            seen.add(key)
    return rows


def _missing_cups_detail(action: str) -> dict[str, object]:
    return {
        "success": False,
        "error": f"{action}失败：后端未安装 pycups 或 libcups。",
        "diagnostics": [
            _diagnostic(
                "pycups",
                False,
                "pycups 不可用",
                "请安装 pycups，并确认 Docker 镜像包含 libcups2-dev/libcups2。",
            )
        ],
    }


def _cups_error_message(exc: Exception, fallback: str) -> str:
    return cups_error_message(exc, fallback)


def _is_cups_permission_error(message: str) -> bool:
    return is_cups_permission_error(message)


def _detail_has_permission_error(detail: dict[str, object] | None) -> bool:
    if not isinstance(detail, dict):
        return False
    values = [str(detail.get("error") or ""), str(detail.get("message") or "")]
    for item in detail.get("diagnostics") or []:
        if isinstance(item, dict):
            values.append(str(item.get("message") or ""))
            values.append(str(item.get("hint") or ""))
    return any(_is_cups_permission_error(value) for value in values)


def _connection(action: str = "连接 CUPS"):
    conn, error = create_cups_connection()
    if conn is None:
        raise RuntimeError(error or _missing_cups_detail(action)["error"])
    return conn


def _call_cups(action: str, callback):
    result, detail = cups_call(action, callback)
    if detail.get("success"):
        diagnostics = detail.get("diagnostics", [])
        diagnostics.append(_diagnostic("pycups", True, f"{action}成功。"))
        return result, {"success": True, "diagnostics": diagnostics}
    
    message = detail.get("error", f"{action}失败")
    error = message
    hint = f"请确认 CUPS 服务可访问，当前 CUPS_SERVER={_cups_server() or '本机默认'}。"
    
    raw_error = detail.get("raw_error", "")
    ipp_diagnostics = []
    
    if detail.get("diagnostics"):
        for diag in detail["diagnostics"]:
            if diag.get("source") == "pycups-ipp":
                ipp_diagnostics.append(diag)
    
    if _is_cups_permission_error(message):
        error = f"CUPS 拒绝执行“{action}”：当前后端没有足够的 CUPS 管理权限。"
        hint = "如果打印机已在系统中添加，可直接使用现有队列；否则请在宿主机 CUPS/系统打印机设置中授权后端或先手动添加该打印机。"
        message = "CUPS 拒绝当前操作，后端没有足够的打印机管理权限。"
    elif "1280" in message or "server-error-internal-error" in message.lower():
        hint = "CUPS 服务器内部错误。可能原因：1) PPD 驱动文件不存在或格式错误；2) CUPS 服务器配置问题；3) 打印机 URI 格式不正确；4) 驱动名称无效。"
        if raw_error:
            hint += f" 原始错误: {raw_error}"
    
    diagnostics = [
        _diagnostic(
            "pycups",
            False,
            message,
            hint,
        )
    ]
    diagnostics.extend(ipp_diagnostics)
    
    return None, {
        "success": False,
        "error": error,
        "diagnostics": diagnostics,
        "raw_error": raw_error,
    }


def _state(value) -> tuple[str, str]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown", "未知"
    if number == 3:
        return "idle", "空闲"
    if number == 4:
        return "processing", "正在打印"
    if number == 5:
        return "stopped", "已停止"
    return "unknown", "未知"


def _job_state(value) -> tuple[str, str]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown", "未知"
    return {
        3: ("pending", "等待中"),
        4: ("held", "已暂停"),
        5: ("processing", "正在打印"),
        6: ("stopped", "已停止"),
        7: ("canceled", "已取消"),
        8: ("aborted", "已中止"),
        9: ("completed", "已完成"),
    }.get(number, ("unknown", "未知"))


def _attr_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _attr_first(value, default: str = "") -> str:
    values = _attr_values(value)
    return values[0] if values else default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _queue_uri(name: str) -> str:
    server = _cups_server() or "localhost"
    return f"ipp://{server}/printers/{name}"


def _attributes(conn, name: str) -> dict[str, object]:
    try:
        return dict(conn.getPrinterAttributes(name))
    except TypeError:
        return dict(conn.getPrinterAttributes(printer=name))


def _default_name(conn) -> str:
    try:
        return str(conn.getDefault() or "")
    except Exception:
        return ""


def _jobs_for_printer(conn, name: str, which_jobs: str = "not-completed", limit: int = 200) -> list[dict[str, object]]:
    jobs = conn.getJobs(which_jobs=which_jobs, my_jobs=False)
    rows = []
    for job_id, attrs in jobs.items():
        destination = str(attrs.get("job-printer-name") or attrs.get("printer-uri") or "")
        printer_uri = str(attrs.get("job-printer-uri") or attrs.get("printer-uri") or "")
        if destination and destination != name and not printer_uri.endswith(f"/{name}"):
            continue
        created = attrs.get("time-at-creation") or attrs.get("time-at-processing") or 0
        state, state_text = _job_state(attrs.get("job-state"))
        if state == "unknown" and which_jobs == "completed":
            state, state_text = "completed", "已完成"
        rows.append(
            {
                "id": job_id,
                "title": str(attrs.get("job-name") or attrs.get("document-name-supplied") or f"job-{job_id}"),
                "user": str(attrs.get("job-originating-user-name") or ""),
                "state": state,
                "state_text": state_text,
                "created_at": datetime.fromtimestamp(created).isoformat() if created else "",
                "size": _safe_int(attrs.get("job-k-octets"), 0) * 1024,
            }
        )
    return rows[:limit]


def _metadata_rows(db) -> dict[str, dict[str, object]]:
    rows = db.execute("SELECT * FROM printers").fetchall()
    return {row["name"]: dict(row) for row in rows}


def _metadata_for(db, name: str) -> dict[str, object]:
    row = db.execute("SELECT * FROM printers WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else {}


def _printer_object_from_metadata(meta: dict[str, object], default_name: str = "") -> dict[str, object]:
    name = str(meta.get("name") or "")
    is_enabled = _safe_bool(meta.get("is_enabled"), True)
    accepting_jobs = _safe_bool(meta.get("accepting_jobs"), is_enabled)
    return {
        "name": name,
        "display_name": str(meta.get("description") or name),
        "uri": str(meta.get("uri") or ""),
        "cups_uri": _queue_uri(name),
        "driver": str(meta.get("driver") or DRIVERLESS_ID),
        "driver_label": str(meta.get("driver") or DRIVERLESS_ID),
        "location": str(meta.get("location") or ""),
        "description": str(meta.get("description") or ""),
        "state": "idle" if is_enabled else "stopped",
        "state_text": "空闲" if is_enabled else "已停止",
        "state_message": "",
        "state_reasons": ["none"],
        "is_default": bool(default_name) and name == default_name,
        "is_cups_default": bool(default_name) and name == default_name,
        "is_enabled": is_enabled,
        "accepting_jobs": accepting_jobs,
        # 【新增功能】打印机属性（后台配置）：是否支持彩色打印 / 是否支持自动双面打印。
        # 老库默认彩色=否、自动双面=是，保证升级后原有打印流程不变。
        "is_support_color": _safe_bool(meta.get("is_support_color"), False),
        "is_support_auto_duplex": _safe_bool(meta.get("is_support_auto_duplex"), True),
        "installed": True,
        "queued_jobs": 0,
        "marker_names": [],
        "marker_types": [],
        "marker_levels": [],
        "marker_colors": [],
        "media_ready": ["iso_a4_210x297mm"],
        "last_test_at": str(meta.get("last_test_at") or meta.get("last_checked_at") or ""),
        "last_test_success": None if meta.get("last_test_success") is None else _safe_bool(meta.get("last_test_success")),
        "last_test_note": str(meta.get("last_test_note") or ""),
        "last_error": str(meta.get("last_error") or ""),
        "last_status": str(meta.get("last_status") or ""),
        "updated_at": str(meta.get("updated_at") or ""),
    }


def _metadata_only_printer_object(meta: dict[str, object], default_name: str = "", include_attrs: bool = False) -> dict[str, object]:
    row = _printer_object_from_metadata(meta, default_name)
    row.update(
        {
            "installed": False,
            "state": "unknown",
            "state_text": "等待 CUPS 同步",
            "state_message": "CUPS 列表暂未返回该队列，已显示本地保存的打印机配置。",
            "state_reasons": ["metadata-only"],
            "queued_jobs": 0,
            "is_cups_default": False,
        }
    )
    if include_attrs:
        row.update(
            {
                "uptime_seconds": 0,
                "state_duration_seconds": 0,
                "firmware_version": "",
                "supported_options": {},
                "attributes": {},
                "jobs": [],
            }
        )
    return row


def _save_metadata(
    db,
    name: str,
    uri: str = "",
    driver: str = DRIVERLESS_ID,
    location: str = "",
    description: str = "",
    is_default: bool = False,
    is_enabled: bool = True,
    accepting_jobs: bool = True,
    is_support_color: bool | None = None,
    is_support_auto_duplex: bool | None = None,
) -> None:
    """写入打印机元数据。

    【新增功能】is_support_color / is_support_auto_duplex 为「是否支持彩色打印 / 自动双面打印」：
      - None：不修改（UPDATE 走 COALESCE 保留原值；INSERT 用默认值 彩色=否、自动双面=是），
        这样其它调用点（删除兜底、驱动同步等）无需关心这两个新字段也不会把它们清零。
      - True/False：写入 1/0。
    """
    now = datetime.utcnow().isoformat()
    existing = db.execute("SELECT id FROM printers WHERE name = ?", (name,)).fetchone()
    color_value = 0 if is_support_color is None else (1 if is_support_color else 0)
    duplex_value = 1 if is_support_auto_duplex is None else (1 if is_support_auto_duplex else 0)
    if existing:
        db.execute(
            """
            UPDATE printers
            SET uri = ?, driver = ?, location = ?, description = ?, is_default = ?, is_enabled = ?, accepting_jobs = ?, hidden = 0,
                is_support_color = COALESCE(?, is_support_color),
                is_support_auto_duplex = COALESCE(?, is_support_auto_duplex),
                updated_at = ?
            WHERE name = ?
            """,
            (
                uri,
                driver,
                location,
                description,
                1 if is_default else 0,
                1 if is_enabled else 0,
                1 if accepting_jobs else 0,
                None if is_support_color is None else color_value,
                None if is_support_auto_duplex is None else duplex_value,
                now,
                name,
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO printers (
                id, name, uri, driver, location, description, is_default, is_enabled, accepting_jobs,
                is_support_color, is_support_auto_duplex, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                name,
                uri,
                driver,
                location,
                description,
                1 if is_default else 0,
                1 if is_enabled else 0,
                1 if accepting_jobs else 0,
                color_value,
                duplex_value,
                now,
                now,
            ),
        )


def _save_local_metadata(
    db,
    name: str,
    uri: str = "",
    driver: str = DRIVERLESS_ID,
    location: str = "",
    description: str = "",
    is_default: bool = False,
    is_enabled: bool = True,
    accepting_jobs: bool = True,
    hidden: bool = False,
    is_support_color: bool | None = None,
    is_support_auto_duplex: bool | None = None,
) -> None:
    # 【新增功能】保留本地打印机配置时一并保存彩色/自动双面能力（None=保持原值）。
    _save_metadata(db, name, uri, driver, location, description or name, is_default, is_enabled, accepting_jobs, is_support_color, is_support_auto_duplex)
    db.execute("UPDATE printers SET hidden = ? WHERE name = ?", (1 if hidden else 0, name))


def _sync_default_setting(db, name: str) -> None:
    db.execute("UPDATE settings SET value = ? WHERE key = 'default_printer'", (name,))
    db.execute("UPDATE printers SET is_default = CASE WHEN name = ? THEN 1 ELSE 0 END", (name,))


def _clear_default_setting(db, name: str) -> bool:
    row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    if row and row["value"] == name:
        db.execute("UPDATE settings SET value = '' WHERE key = 'default_printer'")
        db.execute("UPDATE printers SET is_default = 0 WHERE name = ?", (name,))
        return True
    return False


def _printer_object(name: str, attrs: dict[str, object], default_name: str, meta: dict[str, object] | None = None, include_attrs: bool = False) -> dict[str, object]:
    meta = meta or {}
    state, state_text = _state(attrs.get("printer-state"))
    uri = str(attrs.get("device-uri") or meta.get("uri") or "")
    description = str(attrs.get("printer-info") or meta.get("description") or "")
    location = str(attrs.get("printer-location") or meta.get("location") or "")
    make_model = str(attrs.get("printer-make-and-model") or "")
    driver = str(meta.get("driver") or attrs.get("printer-driver-installer") or DRIVERLESS_ID)
    accepting_jobs = _safe_bool(attrs.get("printer-is-accepting-jobs"), True)
    state_reasons = _attr_values(attrs.get("printer-state-reasons")) or ["none"]
    marker_levels = [_safe_int(value, -1) for value in _attr_values(attrs.get("marker-levels")) if _safe_int(value, -1) >= 0]
    row = {
        "name": name,
        "display_name": description or name,
        "uri": uri,
        "cups_uri": _attr_first(attrs.get("printer-uri-supported"), _queue_uri(name)),
        "driver": driver,
        "driver_label": make_model or driver,
        "location": location,
        "description": description,
        "state": state,
        "state_text": state_text,
        "state_message": str(attrs.get("printer-state-message") or ""),
        "state_reasons": state_reasons,
        "is_default": bool(default_name) and name == default_name,
        "is_cups_default": bool(default_name) and name == default_name,
        "is_enabled": state != "stopped",
        "accepting_jobs": accepting_jobs,
        # 【新增功能】打印机属性（后台配置）：是否支持彩色/自动双面，随打印机列表与详情一起返回
        "is_support_color": _safe_bool(meta.get("is_support_color"), False),
        "is_support_auto_duplex": _safe_bool(meta.get("is_support_auto_duplex"), True),
        "installed": True,
        "queued_jobs": _safe_int(attrs.get("queued-job-count"), 0),
        "marker_names": _attr_values(attrs.get("marker-names")),
        "marker_types": _attr_values(attrs.get("marker-types")),
        "marker_levels": marker_levels,
        "marker_colors": _attr_values(attrs.get("marker-colors")),
        "media_ready": _attr_values(attrs.get("media-ready")),
        "last_test_at": str(meta.get("last_test_at") or meta.get("last_checked_at") or ""),
        "last_test_success": None if meta.get("last_test_success") is None else _safe_bool(meta.get("last_test_success")),
        "last_test_note": str(meta.get("last_test_note") or ""),
        "last_error": str(meta.get("last_error") or ""),
        "last_status": str(meta.get("last_status") or ""),
        "updated_at": str(meta.get("updated_at") or ""),
    }
    if include_attrs:
        row.update(
            {
                "state_duration_seconds": _safe_int(datetime.utcnow().timestamp(), 0) - _safe_int(attrs.get("printer-state-change-time"), 0) if attrs.get("printer-state-change-time") else 0,
                "uptime_seconds": _safe_int(datetime.utcnow().timestamp(), 0) - _safe_int(attrs.get("printer-up-time"), 0) if attrs.get("printer-up-time") else 0,
                "firmware_version": str(attrs.get("printer-firmware-string-version") or attrs.get("printer-firmware-name") or ""),
                "supported_options": {
                    "sides-supported": _attr_values(attrs.get("sides-supported")),
                    "media-supported": _attr_values(attrs.get("media-supported")),
                    "print-color-mode-supported": _attr_values(attrs.get("print-color-mode-supported")),
                },
                "attributes": {key: ", ".join(_attr_values(value)) for key, value in attrs.items()},
            }
        )
    return row


def printer_system(db) -> dict[str, object]:
    default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    db_default = default_row["value"] if default_row else ""
    result = {
        "success": True,
        "cups_server": _cups_server(),
        "pycups_available": cups is not None,
        "connected": False,
        "default_printer": "",
        "printer_count": 0,
        "diagnostics": [],
    }
    if cups is None:
        result["diagnostics"] = _missing_cups_detail("检查 CUPS")["diagnostics"]
        return result

    def read(conn):
        printers = conn.getPrinters()
        return {"default": _default_name(conn), "count": len(printers)}

    data, detail = _call_cups("检查 CUPS", read)
    result["diagnostics"] = detail.get("diagnostics", [])
    if data is not None and detail.get("success"):
        result.update({"connected": True, "printer_count": data["count"]})
    else:
        result["diagnostics"] = detail.get("diagnostics", [])
    # 应用内 default_printer 设置是默认打印机的唯一权威来源；取消默认后为空即"暂未设置"，
    # 不再回退到 CUPS 自身的默认。
    result["default_printer"] = db_default
    return result


def list_printers(db, include_attrs: bool = False, include_hidden: bool = False) -> list[dict[str, object]]:
    def read(conn):
        # 应用内的 default_printer 设置是默认打印机的唯一权威来源；
        # 取消默认后该设置为空，此时不再回退到 CUPS 自身的默认，保证"暂未设置默认打印机"生效。
        default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
        default_name = (default_row["value"] if default_row else "") or ""
        meta_rows = _metadata_rows(db)
        output = []
        seen = set()
        for name, base_attrs in conn.getPrinters().items():
            meta = meta_rows.get(name)
            if meta and _safe_bool(meta.get("hidden")) and not include_hidden:
                continue
            attrs = dict(base_attrs or {})
            try:
                attrs.update(_attributes(conn, name))
            except Exception:
                pass
            output.append(_printer_object(name, attrs, default_name, meta, include_attrs))
            seen.add(name)
        for name, meta in meta_rows.items():
            if name in seen:
                continue
            if _safe_bool(meta.get("hidden")) and not include_hidden:
                continue
            output.append(_metadata_only_printer_object(meta, default_name, include_attrs))
        return output

    rows, detail = _call_cups("读取打印机列表", read)
    if rows is None:
        meta_rows = _metadata_rows(db)
        if meta_rows:
            default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
            default_name = default_row["value"] if default_row else ""
            return [
                _metadata_only_printer_object(meta, default_name, include_attrs)
                for meta in meta_rows.values()
                if include_hidden or not _safe_bool(meta.get("hidden"))
            ]
        raise RuntimeError(detail)
    return rows


def get_printer(db, name: str) -> dict[str, object]:
    meta = _metadata_for(db, name)
    def read(conn):
        printers = conn.getPrinters()
        if name not in printers:
            if meta:
                default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
                printer = _metadata_only_printer_object(meta, default_row["value"] if default_row else "", True)
                printer["jobs"] = []
                return printer
            raise FileNotFoundError("打印机不存在")
        attrs = dict(printers.get(name) or {})
        attrs.update(_attributes(conn, name))
        printer = _printer_object(name, attrs, _default_name(conn), meta, True)
        printer["jobs"] = _jobs_for_printer(conn, name, "not-completed", 20)
        return printer

    try:
        row, detail = _call_cups("读取打印机详情", read)
    except KeyError:
        raise ValueError("打印机不存在")
    if row is None:
        if meta:
            default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
            printer = _metadata_only_printer_object(meta, default_row["value"] if default_row else "", True)
            printer["jobs"] = []
            return printer
        raise RuntimeError(detail)
    return row


def _connection_type(uri: str) -> str:
    return urlparse(uri).scheme or "unknown"


def _normalized_text(*values: object) -> str:
    text = " ".join(unquote(str(value or "")) for value in values)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _detect_brand(*values: object) -> tuple[str, dict[str, object] | None]:
    text = f" {_normalized_text(*values)} "
    for brand, profile in BRAND_PROFILES.items():
        for alias in profile["aliases"]:
            alias_text = _normalized_text(alias)
            if alias_text and f" {alias_text} " in text:
                return brand, profile
    return "", None


def _model_tokens(*values: object) -> list[str]:
    text = _normalized_text(*values)
    tokens = []
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) < 3 and not token.isdigit():
            continue
        if token in {"printer", "series", "driver", "airprint", "mopria", "everywhere", "generic"}:
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def _driver_haystack(row: dict[str, object]) -> str:
    return _normalized_text(row.get("id"), row.get("label"), row.get("make"), row.get("model"))


def _driver_reason(row: dict[str, object], brand_label: str, connection_type: str, confidence: str) -> str:
    if row["id"] == DRIVERLESS_ID:
        if connection_type in DRIVERLESS_PROTOCOLS:
            return f"{brand_label or '该设备'}支持 IPP/AirPrint/Mopria，优先使用免驱。"
        return "未找到更精确 PPD，使用 IPP Everywhere / AirPrint / Mopria 作为通用免驱。"
    if confidence == "low":
        return f"未发现明显型号匹配，可作为 {connection_type.upper()} 连接的备选 CUPS 驱动。"
    if brand_label:
        return f"已按 {brand_label} 型号和 {connection_type.upper()} 连接匹配到 CUPS 驱动（{confidence}）。"
    return f"已按 {connection_type.upper()} 连接匹配到通用 CUPS 驱动（{confidence}）。"


def _is_generic_driver(row: dict[str, object]) -> bool:
    haystack = _driver_haystack(row)
    make = _normalized_text(row.get("make"))
    return make == "generic" or any(word in haystack for word in GENERIC_DRIVER_WORDS)


def _driver_install_hint(
    row: dict[str, object],
    confidence: str,
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
    info: str = "",
) -> dict[str, object]:
    connection = (connection_type or _connection_type(uri)).lower()
    brand, profile = _detect_brand(make_model, info, uri)
    brand_label = str(profile["label"]) if profile else ""
    hint = BRAND_DRIVER_HINTS.get(brand, {})
    packages = list(hint.get("packages") or [])
    detail = str(hint.get("hint") or "")
    driver_id = str(row.get("id") or "")
    generic = _is_generic_driver(row)
    needs_package = False
    severity = "info"

    if driver_id == DRIVERLESS_ID and connection in DRIVERLESS_PROTOCOLS and confidence in {"high", "medium"}:
        message = f"{brand_label or '该设备'}适合使用免驱队列。"
    elif connection in LEGACY_PROTOCOLS and brand and (confidence == "low" or driver_id == DRIVERLESS_ID):
        needs_package = bool(packages) or brand not in {"huawei"}
        severity = "warning"
        message = f"未找到可靠的 {brand_label} 专用 CUPS 驱动，建议安装/导入厂商驱动后再添加。"
    elif connection in LEGACY_PROTOCOLS and brand and generic:
        needs_package = bool(packages)
        severity = "warning"
        message = f"当前只能匹配到通用驱动；可先打印测试页，若缺少双面/纸盒/色彩选项，请安装 {brand_label} 专用驱动。"
    elif confidence == "low":
        needs_package = bool(packages)
        severity = "warning"
        message = "未找到明显型号匹配的驱动，建议优先使用 IPP Everywhere，或安装厂商 PPD/CUPS 驱动。"
    else:
        message = "已找到可用驱动，添加后建议发送测试页确认纸张、单双面和色彩选项。"

    return {
        "brand": brand,
        "brand_label": brand_label,
        "needs_driver_package": needs_package,
        "severity": severity,
        "message": message,
        "packages": packages,
        "hint": detail,
    }


def _score_driver(
    row: dict[str, object],
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
    info: str = "",
) -> tuple[int, str, str]:
    connection = (connection_type or _connection_type(uri)).lower()
    brand, profile = _detect_brand(make_model, info, uri)
    brand_label = str(profile["label"]) if profile else ""
    haystack = _driver_haystack(row)
    target_text = _normalized_text(make_model, info, uri)
    target_tokens = _model_tokens(make_model, info)
    score = 0

    if row["id"] == DRIVERLESS_ID:
        score = 520
        if connection in DRIVERLESS_PROTOCOLS:
            score += 360
        if "airprint" in target_text or "mopria" in target_text or "driverless" in target_text:
            score += 120
        if brand == "huawei":
            score += 280
            if "/ipp/print" in (uri or ""):
                score += 80
        if connection in LEGACY_PROTOCOLS:
            score -= 400
        confidence = "high" if score >= 850 else "medium"
        return score, confidence, _driver_reason(row, brand_label, connection or "unknown", confidence)

    if brand and profile:
        aliases = [_normalized_text(alias) for alias in profile["aliases"]]
        preferred = [_normalized_text(word) for word in profile["preferred"]]
        if any(alias and alias in haystack for alias in aliases):
            score += 360
        for index, keyword in enumerate(preferred):
            if keyword and keyword in haystack:
                score += max(60, 180 - index * 18)

    for token in target_tokens:
        if token in haystack:
            score += 38 if token.isdigit() else 28
    phrase = _normalized_text(make_model)
    if phrase and phrase in haystack:
        score += 180

    if connection in LEGACY_PROTOCOLS:
        if "pcl" in haystack or "pxl" in haystack:
            score += 155
        if "postscript" in haystack or re.search(r"\bps\b", haystack):
            score += 120
        if "generic" in haystack:
            score += 75
    elif connection in DRIVERLESS_PROTOCOLS:
        if "driverless" in haystack or "airprint" in haystack or "mopria" in haystack:
            score += 120

    if "gutenprint" in haystack:
        score += 35
    if "foomatic" in haystack:
        score += 45
    if row.get("source") == "local-ppd" and score > 0:
        score += 65
    if "raw" in haystack:
        score -= 180

    confidence = "high" if score >= 520 else "medium" if score >= 260 else "low"
    return score, confidence, _driver_reason(row, brand_label, connection or "unknown", confidence)


def _recommend_driver(
    drivers: list[dict[str, object]],
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
    info: str = "",
) -> dict[str, object]:
    rows = drivers or [_driver_row(DRIVERLESS_ID)]
    scored = []
    for row in rows:
        score, confidence, reason = _score_driver(row, make_model, uri, connection_type, info)
        item = {**row, "score": score, "confidence": confidence, "reason": reason}
        scored.append(item)
    scored.sort(key=lambda item: (item["score"], item["id"] == DRIVERLESS_ID), reverse=True)
    best = scored[0] if scored else {**_driver_row(DRIVERLESS_ID), "score": 0, "confidence": "low", "reason": ""}
    install_hint = _driver_install_hint(best, str(best.get("confidence") or "low"), make_model, uri, connection_type, info)
    return {
        "driver": str(best["id"]),
        "label": str(best.get("label") or best["id"]),
        "confidence": str(best.get("confidence") or "low"),
        "reason": str(best.get("reason") or ""),
        "install_hint": install_hint,
        "candidates": [
            {
                "id": str(item["id"]),
                "label": str(item.get("label") or item["id"]),
                "confidence": str(item.get("confidence") or "low"),
                "score": int(item.get("score") or 0),
                "install_hint": _driver_install_hint(item, str(item.get("confidence") or "low"), make_model, uri, connection_type, info),
            }
            for item in scored[:5]
        ],
    }


def _annotate_driver_recommendation(
    rows: list[dict[str, object]],
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
    info: str = "",
) -> dict[str, object] | None:
    if not rows or not (make_model or uri or connection_type or info).strip():
        return None
    recommendation = _recommend_driver(rows, make_model, uri, connection_type, info)
    recommended_id = recommendation["driver"]
    for row in rows:
        score, confidence, reason = _score_driver(row, make_model, uri, connection_type, info)
        row["recommended"] = row["id"] == recommended_id
        row["confidence"] = confidence
        row["recommendation_score"] = score
        row["recommendation_reason"] = reason
        row["install_hint"] = _driver_install_hint(row, confidence, make_model, uri, connection_type, info)
    rows.sort(key=lambda row: (row["recommended"], row.get("recommendation_score", 0), row["id"] == DRIVERLESS_ID), reverse=True)
    return recommendation


def _is_ppd_filename(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(".ppd") or lower.endswith(".ppd.gz")


def _is_driver_archive_filename(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(".zip") or lower.endswith(".tar") or lower.endswith(".tgz") or lower.endswith(".tar.gz")


def _read_ppd_text(path: Path, limit: int = PPD_TEXT_SCAN_BYTES) -> str:
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _ppd_text_from_bytes(filename: str, content: bytes, limit: int = PPD_TEXT_SCAN_BYTES) -> str:
    try:
        if filename.lower().endswith(".gz"):
            with gzip.open(io.BytesIO(content), "rt", encoding="utf-8", errors="ignore") as handle:
                return handle.read(limit)
        return content[:limit].decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _looks_like_ppd(filename: str, content: bytes) -> bool:
    text = _ppd_text_from_bytes(filename, content)
    return "*PPD-Adobe:" in text or "*NickName:" in text or "*ModelName:" in text


def _clean_ppd_value(value: str) -> str:
    value = value.strip().strip('"').strip("'").strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    return value


def _ppd_metadata(path: Path) -> dict[str, object]:
    text = _read_ppd_text(path)
    fields: dict[str, str] = {}
    for key in ["Manufacturer", "ModelName", "NickName", "ShortNickName", "Product", "LanguageVersion"]:
        match = re.search(rf"^\*{key}\s*:\s*(.+)$", text, flags=re.MULTILINE)
        if match:
            fields[key] = _clean_ppd_value(match.group(1))
    nickname = fields.get("NickName") or fields.get("ShortNickName") or fields.get("ModelName") or path.stem
    make = fields.get("Manufacturer") or ""
    model = fields.get("ModelName") or fields.get("Product") or nickname
    language = fields.get("LanguageVersion") or ""
    return {"make": make, "model": model, "label": nickname, "language": language}


def _local_ppd_paths() -> list[Path]:
    paths = []
    seen = set()
    for directory in _driver_search_dirs():
        if not directory.exists() or not directory.is_dir():
            continue
        for suffix in ("*.ppd", "*.PPD", "*.ppd.gz", "*.PPD.GZ"):
            for path in directory.rglob(suffix):
                if not path.is_file():
                    continue
                key = str(path.resolve())
                if key not in seen:
                    paths.append(path)
                    seen.add(key)
    return sorted(paths, key=lambda item: item.name.lower())


def _local_ppd_row(path: Path, include_raw: bool = False) -> dict[str, object]:
    metadata = _ppd_metadata(path)
    row = {
        "id": str(path.resolve()),
        "label": metadata["label"] or path.name,
        "make": metadata["make"],
        "model": metadata["model"] or metadata["label"] or path.stem,
        "recommended": False,
        "source": "local-ppd",
        "filename": path.name,
    }
    if include_raw:
        row["raw"] = {"path": str(path), **metadata}
    return row


def _local_driver_rows(include_raw: bool = False) -> list[dict[str, object]]:
    return [_local_ppd_row(path, include_raw) for path in _local_ppd_paths()]


def _read_driver_rows(conn, include_raw: bool = False) -> list[dict[str, object]]:
    rows = [_driver_row(DRIVERLESS_ID)]
    for driver_id, attrs in conn.getPPDs().items():
        row = _driver_row(driver_id, dict(attrs or {}))
        if include_raw:
            row["raw"] = dict(attrs or {})
        rows.append(row)
    rows.extend(_local_driver_rows(include_raw))
    return rows


def _driver_row(driver_id: str, attrs: dict[str, object] | None = None) -> dict[str, object]:
    attrs = attrs or {}
    make = _attr_first(attrs.get("ppd-make") or attrs.get("make"), "")
    model = _attr_first(attrs.get("ppd-make-and-model") or attrs.get("ppd-product") or attrs.get("ppd-name"), driver_id)
    language = _attr_first(attrs.get("ppd-natural-language"), "")
    label = model or driver_id
    if language and language.lower() not in {"en", "zh", "zh_cn", "zh-cn"}:
        label = f"{label} ({language})"
    if driver_id == DRIVERLESS_ID:
        return {
            "id": DRIVERLESS_ID,
            "label": "IPP Everywhere / AirPrint / Mopria",
            "make": "Generic",
            "model": "Driverless",
            "recommended": True,
            "source": "driverless",
        }
    return {"id": driver_id, "label": label, "make": make, "model": model, "recommended": False, "source": "cups"}


def list_printer_drivers(
    search: str = "",
    limit: int = 50,
    include_raw: bool = False,
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
) -> dict[str, object]:
    query = (search or "").strip().lower()
    target_context = bool((make_model or uri or connection_type).strip())

    cache_key = f"drivers_{query}_{limit}_{include_raw}"
    with _scan_cache_lock:
        if cache_key in _scan_cache:
            cached = _scan_cache[cache_key]
            if time.time() - cached["timestamp"] < _SCAN_CACHE_TTL:
                cached_result = cached["result"]
                if target_context:
                    rows = cached_result.get("drivers", [_driver_row(DRIVERLESS_ID)])
                    recommendation = _annotate_driver_recommendation(rows, make_model, uri, connection_type)
                    return {"success": True, "drivers": rows, "total": len(rows), "recommendation": recommendation, "diagnostics": cached_result.get("diagnostics", [])}
                return cached_result

    def read(conn):
        drivers = _read_driver_rows(conn, include_raw)
        filtered = [row for row in drivers if not query or query in _driver_haystack(row)]
        if not filtered:
            filtered = [_driver_row(DRIVERLESS_ID)]
        recommendation = _annotate_driver_recommendation(filtered, make_model, uri, connection_type) if target_context else None
        return {"drivers": filtered[: max(1, min(limit, 200))], "recommendation": recommendation}

    data, detail = _call_cups("读取 CUPS 驱动列表", read)
    if data is None:
        rows = [_driver_row(DRIVERLESS_ID), *_local_driver_rows(include_raw)]
        if query:
            rows = [row for row in rows if query in _driver_haystack(row)] or [_driver_row(DRIVERLESS_ID)]
        recommendation = _annotate_driver_recommendation(rows, make_model, uri, connection_type) if target_context else None
        rows = rows[: max(1, min(limit, 200))]
        diagnostics = detail.get("diagnostics", [])
    else:
        rows = data["drivers"]
        recommendation = data.get("recommendation")
        diagnostics = detail.get("diagnostics", [])
    result = {"success": True, "drivers": rows, "total": len(rows), "recommendation": recommendation, "diagnostics": diagnostics}

    if not target_context:
        with _scan_cache_lock:
            _scan_cache[cache_key] = {"timestamp": time.time(), "result": result}
    return result


def _safe_ppd_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        raise ValueError("请选择 PPD 驱动文件")
    if not _is_ppd_filename(name):
        raise ValueError("仅支持 .ppd、.ppd.gz 或包含 PPD 的 zip/tar 驱动包")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")
    if not name:
        name = f"driver-{uuid4().hex}.ppd"
    if not _is_ppd_filename(name):
        name = f"{name}.ppd"
    return name[:160]


def _store_ppd_content(filename: str, content: bytes) -> dict[str, object]:
    if len(content) > PPD_FILE_MAX_BYTES:
        raise ValueError("单个 PPD 驱动文件不能超过 10MB")
    if not _looks_like_ppd(filename, content):
        raise ValueError("PPD 文件内容无法识别，请确认文件来自打印机厂商或 CUPS 驱动包")
    safe_name = _safe_ppd_filename(filename)
    target_dir = _driver_upload_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    if target.exists():
        suffix = ".ppd.gz" if target.name.lower().endswith(".ppd.gz") else ".ppd"
        stem = target.name[: -len(suffix)]
        target = target_dir / f"{stem}-{uuid4().hex[:8]}{suffix}"
    target.write_bytes(content)
    return _local_ppd_row(target, include_raw=True)


def _archive_ppd_entries(filename: str, content: bytes) -> list[tuple[str, bytes]]:
    lower = filename.lower()
    entries: list[tuple[str, bytes]] = []
    if lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for info in archive.infolist():
                    if len(entries) >= DRIVER_ARCHIVE_MAX_PPDS:
                        break
                    if info.is_dir() or not _is_ppd_filename(info.filename):
                        continue
                    if info.file_size > PPD_FILE_MAX_BYTES:
                        continue
                    entries.append((Path(info.filename).name, archive.read(info)))
        except zipfile.BadZipFile as exc:
            raise ValueError("驱动压缩包无法读取，请确认 zip 文件完整") from exc
    elif lower.endswith(".tar") or lower.endswith(".tgz") or lower.endswith(".tar.gz"):
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
                for member in archive.getmembers():
                    if len(entries) >= DRIVER_ARCHIVE_MAX_PPDS:
                        break
                    if not member.isfile() or not _is_ppd_filename(member.name):
                        continue
                    if member.size > PPD_FILE_MAX_BYTES:
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        continue
                    entries.append((Path(member.name).name, handle.read(PPD_FILE_MAX_BYTES + 1)))
        except tarfile.TarError as exc:
            raise ValueError("驱动压缩包无法读取，请确认 tar 文件完整") from exc
    return entries


def import_ppd_driver(
    filename: str,
    content: bytes,
    make_model: str = "",
    uri: str = "",
    connection_type: str = "",
    info: str = "",
) -> dict[str, object]:
    if not content:
        raise ValueError("PPD 驱动文件不能为空")
    if len(content) > DRIVER_UPLOAD_MAX_BYTES:
        raise ValueError("驱动文件不能超过 50MB")
    if _is_driver_archive_filename(filename):
        rows = []
        diagnostics = []
        for entry_name, entry_content in _archive_ppd_entries(filename, content):
            try:
                rows.append(_store_ppd_content(entry_name, entry_content))
            except ValueError as exc:
                diagnostics.append(_diagnostic("local-ppd", False, f"{entry_name} 已跳过", str(exc)))
        if not rows:
            raise ValueError("驱动包中没有找到可用的 PPD 文件")
        recommendation = _annotate_driver_recommendation(rows, make_model, uri, connection_type, info)
        diagnostics.insert(0, _diagnostic("local-ppd", True, f"已从驱动包导入 {len(rows)} 个 PPD。"))
        return {
            "success": True,
            "message": "PPD 驱动包已导入",
            "driver": rows[0],
            "drivers": rows,
            "imported_count": len(rows),
            "recommendation": recommendation,
            "diagnostics": diagnostics,
        }
    row = _store_ppd_content(filename, content)
    rows = [row]
    recommendation = _annotate_driver_recommendation(rows, make_model, uri, connection_type, info)
    return {
        "success": True,
        "message": "PPD 驱动已导入",
        "driver": rows[0],
        "recommendation": recommendation,
        "diagnostics": [_diagnostic("local-ppd", True, f"已导入 {row.get('filename') or filename}。")],
    }


def normalize_printer_uri(uri: str = "", host: str = "", connection_type: str = "ipp", queue_path: str = "") -> str:
    if uri.strip():
        parsed = urlparse(uri.strip())
        if parsed.scheme not in ALLOWED_URI_SCHEMES:
            raise ValueError("打印机 URI 协议仅支持 ipp、ipps、socket、lpd、usb、dnssd")
        return uri.strip()
    host = host.strip()
    if not host:
        raise ValueError("请填写打印机 URI 或 IP/主机名")
    connection = (connection_type or "ipp").strip().lower()
    if connection not in {"ipp", "ipps", "socket", "lpd"}:
        raise ValueError("连接类型仅支持 ipp、ipps、socket、lpd")
    if connection == "socket":
        return f"socket://{host}:9100"
    default_path = "queue" if connection == "lpd" else "ipp/print"
    suffix = queue_path.strip() or default_path
    suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{connection}://{host}{suffix}"


def _probe_socket(host: str, port: int, timeout: float = 2.5) -> bool:
    with socket.create_connection((host, port), timeout=timeout):
        return True


def probe_printer_uri(uri: str) -> dict[str, object]:
    try:
        normalized = normalize_printer_uri(uri=uri)
    except ValueError as exc:
        return {"success": False, "uri": uri, "normalized_uri": uri, "reachable": False, "diagnostics": [_diagnostic("validation", False, str(exc))]}
    parsed = urlparse(normalized)
    diagnostics = []
    reachable = False
    printer_info = {}
    try:
        if parsed.scheme == "socket":
            _probe_socket(parsed.hostname or "", parsed.port or 9100)
            reachable = True
            diagnostics.append(_diagnostic("network", True, "Socket 端口可访问。"))
        elif parsed.scheme in {"ipp", "ipps"}:
            _probe_socket(parsed.hostname or "", parsed.port or (443 if parsed.scheme == "ipps" else 631))
            reachable = True
            diagnostics.append(_diagnostic("ipp-probe", True, "IPP 端口可访问。"))
        elif parsed.scheme == "lpd":
            _probe_socket(parsed.hostname or "", parsed.port or 515)
            reachable = True
            diagnostics.append(_diagnostic("network", True, "LPD 端口可访问。"))
        else:
            reachable = True
            diagnostics.append(_diagnostic("uri", True, "URI 格式有效。"))
    except Exception as exc:
        diagnostics.append(
            _diagnostic(
                "network",
                False,
                f"无法连接 {parsed.hostname or normalized}",
                f"{_cups_error_message(exc, '连接失败')}。请确认打印机在线，或尝试 ipp://<IP>/ipp/print。",
            )
        )
    recommendation = None
    existing_queue = {}
    if cups is not None:
        def read_existing(conn):
            name, attrs, reason = _existing_queue_for_uri(conn, normalized)
            if not name:
                return {}
            return {
                "name": name,
                "uri": str(attrs.get("device-uri") or normalized),
                "make_and_model": str(attrs.get("printer-make-and-model") or attrs.get("printer-info") or name),
                "reason": reason,
            }

        existing_queue, existing_detail = _call_cups("匹配已有打印队列", read_existing)
        if existing_queue is None:
            diagnostics.extend(existing_detail.get("diagnostics", []))
            existing_queue = {}
        elif existing_queue:
            printer_info = {
                "name": existing_queue["name"],
                "make_and_model": existing_queue.get("make_and_model", ""),
            }
            diagnostics.append(
                _diagnostic(
                    "cups-existing-queue",
                    True,
                    f"已找到现有队列 {existing_queue['name']}。",
                    str(existing_queue.get("reason") or "可直接连接该队列，不需要重复创建。"),
                )
            )

        def read_drivers(conn):
            return _recommend_driver(_read_driver_rows(conn), str(printer_info.get("make_and_model") or ""), normalized, parsed.scheme or "unknown")

        recommendation, driver_detail = _call_cups("推荐打印机驱动", read_drivers)
        if recommendation is None:
            diagnostics.extend(driver_detail.get("diagnostics", []))
    return {
        "success": reachable,
        "uri": normalized,
        "normalized_uri": normalized,
        "reachable": reachable,
        "connection_type": parsed.scheme or "unknown",
        "printer_info": printer_info,
        "installed": bool(existing_queue),
        "installed_name": existing_queue.get("name", "") if existing_queue else "",
        "recommended_driver": recommendation.get("driver") if recommendation else "",
        "recommended_driver_label": recommendation.get("label") if recommendation else "",
        "driver_confidence": recommendation.get("confidence") if recommendation else "",
        "driver_reason": recommendation.get("reason") if recommendation else "",
        "driver_install_hint": recommendation.get("install_hint") if recommendation else {},
        "diagnostics": diagnostics,
    }


def _ensure_queue_missing(conn, name: str) -> None:
    if name in conn.getPrinters():
        raise FileExistsError("打印机队列名称已存在")


def _ensure_queue_exists(conn, name: str) -> None:
    if name not in conn.getPrinters():
        raise FileNotFoundError("打印机不存在")


def _set_enabled(conn, name: str, enabled: bool, accepting_jobs: bool = True) -> None:
    if enabled:
        if hasattr(conn, "enablePrinter"):
            conn.enablePrinter(name)
        if accepting_jobs and hasattr(conn, "acceptJobs"):
            conn.acceptJobs(name)
    else:
        if hasattr(conn, "disablePrinter"):
            conn.disablePrinter(name)
        if hasattr(conn, "rejectJobs"):
            conn.rejectJobs(name)


def _try_set_cups_default(conn, name: str, diagnostics: list[dict[str, object]]) -> bool:
    try:
        conn.setDefault(name)
        return True
    except Exception as exc:
        message = _cups_error_message(exc, "CUPS 默认打印机设置失败")
        if _is_cups_permission_error(message):
            diagnostics.append(
                _diagnostic(
                    "cups-default",
                    False,
                    "CUPS 拒绝设置系统默认打印机，后端没有足够的打印机管理权限。",
                    "CUPS 拒绝设置系统默认打印机，已保留应用内默认打印机。",
                )
            )
            return False
        raise


def _uri_tcp_reachable(uri: str) -> bool:
    parsed = urlparse(uri or "")
    if not parsed.hostname:
        return False
    if parsed.scheme == "socket":
        port = parsed.port or 9100
    elif parsed.scheme == "lpd":
        port = parsed.port or 515
    elif parsed.scheme == "ipps":
        port = parsed.port or 443
    else:
        port = parsed.port or 631
    try:
        _probe_socket(parsed.hostname, port, timeout=1.5)
        return True
    except Exception:
        return False


def _existing_queue_for_uri(conn, uri: str, allow_single_reachable: bool = False) -> tuple[str, dict[str, object], str]:
    requested = urlparse(uri or "")
    requested_host = requested.hostname or ""
    candidates = []
    try:
        existing_printers = conn.getPrinters()
    except Exception:
        existing_printers = {}
    for queue_name, base_attrs in existing_printers.items():
        attrs = dict(base_attrs or {})
        try:
            attrs.update(_attributes(conn, queue_name))
        except Exception:
            pass
        device_uri = str(attrs.get("device-uri") or "")
        candidates.append((queue_name, attrs, device_uri))
        if device_uri == uri:
            return queue_name, attrs, "已有 CUPS 队列使用相同设备 URI。"
        device_host = urlparse(device_uri).hostname or ""
        if requested_host and device_host and device_host == requested_host:
            return queue_name, attrs, "已有 CUPS 队列连接到同一台打印机。"
    if allow_single_reachable and len(candidates) == 1 and requested.scheme in {"ipp", "ipps", "socket", "lpd"} and _uri_tcp_reachable(uri):
        queue_name, attrs, _device_uri = candidates[0]
        return queue_name, attrs, "CUPS 拒绝创建新队列，已复用当前唯一可用的本地队列。"
    return "", {}, ""


def _add_or_update_queue(conn, name: str, uri: str, driver: str, location: str, description: str) -> None:
    kwargs = {"device": uri, "info": description or name, "location": location or ""}
    if driver == DRIVERLESS_ID:
        kwargs["ppdname"] = DRIVERLESS_ID
    elif _is_ppd_filename(driver) and Path(driver).exists():
        kwargs["ppd"] = driver
    else:
        kwargs["ppdname"] = driver
    conn.addPrinter(name, **kwargs)


def update_printer(db, name: str, payload) -> dict[str, object]:
    current = get_printer(db, name)
    new_name = (getattr(payload, "new_name", None) or name).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", new_name):
        raise ValueError("新队列名称只能包含字母、数字、下划线、点和短横线")
    payload_uri = getattr(payload, "uri", None)
    payload_host = getattr(payload, "host", "") or ""
    uri_source = payload_uri if payload_uri is not None else ("" if payload_host else current.get("uri") or "")
    uri = normalize_printer_uri(
        uri=uri_source or "",
        host=payload_host,
        connection_type=getattr(payload, "connection_type", None) or "ipp",
        queue_path=getattr(payload, "queue_path", "") or "",
    )
    driver = getattr(payload, "driver", None) or current.get("driver") or DRIVERLESS_ID
    location = current.get("location", "")
    description = current.get("description", "")
    if getattr(payload, "location", None) is not None:
        location = payload.location or ""
    if getattr(payload, "description", None) is not None:
        description = payload.description or ""
    is_default = current.get("is_default", False) if getattr(payload, "is_default", None) is None else bool(payload.is_default)
    was_default = bool(current.get("is_default"))
    is_enabled = current.get("is_enabled", True) if getattr(payload, "is_enabled", None) is None else bool(payload.is_enabled)
    accepting_jobs = current.get("accepting_jobs", True) if getattr(payload, "accepting_jobs", None) is None else bool(payload.accepting_jobs)
    # 【新增功能】打印机属性：后端未收到该字段（None）时保留数据库原值，便于旧前端/其它调用点兼容。
    is_support_color = current.get("is_support_color", False) if getattr(payload, "is_support_color", None) is None else bool(payload.is_support_color)
    is_support_auto_duplex = (
        current.get("is_support_auto_duplex", True) if getattr(payload, "is_support_auto_duplex", None) is None else bool(payload.is_support_auto_duplex)
    )
    capabilities = {"is_support_color": is_support_color, "is_support_auto_duplex": is_support_auto_duplex}

    def update(conn):
        _ensure_queue_exists(conn, name)
        default_diagnostics = []
        if new_name != name:
            _ensure_queue_missing(conn, new_name)
            _add_or_update_queue(conn, new_name, uri, driver, location, description)
            _set_enabled(conn, new_name, is_enabled, accepting_jobs)
            default_name = _default_name(conn)
            if is_default:
                if _try_set_cups_default(conn, new_name, default_diagnostics):
                    default_name = new_name
            delete_error = ""
            try:
                conn.deletePrinter(name)
            except Exception as exc:
                delete_error = _cups_error_message(exc, "旧队列删除失败")
            attrs = _attributes(conn, new_name)
            printer = _printer_object(new_name, attrs, default_name, capabilities, True)
            if is_default:
                printer["is_default"] = True
            return printer, delete_error, default_diagnostics
        _add_or_update_queue(conn, name, uri, driver, location, description)
        _set_enabled(conn, name, is_enabled, accepting_jobs)
        default_name = _default_name(conn)
        if is_default:
            if _try_set_cups_default(conn, name, default_diagnostics):
                default_name = name
        attrs = _attributes(conn, name)
        printer = _printer_object(name, attrs, default_name, capabilities, True)
        if is_default:
            printer["is_default"] = True
        return printer, "", default_diagnostics

    data, detail = _call_cups("更新 CUPS 打印队列", update)
    if data is None:
        if _detail_has_permission_error(detail):
            if new_name != name:
                _save_local_metadata(db, name, current.get("uri", ""), current.get("driver", DRIVERLESS_ID), current.get("location", ""), current.get("description", name), was_default, bool(current.get("is_enabled", True)), bool(current.get("accepting_jobs", True)), hidden=True)
                _clear_default_setting(db, name)
            _save_local_metadata(db, new_name, uri, driver, location, description, is_default, is_enabled, accepting_jobs, is_support_color=is_support_color, is_support_auto_duplex=is_support_auto_duplex)
            if is_default:
                _sync_default_setting(db, new_name)
            elif was_default:
                _clear_default_setting(db, name)
            db.commit()
            default_row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
            printer = _metadata_only_printer_object(_metadata_for(db, new_name), default_row["value"] if default_row else "", True)
            return {
                "success": True,
                "message": "打印机配置已更新",
                "printer": printer,
                "diagnostics": _metadata_fallback_diagnostics(
                    detail,
                    "CUPS 拒绝更新队列，已先保存后台打印机配置。",
                    "如需同步修改系统队列，请在宿主机 CUPS/系统打印机设置中授权后端。",
                ),
            }
        raise RuntimeError(detail)
    printer, delete_error, default_diagnostics = data
    if new_name != name:
        db.execute("DELETE FROM printers WHERE name = ?", (name,))
        _clear_default_setting(db, name)
    _save_metadata(db, new_name, uri, driver, location, description, is_default, is_enabled, accepting_jobs, is_support_color, is_support_auto_duplex)
    if is_default:
        _sync_default_setting(db, new_name)
    elif was_default:
        _clear_default_setting(db, name)
    db.commit()
    diagnostics = detail.get("diagnostics", [])
    diagnostics.extend(default_diagnostics)
    if delete_error:
        diagnostics.append(_diagnostic("cups-delete-old-queue", False, delete_error, "新队列已创建，请在 CUPS 中人工清理旧队列。"))
    return {"success": True, "message": "打印机已更新", "printer": printer, "diagnostics": diagnostics}


def remove_printer(db, name: str, force: bool = False) -> dict[str, object]:
    metadata_exists = db.execute("SELECT name FROM printers WHERE name = ?", (name,)).fetchone() is not None

    def delete(conn):
        if name not in conn.getPrinters():
            if not metadata_exists:
                raise FileNotFoundError("打印机不存在")
            return False
        conn.deletePrinter(name)
        return True

    deleted_from_cups, detail = _call_cups("删除 CUPS 打印队列", delete)
    if deleted_from_cups is None:
        if _detail_has_permission_error(detail):
            meta = _metadata_for(db, name) or {}
            _save_local_metadata(
                db,
                name,
                str(meta.get("uri") or ""),
                str(meta.get("driver") or DRIVERLESS_ID),
                str(meta.get("location") or ""),
                str(meta.get("description") or name),
                _safe_bool(meta.get("is_default")),
                _safe_bool(meta.get("is_enabled"), True),
                _safe_bool(meta.get("accepting_jobs"), True),
                hidden=True,
            )
            default_cleared = _clear_default_setting(db, name)
            db.commit()
            return {
                "success": True,
                "message": "打印机已从后台移除",
                "deleted": name,
                "default_cleared": default_cleared,
                "cups_deleted": False,
                "diagnostics": _metadata_fallback_diagnostics(
                    detail,
                    "CUPS 拒绝删除系统队列，已先从后台列表隐藏。",
                    "如需彻底删除系统打印队列，请在宿主机 CUPS/系统打印机设置中删除。",
                ),
            }
        raise RuntimeError(detail)
    db.execute("DELETE FROM printers WHERE name = ?", (name,))
    default_cleared = _clear_default_setting(db, name)
    db.commit()
    diagnostics = detail.get("diagnostics", [])
    if not deleted_from_cups:
        diagnostics.append(_diagnostic("cups-delete", True, "CUPS 队列原本不存在，已清理本地元数据。"))
    return {"success": True, "message": "打印机已删除", "deleted": name, "default_cleared": default_cleared, "diagnostics": diagnostics}


def set_default_printer(db, name: str) -> dict[str, object]:
    metadata_exists = db.execute("SELECT name FROM printers WHERE name = ?", (name,)).fetchone() is not None

    def set_default(conn):
        _ensure_queue_exists(conn, name)
        diagnostics = []
        _try_set_cups_default(conn, name, diagnostics)
        return diagnostics

    default_diagnostics, detail = _call_cups("设置默认打印机", set_default)
    if default_diagnostics is None:
        if metadata_exists:
            _sync_default_setting(db, name)
            db.commit()
            return {
                "success": True,
                "message": "默认打印机已更新",
                "printer": name,
                "diagnostics": _metadata_fallback_diagnostics(
                    detail,
                    "CUPS 当前未返回该队列，已先保存为系统默认打印机。",
                    "刷新 CUPS 或宿主机打印队列后会自动恢复实时状态。",
                ),
            }
        raise RuntimeError(detail)
    _sync_default_setting(db, name)
    db.commit()
    return {"success": True, "message": "默认打印机已更新", "printer": name, "diagnostics": detail.get("diagnostics", []) + default_diagnostics}


def clear_default_printer(db) -> dict[str, object]:
    # 取消默认打印机：清空应用内 default_printer 设置并复位所有 is_default 标记，
    # 使系统进入"暂未设置默认打印机"状态。
    db.execute("UPDATE settings SET value = '' WHERE key = 'default_printer'")
    db.execute("UPDATE printers SET is_default = 0")
    db.commit()
    return {"success": True, "message": "已取消默认打印机", "printer": ""}


def set_printer_enabled(db, name: str, enabled: bool, accepting_jobs: bool = True) -> dict[str, object]:
    metadata_exists = db.execute("SELECT name FROM printers WHERE name = ?", (name,)).fetchone() is not None

    def set_enabled(conn):
        _ensure_queue_exists(conn, name)
        _set_enabled(conn, name, enabled, accepting_jobs)
        return True

    ok, detail = _call_cups("更新打印机启用状态", set_enabled)
    if ok is None:
        if not metadata_exists:
            raise RuntimeError(detail)
        now = datetime.utcnow().isoformat()
        db.execute(
            "UPDATE printers SET is_enabled = ?, accepting_jobs = ?, updated_at = ? WHERE name = ?",
            (1 if enabled else 0, 1 if accepting_jobs else 0, now, name),
        )
        db.commit()
        return {
            "success": True,
            "message": "打印机已启用" if enabled else "打印机已停用",
            "printer": name,
            "enabled": enabled,
            "accepting_jobs": accepting_jobs,
            "diagnostics": _metadata_fallback_diagnostics(
                detail,
                "CUPS 当前未返回该队列，已先保存启用状态到本地配置。",
                "刷新 CUPS 或宿主机打印队列后会自动恢复实时状态。",
            ),
        }
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE printers SET is_enabled = ?, accepting_jobs = ?, updated_at = ? WHERE name = ?",
        (1 if enabled else 0, 1 if accepting_jobs else 0, now, name),
    )
    db.commit()
    return {
        "success": True,
        "message": "打印机已启用" if enabled else "打印机已停用",
        "printer": name,
        "enabled": enabled,
        "accepting_jobs": accepting_jobs,
        "diagnostics": detail.get("diagnostics", []),
    }


def _test_pdf_bytes() -> bytes:
    content = b"BT /F1 18 Tf 72 760 Td (Cloud Print test page) Tj 0 -30 Td (Printer check OK.) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(pdf)


def test_printer(db, name: str, payload=None) -> dict[str, object]:
    copies = max(1, _safe_int(getattr(payload, "copies", 1), 1))
    duplex = bool(getattr(payload, "duplex", False))
    metadata_exists = db.execute("SELECT name FROM printers WHERE name = ?", (name,)).fetchone() is not None

    def submit(conn):
        _ensure_queue_exists(conn, name)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(_test_pdf_bytes())
            path = Path(handle.name)
        try:
            options = {"copies": str(copies)}
            if duplex:
                options["sides"] = "two-sided-long-edge"
            return str(conn.printFile(name, str(path), "Cloud Print test page", options))
        finally:
            path.unlink(missing_ok=True)

    job_id, detail = _call_cups("发送测试页", submit)
    if job_id is None:
        if metadata_exists:
            raise RuntimeError(
                {
                    "success": False,
                    "error": "CUPS 当前未返回该打印队列，暂时不能发送真实测试页。",
                    "diagnostics": _metadata_fallback_diagnostics(
                        detail,
                        "打印机配置已存在，但 CUPS 实时队列不可用。",
                        "请刷新 CUPS/宿主机打印队列，或确认容器已挂载正确的 CUPS socket。",
                    ),
                }
            )
        raise RuntimeError(detail)
    return {
        "success": True,
        "message": "测试页已发送",
        "printer": name,
        "job_id": job_id,
        "requires_user_confirmation": True,
        "diagnostics": detail.get("diagnostics", []),
    }


def record_printer_test_result(db, name: str, success: bool, note: str | None = None) -> dict[str, object]:
    if name not in _metadata_rows(db):
        live_names = []
        try:
            live_names = list(_connection("读取打印机列表").getPrinters().keys())
        except Exception:
            pass
        if name not in live_names:
            raise ValueError("打印机不存在")
        _save_metadata(db, name)
    now = datetime.utcnow().isoformat()
    note_text = (note or "").strip()
    db.execute(
        """
        UPDATE printers
        SET last_status = ?, last_checked_at = ?, last_test_at = ?, last_test_success = ?, last_test_note = ?, updated_at = ?
        WHERE name = ?
        """,
        ("测试页已确认打印成功" if success else "测试页未成功打印", now, now, 1 if success else 0, note_text, now, name),
    )
    db.commit()
    return {
        "success": True,
        "message": "测试结果已保存",
        "printer": name,
        "last_test_success": success,
        "last_test_at": now,
        "last_test_note": note_text,
    }


def list_printer_jobs(db, name: str, which_jobs: str = "not-completed", limit: int = 20) -> dict[str, object]:
    allowed = {"not-completed", "completed", "all"}
    if which_jobs not in allowed:
        raise ValueError("任务范围仅支持 not-completed、completed、all")
    metadata_exists = db.execute("SELECT name FROM printers WHERE name = ?", (name,)).fetchone() is not None

    def read(conn):
        _ensure_queue_exists(conn, name)
        return _jobs_for_printer(conn, name, which_jobs, max(1, min(limit, 100)))

    jobs, detail = _call_cups("读取打印任务", read)
    if jobs is None:
        if metadata_exists:
            return {
                "success": True,
                "printer": name,
                "jobs": [],
                "diagnostics": _metadata_fallback_diagnostics(
                    detail,
                    "CUPS 当前未返回该队列，暂时没有可读取的实时任务。",
                    "刷新 CUPS 或宿主机打印队列后会自动恢复实时任务列表。",
                ),
            }
        raise RuntimeError(detail)
    return {"success": True, "printer": name, "jobs": jobs, "diagnostics": detail.get("diagnostics", [])}


def get_cups_error_log(lines: int = 200) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    log_path = Path("/var/log/cups/error_log")
    content = ""
    try:
        if log_path.exists():
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                start = max(0, len(all_lines) - lines)
                content = "".join(all_lines[start:])
            diagnostics.append(_diagnostic("cups-error-log", True, f"已读取 CUPS 错误日志最后 {len(all_lines[start:])} 行。", f"日志路径：{log_path}"))
        else:
            diagnostics.append(_diagnostic("cups-error-log", False, "CUPS 错误日志文件不存在。", "请确认 CUPS 容器已正确挂载日志目录。"))
    except Exception as exc:
        diagnostics.append(_diagnostic("cups-error-log", False, f"读取 CUPS 错误日志失败：{exc}", "可能是权限问题或日志文件损坏。"))
    return {"success": True, "content": content, "diagnostics": diagnostics}


def get_cups_page_log(lines: int = 200) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    log_path = Path("/var/log/cups/page_log")
    content = ""
    try:
        if log_path.exists():
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                start = max(0, len(all_lines) - lines)
                content = "".join(all_lines[start:])
            diagnostics.append(_diagnostic("cups-page-log", True, f"已读取 CUPS 页面日志最后 {len(all_lines[start:])} 行。", f"日志路径：{log_path}"))
        else:
            diagnostics.append(_diagnostic("cups-page-log", False, "CUPS 页面日志文件不存在。", "页面日志记录打印页数统计。"))
    except Exception as exc:
        diagnostics.append(_diagnostic("cups-page-log", False, f"读取 CUPS 页面日志失败：{exc}", "可能是权限问题或日志文件损坏。"))
    return {"success": True, "content": content, "diagnostics": diagnostics}


def get_cups_access_log(lines: int = 200) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    log_path = Path("/var/log/cups/access_log")
    content = ""
    try:
        if log_path.exists():
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                start = max(0, len(all_lines) - lines)
                content = "".join(all_lines[start:])
            diagnostics.append(_diagnostic("cups-access-log", True, f"已读取 CUPS 访问日志最后 {len(all_lines[start:])} 行。", f"日志路径：{log_path}"))
        else:
            diagnostics.append(_diagnostic("cups-access-log", False, "CUPS 访问日志文件不存在。", "访问日志记录 HTTP/IPP 请求。"))
    except Exception as exc:
        diagnostics.append(_diagnostic("cups-access-log", False, f"读取 CUPS 访问日志失败：{exc}", "可能是权限问题或日志文件损坏。"))
    return {"success": True, "content": content, "diagnostics": diagnostics}


def get_cups_filter_status() -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    filter_dir = Path("/usr/lib/cups/filter")
    backend_dir = Path("/usr/lib/cups/backend")
    filters: list[dict[str, object]] = []
    backends: list[dict[str, object]] = []
    
    try:
        if filter_dir.exists():
            for path in sorted(filter_dir.iterdir()):
                if path.is_file():
                    is_executable = path.is_executable()
                    size = path.stat().st_size if is_executable else 0
                    filters.append({
                        "name": path.name,
                        "path": str(path),
                        "executable": is_executable,
                        "size_bytes": size,
                    })
                    if not is_executable:
                        diagnostics.append(_diagnostic("cups-filter", False, f"过滤器 {path.name} 没有执行权限", "需要 chmod 755"))
            diagnostics.append(_diagnostic("cups-filters", True, f"发现 {len(filters)} 个过滤器", f"目录：{filter_dir}"))
        else:
            diagnostics.append(_diagnostic("cups-filters", False, "过滤器目录不存在", f"路径：{filter_dir}"))
        
        if backend_dir.exists():
            for path in sorted(backend_dir.iterdir()):
                if path.is_file():
                    is_executable = path.is_executable()
                    backends.append({
                        "name": path.name,
                        "path": str(path),
                        "executable": is_executable,
                    })
                    if not is_executable:
                        diagnostics.append(_diagnostic("cups-backend", False, f"后端 {path.name} 没有执行权限", "需要 chmod 755"))
            diagnostics.append(_diagnostic("cups-backends", True, f"发现 {len(backends)} 个后端", f"目录：{backend_dir}"))
        else:
            diagnostics.append(_diagnostic("cups-backends", False, "后端目录不存在", f"路径：{backend_dir}"))
        
        essential_filters = ["pdftopdf", "cgpdftopdf", "gstoraster", "pdftoopvp", "pdftoraster"]
        for filter_name in essential_filters:
            found = any(f["name"] == filter_name for f in filters)
            if not found:
                diagnostics.append(_diagnostic("cups-filter-missing", False, f"缺少必要过滤器 {filter_name}", "可能导致打印失败"))
        
        essential_backends = ["ipp", "ipps", "socket", "lpd"]
        for backend_name in essential_backends:
            found = any(b["name"] == backend_name for b in backends)
            if not found:
                diagnostics.append(_diagnostic("cups-backend-missing", False, f"缺少必要后端 {backend_name}", "可能导致连接失败"))
    
    except Exception as exc:
        diagnostics.append(_diagnostic("cups-filter-status", False, f"获取过滤器状态失败：{exc}", ""))
    
    return {"success": True, "filters": filters, "backends": backends, "diagnostics": diagnostics}


def get_cups_queue_status(db) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    queues: list[dict[str, object]] = []
    
    def read(conn):
        result = []
        for name, attrs in conn.getPrinters().items():
            full_attrs = dict(attrs or {})
            try:
                full_attrs.update(_attributes(conn, name))
            except Exception:
                pass
            
            state = str(full_attrs.get("printer-state") or "")
            state_text = str(full_attrs.get("printer-state-message") or "")
            state_reasons = _cups_attr_values(full_attrs.get("printer-state-reasons"))
            
            queue_info = {
                "name": name,
                "uri": str(full_attrs.get("device-uri") or ""),
                "make_and_model": str(full_attrs.get("printer-make-and-model") or ""),
                "location": str(full_attrs.get("printer-location") or ""),
                "state": CUPS_STATE_LABELS.get(state, state),
                "state_text": state_text,
                "state_reasons": state_reasons,
                "is_default": name == _default_name(conn),
                "accepting_jobs": bool(full_attrs.get("printer-is-accepting-jobs")),
                "queued_jobs": int(full_attrs.get("printer-queued-jobs") or 0),
                "has_filter_failed": any("filter-failed" in str(r).lower() for r in state_reasons) or "filter failed" in state_text.lower(),
            }
            if queue_info["has_filter_failed"]:
                diagnostics.append(_diagnostic("cups-queue-filter-failed", False, f"队列 {name} 过滤器失败", f"状态：{state_text}, 原因：{state_reasons}"))
            result.append(queue_info)
        return result
    
    queues, detail = _call_cups("读取 CUPS 队列状态", read)
    if queues is None:
        diagnostics.extend(detail.get("diagnostics", []))
        return {"success": False, "queues": [], "diagnostics": diagnostics}
    
    diagnostics.extend(detail.get("diagnostics", []))
    failed_count = sum(1 for q in queues if q["has_filter_failed"])
    if failed_count > 0:
        diagnostics.append(_diagnostic("cups-queue-summary", False, f"{failed_count} 个队列存在过滤器失败问题", "请检查 CUPS 错误日志获取详细信息"))
    else:
        diagnostics.append(_diagnostic("cups-queue-summary", True, f"所有 {len(queues)} 个队列状态正常", ""))
    
    return {"success": True, "queues": queues, "diagnostics": diagnostics}


def get_cups_diagnostics(db) -> dict[str, object]:
    results = {}
    all_diagnostics = []
    
    results["system"] = printer_system(db)
    all_diagnostics.extend(results["system"].get("diagnostics", []))
    
    results["filters"] = get_cups_filter_status()
    all_diagnostics.extend(results["filters"].get("diagnostics", []))
    
    results["queues"] = get_cups_queue_status(db)
    all_diagnostics.extend(results["queues"].get("diagnostics", []))
    
    results["error_log"] = get_cups_error_log(100)
    all_diagnostics.extend(results["error_log"].get("diagnostics", []))
    
    errors = [d for d in all_diagnostics if not d.get("ok")]
    warnings = [d for d in all_diagnostics if d.get("severity") == "warning"]
    
    return {
        "success": len(errors) == 0,
        "has_errors": len(errors) > 0,
        "has_warnings": len(warnings) > 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "results": results,
        "diagnostics": all_diagnostics,
        "errors": errors,
        "warnings": warnings,
    }
