import math
import json
import sqlite3
from datetime import datetime


STANDARD_PRICING_MODE = "standard"
COVERAGE_TIERED_PRICING_MODE = "coverage_tiered"


def _parse_json_setting(db: sqlite3.Connection, key: str, default):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] == "":
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return default


def get_numeric_setting(db: sqlite3.Connection, key: str, default: float) -> float:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return float(row["value"])


def get_string_setting(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def get_bool_setting(db: sqlite3.Connection, key: str, default: bool = False) -> bool:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}


def get_pricing_mode(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT value FROM settings WHERE key = 'pricing_mode'").fetchone()
    if row is None or row["value"] not in {STANDARD_PRICING_MODE, COVERAGE_TIERED_PRICING_MODE}:
        return STANDARD_PRICING_MODE
    return row["value"]


def calculate_price(db: sqlite3.Connection, page_count: int, copies: int, double_sided: bool) -> float:
    if double_sided:
        billable_pages = math.ceil(page_count / 2)
        unit_price = get_numeric_setting(db, "duplex_price", 0.3)
    else:
        billable_pages = page_count
        unit_price = get_numeric_setting(db, "single_price", 0.5)
    return round(billable_pages * copies * unit_price, 2)


def calculate_sheet_count(page_count: int, copies: int, double_sided: bool) -> int:
    pages = max(int(page_count or 0), 0)
    copy_count = max(int(copies or 1), 1)
    sheets_per_copy = math.ceil(pages / 2) if double_sided else pages
    return sheets_per_copy * copy_count


def coverage_factor(coverage: float) -> float:
    if coverage <= 5:
        return 1.0
    if coverage <= 15:
        return 1.75
    if coverage <= 30:
        return 3.25
    if coverage <= 50:
        return 5.0
    return 6.0


def row_page_coverages(file_row: sqlite3.Row) -> list[float]:
    raw_coverages = file_row["page_coverages"]
    if raw_coverages:
        try:
            values = json.loads(raw_coverages)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            coverages = []
            for value in values:
                try:
                    coverages.append(float(value))
                except (TypeError, ValueError):
                    continue
            if coverages:
                return coverages
    page_count = max(int(file_row["page_count"] or 0), 0)
    average = float(file_row["black_coverage"] or 0)
    return [average for _ in range(page_count)]


def calculate_coverage_tiered_price(db: sqlite3.Connection, files: list[sqlite3.Row], copies: int, double_sided: bool) -> float:
    base_key = "coverage_duplex_base_price" if double_sided else "coverage_single_base_price"
    default_base = 0.08 if double_sided else 0.10
    base_price = get_numeric_setting(db, base_key, default_base)
    total = 0.0
    for file_row in files:
        for coverage in row_page_coverages(file_row):
            total += base_price * coverage_factor(coverage)
    return round(total * copies, 2)


def calculate_file_base_amount(
    db: sqlite3.Connection,
    file_row: sqlite3.Row,
    copies: int,
    double_sided: bool,
    pricing_mode: str,
) -> float:
    """按单份文档计算基础金额，双面仅在该份文档内部按 ceil(页数/2) 折算。"""
    if pricing_mode == COVERAGE_TIERED_PRICING_MODE:
        return calculate_coverage_tiered_price(db, [file_row], copies, double_sided)
    page_count = int(file_row["page_count"] or 0)
    return calculate_price(db, page_count, copies, double_sided)


def normalize_discount(value) -> float | None:
    try:
        discount = float(value)
    except (TypeError, ValueError):
        return None
    if discount > 1 and discount <= 100:
        discount = discount / 100
    if discount <= 0 or discount > 1:
        return None
    return discount


def bulk_discount_rules(db: sqlite3.Connection) -> list[dict]:
    raw_rules = _parse_json_setting(db, "bulk_discount_rules", [])
    if not isinstance(raw_rules, list):
        return []
    rules = []
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        try:
            min_sheets = int(rule.get("min_sheets", 0))
        except (TypeError, ValueError):
            continue
        discount = normalize_discount(rule.get("discount"))
        if min_sheets <= 0 or discount is None:
            continue
        rules.append({"min_sheets": min_sheets, "discount": discount})
    return sorted(rules, key=lambda item: item["min_sheets"])


def best_bulk_discount(db: sqlite3.Connection, sheet_count: int) -> dict | None:
    if not get_bool_setting(db, "bulk_discount_enabled", True):
        return None
    matched = [rule for rule in bulk_discount_rules(db) if sheet_count >= rule["min_sheets"]]
    if not matched:
        return None
    rule = matched[-1]
    return {
        "type": "bulk",
        "label": f"满{rule['min_sheets']}张{int(round(rule['discount'] * 100))}折",
        "min_sheets": rule["min_sheets"],
        "discount": rule["discount"],
    }


def promotion_summary(db: sqlite3.Connection) -> dict:
    bulk_enabled = get_bool_setting(db, "bulk_discount_enabled", True)
    bulk_rules = [
        {
            "min_sheets": rule["min_sheets"],
            "discount": rule["discount"],
            "label": f"满{rule['min_sheets']}张/份{int(round(rule['discount'] * 100))}折",
        }
        for rule in bulk_discount_rules(db)
    ] if bulk_enabled else []

    daily_offer = None
    if get_bool_setting(db, "daily_limited_offer_enabled", False):
        all_day = get_bool_setting(db, "daily_limited_offer_all_day", False)
        start_time = get_string_setting(db, "daily_limited_offer_start_time", "")
        end_time = get_string_setting(db, "daily_limited_offer_end_time", "")
        quota = int(get_numeric_setting(db, "daily_limited_offer_sheet_quota", 0))
        is_free = get_bool_setting(db, "daily_limited_offer_free", False)
        discount = normalize_discount(get_numeric_setting(db, "daily_limited_offer_discount", 1.0))
        offer_valid = is_free or (discount is not None and discount < 1)
        # 勾选“全天”后忽略开始/结束时间，全天生效；否则仍要求有效的时间窗口。
        window_valid = all_day or (bool(start_time) and bool(end_time) and start_time < end_time)
        if window_valid and quota > 0 and offer_valid:
            used_sheets = daily_offer_used_sheets(db)
            remaining_sheets = max(quota - used_sheets, 0)
            daily_offer = {
                "enabled": True,
                "all_day": all_day,
                "start_time": "" if all_day else start_time,
                "end_time": "" if all_day else end_time,
                "quota": quota,
                "used_sheets": used_sheets,
                "remaining_sheets": remaining_sheets,
                "free": is_free,
                "discount": 0.0 if is_free else discount,
                "label": ("今日限时免费" if is_free else f"今日限时特价{int(round(discount * 100))}折")
                if not all_day
                else ("今日全天免费" if is_free else f"今日全天特价{int(round(discount * 100))}折"),
            }

    return {
        "daily_limited_offer": daily_offer,
        "bulk_discount": {
            "enabled": bulk_enabled and bool(bulk_rules),
            "rules": bulk_rules,
        },
    }


def _time_in_daily_offer_window(now: datetime, start_time: str, end_time: str) -> bool:
    if not start_time or not end_time or start_time >= end_time:
        return False
    current = now.strftime("%H:%M")
    return start_time <= current < end_time


def daily_offer_used_sheets(db: sqlite3.Connection) -> int:
    row = db.execute(
        """
        SELECT COALESCE(SUM(sheet_count), 0) AS used_sheets
        FROM orders
        WHERE id NOT LIKE 'TEST%'
          AND date(created_at, 'localtime') = date('now', 'localtime')
          AND EXISTS (
              SELECT 1
              FROM order_items
              WHERE order_items.order_id = orders.id
          )
        """
    ).fetchone()
    return int(row["used_sheets"] or 0)


def daily_limited_offer_discount(db: sqlite3.Connection, sheet_count: int, now: datetime | None = None) -> dict | None:
    if not get_bool_setting(db, "daily_limited_offer_enabled", False):
        return None
    start_time = get_string_setting(db, "daily_limited_offer_start_time", "")
    end_time = get_string_setting(db, "daily_limited_offer_end_time", "")
    current_time = now or datetime.now()
    # 勾选“全天”后忽略开始/结束时间，全天在额度内均命中；否则要求当前时间落在时间窗口内。
    if not get_bool_setting(db, "daily_limited_offer_all_day", False):
        if not _time_in_daily_offer_window(current_time, start_time, end_time):
            return None
    quota = int(get_numeric_setting(db, "daily_limited_offer_sheet_quota", 0))
    if quota <= 0:
        return None
    used_sheets = daily_offer_used_sheets(db)
    remaining_sheets = max(quota - used_sheets, 0)
    if sheet_count <= 0 or sheet_count > remaining_sheets:
        return None
    # 完全免费开关优先于折扣百分比：命中后限时特价直接把金额打到 0（免费），
    # 复用后端已有的“金额为 0 免费单”流程（直接置为 paid 并派发打印，不走支付网关）。
    if get_bool_setting(db, "daily_limited_offer_free", False):
        return {
            "type": "daily_limited",
            "label": "限时免费",
            "discount": 0.0,
            "free": True,
            "quota": quota,
            "used_sheets": used_sheets,
            "remaining_sheets": remaining_sheets,
            "start_time": start_time,
            "end_time": end_time,
        }
    discount = normalize_discount(get_numeric_setting(db, "daily_limited_offer_discount", 1.0))
    if discount is None or discount >= 1:
        return None
    return {
        "type": "daily_limited",
        "label": f"限时特价{int(round(discount * 100))}折",
        "discount": discount,
        "free": False,
        "quota": quota,
        "used_sheets": used_sheets,
        "remaining_sheets": remaining_sheets,
        "start_time": start_time,
        "end_time": end_time,
    }


def _discounted_amount(base_amount: float, discount: float) -> float:
    return round(base_amount * discount, 2)


def _price_detail(base_amount: float, sheet_count: int, pricing_mode: str, discounts: list[dict | None]) -> dict:
    candidates = [{"amount": round(base_amount, 2), "applied_discount": None}]
    for discount in discounts:
        if not discount:
            continue
        candidates.append({
            "amount": _discounted_amount(base_amount, discount["discount"]),
            "applied_discount": discount,
        })
    selected = min(candidates, key=lambda item: item["amount"])
    amount = selected["amount"]
    return {
        "amount": amount,
        "base_amount": round(base_amount, 2),
        "discount_amount": round(round(base_amount, 2) - amount, 2),
        "sheet_count": sheet_count,
        "pricing_mode": pricing_mode,
        "applied_discount": selected["applied_discount"],
    }


def calculate_price_detail(db: sqlite3.Connection, page_count: int, copies: int, double_sided: bool) -> dict:
    base_amount = calculate_price(db, page_count, copies, double_sided)
    sheet_count = calculate_sheet_count(page_count, copies, double_sided)
    return _price_detail(
        base_amount,
        sheet_count,
        STANDARD_PRICING_MODE,
        [
            best_bulk_discount(db, sheet_count),
            daily_limited_offer_discount(db, sheet_count),
        ],
    )


def resolve_file_double_sided(file_row: sqlite3.Row, double_sided) -> bool:
    """解析单份文档的双面设置：接受布尔（作用于所有文件）或 {file_id: bool} 映射。

    单页文档强制单面：双面对单页无意义，不会把两份单页合并到同一张纸。
    """
    if isinstance(double_sided, dict):
        requested = bool(double_sided.get(file_row["id"], False))
    else:
        requested = bool(double_sided)
    if int(file_row["page_count"] or 0) < 2:
        return False
    return requested


def calculate_files_price_detail(db: sqlite3.Connection, files: list[sqlite3.Row], copies: int, double_sided) -> dict:
    """逐份文档计价：每份文档按自身页数与自身单/双面独立折算张数与金额后求和。

    ``double_sided`` 可为布尔（对所有文件生效）或 {file_id: bool} 的按份映射。
    """
    pricing_mode = get_pricing_mode(db)
    base_amount = 0.0
    sheet_count = 0
    for file_row in files:
        file_duplex = resolve_file_double_sided(file_row, double_sided)
        base_amount += calculate_file_base_amount(db, file_row, copies, file_duplex, pricing_mode)
        sheet_count += calculate_sheet_count(int(file_row["page_count"] or 0), copies, file_duplex)
    base_amount = round(base_amount, 2)
    return _price_detail(
        base_amount,
        sheet_count,
        pricing_mode,
        [
            best_bulk_discount(db, sheet_count),
            daily_limited_offer_discount(db, sheet_count),
        ],
    )


def calculate_files_price(db: sqlite3.Connection, files: list[sqlite3.Row], copies: int, double_sided) -> float:
    return calculate_files_price_detail(db, files, copies, double_sided)["amount"]
