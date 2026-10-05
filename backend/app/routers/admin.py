import sqlite3
import shutil
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..config import get_settings as get_app_settings
from ..database import get_db
from ..models.schemas import AdminRedemptionBatchCreate, AdminRedemptionCreate, AdminUserCreate, AdminUserUpdate, BackupCreateRequest, BackupPolicyUpdate, BalanceSet, BalanceUpdate, FileCacheCleanupRequest, PaymentSettingsUpdate, PaymentTestRequest, PrinterEnabledUpdate, PrinterTestPageRequest, PrinterTestResult, PrinterUpdate, PrinterUriProbe, SettingsUpdate
from ..services.backup import backup_file_path, backup_policy, create_backup, delete_backup, inspect_initial_restore, inspect_uploaded_backup, is_initial_restore_available, list_backups, restore_initial_backup, restore_uploaded_backup, update_backup_policy
from ..services.epay import build_success_notify_payload, complete_epay_payment, create_epay_request, get_payment_settings, validate_payment_settings
from ..services.cups_printer import get_printer as get_cups_printer, clear_default_printer, import_ppd_driver, list_printer_drivers, list_printer_jobs, list_printers, normalize_printer_uri, printer_system, probe_printer_uri, record_printer_test_result, remove_printer, set_default_printer, set_printer_enabled, test_printer, update_printer
from ..services.print_monitor import check_printing_orders
from ..services.queue import queue_overview
from ..services.redemption import batch_generate_codes, create_code, delete_code, list_code_logs, list_codes
# 必须用别名引入：下面的路由函数同名会覆盖模块级名字，导致路由调用自己。
from ..services.stats import daily_stats as build_daily_stats
from ..utils.security import hash_password
from .deps import admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"])
setup_router = APIRouter(prefix="/api/setup", tags=["setup"])

PAYMENT_TEST_SUBJECT = "云打印测试支付"


def _serialize_payment_test(db: sqlite3.Connection, order_id: str) -> dict:
    if not order_id.startswith("TEST"):
        raise HTTPException(status_code=400, detail="仅支持测试支付单")
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="测试支付单不存在")
    payment = db.execute(
        "SELECT * FROM payments WHERE order_id = ? ORDER BY paid_at DESC, rowid DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    return {
        "success": True,
        "order_id": order["id"],
        "amount": float(order["total_amount"]),
        "payment_method": order["payment_method"],
        "status": order["status"],
        "paid_at": order["paid_at"],
        "payment_status": payment["status"] if payment else None,
        "epay_trade_no": payment["epay_trade_no"] if payment else None,
        "payment_url": f"/api/payment/submit/{order['id']}",
    }


@router.get("/dashboard")
def dashboard(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    totals = db.execute(
        """
        SELECT
            COUNT(*) AS orders_count,
            COALESCE(SUM(total_amount), 0) AS revenue,
            SUM(CASE WHEN status = 'print_failed' THEN 1 ELSE 0 END) AS failed_prints,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_orders
        FROM orders
        """
    ).fetchone()
    overview = queue_overview(db)
    result = dict(totals)
    result["printing_count"] = overview["printing_count"]
    result["queue_count"] = overview["total"]
    return {"totals": result}


@router.get("/daily-stats")
def daily_stats(days: int = Query(default=7, ge=1, le=90), db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    """后台概览「每日数据统计」：按**本地时区**返回最近 N 天的订单数、收入与打印失败数。

    时间范围切换按钮传 `days=7` / `days=30`；聚合与分日口径集中在
    `backend/app/services/stats.py`（库里时间戳是 UTC 文本，同一张表还混着
    `YYYY-MM-DD HH:MM:SS` 与 `YYYY-MM-DDTHH:MM:SS.ffffff` 两种格式）。
    """
    return build_daily_stats(db, days)


@router.get("/print-queue")
def print_queue(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    return queue_overview(db)


@router.post("/orders/refresh-print-status")
def refresh_print_status(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    """管理员主动确认所有 printing 订单的打印状态，不依赖前台刷新。"""
    changed = check_printing_orders()
    overview = queue_overview(db)
    return {"success": True, "updated": changed, "queue": overview}



@router.get("/orders")
def orders(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    rows = db.execute(
        """
        SELECT
            orders.*,
            payments.status AS payment_status,
            payments.paid_at AS payment_paid_at,
            payments.epay_trade_no AS epay_trade_no
        FROM orders
        LEFT JOIN payments ON payments.rowid = (
            SELECT rowid
            FROM payments AS latest_payment
            WHERE latest_payment.order_id = orders.id
            ORDER BY latest_payment.paid_at DESC, latest_payment.rowid DESC
            LIMIT 1
        )
        ORDER BY orders.created_at DESC
        LIMIT 100
        """
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("/orders/{order_id}/mark-complete")
def mark_order_complete(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    db.execute("UPDATE orders SET status = 'completed', printed_at = COALESCE(printed_at, ?) WHERE id = ?", (datetime.utcnow().isoformat(), order_id))
    db.commit()
    return {"success": True}


@router.delete("/orders/{order_id}")
def delete_order(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    order = db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return {"success": True}
    result = _delete_order_records(db, order_id)
    db.commit()
    return result


@router.delete("/orders/{order_id}/unpaid")
def delete_unpaid_order(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    order = db.execute("SELECT id, status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return {"success": True}
    payment = db.execute(
        """
        SELECT status
        FROM payments
        WHERE order_id = ?
        ORDER BY paid_at DESC, rowid DESC
        LIMIT 1
        """,
        (order_id,),
    ).fetchone()
    if order["status"] != "pending" or (payment and payment["status"] == "paid"):
        raise HTTPException(status_code=422, detail="仅允许删除未支付订单")
    result = _delete_order_records(db, order_id)
    db.commit()
    return result


@router.delete("/orders/unpaid/bulk")
def delete_all_unpaid_orders(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    rows = db.execute(
        """
        SELECT id
        FROM orders
        WHERE status = 'pending'
          AND NOT EXISTS (
              SELECT 1
              FROM payments
              WHERE payments.order_id = orders.id
                AND payments.status = 'paid'
          )
        ORDER BY created_at DESC
        """
    ).fetchall()
    deleted_order_ids = []
    deleted_files = []
    skipped_shared_files = []
    for row in rows:
        result = _delete_order_records(db, row["id"])
        deleted_order_ids.append(row["id"])
        deleted_files.extend(result["deleted_files"])
        skipped_shared_files.extend(result["skipped_shared_files"])
    db.commit()
    return {
        "success": True,
        "deleted": len(deleted_order_ids),
        "deleted_order_ids": deleted_order_ids,
        "deleted_files": deleted_files,
        "skipped_shared_files": skipped_shared_files,
    }


def _delete_order_records(db: sqlite3.Connection, order_id: str) -> dict:
    order_files = db.execute(
        """
        SELECT DISTINCT files.*
        FROM order_items
        JOIN files ON files.id = order_items.file_id
        WHERE order_items.order_id = ?
        """,
        (order_id,),
    ).fetchall()
    upload_root = get_app_settings().upload_dir.resolve()
    file_cleanup_targets = []
    skipped_shared_files = []
    for file_row in order_files:
        other_order_count = db.execute(
            "SELECT COUNT(*) AS count FROM order_items WHERE file_id = ? AND order_id != ?",
            (file_row["id"], order_id),
        ).fetchone()
        if int(other_order_count["count"]) > 0:
            skipped_shared_files.append(file_row["id"])
            continue
        file_cleanup_targets.append((file_row, _file_cache_target(file_row, upload_root)))

    db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
    db.execute("DELETE FROM payments WHERE order_id = ?", (order_id,))
    db.execute("DELETE FROM alerts WHERE order_id = ?", (order_id,))

    deleted_files = []
    for file_row, target in file_cleanup_targets:
        if target and target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        db.execute("DELETE FROM alerts WHERE file_id = ?", (file_row["id"],))
        db.execute("DELETE FROM files WHERE id = ?", (file_row["id"],))
        deleted_files.append(file_row["id"])

    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    return {"success": True, "deleted_files": deleted_files, "skipped_shared_files": skipped_shared_files}


@router.get("/orders/{order_id}/detail")
def order_detail(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    order = db.execute(
        """
        SELECT
            orders.*,
            payments.status AS payment_status,
            payments.paid_at AS payment_paid_at,
            payments.epay_trade_no AS epay_trade_no,
            users.username AS user_username,
            users.email AS user_email,
            users.phone AS user_phone
        FROM orders
        LEFT JOIN payments ON payments.rowid = (
            SELECT rowid
            FROM payments AS latest_payment
            WHERE latest_payment.order_id = orders.id
            ORDER BY latest_payment.paid_at DESC, latest_payment.rowid DESC
            LIMIT 1
        )
        LEFT JOIN users ON users.id = orders.user_id
        WHERE orders.id = ?
        """,
        (order_id,),
    ).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    files = db.execute(
        """
        SELECT files.*, order_items.is_double_sided AS item_is_double_sided
        FROM order_items
        JOIN files ON files.id = order_items.file_id
        WHERE order_items.order_id = ?
        ORDER BY files.uploaded_at DESC
        """,
        (order_id,),
    ).fetchall()
    file_infos = []
    for file_row in files:
        info = _admin_file_info(file_row)
        info["is_double_sided"] = bool(file_row["item_is_double_sided"])
        file_infos.append(info)
    return {
        "order": dict(order),
        "user": {
            "id": order["user_id"],
            "username": order["user_username"],
            "email": order["user_email"],
            "phone": order["user_phone"],
        },
        "files": file_infos,
    }


@router.post("/file-cache/cleanup")
def cleanup_file_cache(payload: FileCacheCleanupRequest, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    if payload.start_at and payload.end_at and payload.start_at > payload.end_at:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    select_cache_sql = """
    SELECT
        files.*,
        EXISTS(SELECT 1 FROM order_items WHERE order_items.file_id = files.id) AS has_order
    FROM files
    WHERE (? IS NULL OR datetime(files.uploaded_at) >= datetime(?))
      AND (? IS NULL OR datetime(files.uploaded_at) <= datetime(?))
    ORDER BY files.uploaded_at DESC
    """
    start_at = payload.start_at.isoformat() if payload.start_at else None
    end_at = payload.end_at.isoformat() if payload.end_at else None
    rows = db.execute(select_cache_sql, (start_at, start_at, end_at, end_at)).fetchall()
    upload_root = get_app_settings().upload_dir.resolve()
    result_files = []
    deleted = 0
    skipped = 0
    freed_bytes = 0
    for row in rows:
        has_order = bool(row["has_order"])
        target = _file_cache_target(row, upload_root)
        size_bytes = _path_size(target) if target else 0
        item = {
            "id": row["id"],
            "original_name": row["original_name"],
            "uploaded_at": row["uploaded_at"],
            "has_order": has_order,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
        }
        if has_order and not payload.include_order_files:
            skipped += 1
            item.update({"action": "skipped", "reason": "已关联订单"})
            result_files.append(item)
            continue
        if target is None or not target.exists():
            skipped += 1
            item.update({"action": "skipped", "reason": "缓存文件不存在"})
            result_files.append(item)
            continue
        freed_bytes += size_bytes
        if payload.dry_run:
            item.update({"action": "candidate", "reason": "可清理"})
        else:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            db.execute(
                "UPDATE files SET status = 'cleaned', error_message = ? WHERE id = ?",
                ("缓存已清理", row["id"]),
            )
            deleted += 1
            item.update({"action": "deleted", "reason": "已清理"})
        result_files.append(item)
    if not payload.dry_run:
        db.commit()
    return {
        "success": True,
        "dry_run": payload.dry_run,
        "matched": len(rows),
        "deleted": deleted,
        "skipped": skipped,
        "releasable_mb": round(freed_bytes / 1024 / 1024, 2),
        "files": result_files,
    }


@router.get("/backups")
def get_backups(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    return {"backups": list_backups(), "policy": backup_policy(db)}


@router.put("/backups/policy")
def save_backup_policy(payload: BackupPolicyUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    return update_backup_policy(db, payload)


@router.post("/backups")
def make_backup(payload: BackupCreateRequest, _admin=Depends(admin_user)):
    return create_backup(payload.archive_format, "manual")


@router.post("/backups/inspect")
async def inspect_backup(file: UploadFile = File(...), _admin=Depends(admin_user)):
    return await inspect_uploaded_backup(file)


@router.post("/backups/restore")
async def restore_backup(file: UploadFile = File(...), _admin=Depends(admin_user)):
    return await restore_uploaded_backup(file)


@router.get("/backups/{filename}/download")
def download_backup(filename: str, _admin=Depends(admin_user)):
    path = backup_file_path(filename)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.delete("/backups/{filename}")
def remove_backup(filename: str, _admin=Depends(admin_user)):
    return delete_backup(filename)


@setup_router.get("/restore/status")
def setup_restore_status():
    return {"available": is_initial_restore_available()}


@setup_router.post("/restore/inspect")
async def setup_restore_inspect(file: UploadFile = File(...)):
    return await inspect_initial_restore(file)


@setup_router.post("/restore")
async def setup_restore(file: UploadFile = File(...)):
    return await restore_initial_backup(file)


@router.get("/users")
def users(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    rows = db.execute("SELECT id, username, email, phone, balance, is_admin, is_active, created_at FROM users ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@router.post("/users")
def create_user(payload: AdminUserCreate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    user_id = str(uuid4())
    try:
        db.execute(
            """
            INSERT INTO users (id, username, password_hash, email, phone, balance, is_admin, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload.username,
                hash_password(payload.password),
                payload.email or None,
                payload.phone or None,
                payload.balance,
                1 if payload.is_admin else 0,
                1 if payload.is_active else 0,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名或手机号已存在") from exc
    return {"success": True, "user_id": user_id}


@router.put("/users/{user_id}")
def edit_user(user_id: str, payload: AdminUserUpdate, db: sqlite3.Connection = Depends(get_db), admin: sqlite3.Row = Depends(admin_user)):
    user = db.execute("SELECT id, is_admin, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    if user_id == admin["id"] and data.get("is_active") is False:
        raise HTTPException(status_code=422, detail="不能封禁当前登录管理员")
    if user_id == admin["id"] and data.get("is_admin") is False:
        raise HTTPException(status_code=422, detail="不能取消当前登录管理员权限")
    if bool(user["is_admin"]) and data.get("is_admin") is False and _admin_count(db) <= 1:
        raise HTTPException(status_code=422, detail="至少保留一个管理员")
    if bool(user["is_admin"]) and data.get("is_active") is False and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=422, detail="至少保留一个可用管理员")

    current = db.execute("SELECT username, email, phone, is_admin, is_active, password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    username = current["username"]
    email = current["email"]
    phone = current["phone"]
    is_admin = int(current["is_admin"])
    is_active = int(current["is_active"])
    password_hash = current["password_hash"]
    for key in ("username", "email", "phone", "is_admin", "is_active"):
        if key in data:
            value = data[key]
            if key in {"is_admin", "is_active"}:
                value = 1 if value else 0
            if key in {"email", "phone"}:
                value = value or None
            if key == "username":
                username = value
            elif key == "email":
                email = value
            elif key == "phone":
                phone = value
            elif key == "is_admin":
                is_admin = value
            elif key == "is_active":
                is_active = value
    if data.get("password"):
        password_hash = hash_password(data["password"])
    if not data:
        return {"success": True}
    try:
        db.execute(
            """
            UPDATE users
            SET username = ?, email = ?, phone = ?, is_admin = ?, is_active = ?, password_hash = ?
            WHERE id = ?
            """,
            (username, email, phone, is_admin, is_active, password_hash, user_id),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名或手机号已存在") from exc
    return {"success": True}


@router.post("/users/{user_id}/balance")
def update_balance(user_id: str, payload: BalanceUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    amount = payload.amount
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
    db.commit()
    return {"success": True}


@router.put("/users/{user_id}/balance")
def set_balance(user_id: str, payload: BalanceSet, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.execute("UPDATE users SET balance = ? WHERE id = ?", (payload.balance, user_id))
    db.commit()
    return {"success": True}


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    user = db.execute("SELECT is_admin, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if bool(user["is_active"]) and bool(user["is_admin"]) and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=422, detail="至少保留一个可用管理员")
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (0 if user["is_active"] else 1, user_id))
    db.commit()
    return {"success": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, db: sqlite3.Connection = Depends(get_db), admin: sqlite3.Row = Depends(admin_user)):
    user = db.execute("SELECT id, is_admin, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        return {"success": True}
    if user_id == admin["id"]:
        raise HTTPException(status_code=422, detail="不能删除当前登录管理员")
    if bool(user["is_admin"]) and _admin_count(db) <= 1:
        raise HTTPException(status_code=422, detail="至少保留一个管理员")
    if bool(user["is_admin"]) and bool(user["is_active"]) and _active_admin_count(db) <= 1:
        raise HTTPException(status_code=422, detail="至少保留一个可用管理员")
    db.execute("UPDATE files SET user_id = NULL WHERE user_id = ?", (user_id,))
    db.execute("UPDATE orders SET user_id = NULL WHERE user_id = ?", (user_id,))
    # auth_sessions.user_id 外键引用 users(id)，删除用户前必须先断开会话引用，
    # 否则开启 PRAGMA foreign_keys 时 DELETE 会触发 FOREIGN KEY 约束失败（500）。
    db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return {"success": True}


# ============================================================================
# 兑换码管理（后台 /api/admin/redemptions）
# 业务逻辑见 services/redemption.py。所有接口均需管理员权限。
# ============================================================================

# 兑换码状态中文标签与前端 badge 样色（service 里算好 status 字段，这里供对照展示用）。
REDEMPTION_STATUS_LABELS = {"unused": "未使用", "used": "已使用", "expired": "已过期"}


@router.get("/redemptions")
def redemption_codes(
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=64),
):
    """分页返回兑换码列表（最新在前），支持按兑换码模糊搜索。"""
    return list_codes(db, limit=limit, offset=offset, search=search)


@router.get("/redemptions/{code_id}/logs")
def redemption_code_logs(code_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    """返回单个兑换码的兑换日志（兑换用户 + 时间 + 到账金额）。"""
    return {"logs": list_code_logs(db, code_id)}


@router.post("/redemptions")
def create_redemption_code(
    payload: AdminRedemptionCreate,
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    """手动新增单个兑换码（自定义码 + 面额 + 可用次数 + 有效期 + 每用户最大兑换次数）。

    有效期支持两种互斥方式（见 AdminRedemptionCreate）：expiry_mode="days" 走 valid_days；
    expiry_mode="date" 时 expire_date（YYYY-MM-DD）由服务层归一化成当天 23:59:59 后写库。
    这里必须把 payload.expire_date 显式作为关键字参数透传，漏传会让「指定到期日期」静默失效。
    """
    result = create_code(
        db,
        payload.code,
        payload.amount,
        payload.usable_count,
        payload.valid_days,
        payload.per_user_max_times,
        expires_at=payload.expire_date,
    )
    return {"success": True, **result}


@router.post("/redemptions/batch")
def batch_create_redemption_codes(
    payload: AdminRedemptionBatchCreate,
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    """批量生成随机兑换码（数量 + 每张面额 + 可用次数 + 有效期）。

    有效期同样支持「按天数」或「指定到期日期」二选一，透传方式与手动新增一致。
    """
    created = batch_generate_codes(
        db,
        payload.count,
        payload.amount,
        payload.usable_count,
        payload.valid_days,
        expires_at=payload.expire_date,
    )
    return {"success": True, "codes": created, "count": len(created)}


@router.delete("/redemptions/{code_id}")
def delete_redemption_code(code_id: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    """删除一个兑换码（连同其兑换日志）。不存在时也视为成功（幂等）。"""
    delete_code(db, code_id)
    return {"success": True}


def _admin_file_info(row: sqlite3.Row) -> dict:
    stored_path = Path(row["stored_path"]) if row["stored_path"] else None
    pdf_path = Path(row["pdf_path"]) if row["pdf_path"] else None
    pdf_exists = bool(pdf_path and pdf_path.exists())
    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "page_count": row["page_count"],
        "file_size": row["file_size"],
        "black_coverage": row["black_coverage"],
        "is_safe": bool(row["is_safe"]),
        "status": row["status"],
        "error_message": row["error_message"],
        "uploaded_at": row["uploaded_at"],
        "original_exists": bool(stored_path and stored_path.exists()),
        "pdf_exists": pdf_exists,
        "preview_url": f"/api/files/{row['id']}/preview" if pdf_exists else None,
        "cache_size_mb": round(_path_size(_first_existing_parent(stored_path, pdf_path)) / 1024 / 1024, 2),
    }


def _first_existing_parent(*paths: Path | None) -> Path | None:
    for path in paths:
        if path is None:
            continue
        if path.exists():
            return path.parent if path.is_file() else path
        if path.parent.exists():
            return path.parent
    return None


def _file_cache_target(row: sqlite3.Row, upload_root: Path) -> Path | None:
    target = _first_existing_parent(
        Path(row["stored_path"]) if row["stored_path"] else None,
        Path(row["pdf_path"]) if row["pdf_path"] else None,
    )
    if target is None:
        return None
    try:
        resolved = target.resolve()
        resolved.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"文件 {row['original_name']} 不在上传目录内，已拒绝清理")
    if resolved == upload_root:
        raise HTTPException(status_code=422, detail=f"文件 {row['original_name']} 指向上传根目录，已拒绝清理")
    return resolved


def _path_size(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _admin_count(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT COUNT(*) AS count FROM users WHERE is_admin = 1").fetchone()
    return int(row["count"])


def _active_admin_count(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT COUNT(*) AS count FROM users WHERE is_admin = 1 AND is_active = 1").fetchone()
    return int(row["count"])


_CONFIG_SEEDED_SETTING_KEYS = ("cups_server", "cups_user", "cups_password", "epay_gateway", "epay_pid", "epay_key")
_SECRET_SETTING_KEYS = {"cups_password", "epay_key"}


def _config_seeded_setting_notices(data: dict[str, object]) -> list[str]:
    """保存 config.json 播种过的设置时，提示「库优先」这一约定。

    `init_db()` 用 INSERT OR IGNORE 把 config.json 里的 CUPS_*/EPAY_* 写进 settings 表，
    运行期读取一律「数据库优先、config.json 兜底」（见 `utils/cups_utils.get_cups_config`、
    `services/epay.get_payment_settings`）。因此初始化之后再改 config.json 不会覆盖后台设置，
    这里在保存响应里给出提示，避免用户误以为 config.json 仍然生效。
    """
    app_settings = get_app_settings()
    notices: list[str] = []
    for key in _CONFIG_SEEDED_SETTING_KEYS:
        if key not in data:
            continue
        config_value = str(getattr(app_settings, key, "") or "").strip()
        saved_value = str(data[key]).strip()
        if not config_value or config_value == saved_value:
            continue
        if key in _SECRET_SETTING_KEYS:
            notices.append(f"{key} 已保存到数据库；config.json 中的同名键只在首次建库时生效，之后修改 config.json 不会覆盖这里的设置。")
        else:
            notices.append(
                f"{key} 已保存为 {saved_value}；config.json 中的值（{config_value}）只在首次建库时生效，之后修改 config.json 不会覆盖这里的设置。"
            )
    return notices


@router.get("/settings")
def get_settings(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


@router.put("/settings")
def update_settings(payload: SettingsUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        if isinstance(value, (list, dict)):
            stored_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            stored_value = "true" if value else "false"
        else:
            stored_value = str(value)
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, stored_value))
    db.commit()
    # 修改 CUPS 服务器地址后，重新配置的 CUPS 队列会丢失默认打印机设置。
    # 这里把本地保存的默认打印机重新推送到新的 CUPS 服务器，避免每次配置都要手动重设默认。
    if "cups_server" in data:
        _reapply_default_printer(db)
    return {"success": True, "notices": _config_seeded_setting_notices(data)}


def _reapply_default_printer(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    default_name = (row["value"] if row else "") or ""
    if not default_name:
        return
    try:
        set_default_printer(db, default_name)
    except Exception:
        # 新 CUPS 服务器可能暂未同步该队列，忽略失败，保留本地默认配置即可。
        pass


@router.get("/payment-settings")
def payment_settings(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    settings = get_payment_settings(db)
    validation = validate_payment_settings(settings)
    return {
        "epay_gateway": settings["epay_gateway"],
        "epay_pid": settings["epay_pid"],
        "epay_key_configured": bool(settings["epay_key"]) and "易支付商户密钥未配置" not in validation["errors"],
        "epay_key_masked": "已配置" if settings["epay_key"] and "易支付商户密钥未配置" not in validation["errors"] else "未配置",
        "public_base_url": settings["public_base_url"],
        "frontend_base_url": settings["frontend_base_url"],
        "validation": validation,
    }


@router.put("/payment-settings")
def update_payment_settings(payload: PaymentSettingsUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    data = payload.model_dump()
    if not data.get("epay_key"):
        data.pop("epay_key", None)
    for key, value in data.items():
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    db.commit()
    return {"success": True, "notices": _config_seeded_setting_notices(data)}


@router.post("/payment-test")
def create_payment_test(payload: PaymentTestRequest, db: sqlite3.Connection = Depends(get_db), admin: sqlite3.Row = Depends(admin_user)):
    order_id = f"TEST{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8]}"
    amount = round(float(payload.amount), 2)
    payment_request = create_epay_request(order_id, amount, PAYMENT_TEST_SUBJECT, payload.payment_method, db)
    paid_at = None
    db.execute(
        """
        INSERT INTO orders (id, user_id, order_type, total_amount, status, is_double_sided, copies, payment_method, printer_name)
        VALUES (?, ?, 'test', ?, 'pending', 0, 1, ?, NULL)
        """,
        (order_id, admin["id"], amount, payload.payment_method),
    )
    db.execute(
        """
        INSERT INTO payments (id, order_id, amount, payment_method, status, paid_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (str(uuid4()), order_id, amount, payload.payment_method, paid_at),
    )
    db.commit()
    result = _serialize_payment_test(db, order_id)
    result.update(
        {
            "payment_url": payment_request.submit_url,
            "payment_submit_url": payment_request.submit_url,
            "gateway": payment_request.gateway,
            "params": payment_request.params,
        }
    )
    return result


@router.get("/payment-test/{order_id}")
def get_payment_test(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(admin_user)):
    return _serialize_payment_test(db, order_id)


@router.post("/payment-test/{order_id}/simulate-success")
def simulate_payment_test_success(order_id: str, db: sqlite3.Connection = Depends(get_db), _admin: sqlite3.Row = Depends(admin_user)):
    test_order = _serialize_payment_test(db, order_id)
    if test_order["status"] != "pending":
        return test_order
    payload = build_success_notify_payload(
        order_id,
        float(test_order["amount"]),
        PAYMENT_TEST_SUBJECT,
        test_order["payment_method"],
        db=db,
    )
    complete_epay_payment(db, payload)
    result = _serialize_payment_test(db, order_id)
    result.update({"simulated": True, "params": payload})
    return result


def _is_printer_permission_error(message: str) -> bool:
    normalized = (message or "").lower()
    return (
        "4096" in normalized
        or "unauthorized" in normalized
        or "not-authorized" in normalized
        or "forbidden" in normalized
        or "cups 拒绝" in normalized
        or "没有足够的 cups" in normalized
        or "没有足够的打印机管理权限" in normalized
    )


def _raise_printer_error(exc: Exception) -> None:
    detail = exc.args[0] if exc.args else str(exc)
    message = ""
    if isinstance(detail, dict):
        message = str(detail.get("error") or detail.get("message") or "")
        if not message:
            for item in detail.get("diagnostics") or []:
                if isinstance(item, dict):
                    message = str(item.get("message") or item.get("hint") or "")
                    if message:
                        break
    else:
        message = str(detail)
    
    if _is_printer_permission_error(message):
        permission_message = "CUPS 拒绝当前操作：后端没有足够的打印机管理权限。"
        permission_hint = "请优先使用系统中已有的打印队列，或在宿主机 CUPS/系统打印机设置中授权后端创建和管理队列。"
        if isinstance(detail, dict):
            diagnostics = detail.get("diagnostics") or [
                {
                    "source": "pycups",
                    "ok": False,
                    "message": permission_message,
                    "hint": permission_hint,
                }
            ]
            normalized_diagnostics = []
            for item in diagnostics:
                if not isinstance(item, dict):
                    continue
                item_message = str(item.get("message") or "")
                item_hint = str(item.get("hint") or "")
                if _is_printer_permission_error(item_message) or _is_printer_permission_error(item_hint):
                    item = {**item, "message": permission_message, "hint": permission_hint}
                normalized_diagnostics.append(item)
            detail = {
                **detail,
                "error": permission_message,
                "diagnostics": normalized_diagnostics,
            }
        else:
            detail = {
                "success": False,
                "error": permission_message,
                "diagnostics": [
                    {
                        "source": "pycups",
                        "ok": False,
                        "message": permission_message,
                        "hint": permission_hint,
                    }
                ],
            }
        raise HTTPException(status_code=422, detail=detail) from exc
    
    if "1280" in message or "server-error-internal-error" in message.lower():
        internal_error_message = "CUPS 服务器内部错误"
        internal_hint = "可能原因：1) PPD 驱动文件不存在或格式错误；2) CUPS 服务器配置问题；3) 打印机 URI 格式不正确；4) 驱动名称无效。建议检查驱动名称是否正确，或尝试使用 'everywhere' 驱动。"
        
        if isinstance(detail, dict):
            existing_diagnostics = detail.get("diagnostics") or []
            has_server_error_diag = any(
                isinstance(d, dict) and d.get("source") == "cups-server-error"
                for d in existing_diagnostics
            )
            if not has_server_error_diag:
                existing_diagnostics.append({
                    "source": "cups-server-error",
                    "ok": False,
                    "message": internal_error_message,
                    "hint": internal_hint,
                })
            detail = {
                **detail,
                "error": internal_error_message,
                "diagnostics": existing_diagnostics,
            }
        else:
            detail = {
                "success": False,
                "error": internal_error_message,
                "diagnostics": [
                    {
                        "source": "cups-server-error",
                        "ok": False,
                        "message": message,
                        "hint": internal_hint,
                    }
                ],
            }
        raise HTTPException(status_code=502, detail=detail) from exc
    
    if "不存在" in message:
        raise HTTPException(status_code=404, detail=detail) from exc
    if "已存在" in message:
        raise HTTPException(status_code=409, detail=detail) from exc
    if "pycups" in message or "CUPS 服务不可用" in message or "failed to connect" in message or "无法连接 CUPS" in message:
        raise HTTPException(status_code=503, detail=detail) from exc
    raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/printer-system")
def get_printer_system(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return printer_system(db)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.get("/printers")
def printers(
    include_attrs: bool = Query(default=False),
    include_hidden: bool = Query(default=False),
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    try:
        return list_printers(db, include_attrs=include_attrs, include_hidden=include_hidden)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.get("/printer-drivers")
def printer_drivers(
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    include_raw: bool = Query(default=False),
    make_model: str = Query(default=""),
    uri: str = Query(default=""),
    connection_type: str = Query(default=""),
    _admin=Depends(admin_user),
):
    try:
        return list_printer_drivers(
            search=search,
            limit=limit,
            include_raw=include_raw,
            make_model=make_model,
            uri=uri,
            connection_type=connection_type,
        )
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.post("/printer-drivers/ppd")
async def upload_printer_ppd_driver(
    file: UploadFile = File(...),
    make_model: str = Form(default=""),
    uri: str = Form(default=""),
    connection_type: str = Form(default=""),
    info: str = Form(default=""),
    _admin=Depends(admin_user),
):
    try:
        return import_ppd_driver(
            file.filename or "",
            await file.read(),
            make_model=make_model,
            uri=uri,
            connection_type=connection_type,
            info=info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/printer-info")
def get_printer_info(
    name: str = Query(default=""),
    uri: str = Query(default=""),
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    try:
        if name:
            return get_cups_printer(db, name)
        if uri:
            return probe_printer_uri(uri)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_printer_error(exc)
    raise HTTPException(status_code=422, detail="请提供打印机名称或 URI")


@router.post("/printer-uri/probe")
def probe_printer_uri_endpoint(payload: PrinterUriProbe, _admin=Depends(admin_user)):
    try:
        uri = normalize_printer_uri(
            uri=payload.uri or "",
            host=payload.host or "",
            connection_type=payload.connection_type or "ipp",
            queue_path=payload.queue_path or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return probe_printer_uri(uri)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.get("/printers/{printer_name}")
def get_printer(printer_name: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return get_cups_printer(db, printer_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.patch("/printers/{printer_name}")
@router.put("/printers/{printer_name}")
def edit_printer(printer_name: str, payload: PrinterUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return update_printer(db, printer_name, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.put("/printers/{printer_name}/default")
@router.post("/printers/{printer_name}/default")
def make_default_printer(printer_name: str, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return set_default_printer(db, printer_name)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.put("/printers/default/clear")
@router.post("/printers/default/clear")
def clear_default_printer_endpoint(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return clear_default_printer(db)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.put("/printers/{printer_name}/enabled")
@router.post("/printers/{printer_name}/enabled")
@router.post("/printers/{printer_name}/toggle")
def update_printer_enabled(printer_name: str, payload: PrinterEnabledUpdate, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return set_printer_enabled(db, printer_name, payload.enabled, payload.accepting_jobs)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.post("/printers/{printer_name}/test-page")
@router.post("/printers/{printer_name}/test")
def test_print(printer_name: str, payload: PrinterTestPageRequest | None = None, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return test_printer(db, printer_name, payload or PrinterTestPageRequest())
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.post("/printers/{printer_name}/test-result")
def save_test_print_result(printer_name: str, payload: PrinterTestResult, db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    try:
        return record_printer_test_result(db, printer_name, payload.success, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/printers/{printer_name}/jobs")
def printer_jobs(
    printer_name: str,
    which_jobs: str = Query(default="not-completed"),
    limit: int = Query(default=20, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    try:
        return list_printer_jobs(db, printer_name, which_jobs, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.delete("/printers/{printer_name}")
def delete_printer(
    printer_name: str,
    force: bool = Query(default=False),
    db: sqlite3.Connection = Depends(get_db),
    _admin=Depends(admin_user),
):
    try:
        return remove_printer(db, printer_name, force)
    except RuntimeError as exc:
        _raise_printer_error(exc)


@router.get("/cups/logs")
def cups_error_log(lines: int = Query(default=200, ge=1, le=1000), _admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_error_log
    return get_cups_error_log(lines=lines)


@router.get("/cups/logs/page")
def cups_page_log(lines: int = Query(default=200, ge=1, le=1000), _admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_page_log
    return get_cups_page_log(lines=lines)


@router.get("/cups/logs/access")
def cups_access_log(lines: int = Query(default=200, ge=1, le=1000), _admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_access_log
    return get_cups_access_log(lines=lines)


@router.get("/cups/filters")
def cups_filter_status(_admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_filter_status
    return get_cups_filter_status()


@router.get("/cups/queues")
def cups_queue_status(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_queue_status
    return get_cups_queue_status(db)


@router.get("/cups/diagnostics")
def cups_diagnostics(db: sqlite3.Connection = Depends(get_db), _admin=Depends(admin_user)):
    from ..services.cups_printer import get_cups_diagnostics
    return get_cups_diagnostics(db)
