"""打印排队计算。

系统里“正在打印/排队”的打印单指以下两类：

- ``printing``：已经发送到打印机、尚未确认完成的订单。
- ``paid``：已支付、等待派发到打印机的打印订单（含免费订单）。

充值单（``order_type='recharge'``）和测试单（``order_type='test'``）不参与排队。

排队按订单计数：一个订单算一个人。排队先后顺序按“进入打印流程的时间”排序，
优先使用 ``printed_at``（派发时间），其次 ``paid_at``，最后 ``created_at``。
"""

import sqlite3


# 参与排队的订单状态：正在打印，以及已支付待派发。
QUEUE_STATUSES = ("printing", "paid")

# 用于排序的时间字段优先级：派发时间 -> 支付时间 -> 创建时间。
_QUEUE_ORDER_BY = "COALESCE(printed_at, paid_at, created_at) ASC, created_at ASC, id ASC"


def _queue_rows(db: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in QUEUE_STATUSES)
    return db.execute(
        f"""
        SELECT id, status, printer_name, contact_name, copies, sheet_count,
               printed_at, paid_at, created_at
        FROM orders
        WHERE order_type = 'print'
          AND status IN ({placeholders})
        ORDER BY {_QUEUE_ORDER_BY}
        """,
        QUEUE_STATUSES,
    ).fetchall()


def queue_position(db: sqlite3.Connection, order_id: str) -> dict:
    """计算指定订单在打印队列中的位置。

    返回字段：

    - ``in_queue``：该订单是否在排队/打印中。
    - ``ahead``：前面还有多少个订单（不含自己）。
    - ``position``：该订单排第几位（从 1 开始）；不在队列时为 0。
    - ``total``：当前队列总人数（含正在打印的）。
    - ``printing``：当前正在打印的订单数量。
    """
    rows = _queue_rows(db)
    total = len(rows)
    printing = sum(1 for row in rows if row["status"] == "printing")
    ahead = 0
    position = 0
    in_queue = False
    for index, row in enumerate(rows):
        if row["id"] == order_id:
            in_queue = True
            ahead = index
            position = index + 1
            break
    return {
        "in_queue": in_queue,
        "ahead": ahead,
        "position": position,
        "total": total,
        "printing": printing,
    }


def queue_overview(db: sqlite3.Connection) -> dict:
    """后台排队看板数据：正在打印与排队中的订单明细。"""
    rows = _queue_rows(db)
    items = []
    for index, row in enumerate(rows):
        item = dict(row)
        item["position"] = index + 1
        items.append(item)
    printing = [item for item in items if item["status"] == "printing"]
    waiting = [item for item in items if item["status"] != "printing"]
    return {
        "total": len(items),
        "printing_count": len(printing),
        "waiting_count": len(waiting),
        "printing": printing,
        "waiting": waiting,
        "items": items,
    }
