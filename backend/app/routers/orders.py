import sqlite3
import json
from datetime import datetime
from secrets import randbelow
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..database import get_db
from ..models.schemas import PHONE_PATTERN, PaymentCreateRequest
from ..services.epay import complete_epay_payment, create_payment_url, get_payment_settings, render_payment_submit_form
from ..services.print_monitor import refresh_printing_order_status
from ..services.pricing import calculate_files_price_detail, get_numeric_setting, resolve_file_double_sided
from ..services.printer import print_pdf
from ..services.queue import queue_position
from .deps import optional_user

router = APIRouter(prefix="/api", tags=["orders"])

PAYMENT_SUBJECT = "云打印订单"
RECHARGE_SUBJECT = "云打印余额充值"
PAYMENT_TEST_SUBJECT = "云打印测试支付"


def order_has_print_files(db: sqlite3.Connection, order_id: str) -> bool:
    row = db.execute("SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?", (order_id,)).fetchone()
    return bool(row and int(row["count"]) > 0)


def payment_subject_for_order(order_id: str, order_type: str | None = None) -> str:
    if order_type == "recharge":
        return RECHARGE_SUBJECT
    if order_type == "test" or order_id.startswith("TEST"):
        return PAYMENT_TEST_SUBJECT
    return PAYMENT_SUBJECT


def dispatch_print_files_if_present(db: sqlite3.Connection, order_id: str) -> None:
    if order_has_print_files(db, order_id):
        dispatch_order_print(db, order_id)


def generate_order_id(db: sqlite3.Connection) -> str:
    for _ in range(20):
        candidate = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{randbelow(1_000_000):06d}"
        exists = db.execute("SELECT id FROM orders WHERE id = ?", (candidate,)).fetchone()
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail="订单号生成失败，请稍后重试")


def dispatch_order_print(db: sqlite3.Connection, order_id: str) -> None:
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    files = db.execute(
        """
        SELECT files.pdf_path AS pdf_path, order_items.is_double_sided AS is_double_sided
        FROM order_items
        JOIN files ON files.id = order_items.file_id
        WHERE order_items.order_id = ?
        """,
        (order_id,),
    ).fetchall()
    if not files:
        return
    default_printer = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    default_value = default_printer["value"] if default_printer else None
    errors = []
    job_ids = []
    for file_row in files:
        job_id, error = print_pdf(
            file_row["pdf_path"],
            order["copies"],
            bool(file_row["is_double_sided"]),
            order["printer_name"],
            default_printer=default_value,
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


def refresh_order_print_status(db: sqlite3.Connection, order: sqlite3.Row) -> sqlite3.Row:
    return refresh_printing_order_status(db, order)


@router.post("/payment/create")
def create_order(
    payload: PaymentCreateRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row | None = Depends(optional_user),
):
    if not payload.file_ids:
        raise HTTPException(status_code=400, detail="请选择要打印的文件")
    if len(payload.file_ids) != len(set(payload.file_ids)):
        raise HTTPException(status_code=400, detail="文件列表存在重复项")
    placeholders = ",".join("?" for _ in payload.file_ids)
    files = db.execute(f"SELECT * FROM files WHERE id IN ({placeholders})", payload.file_ids).fetchall()
    if len(files) != len(set(payload.file_ids)):
        raise HTTPException(status_code=404, detail="部分文件不存在")
    unsafe = [item for item in files if not bool(item["is_safe"])]
    if unsafe:
        raise HTTPException(status_code=400, detail="存在未通过安全检测的文件")
    # 按份双面：file_settings 中指定的文件用其独立设置，未指定的回退到全局 double_sided。
    duplex_map = payload.print_settings.double_sided_map()
    global_duplex = payload.print_settings.double_sided
    requested_duplex = {
        item["id"]: bool(duplex_map[item["id"]]) if item["id"] in duplex_map else global_duplex
        for item in files
    }
    # 双面按份独立生效，仅对该份文档自身正反面有效；单页文档不能双面，
    # 更不会把两份单页文档合并到同一张纸的正反两面。
    for item in files:
        if requested_duplex[item["id"]] and int(item["page_count"] or 0) < 2:
            raise HTTPException(
                status_code=400,
                detail="双面打印仅适用于自身页数不少于 2 页的文档，单页文档只能单面打印",
            )
    # 计价与存储都使用逐份生效后的映射（resolve 会对单页强制单面兜底）。
    effective_duplex = {item["id"]: resolve_file_double_sided(item, requested_duplex) for item in files}
    price_detail = calculate_files_price_detail(db, files, payload.print_settings.copies, requested_duplex)
    amount = price_detail["amount"]
    user_id = user["id"] if user else None
    if payload.payment_method == "balance":
        if user is None:
            raise HTTPException(status_code=401, detail="余额支付需要登录")
        min_balance = get_numeric_setting(db, "min_balance", 1)
        if user["balance"] - amount < min_balance:
            raise HTTPException(status_code=400, detail="余额不足，请充值后再打印")
    contact_name = payload.print_settings.contact_name
    contact_phone = payload.print_settings.contact_phone
    if user is not None:
        contact_name = contact_name or user["real_name"]
        contact_phone = contact_phone or user["phone"]
    if not contact_name:
        raise HTTPException(status_code=400, detail="请填写打印人姓名")
    if not contact_phone or not PHONE_PATTERN.fullmatch(contact_phone):
        raise HTTPException(status_code=400, detail="请填写 11 位中国大陆手机号")
    order_id = generate_order_id(db)
    # 订单级 is_double_sided 作为聚合标识：任一文档启用双面即为真，
    # 真正的按份设置存于 order_items.is_double_sided。
    order_double_sided = any(effective_duplex.values())
    db.execute(
        """
        INSERT INTO orders (
            id, user_id, order_type, total_amount, is_double_sided, copies, payment_method, printer_name, contact_name, contact_phone,
            sheet_count, base_amount, discount_amount, pricing_detail
        )
        VALUES (?, ?, 'print', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            user_id,
            amount,
            1 if order_double_sided else 0,
            payload.print_settings.copies,
            payload.payment_method,
            payload.print_settings.printer_name,
            contact_name,
            contact_phone,
            price_detail["sheet_count"],
            price_detail["base_amount"],
            price_detail["discount_amount"],
            json.dumps(price_detail, ensure_ascii=False),
        ),
    )
    for file_id in payload.file_ids:
        db.execute(
            "INSERT INTO order_items (id, order_id, file_id, is_double_sided) VALUES (?, ?, ?, ?)",
            (str(uuid4()), order_id, file_id, 1 if effective_duplex.get(file_id) else 0),
        )
    payment_id = str(uuid4())
    status = "pending"
    paid_at = None
    qr_url = None
    is_free_order = round(float(amount), 2) <= 0
    settle_immediately = payload.payment_method == "balance" or is_free_order
    if settle_immediately:
        if payload.payment_method == "balance":
            db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user_id))
        db.execute("UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ?", (datetime.utcnow().isoformat(), order_id))
        status = "paid"
        paid_at = datetime.utcnow().isoformat()
    else:
        qr_url = create_payment_url(order_id, amount, PAYMENT_SUBJECT, payload.payment_method, db)
    db.execute(
        """
        INSERT INTO payments (id, order_id, amount, payment_method, status, paid_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payment_id, order_id, amount, payload.payment_method, status, paid_at),
    )
    if settle_immediately:
        dispatch_order_print(db, order_id)
    db.commit()
    queue = queue_position(db, order_id)
    return {
        "order_id": order_id,
        "amount": amount,
        "base_amount": price_detail["base_amount"],
        "discount_amount": price_detail["discount_amount"],
        "sheet_count": price_detail["sheet_count"],
        "applied_discount": price_detail["applied_discount"],
        "qr_code_url": qr_url,
        "balance_deducted": payload.payment_method == "balance",
        "free_order": is_free_order,
        "queue": queue,
    }


@router.get("/orders/{order_id}/queue")
def get_order_queue(order_id: str, db: sqlite3.Connection = Depends(get_db)):
    order = db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return queue_position(db, order_id)


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: sqlite3.Connection = Depends(get_db)):
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = refresh_order_print_status(db, order)
    result = dict(order)
    result["queue"] = queue_position(db, order_id)
    return result


@router.get("/payment/submit/{order_id}", response_class=HTMLResponse)
def epay_submit(order_id: str, db: sqlite3.Connection = Depends(get_db)):
    order = db.execute("SELECT id, order_type, total_amount, payment_method, status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["payment_method"] == "balance":
        raise HTTPException(status_code=400, detail="余额订单无需跳转支付")
    if order["status"] != "pending":
        raise HTTPException(status_code=400, detail="订单已支付或已关闭")
    return HTMLResponse(
        render_payment_submit_form(
            order_id,
            float(order["total_amount"]),
            payment_subject_for_order(order_id, order["order_type"]),
            order["payment_method"],
            db,
        )
    )


@router.api_route("/payment/notify", methods=["GET", "POST"])
async def epay_notify(request: Request, db: sqlite3.Connection = Depends(get_db)):
    if request.method == "GET":
        payload = dict(request.query_params)
    else:
        form = await request.form()
        payload = {key: str(value) for key, value in form.items()}
    complete_epay_payment(
        db,
        payload,
        dispatch_callback=dispatch_print_files_if_present,
    )
    return PlainTextResponse("success")


@router.get("/payment/return/{order_id}")
def epay_return(order_id: str, request: Request, db: sqlite3.Connection = Depends(get_db)):
    payload = dict(request.query_params)
    if payload.get("out_trade_no"):
        if payload["out_trade_no"] != order_id:
            raise HTTPException(status_code=400, detail="支付返回订单号不匹配")
        required_payment_fields = {"sign", "trade_no", "trade_status", "money"}
        if required_payment_fields.issubset(payload):
            complete_epay_payment(db, payload, dispatch_callback=dispatch_print_files_if_present)
    order = db.execute("SELECT id, order_type FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    frontend_base_url = get_payment_settings(db)["frontend_base_url"].rstrip("/")
    if order["order_type"] == "recharge":
        return RedirectResponse(url=f"{frontend_base_url}/user/dashboard?recharge_order={order_id}", status_code=303)
    return RedirectResponse(url=f"{frontend_base_url}/payment/{order_id}", status_code=303)
