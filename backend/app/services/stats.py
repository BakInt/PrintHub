"""后台「每日数据统计」按**本地时区**聚合订单数据。

为什么单独放在这里：数据库里的时间戳统一是 UTC 文本，但后台运营看的是「本地哪一天」。
`orders.created_at` 由 SQLite `CURRENT_TIMESTAMP` 生成（`YYYY-MM-DD HH:MM:SS`），
而 `paid_at` / `printed_at` 由 `datetime.utcnow().isoformat()` 生成
（`YYYY-MM-DDTHH:MM:SS.ffffff`）——同一张表里两种格式并存，所以这里统一先用
SQLite 的 `datetime()` 归一化，再按「UTC 小时桶 → 本地日期」折算，避免直接对
字符串做 `substr` 分日导致时区错位。

容器里 `docker-compose.yml` 已设置 `TZ=Asia/Shanghai`，因此本地时区即东八区；
若部署方改 `TZ`，本模块的分日口径会随之变化，这是预期行为。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# `orders.status` 里表示「打印失败」的取值，与后台概览卡片口径一致。
FAILED_STATUS = "print_failed"
# 后台时间范围切换按钮提供「近 7 天 / 近 30 天」，这里给出通用默认值与上下限。
DEFAULT_DAYS = 7
MIN_DAYS = 1
MAX_DAYS = 90


def _utc_boundary_text(moment: datetime) -> str:
    """把不带时区的「本地时间」折算成 UTC 文本，可直接与 `orders.created_at` 比较。

    传入的 naive datetime 会被 Python 按本机本地时区解释（`astimezone` 的既有语义），
    所以 `datetime.combine(day, time.min)` 就是「本地当天 00:00」对应的 UTC 时刻。
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_date_of_utc_hour(bucket: str | None) -> date | None:
    """把 SQLite 分出来的 UTC 小时桶（`YYYY-MM-DD HH`）折算成本地日期。"""
    if not bucket:
        return None
    try:
        parsed = datetime.strptime(bucket, "%Y-%m-%d %H")
    except (TypeError, ValueError):
        return None
    # 无参 astimezone() 按「该时刻」的本地时区规则折算，跨夏令时也不会整体偏移。
    return parsed.replace(tzinfo=timezone.utc).astimezone().date()


def timezone_label() -> str:
    """当前生效的本地时区偏移，例如 `UTC+08:00`（仅用于接口回显与排查）。"""
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def normalize_days(days: Any) -> int:
    """把外部传入的天数收敛到 [MIN_DAYS, MAX_DAYS]，非法值回退默认 7 天。"""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(MIN_DAYS, min(MAX_DAYS, value))


def _day_sequence(days: int) -> list[date]:
    """返回最近 `days` 个本地日期（升序，最后一个是今天）。"""
    today = datetime.now().date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def daily_stats(db: sqlite3.Connection, days: int = DEFAULT_DAYS) -> dict:
    """按本地时区聚合每日订单数、收入与打印失败数。

    口径与后台概览卡片（`GET /api/admin/dashboard`）保持一致：统计 `orders` 表全部订单，
    不按 `order_type` 过滤，`revenue` 为 `total_amount` 之和。这样「每日数据统计」里的
    合计与卡片上的数字对得上，不会出现两处口径不一致的困惑。
    """
    days = normalize_days(days)
    sequence = _day_sequence(days)
    # 查询窗口 = 本地「第一天 00:00」到「最后一天次日 00:00」对应的 UTC 半开区间。
    start_utc = _utc_boundary_text(datetime.combine(sequence[0], time.min))
    end_utc = _utc_boundary_text(datetime.combine(sequence[-1] + timedelta(days=1), time.min))

    # 只按 UTC 小时聚合（最多 days * 24 行），再在 Python 侧折算成本地日期，
    # 这样既不用为每一天各发一条查询，也能正确处理本地时区与夏令时。
    buckets = db.execute(
        """
        SELECT
            strftime('%Y-%m-%d %H', datetime(created_at)) AS bucket,
            COUNT(*) AS orders_count,
            COALESCE(SUM(total_amount), 0) AS revenue,
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS failed_count
        FROM orders
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) < datetime(?)
        GROUP BY bucket
        """,
        (FAILED_STATUS, start_utc, end_utc),
    ).fetchall()

    per_day: dict[date, dict[str, float]] = {}
    for row in buckets:
        local_day = _local_date_of_utc_hour(row["bucket"])
        if local_day is None:
            continue
        slot = per_day.setdefault(local_day, {"orders": 0, "revenue": 0.0, "failed": 0})
        slot["orders"] += int(row["orders_count"] or 0)
        slot["revenue"] += float(row["revenue"] or 0)
        slot["failed"] += int(row["failed_count"] or 0)

    items = []
    for day in sequence:
        slot = per_day.get(day) or {"orders": 0, "revenue": 0.0, "failed": 0}
        orders_count = int(slot["orders"])
        failed_count = int(slot["failed"])
        items.append(
            {
                "date": day.isoformat(),
                # 前端横轴标签，例如 10/01。
                "label": f"{day.month:02d}/{day.day:02d}",
                "orders": orders_count,
                "revenue": round(float(slot["revenue"]), 2),
                "failed": failed_count,
                # 当日打印失败率（%），分母为当日订单数；无订单时为 0。
                "failure_rate": round(failed_count * 100 / orders_count, 2) if orders_count else 0.0,
            }
        )

    total_orders = sum(item["orders"] for item in items)
    total_failed = sum(item["failed"] for item in items)
    totals = {
        "orders": total_orders,
        "revenue": round(sum(item["revenue"] for item in items), 2),
        "failed": total_failed,
        "failure_rate": round(total_failed * 100 / total_orders, 2) if total_orders else 0.0,
    }

    return {
        "days": days,
        "start_date": sequence[0].isoformat(),
        "end_date": sequence[-1].isoformat(),
        "timezone": timezone_label(),
        "items": items,
        "totals": totals,
    }
