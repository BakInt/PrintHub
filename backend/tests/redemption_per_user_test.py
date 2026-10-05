"""兑换码「每个用户最大兑换次数」(per_user_max_times) 专项验证脚本。

本脚本**不依赖 pycups / CUPS / FastAPI 应用**，只用 sqlite3 建最小表结构直连
`app.services.redemption`，在 Windows 本地即可运行：

    cd backend
    python tests/redemption_per_user_test.py

覆盖点：
1. 表结构含 per_user_max_times 列，默认 0；create_code 缺省写入 0，负数被夹到 0。
2. 关闭限制（0）：完全保持原有总次数逻辑（usable_count=2 可兑 2 次，第 3 次 USED_UP）。
3. 开启限制（N）：同一用户最多兑换 N 次，第 N+1 次被拒（REDEMPTION_PER_USER_LIMIT 中文提示），
   失败时余额与 used_count 都不变（事务整体回滚）。
4. 双重校验：开启每用户限制后**仍受 usable_count 总次数约束**（usable_count=1 时第二个用户
   被 REDEMPTION_CODE_USED_UP 拦住），这是与旧版「每用户一次忽略总次数」的关键差异。
5. 不同用户各自计数互不影响；used_count 随成功兑换累加，全局用满后状态变为 used。
6. 开启限制的码仍受过期约束（过期优先）。
7. 旧库缺列（行里没有 per_user_max_times）按 0 处理，不报错。
8. migrate_redemption_per_user_limit()：旧库 per_user_once=1 → per_user_max_times=1，
   已有更大上限不被覆盖，重复执行幂等，新库（无旧列）直接跳过。
9. list_codes/_serialize_code 返回 per_user_max_times，供后台列表展示。
10. AdminRedemptionCreate 接受 per_user_max_times；旧前端 per_user_once=True 折算为 1；
    用户侧 RedeemRequest.code 仍必填。
11. 【新增】有效期二选一（expiry_mode=days|date）：指定到期日期时归一化为当天 23:59:59
    写入 expires_at、valid_days 归零；日期过期后过期判断优先；按天数模式行为不变；
    list_codes/_serialize_code 通过 expiry_mode 回传当前方式。
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from app.services.redemption import (  # noqa: E402
    batch_generate_codes,
    code_status,
    count_user_redemptions,
    create_code,
    expiry_mode_of,
    has_redeemed,
    list_codes,
    normalize_expire_date,
    per_user_max_times_of,
    redeem,
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    real_name TEXT,
    email TEXT,
    phone TEXT UNIQUE,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE redemption_codes (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    amount REAL NOT NULL,
    usable_count INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0,
    per_user_max_times INTEGER DEFAULT 0,
    valid_days INTEGER DEFAULT 0,
    expires_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code)
);

CREATE TABLE redemption_logs (
    id TEXT PRIMARY KEY,
    code_id TEXT NOT NULL,
    user_id TEXT,
    amount REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (code_id) REFERENCES redemption_codes(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
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


def add_user(db: sqlite3.Connection, user_id: str, balance: float = 0.0) -> sqlite3.Row:
    db.execute(
        "INSERT INTO users (id, username, password_hash, balance) VALUES (?, ?, 'x', ?)",
        (user_id, user_id, balance),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def expect_error(label: str, fn, expected_code: str) -> None:
    try:
        fn()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        check(
            label,
            exc.status_code == 400 and detail.get("code") == expected_code,
            f"-> status={exc.status_code} detail={exc.detail}",
        )
    else:
        check(label, False, "-> 未抛出 HTTPException")


def balance_of(db: sqlite3.Connection, user_id: str) -> float:
    row = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    return round(float(row["balance"]), 2)


def used_count_of(db: sqlite3.Connection, code_id: str) -> int:
    row = db.execute("SELECT used_count FROM redemption_codes WHERE id = ?", (code_id,)).fetchone()
    return int(row["used_count"])


def max_times_of(db: sqlite3.Connection, code_id: str) -> int:
    row = db.execute("SELECT per_user_max_times FROM redemption_codes WHERE id = ?", (code_id,)).fetchone()
    return int(row["per_user_max_times"])


def expires_at_of(db: sqlite3.Connection, code_id: str):
    row = db.execute("SELECT expires_at FROM redemption_codes WHERE id = ?", (code_id,)).fetchone()
    return row["expires_at"]


def valid_days_of(db: sqlite3.Connection, code_id: str) -> int:
    row = db.execute("SELECT valid_days FROM redemption_codes WHERE id = ?", (code_id,)).fetchone()
    return int(row["valid_days"])


def code_row(db: sqlite3.Connection, code_id: str) -> sqlite3.Row:
    return db.execute("SELECT * FROM redemption_codes WHERE id = ?", (code_id,)).fetchone()


def test_schema_default():
    print("\n[1] 表结构 per_user_max_times 默认 0")
    db = new_db()
    created = create_code(db, "DEFAULTCASE1", 10.0)
    check("未传 per_user_max_times 时入库为 0", max_times_of(db, created["id"]) == 0, f"-> {max_times_of(db, created['id'])}")
    check("create_code 返回 per_user_max_times=0", created["per_user_max_times"] == 0, f"-> {created}")
    negative = create_code(db, "NEGATIVECASE", 10.0, per_user_max_times=-5)
    check("负数上限被夹到 0（视为关闭限制）", max_times_of(db, negative["id"]) == 0)
    positive = create_code(db, "POSITIVECASE", 10.0, usable_count=3, per_user_max_times=2)
    check("正整数上限原样入库", max_times_of(db, positive["id"]) == 2)
    check("返回体同步带上限", positive["per_user_max_times"] == 2)


def test_total_count_unchanged():
    print("\n[2] per_user_max_times=0：原有总次数逻辑不变")
    db = new_db()
    user_a = add_user(db, "user-a")
    created = create_code(db, "TOTALCOUNT01", 5.0, usable_count=2)
    code_id = created["id"]

    check("第1次兑换成功", redeem(db, user_a, "TOTALCOUNT01") == 5.0)
    check("同一用户第2次仍可兑换（总次数语义）", redeem(db, user_a, "TOTALCOUNT01") == 5.0)
    check("余额累计 10", balance_of(db, user_a["id"]) == 10.0, f"-> {balance_of(db, user_a['id'])}")
    check("used_count 为 2", used_count_of(db, code_id) == 2)
    check("状态变为 used", code_status(code_row(db, code_id)) == "used")

    expect_error(
        "第3次超出总次数被拒（沿用原错误码）",
        lambda: redeem(db, user_a, "TOTALCOUNT01"),
        "REDEMPTION_CODE_USED_UP",
    )
    check("失败后余额仍为 10", balance_of(db, user_a["id"]) == 10.0)


def test_per_user_limit():
    print("\n[3] per_user_max_times=2：同一用户最多 2 次（双重校验）")
    db = new_db()
    user_a = add_user(db, "user-a")
    user_b = add_user(db, "user-b")
    created = create_code(db, "PERUSERLIMIT", 20.0, usable_count=5, per_user_max_times=2)
    code_id = created["id"]

    check("用户A 第1次兑换成功（大小写不敏感）", redeem(db, user_a, "peruserlimit") == 20.0)
    check("用户A 第2次兑换成功（未达上限）", redeem(db, user_a, "PERUSERLIMIT") == 20.0)
    check("用户A 余额 +40", balance_of(db, user_a["id"]) == 40.0, f"-> {balance_of(db, user_a['id'])}")
    check("used_count 累加为 2", used_count_of(db, code_id) == 2)
    check("count_user_redemptions(A) = 2", count_user_redemptions(db, code_id, user_a["id"]) == 2)
    check("count_user_redemptions(B) = 0", count_user_redemptions(db, code_id, user_b["id"]) == 0)
    check("has_redeemed(A) 为真", has_redeemed(db, code_id, user_a["id"]) is True)
    check("has_redeemed(B) 为假", has_redeemed(db, code_id, user_b["id"]) is False)
    check("全局未用满，状态仍是 unused", code_status(code_row(db, code_id)) == "unused")

    expect_error(
        "用户A 第3次达到每用户上限被拒",
        lambda: redeem(db, user_a, "PERUSERLIMIT"),
        "REDEMPTION_PER_USER_LIMIT",
    )
    check("失败后余额未被增加", balance_of(db, user_a["id"]) == 40.0, f"-> {balance_of(db, user_a['id'])}")
    check("失败后 used_count 不变", used_count_of(db, code_id) == 2, f"-> {used_count_of(db, code_id)}")

    check("用户B 可独立兑换（各自计数）", redeem(db, user_b, "PERUSERLIMIT") == 20.0)
    check("用户B 余额 +20", balance_of(db, user_b["id"]) == 20.0)
    check("used_count 累加为 3", used_count_of(db, code_id) == 3, f"-> {used_count_of(db, code_id)}")

    try:
        redeem(db, user_a, "PERUSERLIMIT")
    except HTTPException as exc:
        message = exc.detail.get("message", "") if isinstance(exc.detail, dict) else ""
        check("拒绝提示为中文且非空", bool(message) and any("\u4e00" <= ch <= "\u9fff" for ch in message), f"-> {message}")
        check("提示里带上限次数", "2" in message, f"-> {message}")
        print(f"       提示文案：{message}")


def test_dual_check_total_count_still_applies():
    print("\n[4] 双重校验：开启每用户限制后仍受 usable_count 约束")
    db = new_db()
    user_a = add_user(db, "user-a")
    user_b = add_user(db, "user-b")
    # usable_count=1 但每用户上限 5：旧版「每用户一次」会忽略总次数让用户B也兑换成功，
    # 新语义必须双重校验，用户B 被全局总次数拦住。
    created = create_code(db, "DUALCHECK001", 30.0, usable_count=1, per_user_max_times=5)
    code_id = created["id"]

    check("用户A 第1次兑换成功", redeem(db, user_a, "DUALCHECK001") == 30.0)
    check("used_count 为 1（占满全局次数）", used_count_of(db, code_id) == 1)
    check("全局用满后状态为 used", code_status(code_row(db, code_id)) == "used")

    expect_error(
        "用户B 虽未兑换过，仍被总次数拦住",
        lambda: redeem(db, user_b, "DUALCHECK001"),
        "REDEMPTION_CODE_USED_UP",
    )
    check("用户B 余额仍为 0", balance_of(db, user_b["id"]) == 0.0)
    check("used_count 未增加", used_count_of(db, code_id) == 1)

    expect_error(
        "用户A 再次兑换同样被总次数拦住",
        lambda: redeem(db, user_a, "DUALCHECK001"),
        "REDEMPTION_CODE_USED_UP",
    )


def test_expiry_still_applies():
    print("\n[5] per_user_max_times>0 仍受过期约束")
    db = new_db()
    user_a = add_user(db, "user-a")
    created = create_code(db, "EXPIREDLIMIT", 8.0, per_user_max_times=3)
    db.execute(
        "UPDATE redemption_codes SET expires_at = '2000-01-01T00:00:00' WHERE id = ?",
        (created["id"],),
    )
    db.commit()
    expect_error(
        "过期码即便未兑换过也拒绝",
        lambda: redeem(db, user_a, "EXPIREDLIMIT"),
        "REDEMPTION_CODE_EXPIRED",
    )
    check("失败未改变余额", balance_of(db, user_a["id"]) == 0.0)
    check("过期优先于其它判断", code_status(code_row(db, created["id"])) == "expired")


def test_legacy_row_without_column():
    print("\n[6] 旧库缺列时不报错（按 0 处理）")
    db = new_db()
    # 模拟旧库行：查询结果不含 per_user_max_times 键。
    db.execute(
        "INSERT INTO redemption_codes (id, code, amount, usable_count, used_count, valid_days, expires_at)"
        " VALUES ('old-1', 'LEGACYROW001', 3.0, 1, 0, 0, NULL)"
    )
    db.commit()
    row = db.execute(
        "SELECT id, code, amount, usable_count, used_count, valid_days, expires_at FROM redemption_codes WHERE id = 'old-1'"
    ).fetchone()
    check("缺列行按关闭限制处理", per_user_max_times_of(row) == 0)
    check("缺列行 status 走总次数逻辑", code_status(row) == "unused")
    check("缺列行 has_redeemed 判定安全", has_redeemed(db, "old-1", None) is False)
    check("缺列行 count_user_redemptions 判定安全", count_user_redemptions(db, "old-1", None) == 0)


def test_legacy_migration():
    print("\n[7] 旧库迁移：per_user_once=1 → per_user_max_times=1（幂等）")
    from app.database import migrate_redemption_per_user_limit

    db = new_db()
    # 新表结构已是新列名，这里补出旧列来模拟升级前的库。
    db.execute("ALTER TABLE redemption_codes ADD COLUMN per_user_once INTEGER DEFAULT 0")
    rows = [
        ("legacy-1", "LEGACYOLD001", 0, 1),
        ("legacy-2", "LEGACYOLD002", 0, 0),
        ("legacy-3", "LEGACYOLD003", 3, 1),
    ]
    for code_id, code, max_times, per_user_once in rows:
        db.execute(
            "INSERT INTO redemption_codes (id, code, amount, usable_count, used_count, per_user_max_times, valid_days, expires_at, per_user_once)"
            " VALUES (?, ?, 5.0, 1, 0, ?, 0, NULL, ?)",
            (code_id, code, max_times, per_user_once),
        )
    db.commit()

    migrate_redemption_per_user_limit(db)
    db.commit()
    check("旧库勾选过的码换算为每用户 1 次", max_times_of(db, "legacy-1") == 1)
    check("旧库未勾选的码保持 0", max_times_of(db, "legacy-2") == 0)
    check("已有更大上限不被覆盖", max_times_of(db, "legacy-3") == 3)

    migrate_redemption_per_user_limit(db)
    db.commit()
    check("重复执行结果不变（幂等）", max_times_of(db, "legacy-1") == 1 and max_times_of(db, "legacy-3") == 3)

    fresh = new_db()
    kept = create_code(fresh, "FRESHLIB0001", 5.0, per_user_max_times=2)
    migrate_redemption_per_user_limit(fresh)
    fresh.commit()
    check("新库（无旧列）直接跳过且不报错", max_times_of(fresh, kept["id"]) == 2)


def test_list_serialization():
    print("\n[8] 后台列表返回 per_user_max_times")
    db = new_db()
    create_code(db, "LISTLIMIT001", 6.0, usable_count=4, per_user_max_times=3)
    create_code(db, "LISTTOTAL001", 6.0)
    batch_generate_codes(db, 2, 4.0)
    data = list_codes(db, limit=20, offset=0)
    by_code = {item["code"]: item for item in data["items"]}
    check("开启限制的码返回上限 3", by_code["LISTLIMIT001"]["per_user_max_times"] == 3)
    check("未开启的码返回 0", by_code["LISTTOTAL001"]["per_user_max_times"] == 0)
    check(
        "批量生成的码默认 0（保持原总次数逻辑）",
        all(item["per_user_max_times"] == 0 for item in data["items"] if item["code"].startswith("LIST") is False),
    )
    check("列表项均含该字段", all("per_user_max_times" in item for item in data["items"]))
    check("列表项不再返回旧字段 per_user_once", all("per_user_once" not in item for item in data["items"]))


def test_schema_model():
    print("\n[9] AdminRedemptionCreate 支持 per_user_max_times")
    from app.models.schemas import AdminRedemptionCreate, RedeemRequest

    payload = AdminRedemptionCreate(code="MODELCASE001", amount=10, usable_count=1, valid_days=0, per_user_max_times=5)
    check("显式传正整数被接受", payload.per_user_max_times == 5)
    default_payload = AdminRedemptionCreate(code="", amount=10)
    check("缺省为 0（关闭限制，保留原行为）", default_payload.per_user_max_times == 0)
    check("code 仍允许留空", default_payload.code == "")
    legacy_payload = AdminRedemptionCreate(code="MODELCASE002", amount=10, per_user_once=True)
    check("旧前端 per_user_once=True 折算为 1", legacy_payload.per_user_max_times == 1)
    try:
        AdminRedemptionCreate(code="MODELCASE003", amount=10, per_user_max_times=-1)
    except Exception:
        check("负数上限被模型校验拒绝", True)
    else:
        check("负数上限被模型校验拒绝", False, "-> 负数未被拒绝")
    try:
        RedeemRequest(code="  ")
    except Exception:
        check("用户侧 RedeemRequest.code 仍必填", True)
    else:
        check("用户侧 RedeemRequest.code 仍必填", False, "-> 空码未被拒绝")


def test_expire_date_mode():
    print("\n[10] 有效期二选一：指定到期日期（expiry_mode=date）")
    # 归一化：只接受「天」粒度，统一落到当天 23:59:59，避免同一天不同时刻产生歧义。
    check("YYYY-MM-DD 归一化为当天 23:59:59", normalize_expire_date("2030-12-31") == "2030-12-31T23:59:59")
    check("date 对象同样被接受", normalize_expire_date(date(2030, 1, 5)) == "2030-01-05T23:59:59")
    check("带时间的 ISO 串只取当天", normalize_expire_date("2030-01-05T08:30:00") == "2030-01-05T23:59:59")
    check("空值返回 None", normalize_expire_date("") is None and normalize_expire_date(None) is None)
    check("非法日期返回 None", normalize_expire_date("2030-13-45") is None and normalize_expire_date("明天") is None)

    db = new_db()
    dated = create_code(db, "EXPIREDATE01", 12.0, expires_at="2030-12-31")
    dated_id = dated["id"]
    check("入库 expires_at 为当天 23:59:59", expires_at_of(db, dated_id) == "2030-12-31T23:59:59", f"-> {expires_at_of(db, dated_id)}")
    check("日期模式下 valid_days 归零", valid_days_of(db, dated_id) == 0, f"-> {valid_days_of(db, dated_id)}")
    check("create_code 返回体带上归一化到期时间", dated["expires_at"] == "2030-12-31T23:59:59", f"-> {dated}")
    check("expiry_mode_of 判定为 date", expiry_mode_of(code_row(db, dated_id)) == "date")
    check("未到期时状态仍为 unused", code_status(code_row(db, dated_id)) == "unused")

    by_days = create_code(db, "BYDAYSMODE01", 12.0, valid_days=30)
    check("按天数模式仍写 expires_at", expires_at_of(db, by_days["id"]) is not None)
    check("按天数模式 valid_days 保留", valid_days_of(db, by_days["id"]) == 30)
    check("expiry_mode_of 判定为 days", expiry_mode_of(code_row(db, by_days["id"])) == "days")
    forever = create_code(db, "FOREVERMODE1", 12.0, valid_days=0)
    check("0 天仍为永久有效（无 expires_at）", expires_at_of(db, forever["id"]) is None)
    check("永久有效也归 days 模式", expiry_mode_of(code_row(db, forever["id"])) == "days")

    invalid = create_code(db, "BADDATEFALLB", 12.0, valid_days=7, expires_at="不是日期")
    check("非法日期回退到按天数逻辑", expires_at_of(db, invalid["id"]) is not None and valid_days_of(db, invalid["id"]) == 7)

    # 明确的到期日期一旦过去，过期判断必须优先于总次数/每用户限制。
    user_a = add_user(db, "user-a")
    past = create_code(db, "PASTDATE0001", 9.0, usable_count=5, per_user_max_times=3, expires_at="2000-01-01")
    db.execute("UPDATE redemption_codes SET expires_at = '2000-01-01T23:59:59' WHERE id = ?", (past["id"],))
    db.commit()
    check("过期日期码状态为 expired", code_status(code_row(db, past["id"])) == "expired")
    expect_error(
        "指定到期日期已过的码被拒（过期优先）",
        lambda: redeem(db, user_a, "PASTDATE0001"),
        "REDEMPTION_CODE_EXPIRED",
    )
    check("过期失败未增加余额", balance_of(db, user_a["id"]) == 0.0)

    batch = batch_generate_codes(db, 3, 5.0, expires_at="2031-06-30")
    check("批量生成支持统一到期日期", len(batch) == 3 and all(item["expires_at"] == "2031-06-30T23:59:59" for item in batch), f"-> {batch}")
    check("批量生成日期模式 valid_days 归零", all(valid_days_of(db, item["id"]) == 0 for item in batch))

    data = list_codes(db, limit=50, offset=0)
    by_code = {item["code"]: item for item in data["items"]}
    check("列表回传 expiry_mode=date", by_code["EXPIREDATE01"]["expiry_mode"] == "date")
    check("列表回传 expiry_mode=days", by_code["BYDAYSMODE01"]["expiry_mode"] == "days")
    check("列表项均含 expiry_mode", all("expiry_mode" in item for item in data["items"]))


def test_expire_date_schema():
    print("\n[11] AdminRedemptionCreate/Batch 支持 expiry_mode + expire_date")
    from app.models.schemas import AdminRedemptionBatchCreate, AdminRedemptionCreate

    dated = AdminRedemptionCreate(code="MODELDATE001", amount=10, valid_days=30, expiry_mode="date", expire_date="2030-12-31")
    check("日期模式保留 expire_date", dated.expire_date == "2030-12-31")
    check("日期模式下 valid_days 被清 0", dated.valid_days == 0, f"-> {dated.valid_days}")
    check("expiry_mode 原样保留", dated.expiry_mode == "date")

    defaulted = AdminRedemptionCreate(code="MODELDATE002", amount=10, valid_days=15)
    check("缺省 expiry_mode=days", defaulted.expiry_mode == "days")
    check("缺省 expire_date 为 None", defaulted.expire_date is None)
    check("天数模式不清空 valid_days", defaulted.valid_days == 15)

    cleaned = AdminRedemptionCreate(code="MODELDATE003", amount=10, valid_days=10, expiry_mode="days", expire_date="2030-12-31")
    check("天数模式忽略 expire_date（避免歧义）", cleaned.expire_date is None and cleaned.valid_days == 10)

    try:
        AdminRedemptionCreate(code="MODELDATE004", amount=10, expiry_mode="date", expire_date="2030-02-30")
    except Exception:
        check("不存在的日期被模型校验拒绝", True)
    else:
        check("不存在的日期被模型校验拒绝", False, "-> 无效日期未被拒绝")

    try:
        AdminRedemptionCreate(code="MODELDATE005", amount=10, expiry_mode="date", expire_date="")
    except Exception:
        check("日期模式缺少日期被拒绝", True)
    else:
        check("日期模式缺少日期被拒绝", False, "-> 空日期未被拒绝")

    batch_dated = AdminRedemptionBatchCreate(count=5, amount=10, expiry_mode="date", expire_date="2030-12-31")
    check("批量模型同样支持日期模式", batch_dated.expire_date == "2030-12-31" and batch_dated.valid_days == 0)
    batch_cleaned = AdminRedemptionBatchCreate(count=5, amount=10, valid_days=3, expire_date="2030-12-31")
    check("批量模型天数模式忽略 expire_date", batch_cleaned.expire_date is None and batch_cleaned.valid_days == 3)


def main() -> int:
    print("=" * 68)
    print("兑换码 per_user_max_times（每个用户最大兑换次数）专项验证")
    print("=" * 68)
    test_schema_default()
    test_total_count_unchanged()
    test_per_user_limit()
    test_dual_check_total_count_still_applies()
    test_expiry_still_applies()
    test_legacy_row_without_column()
    test_legacy_migration()
    test_list_serialization()
    test_schema_model()
    test_expire_date_mode()
    test_expire_date_schema()
    print("\n" + "=" * 68)
    print(f"结果：通过 {passed} 项，失败 {failed} 项")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
