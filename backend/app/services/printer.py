import json
import platform
import re
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..config import get_settings
from .pdf_postprocess import rasterize_pdf_for_print
from ..utils.cups_utils import (
    create_cups_connection,
    cups_call,
    cups_error_message,
    is_cups_permission_error,
    cups_connectivity_hint,
    get_cups_config,
    get_cups_env,
    test_cups_connection,
    cups_available,
)

try:
    import cups
except ImportError:  # pragma: no cover - exercised in environments without libcups
    cups = None


HIDDEN_SYSTEM_PRINTERS_KEY = "hidden_system_printers"
NETWORK_PROTOCOLS = {
    "ipp": {"port": 631, "uri": "ipp://{host}/ipp/print", "driver_strategy": "driverless", "label": "IPP/AirPrint/Mopria"},
    "socket": {"port": 9100, "uri": "socket://{host}:9100", "driver_strategy": "pcl", "label": "Socket 9100"},
    "lpd": {"port": 515, "uri": "lpd://{host}/queue", "driver_strategy": "pcl", "label": "LPD/LPR"},
}

CUPS_STATE_LABELS = {
    3: "idle",
    4: "processing",
    5: "stopped",
    "3": "idle",
    "4": "processing",
    "5": "stopped",
}
CUPS_STATE_TEXT = {
    "idle": "空闲",
    "processing": "打印中",
    "stopped": "已停止",
}


def _cups_missing_error(action: str) -> str:
    return f"{action}失败：后端未安装 pycups 或 libcups 开发库。请安装 pycups，并确认镜像包含 libcups2-dev。"


def _cups_connection():
    conn, error = create_cups_connection()
    if conn is None:
        raise RuntimeError(error or _cups_missing_error("连接 CUPS"))
    return conn


def _cups_error_message(exc: Exception, fallback: str) -> str:
    return cups_error_message(exc, fallback)


def _is_cups_permission_error(message: str) -> bool:
    return is_cups_permission_error(message)


def _cups_call(action: str, callback):
    result, detail = cups_call(action, callback)
    if detail.get("success"):
        return result, _diagnostic("pycups", True, f"{action}成功。", "")
    message = detail.get("error", f"{action}失败")
    if _is_cups_permission_error(message):
        return None, _diagnostic(
            "pycups",
            False,
            "CUPS 拒绝当前操作，后端没有足够的打印机管理权限。",
            "如果打印机已在系统中添加，可直接使用现有队列；否则请在宿主机 CUPS/系统打印机设置中授权后端或先手动添加该打印机。",
        )
    return None, _diagnostic("pycups", False, message, _cups_connectivity_hint())


def _cups_attr_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cups_state(value) -> str:
    return CUPS_STATE_LABELS.get(value, CUPS_STATE_LABELS.get(str(value), str(value or "unknown")))


def _cups_queue_uri(name: str) -> str:
    server = _cups_server() or "localhost"
    if ":" not in server and not server.startswith("["):
        server = f"{server}:631"
    return f"ipp://{server}/printers/{name}"


def _cups_printer_attributes(conn, name: str) -> dict[str, object]:
    requested = [
        "printer-name",
        "printer-info",
        "printer-location",
        "printer-make-and-model",
        "printer-state",
        "printer-state-message",
        "printer-state-reasons",
        "printer-is-accepting-jobs",
        "queued-job-count",
        "printer-uri-supported",
        "device-uri",
        "marker-names",
        "marker-types",
        "marker-levels",
        "marker-colors",
        "media-ready",
        "printer-up-time",
        "printer-state-change-time",
        "printer-firmware-string-version",
    ]
    try:
        return conn.getPrinterAttributes(name, requested_attributes=requested)
    except TypeError:
        return conn.getPrinterAttributes(name)


def _printer_record_from_cups(name: str, attrs: dict[str, object], default_name: str = "") -> dict[str, object]:
    state = _cups_state(attrs.get("printer-state"))
    uri = str(attrs.get("device-uri") or "")
    description = str(attrs.get("printer-info") or attrs.get("printer-make-and-model") or name)
    reasons = _cups_attr_values(attrs.get("printer-state-reasons")) or ["none"]
    accepting = bool(attrs.get("printer-is-accepting-jobs", True))
    return {
        "name": str(attrs.get("printer-name") or name),
        "uri": uri,
        "driver": "everywhere",
        "location": str(attrs.get("printer-location") or ""),
        "description": description,
        "model": str(attrs.get("printer-make-and-model") or description),
        "connection": _connection_type(uri),
        "status": str(attrs.get("printer-state-message") or CUPS_STATE_TEXT.get(state, state)),
        "state": state,
        "state_text": CUPS_STATE_TEXT.get(state, state),
        "state_message": str(attrs.get("printer-state-message") or ""),
        "state_reasons": reasons,
        "queued_jobs": _safe_int(attrs.get("queued-job-count")),
        "is_default": name == default_name,
        "is_enabled": state != "stopped" and accepting,
        "accepting_jobs": accepting,
        "cups_uri": str(attrs.get("printer-uri-supported") or _cups_queue_uri(name)),
    }


def _cups_env() -> dict[str, str]:
    return get_cups_env()


def _run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=_cups_env())


def _run_command(command: list[str], source: str, timeout: int = 15, hint: str = "") -> tuple[subprocess.CompletedProcess[str] | None, dict[str, object]]:
    executable = command[0]
    if shutil.which(executable) is None:
        return None, _diagnostic(source, False, f"未找到命令 {executable}", hint or _command_hint(executable))
    try:
        result = _run(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr)
        if stdout:
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=stderr), _diagnostic(source, True, "命令超时，已解析已有输出。", "")
        return None, _diagnostic(source, False, "命令超时", hint or "请确认 CUPS 服务和打印机在线后重试。")
    except OSError as exc:
        return None, _diagnostic(source, False, str(exc), hint or _command_hint(executable))
    if result.returncode != 0:
        return result, _diagnostic(source, False, _command_error(result, "命令执行失败"), hint or _command_hint(executable))
    message = _command_error(result, "命令执行成功") if not result.stdout.strip() else "命令执行成功"
    return result, _diagnostic(source, True, message, "")


def _decode_timeout_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _diagnostic(source: str, ok: bool, message: str, hint: str = "") -> dict[str, object]:
    return {"source": source, "ok": ok, "message": message or ("正常" if ok else "失败"), "hint": hint}


def _command_error(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    return (result.stderr or result.stdout or fallback).strip()


def _command_hint(executable: str) -> str:
    if executable in {"lpstat", "lpinfo", "lpadmin", "lpoptions", "cupsenable", "cupsdisable", "lp", "cancel"}:
        if _is_docker():
            return "当前后端运行在 Docker 中，请使用 docker-compose.print-service.yml 启动 CUPS 容器，或配置 CUPS_SERVER。"
        return "请确认本机 CUPS 服务已启动，且命令行可访问 CUPS。"
    if executable == "powershell":
        return "请确认后端运行在 Windows，且 PowerShell 可用。"
    return ""


def _cups_server() -> str:
    config = get_cups_config()
    return config["server"]


def _cups_connectivity_hint() -> str:
    return cups_connectivity_hint()


def _cups_connectivity_error(action: str) -> str | None:
    if _platform_name() == "windows":
        return None
    if cups is None:
        return _cups_missing_error(action)
    if _is_docker() and not _cups_server():
        return f"{action}失败：后端处于真实打印模式，但没有连接到 CUPS 服务（CUPS_SERVER 为空）。{_cups_connectivity_hint()}"
    try:
        _cups_connection().getPrinters()
    except TimeoutError:
        return f"{action}失败：检查 CUPS 服务超时。{_cups_connectivity_hint()}"
    except OSError as exc:
        return f"{action}失败：无法连接 CUPS：{exc}。{_cups_connectivity_hint()}"
    except Exception as exc:
        return f"{action}失败：CUPS 服务不可用：{_cups_error_message(exc, 'scheduler is not running')}。{_cups_connectivity_hint()}"
    return None


def _platform_name() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "darwin"
    if name == "windows":
        return "windows"
    if name == "linux":
        return "linux"
    return "unknown"


def _is_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


PRINTER_TEMPLATES: list[dict[str, object]] = [
    {
        "id": "generic-driverless",
        "brand": "通用",
        "model_family": "IPP Everywhere / AirPrint / Mopria",
        "recommended": True,
        "connection_types": ["ipp", "ipps"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "现代网络打印机首选模板，使用 CUPS driverless 的 -m everywhere。",
        "hints": ["适用于支持 IPP Everywhere、AirPrint 或 Mopria 的主流网络打印机。", "只需要打印机 IP 或主机名。"],
    },
    {
        "id": "huawei-pixlab",
        "brand": "Huawei",
        "model_family": "PixLab / 华为激光打印机",
        "recommended": True,
        "connection_types": ["ipp", "socket", "usb"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "华为 PixLab/激光打印机优先使用 IPP/AirPrint/Mopria；USB 请填写完整 CUPS 设备 URI。",
        "hints": ["网络方式推荐固定打印机 IP。", "IPP 失败可尝试 Socket 9100。", "专有华为驱动请放入 docker/cups/drivers 后重建 CUPS 镜像。"],
    },
    {
        "id": "hp-driverless",
        "brand": "HP",
        "model_family": "LaserJet / OfficeJet / DeskJet 网络打印机",
        "recommended": True,
        "connection_types": ["ipp", "socket", "usb"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "HP 新款网络打印机优先 driverless；容器内 HPLIP 可作为补充驱动来源。",
        "hints": ["如果 driverless 不可用，可在高级配置中选择 HPLIP 或 Socket 9100。"],
    },
    {
        "id": "canon-driverless",
        "brand": "Canon",
        "model_family": "PIXMA / imageCLASS 网络打印机",
        "recommended": True,
        "connection_types": ["ipp", "socket", "usb"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "Canon 网络打印机优先 IPP/AirPrint driverless，旧型号可尝试 Gutenprint。",
        "hints": ["如果打印内容异常，可在高级配置中选择 Gutenprint 相关 model。"],
    },
    {
        "id": "epson-driverless",
        "brand": "Epson",
        "model_family": "EcoTank / WorkForce 网络打印机",
        "recommended": True,
        "connection_types": ["ipp", "socket", "usb"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "Epson 新款网络打印机优先 driverless；容器内 ESC/P-R 和 Gutenprint 可作为补充。",
        "hints": ["老型号可尝试 Epson ESC/P-R 或 Gutenprint model。"],
    },
    {
        "id": "brother-driverless",
        "brand": "Brother",
        "model_family": "HL / DCP / MFC 网络打印机",
        "recommended": True,
        "connection_types": ["ipp", "socket", "lpd", "usb"],
        "driver_strategy": "driverless",
        "uri_pattern": "ipp://{host}/ipp/print",
        "description": "Brother 网络打印机优先 driverless；brlaser 可覆盖部分旧激光型号。",
        "hints": ["旧款 Brother 可尝试 LPD 或 Socket 9100。"],
    },
    {
        "id": "generic-pcl",
        "brand": "通用",
        "model_family": "PCL 激光打印机",
        "recommended": False,
        "connection_types": ["socket", "ipp", "lpd", "usb"],
        "driver_strategy": "pcl",
        "uri_pattern": "socket://{host}:9100",
        "description": "不支持 driverless 的老式激光打印机兜底模板。",
        "hints": ["需要容器 CUPS 内存在 printer-driver-all、foomatic 或 pxlmono 等通用 PCL 驱动。"],
    },
    {
        "id": "generic-postscript",
        "brand": "通用",
        "model_family": "PostScript 打印机",
        "recommended": False,
        "connection_types": ["socket", "ipp", "lpd"],
        "driver_strategy": "postscript",
        "uri_pattern": "socket://{host}:9100",
        "description": "支持 PostScript 的办公打印机或复合机模板。",
        "hints": ["适合明确支持 PostScript/PS 的打印机或复合机。"],
    },
    {
        "id": "jetdirect-socket",
        "brand": "通用",
        "model_family": "JetDirect / Socket 9100",
        "recommended": False,
        "connection_types": ["socket"],
        "driver_strategy": "pcl",
        "uri_pattern": "socket://{host}:9100",
        "description": "直接走 9100 端口的网络打印方式。",
        "hints": ["Socket 只描述连接方式；驱动仍需选择 PCL/PostScript 或厂商 PPD。"],
    },
    {
        "id": "lpd",
        "brand": "通用",
        "model_family": "LPD/LPR",
        "recommended": False,
        "connection_types": ["lpd"],
        "driver_strategy": "pcl",
        "uri_pattern": "lpd://{host}/queue",
        "description": "旧式 LPD/LPR 网络打印方式。",
        "hints": ["如果打印机要求特定队列名，可在高级配置中修改 /queue。"],
    },
]


def list_system_printers() -> dict[str, dict[str, object]]:
    printers, _diagnostics = _installed_printers_for_platform()
    return printers


def _installed_printers_for_platform() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    if _platform_name() == "windows":
        return _windows_installed_printers()
    printers, diagnostics = _cups_installed_printers()
    if _platform_name() == "darwin":
        mac_printers, mac_diagnostics = _macos_profiler_printers(printers)
        diagnostics.extend(mac_diagnostics)
        printers.update({name: value for name, value in mac_printers.items() if name not in printers})
    return printers, diagnostics


def _cups_installed_printers() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    printers: dict[str, dict[str, object]] = {}
    diagnostics: list[dict[str, object]] = []

    def read_printers(conn):
        default_name = _cups_default_printer_name(conn)
        rows = conn.getPrinters()
        output = {}
        for name in rows:
            attrs = dict(rows.get(name) or {})
            attrs.update(_cups_printer_attributes(conn, name))
            output[name] = _printer_record_from_cups(name, attrs, default_name)
        return output

    result, diagnostic = _cups_call("读取 CUPS 打印机列表", read_printers)
    diagnostics.append(diagnostic)
    if isinstance(result, dict):
        printers = result
    if not printers:
        diagnostics.append(_diagnostic("cups-installed", True, "CUPS 未返回已安装打印机。", "请先添加打印队列，或检查后端 CUPS_SERVER。"))
    return printers, diagnostics


def _windows_installed_printers() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-Printer | Select-Object Name,PortName,DriverName,Location,Comment,PrinterStatus,Default | ConvertTo-Json -Depth 2",
    ]
    result, diagnostic = _run_command(command, "windows-get-printer", timeout=15)
    diagnostics = [diagnostic]
    if result is not None and result.returncode == 0 and result.stdout.strip():
        printers = _parse_windows_printer_json(result.stdout)
        if printers:
            return printers, diagnostics
    fallback = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-CimInstance Win32_Printer | Select-Object Name,PortName,DriverName,Location,Comment,PrinterStatus,Default | ConvertTo-Json -Depth 2",
    ]
    fallback_result, fallback_diagnostic = _run_command(fallback, "windows-cim-printer", timeout=15)
    diagnostics.append(fallback_diagnostic)
    if fallback_result is None or fallback_result.returncode != 0 or not fallback_result.stdout.strip():
        return {}, diagnostics
    printers = _parse_windows_printer_json(fallback_result.stdout)
    if not printers:
        diagnostics.append(_diagnostic("windows-printers", True, "Windows 未返回已安装打印机。", "请先在系统“打印机和扫描仪”中安装打印机。"))
    return printers, diagnostics


def _parse_windows_printer_json(raw_json: str) -> dict[str, dict[str, object]]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    rows = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
    printers: dict[str, dict[str, object]] = {}
    for row in rows:
        name = str(row.get("Name") or "").strip()
        if not name:
            continue
        queue_name = _normalize_queue_name(name)
        uri = str(row.get("PortName") or name)
        printers[queue_name] = {
            "name": queue_name,
            "uri": uri,
            "driver": str(row.get("DriverName") or "system"),
            "location": str(row.get("Location") or ""),
            "description": str(row.get("Comment") or name),
            "model": str(row.get("DriverName") or row.get("Comment") or name),
            "connection": _connection_type(uri),
            "status": f"Windows 状态 {row.get('PrinterStatus')}" if row.get("PrinterStatus") is not None else "Windows 系统已安装打印机",
            "is_default": bool(row.get("Default")),
            "is_enabled": True,
            "display_name": name,
        }
    return printers


def _macos_profiler_printers(existing: dict[str, dict[str, object]]) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    result, diagnostic = _run_command(["system_profiler", "SPPrintersDataType"], "macos-system-profiler", timeout=25)
    diagnostics = [diagnostic]
    printers: dict[str, dict[str, object]] = {}
    if result is None or result.returncode != 0:
        return printers, diagnostics
    current: dict[str, object] | None = None
    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "Printers:":
            continue
        if raw_line.startswith("    ") and not raw_line.startswith("      ") and stripped.endswith(":"):
            display = stripped[:-1]
            current = {
                "name": _normalize_queue_name(display),
                "uri": "",
                "driver": "system",
                "location": "",
                "description": display,
                "model": display,
                "connection": "Unknown",
                "status": "macOS 系统已安装打印机",
                "is_default": False,
                "is_enabled": True,
            }
            printers[str(current["name"])] = current
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip()
        if key in {"URI", "URL"}:
            current["uri"] = value
            current["connection"] = _connection_type(value)
        elif key == "Location":
            current["location"] = value
        elif key in {"Make and Model", "Driver Version"}:
            current["description"] = value or current.get("description", "")
            current["model"] = value or current.get("model", "")
        elif key == "Default" and value.lower() == "yes":
            current["is_default"] = True
    for name in existing:
        printers.pop(name, None)
    return printers, diagnostics


def _connection_type(uri: object) -> str:
    value = str(uri or "").lower()
    if value.startswith("usb:"):
        return "USB"
    if value.startswith(("ipp:", "ipps:", "socket:", "lpd:", "dnssd:", "mdns:")) or "._tcp" in value:
        return "Network"
    if value.startswith(("file:", "parallel:", "serial:")):
        return "Local"
    return "Unknown"


def _normalize_queue_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name)).strip("._-")
    return cleaned[:80] or "Discovered_Printer"


def _cups_default_printer_name(conn) -> str:
    try:
        return str(conn.getDefault() or "")
    except Exception:
        return ""


def print_pdf(
    pdf_path: Path,
    copies: int,
    double_sided: bool,
    printer_name: str | None = None,
    default_printer: str | None = None,
) -> tuple[str | None, str | None]:
    settings = get_settings()
    if _platform_name() == "windows":
        return _windows_print_pdf(pdf_path, printer_name or default_printer or settings.default_printer)
    target = printer_name or default_printer or settings.default_printer
    if not target:
        return None, "未指定打印机，也未配置默认打印机。"
    connectivity_error = _cups_connectivity_error("发送打印任务")
    if connectivity_error:
        return None, connectivity_error
    # 打印前整页光栅化：把 PDF 每页转成不透明位图再重组为纯图像 PDF 提交打印。
    # 这样远端 CUPS/打印机的 RIP 只需画一张普通图片，彻底规避「老式 OLE 公式、WMF/EMF
    # 预览图、透明图元在远端光栅化引擎上被整块丢弃」导致的「预览正常、上传打印后化学式
    # 消失」。仅作用于打印副本，不改动入库/预览用的原始矢量 PDF；光栅化失败则安全降级为
    # 直接打印原 PDF，绝不阻断打印。页数、页序保持一致，份数/双面参数语义不变。
    submit_path = pdf_path
    # 光栅化「尽力而为」：任何异常都降级为直接打印原 PDF，绝不让后处理导致打印接口 500。
    try:
        rasterized_path = rasterize_pdf_for_print(pdf_path)
    except Exception:
        rasterized_path = None
    if rasterized_path is not None:
        submit_path = rasterized_path
    command = ["lp", "-d", target]
    if copies > 1:
        command.extend(["-n", str(copies)])
    if double_sided:
        command.extend(["-o", "sides=two-sided-long-edge"])
    command.append(str(submit_path))
    try:
        result = _run(command, timeout=30)
    finally:
        # 打印任务已由 CUPS 复制/入队，删除本地光栅化临时 PDF，避免残留占用磁盘。
        if rasterized_path is not None:
            try:
                rasterized_path.unlink(missing_ok=True)
            except Exception:
                pass
    if result.returncode != 0:
        return None, _command_error(result, "打印命令执行失败")
    job_id = _extract_job_id(result.stdout) or result.stdout.strip() or "cups-job"
    return job_id, None


def _extract_job_id(output: str) -> str:
    match = re.search(r"request id is\s+(\S+)", output)
    return match.group(1) if match else ""


def print_jobs_active(job_ids: str | list[str] | tuple[str, ...]) -> bool | None:
    if _platform_name() == "windows":
        return None
    ids = _normalize_print_job_ids(job_ids)
    if not ids:
        return False
    connectivity_error = _cups_connectivity_error("确认打印任务状态")
    if connectivity_error:
        return None
    try:
        result = _run(["lpstat", "-W", "not-completed", "-o"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    active_ids = set(_normalize_print_job_ids(result.stdout))
    return any(job_id in active_ids for job_id in ids)


def _normalize_print_job_ids(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = "\n".join(str(item) for item in value)
    else:
        raw = str(value or "")
    return re.findall(r"\b[A-Za-z0-9_.-]+-\d+\b", raw)


def _windows_print_pdf(pdf_path: Path, printer_name: str | None) -> tuple[str | None, str | None]:
    settings = get_settings()
    # SumatraPDF / 自定义 PrintTo 命令来自 config/config.json（不再读环境变量）。
    sumatra_path = (settings.sumatra_pdf_path or settings.windows_pdf_print_command or "").strip()
    target = _resolve_windows_printer_name(printer_name or settings.default_printer)
    if sumatra_path:
        result = _run([sumatra_path, "-print-to", target or "", "-silent", str(pdf_path)], timeout=30)
        if result.returncode != 0:
            return None, _command_error(result, "SumatraPDF 打印失败")
        return "windows-sumatra-job", None
    if not target:
        return None, "Windows 打印需要指定打印机，或配置默认打印机。"
    escaped_path = str(pdf_path).replace("'", "''")
    escaped_printer = target.replace("'", "''")
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Start-Process -FilePath '{escaped_path}' -Verb PrintTo -ArgumentList '{escaped_printer}' -WindowStyle Hidden"]
    result = _run(command, timeout=30)
    if result.returncode != 0:
        return None, f"{_command_error(result, 'Windows PrintTo 打印失败')}；建议在 config.json 里配置 sumatra_pdf_path。"
    return "windows-printto-job", None


def _resolve_windows_printer_name(name: str | None) -> str:
    if not name:
        return ""
    if _platform_name() != "windows":
        return name
    for queue_name, printer in list_system_printers().items():
        display_name = str(printer.get("display_name") or queue_name)
        if name in {queue_name, display_name}:
            return display_name
    return name
