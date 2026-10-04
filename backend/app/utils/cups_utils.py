import os
import socket
from typing import Optional, Tuple

try:
    import cups
except ImportError:
    cups = None

from ..config import get_settings


def cups_available() -> bool:
    return cups is not None


def _read_cups_config_from_db() -> dict | None:
    try:
        import sqlite3
        from ..config import get_settings
        
        settings = get_settings()
        if not settings.database_path.exists():
            return None
        
        conn = sqlite3.connect(str(settings.database_path))
        conn.row_factory = sqlite3.Row
        
        cursor = conn.execute("SELECT key, value FROM settings WHERE key IN ('cups_server', 'cups_user', 'cups_password')")
        rows = cursor.fetchall()
        conn.close()
        
        db_config = {row["key"]: row["value"] for row in rows}
        
        if db_config.get("cups_server") or db_config.get("cups_user") or db_config.get("cups_password"):
            return db_config
        return None
    except Exception:
        return None


def get_cups_config() -> dict:
    db_config = _read_cups_config_from_db()
    
    settings = get_settings()
    
    if db_config and db_config.get("cups_server"):
        server = db_config["cups_server"].strip()
    else:
        server = settings.cups_server.strip()
    
    if db_config and db_config.get("cups_user") is not None:
        user = db_config["cups_user"].strip()
    else:
        user = settings.cups_user.strip()
    
    if db_config and db_config.get("cups_password") is not None:
        password = db_config["cups_password"].strip()
    else:
        password = settings.cups_password.strip()
    
    host = "localhost"
    port = 631
    
    if server:
        if ":" in server and not server.startswith("["):
            parts = server.rsplit(":", 1)
            host = parts[0]
            if len(parts) > 1:
                try:
                    port = int(parts[1])
                except ValueError:
                    pass
        else:
            host = server
    
    return {
        "host": host,
        "port": port,
        "server": server,
        "user": user,
        "password": password,
    }


def _setup_cups_auth(config: dict) -> None:
    if cups is None:
        return
    
    if config["user"]:
        if hasattr(cups, "setUser"):
            cups.setUser(config["user"])
    
    if config["password"]:
        def _password_callback(prompt):
            return config["password"]
        
        if hasattr(cups, "setPasswordCB"):
            cups.setPasswordCB(_password_callback)


def create_cups_connection(timeout: int = 10) -> Tuple[Optional[object], Optional[str]]:
    if cups is None:
        return None, "pycups 未安装，请安装 pycups 和 libcups 开发库"
    
    config = get_cups_config()
    
    if hasattr(cups, "setServer"):
        cups.setServer(config["host"])
    if hasattr(cups, "setPort"):
        cups.setPort(config["port"])
    
    _setup_cups_auth(config)
    
    try:
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        
        conn = cups.Connection()
        
        socket.setdefaulttimeout(original_timeout)
        
        return conn, None
    except Exception as exc:
        message = str(exc)
        if "unauthorized" in message.lower() or "not-authorized" in message.lower():
            message = f"CUPS 认证失败：{message}。请检查 CUPS_USER 和 CUPS_PASSWORD 是否正确，以及软路由 CUPS 服务器是否允许该用户访问。"
        elif "Connection refused" in message or "Connection reset" in message:
            message = f"无法连接 CUPS 服务器 {config['host']}:{config['port']}：{message}。请检查软路由 CUPS 服务是否启动，网络是否可达。"
        elif "timed out" in message.lower():
            message = f"连接 CUPS 服务器超时：{message}。请检查网络连接和软路由防火墙设置。"
        return None, message


def cups_call(action: str, callback, timeout: int = 10) -> Tuple[Optional[object], dict]:
    if cups is None:
        return None, {
            "success": False,
            "error": f"{action}失败：pycups 未安装",
            "diagnostics": [{
                "source": "pycups",
                "ok": False,
                "message": "pycups 不可用",
                "hint": "请安装 pycups，并确认系统包含 libcups2-dev/libcups2",
            }],
        }
    
    config = get_cups_config()
    conn, error = create_cups_connection(timeout)
    if conn is None:
        return None, {
            "success": False,
            "error": f"{action}失败：{error}",
            "diagnostics": [{
                "source": "pycups",
                "ok": False,
                "message": error,
                "hint": "请检查 CUPS 服务器配置和网络连接",
            }],
        }
    
    try:
        result = callback(conn)
        return result, {
            "success": True,
            "diagnostics": [{
                "source": "pycups",
                "ok": True,
                "message": f"{action}成功",
                "hint": "",
            }],
        }
    except Exception as exc:
        message = str(exc)
        is_permission_error = any(keyword in message.lower() for keyword in [
            "unauthorized", "not-authorized", "forbidden", "4096", "没有足够的权限"
        ])
        
        diagnostics = []
        
        if cups is not None and isinstance(exc, cups.IPPError):
            parts = [str(part) for part in exc.args if str(part)]
            error_code = None
            error_msg = message
            
            if len(parts) >= 2:
                try:
                    error_code = int(parts[0])
                    error_msg = parts[1] if len(parts) > 1 else message
                except (ValueError, TypeError):
                    pass
            
            diagnostics.append({
                "source": "pycups-ipp",
                "ok": False,
                "message": f"IPP 错误码: {error_code}, 消息: {error_msg}",
                "hint": _ipp_error_hint(error_code, action),
            })
            
            message = f"{error_msg} (IPP 错误码: {error_code})"
        
        if is_permission_error:
            error_message = f"CUPS 拒绝执行“{action}”：当前用户没有足够的管理权限"
            hint = f"请检查 CUPS_USER={config['user']} 的权限，或在软路由 CUPS 配置中授权该用户"
        elif "1280" in message or "server-error-internal-error" in message.lower():
            error_message = f"{action}失败：CUPS 服务器内部错误"
            hint = "这通常是因为：1) PPD 驱动文件不存在或格式错误；2) CUPS 服务器配置问题；3) 打印机 URI 格式不正确。请检查驱动名称和打印机 URI。"
        elif "1200" in message or "server-error-device-error" in message.lower():
            error_message = f"{action}失败：设备错误"
            hint = "请检查打印机是否已连接、电源是否开启、网络是否可达。"
        elif "1203" in message or "server-error-not-found" in message.lower():
            error_message = f"{action}失败：资源未找到"
            hint = "请检查 PPD 驱动文件路径是否正确，或打印机队列名称是否存在。"
        else:
            error_message = f"{action}失败：{message}"
            hint = "请检查 CUPS 服务器状态和打印机配置"
        
        diagnostics.append({
            "source": "pycups",
            "ok": False,
            "message": message,
            "hint": hint,
        })
        
        return None, {
            "success": False,
            "error": error_message,
            "diagnostics": diagnostics,
            "raw_error": str(exc),
        }


def _ipp_error_hint(error_code: int, action: str) -> str:
    hints = {
        1200: "设备错误：请检查打印机连接和电源状态。",
        1201: "设备超时：打印机可能未响应。",
        1202: "设备忙：打印机正在处理其他任务。",
        1203: "未找到：请检查 PPD 驱动文件路径或队列名称。",
        1204: "已被取消：任务已被取消。",
        1205: "文档格式错误：请检查文档格式。",
        1206: "权限不足：当前用户没有权限执行此操作。",
        1207: "已认证：需要认证。",
        1208: "未认证：认证失败或未提供凭证。",
        1209: "不需要：操作不需要执行。",
        1210: "版本不支持：协议版本不兼容。",
        1211: "设备错误：打印机设备出错。",
        1212: "临时错误：临时错误，请稍后重试。",
        1280: "服务器内部错误：这通常是 PPD 驱动问题、CUPS 配置问题或打印机 URI 格式错误。",
        1281: "操作不支持：当前操作不被支持。",
        1282: "操作被取消：操作已被取消。",
        1283: "操作中止：操作被中止。",
        1284: "操作失败：操作失败。",
        1285: "操作不接受：操作不被接受。",
        1286: "操作挂起：操作挂起。",
        1287: "操作冲突：操作冲突。",
        1288: "操作已被重定向：操作已被重定向。",
        1289: "操作已被重试：操作需要重试。",
        1290: "操作已被延迟：操作已被延迟。",
    }
    return hints.get(error_code, f"未知错误码 {error_code}，请查看 CUPS 日志获取更多信息。")


def cups_error_message(exc: Exception, fallback: str = "CUPS 操作失败") -> str:
    if cups is not None and isinstance(exc, cups.IPPError):
        parts = [str(part) for part in exc.args if str(part)]
        return "：".join(parts) or fallback
    return str(exc) or fallback


def is_cups_permission_error(message: str) -> bool:
    normalized = (message or "").lower()
    return any(keyword in normalized for keyword in [
        "unauthorized", "not-authorized", "forbidden", "4096",
        "cups 拒绝", "没有足够的 cups", "没有足够的打印机管理权限"
    ])


def cups_connectivity_hint() -> str:
    config = get_cups_config()
    server_info = f"{config['host']}:{config['port']}"
    if config["user"]:
        return f"请确认 CUPS 服务器 {server_info} 可访问，用户 {config['user']} 有权限执行操作。软路由 CUPS 可能需要在 cupsd.conf 中配置 Allow @LOCAL 或特定用户。"
    return f"请确认 CUPS 服务器 {server_info} 可访问，且当前用户有权限执行 CUPS 命令。"


def get_cups_env() -> dict[str, str]:
    config = get_cups_config()
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    env["CUPS_SERVER"] = f"{config['host']}:{config['port']}"
    if config["user"]:
        env["CUPS_USER"] = config["user"]
    return env


def test_cups_connection() -> dict:
    conn, error = create_cups_connection()
    if conn is None:
        return {
            "success": False,
            "connected": False,
            "error": error,
            "config": get_cups_config(),
        }
    
    try:
        printers = conn.getPrinters()
        default = conn.getDefault()
        return {
            "success": True,
            "connected": True,
            "printer_count": len(printers),
            "default_printer": default or "",
            "config": get_cups_config(),
        }
    except Exception as exc:
        return {
            "success": False,
            "connected": True,
            "error": str(exc),
            "config": get_cups_config(),
        }