"""打印派发：订单支付完成后把打印任务送到打印机。

【性能修复】原先派发在支付/回调的 HTTP 请求里同步执行——打印前整页光栅化 + lp
提交全部完成后请求才返回，文档页数多时用户支付后要等几十秒。现在改为：

- 请求线程只负责「确认是打印单 + 调度」，立即返回；订单停留在 paid（排队口径
  本就把 paid 与 printing 都算作排队中，前端轮询逻辑无需改动）；
- 后台线程用独立数据库连接执行真正的派发（dispatch_order_print），完成后把订单
  置为 printing / print_failed；
- ASYNC_DISPATCH 置 False 时完全回到旧的同步行为（冒烟测试等需要确定性断言的
  场景使用，语义与历史版本一致：在调用方事务内派发，随调用方一起提交）。

防重与兜底：
- 进程内 inflight 集合去重，同一订单同一时刻最多一个派发线程；
- 后台线程先等订单进入 paid（覆盖「先调度、后提交事务」的窗口），已处于
  printing/print_failed/completed 的订单直接退出，天然防重复打印；
- 进程重启等极端情况导致订单停留在 paid 未派发时，下次支付回调的补派发分支
  （complete_epay_payment 的 already_paid 路径）仍会重新调度，与旧版语义一致。
"""

import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from ..database import connect
from .pdf_postprocess import merge_pdfs
from .printer import print_pdf

logger = logging.getLogger(__name__)

# 生产默认异步派发；冒烟测试等确定性场景置 False 回到同步行为。
ASYNC_DISPATCH = True

_inflight_lock = threading.Lock()
_inflight_orders: set[str] = set()


def order_has_print_files(db: sqlite3.Connection, order_id: str) -> bool:
    row = db.execute("SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?", (order_id,)).fetchone()
    return bool(row and int(row["count"]) > 0)


def dispatch_order_print(db: sqlite3.Connection, order_id: str) -> None:
    """把已支付订单的文件逐份提交到打印机，并回写 printing / print_failed 状态。"""
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    files = db.execute(
        """
        SELECT files.pdf_path AS pdf_path, files.needs_rasterize AS needs_rasterize,
               order_items.is_double_sided AS is_double_sided
        FROM order_items
        JOIN files ON files.id = order_items.file_id
        WHERE order_items.order_id = ?
        ORDER BY order_items.rowid
        """,
        (order_id,),
    ).fetchall()
    if not files:
        return
    default_printer = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    default_value = default_printer["value"] if default_printer else None
    # 【新增功能】彩色打印：orders.use_color 为 NULL 表示历史订单/旧前端未指定，
    # 此时向 print_pdf 传 None，完全沿用原有打印逻辑（不转黑白也不强制黑白）。
    color_raw = order["use_color"]
    use_color = None if color_raw is None else bool(color_raw)

    # 【性能修复】按文件的条件光栅化标记决定是否打印前整页光栅化：
    # Office 转换件、含 SMask/Mask 遮罩的 PDF 仍光栅化（防远端 RIP 丢公式/插图）；
    # 纯净 PDF / 图片转换件直接提交原文件，省掉每页 300dpi 光栅化的几十秒耗时。
    # 旧数据/意外缺失的标记一律按 1 处理（保持旧的「一律光栅化」行为，宁慢勿丢图）。
    def _rasterize_flag(value) -> bool:
        return bool(value) if value is not None else True

    errors = []
    job_ids = []
    # 【新增功能】合并双面打印（orders.merge_duplex=1）：把全部文档按下单顺序合并成
    # 一个临时 PDF，作为一个双面任务提交——不同文档的页面连续排到纸张正反面，
    # 两份单页文档也能打在同一张纸的正反两面。合并失败按打印失败处理。
    if bool(order["merge_duplex"]):
        merged_path = None
        try:
            merged_path = merge_pdfs([Path(row["pdf_path"]) for row in files])
            job_id, error = print_pdf(
                merged_path,
                order["copies"],
                True,
                order["printer_name"],
                default_printer=default_value,
                use_color=use_color,
                rasterize=any(_rasterize_flag(row["needs_rasterize"]) for row in files),
            )
            if error:
                errors.append(error)
            elif job_id:
                job_ids.append(job_id)
        except Exception as exc:
            errors.append(f"合并双面打印文件失败：{exc}")
        finally:
            if merged_path is not None:
                try:
                    merged_path.unlink()
                except OSError:
                    pass
    else:
        for file_row in files:
            job_id, error = print_pdf(
                file_row["pdf_path"],
                order["copies"],
                bool(file_row["is_double_sided"]),
                order["printer_name"],
                default_printer=default_value,
                use_color=use_color,
                rasterize=_rasterize_flag(file_row["needs_rasterize"]),
            )
            if error:
                errors.append(error)
            elif job_id:
                job_ids.append(job_id)
    if errors:
        db.execute(
            "UPDATE orders SET status = 'print_failed', print_error = ? WHERE id = ?",
            ("; ".join(errors), order_id),
        )
    else:
        db.execute(
            "UPDATE orders SET status = 'printing', print_job_id = ?, printed_at = ? WHERE id = ?",
            ("\n".join(job_ids), datetime.utcnow().isoformat(), order_id),
        )


def dispatch_print_files_if_present(db: sqlite3.Connection, order_id: str) -> None:
    """支付完成回调入口：确认是打印单后派发（异步模式仅调度，同步模式在调用方事务内执行）。"""
    if not order_has_print_files(db, order_id):
        return
    if ASYNC_DISPATCH:
        schedule_order_dispatch(order_id)
    else:
        dispatch_order_print(db, order_id)


def schedule_order_dispatch(order_id: str) -> None:
    """调度后台派发线程；同一订单已在派发中时静默去重。"""
    with _inflight_lock:
        if order_id in _inflight_orders:
            return
        _inflight_orders.add(order_id)
    thread = threading.Thread(
        target=_dispatch_worker,
        args=(order_id,),
        name=f"print-dispatch-{order_id}",
        daemon=True,
    )
    thread.start()


def _dispatch_worker(order_id: str) -> None:
    try:
        db = connect()
        try:
            if not _wait_for_paid(db, order_id):
                return
            dispatch_order_print(db, order_id)
            db.commit()
            logger.info("订单 %s 后台打印派发完成", order_id)
        finally:
            db.close()
    except Exception as exc:
        logger.exception("订单 %s 后台打印派发失败", order_id)
        _mark_dispatch_failed(order_id, exc)
    finally:
        with _inflight_lock:
            _inflight_orders.discard(order_id)


def _wait_for_paid(db: sqlite3.Connection, order_id: str) -> bool:
    """等待订单进入可派发的 paid 状态；返回 False 表示无需/不可派发。

    调度可能发生在调用方提交事务之前（支付回调先回调、后 commit），此时订单行
    本身与 paid 状态都尚未对其他连接可见——「行不存在」和 pending 一样属于
    「等待调用方提交」的窗口，必须继续轮询而不是放弃。已进入
    printing/completed/print_failed 的订单直接退出（防重复打印）。
    """
    for _ in range(48):  # 最多等 ~12 秒
        row = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            time.sleep(0.25)  # 调用方事务尚未提交，订单行还不可见
            continue
        status = row["status"]
        if status == "paid":
            return True
        if status in ("printing", "completed", "print_failed"):
            return False
        time.sleep(0.25)
    logger.error("订单 %s 未在预期时间内进入 paid 状态，放弃后台派发", order_id)
    return False


def _mark_dispatch_failed(order_id: str, exc: Exception) -> None:
    """派发线程异常时把订单写回 print_failed，避免永远停留在 paid。"""
    try:
        db = connect()
        try:
            db.execute(
                "UPDATE orders SET status = 'print_failed', print_error = ? WHERE id = ? AND status = 'paid'",
                (f"打印派发异常：{exc}", order_id),
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("订单 %s 写回派发失败状态时出错", order_id)
