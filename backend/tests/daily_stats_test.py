"""后台「每日数据统计」按本地时区聚合的专项验证脚本。

本脚本**不依赖 pycups / CUPS / FastAPI 应用**，只用 sqlite3 建最小表结构直连
`app.services.stats`，在 Windows 本地即可运行：

    cd backend
    python tests/daily_stats_test.py

覆盖点：
1. 空库返回完整日期序列（近 7 天 = 7 个点，升序、最后一个是今天），全 0 且不报错。
2. 分日按**本地时区**折算而不是 UTC 日期：本地「今天 00:30」必须落在今天、
   「昨天 23:30」必须落在昨天（东八区下若退化成 UTC 分日，本项必然失败）。
3. 同一天多笔订单的订单数、收入、失败数与失败率聚合正确。
4. `orders.created_at` 两种时间戳格式（`YYYY-MM-DD HH:MM:SS` 与
   `YYYY-MM-DDTHH:MM:SS.ffffff`）都能被正确归日。
5. 收入口径与后台概览卡片一致：不过滤 `order_type`，充值单也计入。
6. 窗口边界：近 7 天不含 7 天前的订单；近 30 天含第 30 天本地 00:10 的单、不含再前一天 23:59 的单。
7. days 归一化：非法值回退 7，0→1，超大值夹到 90。
8. totals 与 items 自洽，收入保留两位小数。
9. `timezone_label()` 形如 `UTC+08:00`。
10. `_utc_boundary_text()` 输出的是本地时刻对应的 UTC 时刻（含夏令时切换日），保证边界不会错位。
"""

import sqlite3
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.stats import (  # noqa: E402
    DEFAULT_DAYS,
    MAX_DAYS,
    MIN_DAYS,
    _utc_boundary_text,
    daily_stats,
    normalize_days,
    timezone_label,
)

SCHEMA = """
CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    order_type TEXT DEFAULT 'print',
    total_amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

passed = 0
failed = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label} {extra}")


def new_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def local_utc_text(local_moment: datetime) -> str:
    """把「本地时间」写成 UTC 文本，用于插入测试数据。

    无参时区的 naive datetime 调用 `astimezone()` 会被按本机本地时区解释，
    与 `app.services.stats` 里的边界折算用的是同一套语义。
    """
    return local_moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_local():
    return datetime.now().date()


def day_at(offset_from_today: int, hour: int = 12, minute: int = 0) -> datetime:
    """今天的本地时间往前推 `offset_from_today` 天。"""
    return datetime.combine(today_local() - timedelta(days=offset_from_today), time(hour, minute))


def add_order(
    db: sqlite3.Connection,
    order_id: str,
    created_at: str,
    total_amount: float = 10.0,
    status: str = "paid",
    order_type: str = "print",
) -> None:
    db.execute(
        "INSERT INTO orders (id, order_type, total_amount, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (order_id, order_type, total_amount, status, created_at),
    )
    db.commit()


def item_of(result: dict, offset_from_today: int) -> dict:
    """取「今天往前推 N 天」那一天的聚合行。"""
    target = (today_local() - timedelta(days=offset_from_today)).isoformat()
    for item in result["items"]:
        if item["date"] == target:
            return item
    raise AssertionError(f"结果里没有 {target} 这一天：{result['items']}")


def test_empty_db():
    print("\n[1] 空库：返回完整日期序列且全 0")
    result = daily_stats(new_db(), 7)
    check("days 回显为 7", result["days"] == 7)
    check("返回 7 个数据点", len(result["items"]) == 7, f"-> {len(result['items'])}")
    check("日期升序且最后一个是今天", result["items"][-1]["date"] == today_local().isoformat())
    check(
        "第一天是今天往前 6 天",
        result["items"][0]["date"] == (today_local() - timedelta(days=6)).isoformat(),
    )
    check("start_date/end_date 与首尾一致", result["start_date"] == result["items"][0]["date"] and result["end_date"] == result["items"][-1]["date"])
    check("横轴标签形如 MM/DD", all(len(item["label"]) == 5 and item["label"][2] == "/" for item in result["items"]))
    check("空库时每天都是 0", all(item["orders"] == 0 and item["revenue"] == 0.0 and item["failed"] == 0 for item in result["items"]))
    check("空库失败率为 0（不发生除零）", all(item["failure_rate"] == 0.0 for item in result["items"]))
    check("totals 全 0", result["totals"]["orders"] == 0 and result["totals"]["revenue"] == 0.0 and result["totals"]["failed"] == 0)


def test_local_timezone_day_boundary():
    print("\n[2] 分日按本地时区折算（东八区下退化成 UTC 分日会失败）")
    db = new_db()
    # 本地今天 00:30 与 本地昨天 23:30：UTC 日期上它们可能同属「昨天」或「今天」，
    # 但按本地时区必须分别落在今天和昨天。
    add_order(db, "BOUNDARY_TODAY", local_utc_text(day_at(0, 0, 30)), total_amount=1.0)
    add_order(db, "BOUNDARY_YESTERDAY", local_utc_text(day_at(1, 23, 30)), total_amount=2.0)
    # 本地今天 23:30 与 本地昨天 00:10，覆盖另一侧边界。
    add_order(db, "BOUNDARY_TODAY_LATE", local_utc_text(day_at(0, 23, 30)), total_amount=4.0)
    add_order(db, "BOUNDARY_YESTERDAY_EARLY", local_utc_text(day_at(1, 0, 10)), total_amount=8.0)

    result = daily_stats(db, 7)
    check("本地今天 00:30 归入今天", item_of(result, 0)["orders"] == 2, f"-> {item_of(result, 0)['orders']}")
    check("本地昨天 23:30 归入昨天", item_of(result, 1)["orders"] == 2, f"-> {item_of(result, 1)['orders']}")
    check("本地今天合计收入 = 1.0 + 4.0", item_of(result, 0)["revenue"] == 5.0, f"-> {item_of(result, 0)['revenue']}")
    check("本地昨天合计收入 = 2.0 + 8.0", item_of(result, 1)["revenue"] == 10.0, f"-> {item_of(result, 1)['revenue']}")
    check("更早的 5 天仍然为 0", all(item_of(result, offset)["orders"] == 0 for offset in range(2, 7)))


def test_aggregation_and_failure_rate():
    print("\n[3] 同一天多笔订单的聚合与失败率")
    db = new_db()
    add_order(db, "AGG1", local_utc_text(day_at(0, 10, 0)), total_amount=12.5, status="completed")
    add_order(db, "AGG2", local_utc_text(day_at(0, 11, 0)), total_amount=3.5, status="print_failed")
    result = daily_stats(db, 7)
    today = item_of(result, 0)
    check("订单数 = 2", today["orders"] == 2, f"-> {today['orders']}")
    check("收入 = 16.0", today["revenue"] == 16.0, f"-> {today['revenue']}")
    check("打印失败数 = 1", today["failed"] == 1, f"-> {today['failed']}")
    check("失败率 = 50.0%", today["failure_rate"] == 50.0, f"-> {today['failure_rate']}")
    check("totals 与 items 自洽", result["totals"]["orders"] == 2 and result["totals"]["revenue"] == 16.0 and result["totals"]["failed"] == 1)
    check("totals 失败率 = 50.0%", result["totals"]["failure_rate"] == 50.0, f"-> {result['totals']['failure_rate']}")


def test_mixed_timestamp_formats_and_order_type():
    print("\n[4] 两种时间戳格式都能归日；收入口径与概览卡片一致（含充值单）")
    db = new_db()
    # SQLite CURRENT_TIMESTAMP 风格（空格分隔，无小数秒）
    add_order(db, "FMT_SPACE", local_utc_text(day_at(0, 9, 0)), total_amount=5.0)
    # datetime.utcnow().isoformat() 风格（T 分隔 + 微秒），与 paid_at/printed_at 写法一致
    micro = day_at(0, 9, 30).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    add_order(db, "FMT_ISO", micro, total_amount=7.0)
    # 充值单也计入（与 GET /api/admin/dashboard 的 revenue 口径保持一致）
    add_order(db, "RECHARGE", local_utc_text(day_at(0, 12, 0)), total_amount=100.0, order_type="recharge")
    result = daily_stats(db, 7)
    today = item_of(result, 0)
    check("空格分隔格式被归入今天", today["orders"] == 3, f"-> {today['orders']}")
    check("T 分隔 + 微秒格式被归入今天", today["revenue"] == 112.0, f"-> {today['revenue']}")
    check("充值单计入收入（口径与后台卡片一致）", today["revenue"] == 112.0)


def test_window_boundaries():
    print("\n[5] 时间窗口边界（近 7 天 / 近 30 天）")
    db = new_db()
    add_order(db, "OUT_OF_7", local_utc_text(day_at(7, 12, 0)), total_amount=50.0)
    add_order(db, "DAY_29", local_utc_text(day_at(29, 0, 10)), total_amount=1.0)
    add_order(db, "DAY_30", local_utc_text(day_at(30, 23, 59)), total_amount=1000.0)

    short = daily_stats(db, 7)
    check("近 7 天不含 7 天前的订单", short["totals"]["orders"] == 0 and short["totals"]["revenue"] == 0.0, f"-> {short['totals']}")

    long = daily_stats(db, 30)
    check("近 30 天返回 30 个数据点", len(long["items"]) == 30, f"-> {len(long['items'])}")
    check("含第 30 天本地 00:10 的订单", item_of(long, 29)["orders"] == 1, f"-> {item_of(long, 29)['orders']}")
    check("不含第 31 天本地 23:59 的订单", long["totals"]["orders"] == 2, f"-> {long['totals']['orders']}")
    check("近 30 天收入 = 1.0 + 50.0", long["totals"]["revenue"] == 51.0, f"-> {long['totals']['revenue']}")
    check("第 31 天的 1000 元未被计入", long["totals"]["revenue"] != 1051.0)


def test_normalize_days():
    print("\n[6] days 归一化")
    check("默认值 = 7", DEFAULT_DAYS == 7)
    check("下界 = 1、上界 = 90", MIN_DAYS == 1 and MAX_DAYS == 90)
    check("None 回退 7", normalize_days(None) == 7, f"-> {normalize_days(None)}")
    check("非法字符串回退 7", normalize_days("abc") == 7, f"-> {normalize_days('abc')}")
    check("数字字符串被接受", normalize_days("30") == 30, f"-> {normalize_days('30')}")
    check("0 被夹到 1", normalize_days(0) == 1, f"-> {normalize_days(0)}")
    check("负数被夹到 1", normalize_days(-5) == 1, f"-> {normalize_days(-5)}")
    check("超大值被夹到 90", normalize_days(999) == 90, f"-> {normalize_days(999)}")
    check("daily_stats 内部同样归一化", len(daily_stats(new_db(), 999)["items"]) == 90)


def test_timezone_label():
    print("\n[7] timezone_label 格式")
    label = timezone_label()
    check("形如 UTC+08:00", len(label) == 9 and label.startswith("UTC") and label[4] in "+-" and label[7] == ":", f"-> {label}")
    check("daily_stats 回显 timezone", daily_stats(new_db(), 7)["timezone"] == label)


def test_boundary_round_trip():
    print("\n[8] _utc_boundary_text 输出的是该本地时刻对应的 UTC 时刻")
    for moment in (
        datetime.combine(today_local(), time.min),
        datetime(2026, 3, 8, 0, 0),
        datetime(2026, 10, 25, 0, 0),
        datetime(2026, 1, 1, 0, 0),
        datetime(2026, 12, 31, 0, 0),
    ):
        text = _utc_boundary_text(moment)
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        # 只比较 UTC 时刻：这样即使某时区恰好在本地午夜切换夏令时（该本地时刻不存在或有歧义）
        # 本项也不会误报，同时仍能证明输出的是 UTC（不是本地时间）且格式可被 SQLite 直接比较。
        check(f"{moment.date().isoformat()} 输出为对应 UTC 时刻", parsed == moment.astimezone(timezone.utc), f"-> {text} -> {parsed}")
    today_text = _utc_boundary_text(datetime.combine(today_local(), time.min))
    back_to_local = datetime.strptime(today_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    check("今天本地 00:00 往返后仍是本地 00:00", back_to_local.hour == 0 and back_to_local.minute == 0 and back_to_local.date() == today_local(), f"-> {today_text} -> {back_to_local}")


def main() -> int:
    print("=" * 68)
    print("后台「每日数据统计」本地时区聚合专项验证")
    print(f"当前本机本地时区：{timezone_label()}")
    print("=" * 68)
    test_empty_db()
    test_local_timezone_day_boundary()
    test_aggregation_and_failure_rate()
    test_mixed_timestamp_formats_and_order_type()
    test_window_boundaries()
    test_normalize_days()
    test_timezone_label()
    test_boundary_round_trip()
    print("\n" + "=" * 68)
    print(f"结果：通过 {passed} 项，失败 {failed} 项")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
