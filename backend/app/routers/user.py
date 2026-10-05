import logging
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..models.schemas import RechargeRequest, RedeemRequest, UserOut, UserProfileUpdate
from ..services.epay import create_payment_url
from ..services.redemption import redeem as redeem_redemption_code
from .deps import current_user
from .auth import row_to_user
from .orders import generate_order_id

logger = logging.getLogger(__name__)

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


@router.post("/redeem")
def redeem_code(request: RedeemRequest, user: sqlite3.Row = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    """个人中心「兑换码充值」：提交兑换码到账余额。

    - 兑换码不存在 / 已过期 / 可用次数已用满 / 超出余额上限 → 400，detail 为
      `{code, message}`（前端弹窗展示 message 里的中文提示）。
    - 数据库或未预期异常 → 500，同样返回标准 JSON 中文提示并记录堆栈，
      不会把 "Internal Server Error" 这种纯文本 500 抛给前端。
    - 成功返回到账金额与最新余额。

    注意：服务函数必须用别名 `redeem_redemption_code` 引入。若像以前那样
    `from ..services.redemption import redeem as redeem_code`，模块级名字会被本函数
    （同名 `redeem_code`）覆盖，导致路由调用自己：AttributeError → 纯文本 500。
    """
    try:
        amount = redeem_redemption_code(db, user, request.code)
        balance_row = db.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.exception("兑换码接口数据库异常：user=%s", user["id"])
        raise HTTPException(status_code=500, detail={"code": "REDEMPTION_FAILED", "message": "兑换失败，请稍后重试"}) from exc
    except Exception as exc:  # noqa: BLE001 - 兜底：任何意外异常都转成标准业务错误
        logger.exception("兑换码接口未预期异常：user=%s", user["id"])
        raise HTTPException(
            status_code=500,
            detail={"code": "REDEMPTION_SERVER_ERROR", "message": "兑换失败，服务器异常，请稍后重试"},
        ) from exc
    return {
        "success": True,
        "amount": round(float(amount), 2),
        "balance": round(float(balance_row["balance"] if balance_row else 0), 2),
    }
