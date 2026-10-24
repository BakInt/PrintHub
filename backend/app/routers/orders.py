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
from ..services.print_dispatch import dispatch_print_files_if_present
from ..services.print_monitor import refresh_printing_order_status
from ..services.pricing import calculate_files_price_detail, get_numeric_setting
from ..services.queue import queue_position
from .deps import optional_user

router = APIRouter(prefix="/api", tags=["orders"])

PAYMENT_SUBJECT = "云打印订单"
RECHARGE_SUBJECT = "云打印余额充值"
PAYMENT_TEST_SUBJECT = "云打印测试支付"


def payment_subject_for_order(order_id: str, order_type: str | None = None) -> str:
    if order_type == "recharge":
        return RECHARGE_SUBJECT
    if order_type == "test" or order_id.startswith("TEST"):
        return PAYMENT_TEST_SUBJECT
    return PAYMENT_SUBJECT


def resolve_order_printer(db: sqlite3.Connection, printer_name: str | None) -> sqlite3.Row | None:
    """【新增功能】解析本次订单实际使用的打印机记录（用于校验彩色/自动双面能力）。

    订单未指定打印机时使用后台「默认打印机」。查不到记录时返回 None，此时跳过能力校验，
    保证没有维护打印机元数据的老部署依然可以正常下单打印。
    """
    name = printer_name
    if not name:
        row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
        name = row["value"] if row else None
    if not name:
        return None
    return db.execute("SELECT * FROM printers WHERE name = ?", (name,)).fetchone()


def generate_order_id(db: sqlite3.Connection) -> str:
    # 安全修复（V-08）：时间戳段可预测，随机段从 6 位扩到 8 位数字（1e8 空间），
    # 配合订单详情的鉴权/脱敏后，枚举他人订单号不再可行。
    for _ in range(20):
        candidate = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{randbelow(100_000_000):08d}"
        exists = db.execute("SELECT id FROM orders WHERE id = ?", (candidate,)).fetchone()
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail="订单号生成失败，请稍后重试")


def ensure_files_accessible(files: list[sqlite3.Row], user: sqlite3.Row | None) -> None:
    """安全修复（V-07）：只能引用「自己的文件」或匿名访客上传的文件（user_id 为空）。

    引用他人上传的文件与文件不存在返回同一响应，不泄露他人 file_id 的存在性；
    管理员豁免（后台修复场景）。
    """
    for item in files:
        owner_id = item["user_id"]
        if owner_id is None:
            continue
        if user is None or (not bool(user["is_admin"]) and owner_id != user["id"]):
            raise HTTPException(status_code=403, detail="存在不可用的文件，请重新上传后再试")


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
    # 安全修复（V-07）：禁止引用他人上传的文件（详见 ensure_files_accessible）。
    ensure_files_accessible(files, user)
    # 【新增功能】合并双面打印：True 时全部文档合并为一个双面打印流——不同文档的
    # 页面按顺序连续排到纸张正反面（两份单页文档可打在同一张纸正反面），取代旧的按份双面。
    merge_duplex = bool(payload.print_settings.merge_duplex)
    price_detail = calculate_files_price_detail(db, files, payload.print_settings.copies, merge_duplex)
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
    # 订单级 is_double_sided 作为聚合标识（后台展示用）：合并双面时为 1。
    # orders.merge_duplex 单独标记「合并双面打印」，打印派发据此把全部文档合并为一个双面任务。
    order_double_sided = merge_duplex
    # 【新增功能】打印机能力兜底校验：前端已按打印机能力条件渲染，这里再校验一次，
    # 防止绕过前端提交打印机并不支持的能力。查不到打印机记录时跳过（兼容老部署）。
    printer_row = resolve_order_printer(db, payload.print_settings.printer_name)
    if printer_row is not None:
        if payload.print_settings.use_color is True and not bool(printer_row["is_support_color"]):
            raise HTTPException(status_code=400, detail="该打印机未开启彩色打印，请重新选择打印方式")
        if order_double_sided and not bool(printer_row["is_support_auto_duplex"]):
            raise HTTPException(status_code=400, detail="该打印机未开启自动双面打印，请重新选择打印方式")
    # 【新增功能】彩色标记入库：NULL=未指定（旧前端/旧业务），1=彩色，0=黑白。
    use_color_value = None
    if payload.print_settings.use_color is not None:
        use_color_value = 1 if payload.print_settings.use_color else 0
    db.execute(
        """
        INSERT INTO orders (
            id, user_id, order_type, total_amount, is_double_sided, use_color, merge_duplex, copies, payment_method, printer_name, contact_name, contact_phone,
            sheet_count, base_amount, discount_amount, pricing_detail
        )
        VALUES (?, ?, 'print', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            user_id,
            amount,
            1 if order_double_sided else 0,
            use_color_value,
            1 if merge_duplex else 0,
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
        # 合并双面时全部明细标记双面（后台订单详情展示用）；实际合并派发由 orders.merge_duplex 驱动。
        db.execute(
            "INSERT INTO order_items (id, order_id, file_id, is_double_sided) VALUES (?, ?, ?, ?)",
            (str(uuid4()), order_id, file_id, 1 if merge_duplex else 0),
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
        # 【性能修复】免费/余额订单的打印派发改后台异步执行（paid 状态即返回响应，
        # 后台线程完成光栅化与 lp 提交后置 printing），排队口径本就把 paid 算作
        # 排队中，前端无需改动。同步开关见 services/print_dispatch.py。
        dispatch_print_files_if_present(db, order_id)
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


# 安全修复（V-03）：未登录 / 非属主访问订单详情时，只允许拿到打印状态摘要字段。
# 支付结果页（PaymentView）匿名轮询只用到 id/status/total_amount/print_error，
# 这些字段不含个人信息；user_id、联系人姓名、手机号、支付与计价明细只下发给
# 订单属主或管理员。
ANONYMOUS_ORDER_FIELDS = (
    "id",
    "order_type",
    "status",
    "total_amount",
    "copies",
    "is_double_sided",
    "use_color",
    "sheet_count",
    "created_at",
    "paid_at",
    "printed_at",
    "print_error",
)


@router.get("/orders/{order_id}")
def get_order(
    order_id: str,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row | None = Depends(optional_user),
):
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = refresh_order_print_status(db, order)
    result = dict(order)
    result["queue"] = queue_position(db, order_id)
    is_owner = user is not None and order["user_id"] == user["id"]
    if not is_owner and not (user is not None and bool(user["is_admin"])):
        return {**{field: result.get(field) for field in ANONYMOUS_ORDER_FIELDS}, "queue": result["queue"]}
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
