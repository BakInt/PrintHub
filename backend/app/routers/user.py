import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..models.schemas import RechargeRequest, UserOut, UserProfileUpdate
from ..services.epay import create_payment_url
from .deps import current_user
from .auth import row_to_user
from .orders import generate_order_id

router = APIRouter(prefix="/api/user", tags=["user"])

RECHARGE_SUBJECT = "云打印余额充值"


@router.get("/orders")
def my_orders(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: sqlite3.Row = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """分页返回当前用户订单，最新在前。

    - limit/offset 支持前端「加载更多」逐页拉取，默认每页 10 条，单页上限 50 条。
    - total: 当前用户订单总数；has_more: 是否还有更多可加载。
    - total_spent: 全量历史消费（仅打印订单），不随分页变化，保证前端统计准确。
    """
    total = db.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE user_id = ?",
        (user["id"],),
    ).fetchone()["c"]
    total_spent = db.execute(
        "SELECT COALESCE(SUM(total_amount), 0) AS s FROM orders WHERE user_id = ? AND order_type = 'print'",
        (user["id"],),
    ).fetchone()["s"]
    rows = db.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user["id"], limit, offset),
    ).fetchall()
    items = [dict(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total,
        "total_spent": round(float(total_spent or 0), 2),
    }



@router.put("/profile", response_model=UserOut)
def update_profile(
    payload: UserProfileUpdate,
    user: sqlite3.Row = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        db.execute(
            "UPDATE users SET real_name = ?, phone = ? WHERE id = ?",
            (payload.real_name, payload.phone, user["id"]),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="手机号已被其他账号绑定") from exc
    updated = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return row_to_user(updated)


@router.post("/recharge")
def create_recharge_order(
    payload: RechargeRequest,
    user: sqlite3.Row = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    amount = round(float(payload.amount), 2)
    if round(float(user["balance"] or 0), 2) + amount > 100000:
        raise HTTPException(status_code=400, detail="充值后余额不能超过 100000 元")
    order_id = generate_order_id(db)
    payment_url = create_payment_url(order_id, amount, RECHARGE_SUBJECT, payload.payment_method, db)
    db.execute(
        """
        INSERT INTO orders (
            id, user_id, order_type, total_amount, payment_method, sheet_count, base_amount, discount_amount
        )
        VALUES (?, ?, 'recharge', ?, ?, 0, ?, 0)
        """,
        (order_id, user["id"], amount, payload.payment_method, amount),
    )
    db.execute(
        """
        INSERT INTO payments (id, order_id, amount, payment_method, status)
        VALUES (?, ?, ?, ?, 'pending')
        """,
        (str(uuid4()), order_id, amount, payload.payment_method),
    )
    db.commit()
    return {
        "order_id": order_id,
        "amount": amount,
        "payment_method": payload.payment_method,
        "qr_code_url": payment_url,
    }
