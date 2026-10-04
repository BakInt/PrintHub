import logging
import platform
import threading
from datetime import datetime, timedelta, timezone

import sqlite3

from ..config import get_settings
from ..database import connect
from .printer import print_jobs_active


def _check_interval_seconds() -> int:
    """监控间隔取自 config/config.json 的 print_status_check_interval_seconds。"""

    return max(5, int(get_settings().print_status_check_interval_seconds))


def _print_confirm_timeout_seconds() -> int:
    """确认超时取自 config/config.json 的 print_confirm_timeout_seconds。"""

    return max(30, int(get_settings().print_confirm_timeout_seconds))


logger = logging.getLogger(__name__)

_monitor_lock = threading.Lock()
_monitor_started = False
_stop_event = threading.Event()


def start_print_status_monitor() -> None:
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True
        thread = threading.Thread(target=_monitor_loop, name="print-status-monitor", daemon=True)
        thread.start()


def _monitor_loop() -> None:
    interval = _check_interval_seconds()
    logger.info("打印状态后台监控线程已启动，每 %s 秒检查一次。", interval)
    while not _stop_event.wait(interval):
        try:
            changed = check_printing_orders()
            if changed:
                logger.info("打印状态后台检测更新了 %s 个订单。", changed)
        except Exception:
            logger.exception("打印状态后台检测失败")
        interval = _check_interval_seconds()


def check_printing_orders(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    changed = 0
    with connect() as db:
        orders = db.execute(
            """
            SELECT id, status, print_job_id, printed_at, created_at
            FROM orders
            WHERE status = 'printing'
              AND print_job_id IS NOT NULL
              AND print_job_id != ''
            """
        ).fetchall()
        for order in orders:
            changed += update_printing_order_status(db, order, now)
        _check_cups_health(db, now)
        db.commit()
    return changed


def _create_cups_alert(db: sqlite3.Connection, alert_type: str, message: str, now: datetime) -> None:
    existing = db.execute(
        """
        SELECT id FROM alerts
        WHERE level = 'error' AND status = 'open' AND message LIKE ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (f"%{message[:100]}%",),
    ).fetchone()
    
    if existing:
        created = existing["created_at"]
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                if now - created_dt < timedelta(minutes=30):
                    return
            except (ValueError, TypeError):
                pass
    
    alert_id = f"cups-{alert_type}-{now.strftime('%Y%m%d%H%M%S')}-{hash(message) % 10000}"
    db.execute(
        """
        INSERT OR IGNORE INTO alerts (id, level, message, status, created_at)
        VALUES (?, 'error', ?, 'open', ?)
        """,
        (alert_id, message, now.isoformat()),
    )


def _check_cups_health(db: sqlite3.Connection, now: datetime) -> None:
    """检测 CUPS 服务是否可用，不可用且有打印订单在等待时写入告警。

    该函数对任何异常都保持静默，避免影响主监控流程；Windows 平台不做 CUPS 健康检查。
    """
    if platform.system().lower() == "windows":
        return
    pending = db.execute(
        """
        SELECT COUNT(*) AS count FROM orders
        WHERE order_type = 'print' AND status IN ('printing', 'paid')
        """
    ).fetchone()
    if not pending or int(pending["count"]) == 0:
        return
    try:
        from ..utils.cups_utils import test_cups_connection

        result = test_cups_connection()
    except Exception:
        logger.exception("检测 CUPS 健康状态失败")
        return
    if not result.get("connected"):
        error = result.get("error") or "CUPS 服务不可达"
        _create_cups_alert(
            db,
            "connection",
            f"CUPS 打印服务不可用，打印任务可能无法送达或无法确认完成：{error}",
            now,
        )


def refresh_printing_order_status(db: sqlite3.Connection, order: sqlite3.Row, now: datetime | None = None) -> sqlite3.Row:
    if order["status"] != "printing" or not order["print_job_id"]:
        return order
    changed = update_printing_order_status(db, order, now or datetime.utcnow())
    if changed:
        db.commit()
        refreshed = db.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
        return refreshed or order
    return order


def update_printing_order_status(
    db: sqlite3.Connection,
    order: sqlite3.Row,
    now: datetime,
) -> int:
    active = print_jobs_active(order["print_job_id"])
    if active is False:
        cursor = db.execute(
            """
            UPDATE orders
            SET status = 'completed',
                print_error = NULL,
                printed_at = COALESCE(printed_at, ?)
            WHERE id = ? AND status = 'printing'
            """,
            (now.isoformat(), order["id"]),
        )
        return cursor.rowcount

    started_at = _order_print_started_at(order, now)
    if not order["printed_at"]:
        db.execute("UPDATE orders SET printed_at = ? WHERE id = ? AND status = 'printing'", (started_at.isoformat(), order["id"]))

    confirm_timeout_seconds = _print_confirm_timeout_seconds()
    if now - started_at < timedelta(seconds=confirm_timeout_seconds):
        return 0

    timeout_minutes = max(1, int(round(confirm_timeout_seconds / 60)))
    error = (
        f"打印任务 {order['print_job_id']} 在 {timeout_minutes} 分钟内未确认完成，"
        "请检查打印机队列、离线、缺纸或驱动状态。"
    )
    cursor = db.execute(
        """
        UPDATE orders
        SET status = 'print_failed',
            print_error = ?
        WHERE id = ? AND status = 'printing'
        """,
        (error, order["id"]),
    )
    return cursor.rowcount


def _order_print_started_at(order: sqlite3.Row, fallback: datetime) -> datetime:
    return _parse_datetime(order["printed_at"]) or fallback


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
