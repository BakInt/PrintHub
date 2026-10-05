"""兑换码业务逻辑。

后台生成兑换码（手动新增单个 / 批量随机），用户在个人中心「兑换码充值」输入兑换码
兑付额度到余额。核心约定：

- 兑换码不可重复（code 唯一，大小写不敏感、自动去除首尾空白）。
- 手动新增单个兑换码时 code 允许留空，留空即由后端自动生成随机码（与批量生成同一字符集）。
- 一个兑换码最多可被兑换可用次数（usable_count，默认 1）次，达到后视为「已使用」。
- per_user_max_times（每个用户最大兑换次数）为 0 时关闭该限制，完全沿用上面这条
  「按 usable_count 总可用次数」的原有逻辑；为 N > 0 时开启限制：同一个 user_id 最多
  只能兑换此兑换码 N 次，不同用户仍可分别兑换，该用户已兑换次数统计兑换记录表
  redemption_logs。开启后是**双重校验**——总次数和每用户次数两重都必须通过，
  任一超限直接拒绝；因此这类兑换码依然会随 used_count 增长变成「已使用」。
- 有效期有两种**互斥**的配置方式（后台弹窗二选一，不允许同时生效）：
  - 「按天数」：valid_days 表示自生成起的有效天数，0 表示永久有效，由 _compute_expires_at()
    算出 expires_at；
  - 「指定到期日期」：管理员直接用日期控件选一个到期日，normalize_expire_date() 把它归一化成
    当天 23:59:59（本地时间，与库内既有 expires_at 的 naive 本地时间语义一致）后写进
    expires_at，同时把 valid_days 记为 0。
  expires_at 是过期判断的**唯一权威字段**：code_status() 始终优先比较它，因此两种方式在
  兑换校验、后台列表/详情里行为完全一致；存量按天数设置的兑换码逻辑保持不变。
  两种方式由 (valid_days, expires_at) 组合唯一表达，**不需要新增数据库列**：
  valid_days <= 0 且 expires_at 非空即「指定到期日期」，否则是「按天数」（0 天 = 永久有效）。
- 每次成功兑换写一条 redemption_logs（兑换用户 id + 时间 + 到账金额）。
- 兑换入账与扣减可用次数在同一事务内，用「带条件 UPDATE + rowcount 校验」保证
  并发安全（与余额充值防重复入账同一思路，防止同一兑换码被并发重复兑付）。
  每用户次数上限的去重在 BEGIN IMMEDIATE 写锁内复查兑换记录表（见 redeem()），
  保证同一用户并发重复提交也不会突破上限。

历史说明：列 per_user_once（每个登录用户仅可使用一次）已被 per_user_max_times 取代，
本模块不再读写旧列；旧库由 app.database.migrate_redemption_per_user_limit() 做一次
等价换算 per_user_once=1 → per_user_max_times=1。
"""

import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_BALANCE = 100000

# 兑换码字符集：去掉易混淆的 I/O/0/1 后取大写字母 + 数字，保证人手输入不易看错。
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 12


def _business_error(status_code: int, code: str, message: str) -> HTTPException:
    """构造「业务错误码 + 中文提示」的标准错误，供前端弹窗直接展示。

    detail 用 {code, message} 结构：`frontend/src/api/client.js` 的 formatErrorMessage()
    会取 `detail.message` 作为可读文案，同时保留机器可读的错误码。
    这样接口不会把原始异常或英文状态文本（如 "Internal Server Error"）抛给用户。
    """
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def generate_code() -> str:
    """生成一串不可预测的随机兑换码（默认 12 位大写字母数字）。"""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _random_unique_code(db: sqlite3.Connection, max_attempts: int = 20) -> str:
    """生成一个数据库中尚不存在的随机兑换码（用于留空自动生成）。"""
    for _ in range(max_attempts):
        candidate = generate_code()
        exists = db.execute("SELECT 1 FROM redemption_codes WHERE code = ?", (candidate,)).fetchone()
        if not exists:
            return candidate
    raise HTTPException(status_code=500, detail="生成兑换码失败，请重试")


def _compute_expires_at(valid_days: int, created_at: str | None = None) -> str | None:
    """按有效天数计算到期时间；valid_days <= 0 表示永久有效，返回 None。"""
    if valid_days is None or valid_days <= 0:
        return None
    base = datetime.now()
    if created_at:
        try:
            base = datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            pass
    return (base + timedelta(days=valid_days)).isoformat(timespec="seconds")


def normalize_expire_date(value) -> str | None:
    """把管理员选定的到期日期归一化成「当天 23:59:59」的本地时间字符串。

    接受原生日期控件提交的 ``YYYY-MM-DD``（也容忍 ``YYYY/MM/DD`` 与带时间的 ISO 串，
    此时只取日期部分），返回格式与库内既有 ``expires_at`` 完全一致
    （``datetime.isoformat(timespec="seconds")``，naive 本地时间），因此
    ``code_status()`` 的过期比较无需任何改动即可直接复用。
    空值或无法解析时返回 None（调用方决定是报错还是忽略）。
    """
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
        parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    # 到期时间精确到当天结束（23:59:59），当天全天仍可兑换。
    return parsed.replace(hour=23, minute=59, second=59, microsecond=0).isoformat(timespec="seconds")


def expiry_mode_of(code_row) -> str:
    """推断该兑换码的有效期配置方式：``date``=指定到期日期，``days``=按有效天数。

    刻意不新增数据库列：指定到期日期的码固定写成 valid_days=0 + expires_at 非空；
    按天数模式只有 valid_days>0 才会算出 expires_at（valid_days=0 表示永久有效、
    expires_at 为 NULL），所以 (valid_days, expires_at) 组合能唯一定位两种方式。
    旧库存量数据只可能是「按天数」或「永久有效」，一律归为 ``days``，展示与行为都不变。
    """
    try:
        valid_days = int(code_row["valid_days"] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        valid_days = 0
    try:
        expires_at = code_row["expires_at"]
    except (IndexError, KeyError, TypeError):
        expires_at = None
    return "date" if valid_days <= 0 and expires_at else "days"


def code_status(code_row) -> str:
    """返回兑换码当前状态：unused（未使用）/ used（已使用）/ expired（已过期）。

    已过期优先于已使用判断。expires_at 是过期判断的**唯一权威字段**：无论它是按
    valid_days 算出来的，还是管理员直接指定到期日期写进去的，都优先于已使用判断。
    per_user_max_times（每用户最大兑换次数）开启后仍然是
    **双重校验**：全局可用次数用满（used_count >= usable_count）同样视为已使用，
    与「按总次数」模式完全一致；某个用户自己还有没有额度，由兑换记录表按用户单独判断，
    所以这里不再需要「每用户一次」那种恒返回 unused 的特例分支。
    """
    if code_row["expires_at"]:
        try:
            if datetime.now() >= datetime.fromisoformat(code_row["expires_at"]):
                return "expired"
        except (TypeError, ValueError):
            pass
    used = int(code_row["used_count"] or 0)
    usable = int(code_row["usable_count"] or 1)
    if used >= usable:
        return "used"
    return "unused"


def per_user_max_times_of(code_row) -> int:
    """读取兑换码的「每个用户最大兑换次数」：0 表示关闭该限制。

    旧库的 `redemption_codes` 行可能还没有 per_user_max_times 列（迁移未跑或行对象来自旧查询），
    此时按 0 处理，即完全沿用原有总次数逻辑，绝不因为缺列而报错。
    """
    try:
        value = code_row["per_user_max_times"]
    except (IndexError, KeyError, TypeError):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def count_user_redemptions(db: sqlite3.Connection, code_id: str, user_id: str | None) -> int:
    """统计某个用户已经成功兑换该兑换码的次数（每用户次数上限的判定依据）。

    直接数 `redemption_logs` 里 (code_id, user_id) 的记录条数，让「去重条件」和
    「兑换记录」是同一份数据，不存在两处状态不一致的问题。
    """
    if not user_id:
        return 0
    row = db.execute(
        "SELECT COUNT(*) AS c FROM redemption_logs WHERE code_id = ? AND user_id = ?",
        (code_id, user_id),
    ).fetchone()
    return int(row["c"] or 0) if row is not None else 0


def has_redeemed(db: sqlite3.Connection, code_id: str, user_id: str | None) -> bool:
    """该用户是否已经兑换过该兑换码（count_user_redemptions 的布尔简写）。"""
    return count_user_redemptions(db, code_id, user_id) > 0


def _per_user_limit_message(max_times: int) -> str:
    """每用户次数达到上限时的中文提示（事务外预检与写锁内复查共用同一文案）。"""
    return f"您已兑换过该兑换码，每个用户最多可兑换 {max_times} 次"


def _serialize_code(db: sqlite3.Connection, code_row) -> dict:
    """把兑换码行序列化为后台列表需要的字段，并附带最近一次兑换用户信息。"""
    usable = int(code_row["usable_count"] or 1)
    item = dict(code_row)
    item["amount"] = round(float(item["amount"] or 0), 2)
    item["usable_count"] = usable
    item["used_count"] = int(item["used_count"] or 0)
    # 【新增功能】每个用户最大兑换次数：后台列表新增列展示该属性（0=不限制）。
    item["per_user_max_times"] = per_user_max_times_of(code_row)
    # 【新增功能】有效期配置方式：date=指定到期日期，days=按有效天数。
    # 后台列表/详情据此展示「指定到期日期」还是「N 天」，expires_at 始终是过期判断依据。
    item["expiry_mode"] = expiry_mode_of(code_row)
    item["status"] = code_status(code_row)
    item["total_amount"] = round(float(item["amount"] or 0) * usable, 2)
    # 最近一次成功兑换的用户（未使用过则为 None）。
    log = db.execute(
        """
        SELECT rl.user_id, u.username, u.real_name, rl.amount, rl.created_at
        FROM redemption_logs rl
        LEFT JOIN users u ON u.id = rl.user_id
        WHERE rl.code_id = ?
        ORDER BY rl.created_at DESC, rl.rowid DESC
        LIMIT 1
        """,
        (code_row["id"],),
    ).fetchone()
    if log is None:
        item["redeemed_by"] = None
        item["redeemed_at"] = None
    else:
        item["redeemed_by"] = log["username"] or log["real_name"] or log["user_id"]
        item["redeemed_at"] = log["created_at"]
    return item


def create_code(
    db: sqlite3.Connection,
    code: str,
    amount: float,
    usable_count: int = 1,
    valid_days: int = 0,
    per_user_max_times: int = 0,
    expires_at: str | None = None,
) -> dict:
    """手动新增单个兑换码。code 会去空白并转大写。

    code 留空（None / 空串 / 纯空白）时不报错，改为自动生成一个随机兑换码，
    与前端弹窗提示「自定义兑换码（留空随机生成）」一致。
    返回 {id, code, per_user_max_times, valid_days, expires_at}。

    per_user_max_times（弹窗「限制每个用户最大兑换次数」开关 + 数字输入框）：
    0 = 关闭该限制，完全沿用「按 usable_count 总可用次数」的原有逻辑；
    N > 0 = 开启限制，同一个 user_id 最多兑换 N 次，并且仍受总可用次数约束（双重校验）。

    【新增功能】有效期两种互斥方式（弹窗里二选一，不会同时生效）：
    - expires_at 传了可解析的日期（「指定到期日期」模式，来自日期控件）→ 直接采用它
      （normalize_expire_date() 归一化为当天 23:59:59），并把 valid_days 记为 0；
    - 否则按 valid_days 计算到期时间（「按天数」模式，0 表示永久有效，expires_at 存 NULL）。
    两种方式最终都只体现在 expires_at 上，所以过期判断与旧的按天数逻辑完全一致。
    """
    normalized = str(code or "").strip().upper()
    if not normalized:
        normalized = _random_unique_code(db)
    code_id = str(uuid4())
    limit = max(int(per_user_max_times or 0), 0)
    fixed_expires_at = normalize_expire_date(expires_at)
    if fixed_expires_at:
        stored_valid_days = 0
        stored_expires_at = fixed_expires_at
    else:
        stored_valid_days = int(valid_days or 0)
        stored_expires_at = _compute_expires_at(stored_valid_days)
    try:
        db.execute(
            """
            INSERT INTO redemption_codes (id, code, amount, usable_count, used_count, per_user_max_times, valid_days, expires_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                code_id,
                normalized,
                round(float(amount), 2),
                int(usable_count),
                limit,
                stored_valid_days,
                stored_expires_at,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"兑换码 {normalized} 已存在") from exc
    return {
        "id": code_id,
        "code": normalized,
        "per_user_max_times": limit,
        "valid_days": stored_valid_days,
        "expires_at": stored_expires_at,
    }


def batch_generate_codes(
    db: sqlite3.Connection,
    count: int,
    amount: float,
    usable_count: int = 1,
    valid_days: int = 0,
    expires_at: str | None = None,
) -> list:
    """批量生成随机兑换码，返回形如 [{id, code}, ...] 的列表。

    【新增功能】有效期同样支持两种互斥方式：expires_at 传了可解析的日期就直接用它
    （并把 valid_days 记为 0），否则按 valid_days 计算，语义与 create_code() 一致。
    """
    amount = round(float(amount), 2)
    fixed_expires_at = normalize_expire_date(expires_at)
    if fixed_expires_at:
        stored_valid_days = 0
        stored_expires_at = fixed_expires_at
    else:
        stored_valid_days = int(valid_days or 0)
        stored_expires_at = _compute_expires_at(stored_valid_days)
    created = []
    # 用 tries 上限避免极端情况下随机码大量碰撞陷入死循环。
    max_attempts = count * 20
    tries = 0
    while len(created) < count and tries < max_attempts:
        tries += 1
        code = generate_code()
        exists = db.execute("SELECT 1 FROM redemption_codes WHERE code = ?", (code,)).fetchone()
        if exists:
            continue
        code_id = str(uuid4())
        db.execute(
            """
            INSERT INTO redemption_codes (id, code, amount, usable_count, used_count, valid_days, expires_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (code_id, code, amount, int(usable_count), stored_valid_days, stored_expires_at),
        )
        created.append({"id": code_id, "code": code})
    db.commit()
    if len(created) < count:
        raise HTTPException(status_code=500, detail="生成兑换码数量不足，请重试")
    return created


def redeem(db: sqlite3.Connection, user, code: str) -> float:
    """用户兑付兑换码：校验 + 入账 + 记日志，返回到账金额。

    流程：
    1. 查询兑换码并按业务规则校验：不存在 / 已过期 / 可用次数已用满 /
       （per_user_max_times > 0 时）该用户已兑换次数达到上限，各自返回带业务错误码的
       中文提示（400，不抛原始异常）。
    2. 在同一个事务里完成三件事，任一失败整体回滚：
       ① 双重校验 + 原子占用一次可用次数：
          - 每用户次数上限（per_user_max_times > 0）：先在 BEGIN IMMEDIATE 写锁内复查
            兑换记录表，该用户已兑换次数 >= 上限就直接拒绝（此时其它写事务都被挡在锁外，
            同一用户的并发重复提交只会有一个走到这里）；
          - 全局总次数：再执行 `UPDATE ... WHERE used_count < usable_count`，
            rowcount != 1 说明并发下已被别人先占用。开启每用户限制时这一重同样必须通过，
            所以两种模式的占用写法完全一致，事务逻辑不变。
       ② 给用户加余额（事务内重新读余额做上限校验，余额上限见 MAX_BALANCE）；
       ③ 写 `redemption_logs`（兑换码 id + 用户 id + 到账金额 + 时间）。
    3. 任何数据库/未预期异常都会 rollback 并转成标准 500 JSON 错误（记日志），
       绝不把堆栈或纯文本 500 抛给前端。
    """
    # 1. 查询 + 业务校验（HTTPException 直接透传，其余异常统一转标准错误）
    try:
        normalized = str(code or "").strip().upper()
        if not normalized:
            raise _business_error(400, "REDEMPTION_CODE_REQUIRED", "请输入兑换码")

        code_row = db.execute("SELECT * FROM redemption_codes WHERE code = ?", (normalized,)).fetchone()
        if code_row is None:
            raise _business_error(400, "REDEMPTION_CODE_NOT_FOUND", "兑换码不存在")

        status = code_status(code_row)
        if status == "expired":
            raise _business_error(400, "REDEMPTION_CODE_EXPIRED", "兑换码已过期")
        if status == "used":
            raise _business_error(400, "REDEMPTION_CODE_USED_UP", "该兑换码可用次数已用完")

        # 【新增功能】每个用户最大兑换次数：这里做一次快速预检以便给出友好报错，
        # 真正的权威判定在下面的写事务内复查兑换记录表（防同一用户并发重复提交）。
        max_times = per_user_max_times_of(code_row)
        if max_times > 0 and count_user_redemptions(db, code_row["id"], user["id"]) >= max_times:
            raise _business_error(400, "REDEMPTION_PER_USER_LIMIT", _per_user_limit_message(max_times))

        amount = round(float(code_row["amount"] or 0), 2)
        usable = max(int(code_row["usable_count"] or 1), 1)
        if amount <= 0:
            raise _business_error(400, "REDEMPTION_CODE_INVALID_AMOUNT", "兑换码面额无效，请联系管理员")
    except HTTPException:
        raise
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.exception("查询兑换码失败：code=%s", code)
        raise _business_error(500, "REDEMPTION_QUERY_FAILED", "兑换失败，请稍后重试") from exc

    # 2. 入账：占用次数 + 加余额 + 写日志，全部在同一个事务内
    try:
        # 先回滚可能残留的隐式事务，回到干净状态，避免显式 BEGIN 报
        # "cannot start a transaction within a transaction"。
        db.rollback()
        # 显式开启写事务（IMMEDIATE 先拿写锁），并发的重复兑付会在锁上串行化，
        # 再由下面的双重校验保证不会超发。
        db.execute("BEGIN IMMEDIATE")

        balance_row = db.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()
        if balance_row is None:
            raise _business_error(404, "USER_NOT_FOUND", "用户不存在")
        if round(float(balance_row["balance"] or 0), 2) + amount > MAX_BALANCE:
            raise _business_error(400, "REDEMPTION_BALANCE_LIMIT", f"兑换后余额不能超过 {MAX_BALANCE} 元")

        # 双重校验的第一重：每用户最大兑换次数（写锁内复查兑换记录表，权威判据）。
        # 必须在占用全局次数之前判定，超限时直接抛出并由外层整体回滚，
        # used_count 与用户余额都不会发生变化。
        if max_times > 0 and count_user_redemptions(db, code_row["id"], user["id"]) >= max_times:
            raise _business_error(400, "REDEMPTION_PER_USER_LIMIT", _per_user_limit_message(max_times))

        # 双重校验的第二重：全局总可用次数（原有逻辑不变，两种模式共用同一条件 UPDATE），
        # 原子占用一次可用次数，条件更新保证并发下不会超发。
        cursor = db.execute(
            "UPDATE redemption_codes SET used_count = used_count + 1 WHERE id = ? AND used_count < ?",
            (code_row["id"], usable),
        )
        if cursor.rowcount != 1:
            raise _business_error(400, "REDEMPTION_CODE_USED_UP", "该兑换码可用次数已用完")

        updated = db.execute(
            "UPDATE users SET balance = ROUND(balance + ?, 2) WHERE id = ?",
            (amount, user["id"]),
        )
        if updated.rowcount != 1:
            raise _business_error(404, "USER_NOT_FOUND", "用户不存在")

        db.execute(
            "INSERT INTO redemption_logs (id, code_id, user_id, amount) VALUES (?, ?, ?, ?)",
            (str(uuid4()), code_row["id"], user["id"], amount),
        )
        db.commit()
    except HTTPException:
        # 业务校验失败（含并发抢占）：整体回滚，兑换码次数与余额都不变。
        db.rollback()
        raise
    except sqlite3.Error as exc:
        db.rollback()
        logger.exception("兑换码入账失败：code=%s user=%s", code, user["id"])
        raise _business_error(500, "REDEMPTION_FAILED", "兑换失败，请稍后重试") from exc
    except Exception as exc:  # noqa: BLE001 - 兜底：任何意外异常都转成标准业务错误
        db.rollback()
        logger.exception("兑换码入账出现未预期异常：code=%s user=%s", code, user["id"])
        raise _business_error(500, "REDEMPTION_SERVER_ERROR", "兑换失败，服务器异常，请稍后重试") from exc

    return amount


def list_codes(db: sqlite3.Connection, limit: int = 20, offset: int = 0, search: str | None = None) -> dict:
    """分页返回兑换码列表（最新在前）。"""
    where = ""
    params: list = []
    if search:
        where = "WHERE code LIKE ?"
        params.append(f"%{search}%")
    total = db.execute(f"SELECT COUNT(*) AS c FROM redemption_codes {where}", params).fetchone()["c"]
    rows = db.execute(
        f"""
        SELECT * FROM redemption_codes
        {where}
        ORDER BY created_at DESC, rowid DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    items = [_serialize_code(db, row) for row in rows]
    return {"items": items, "total": total, "has_more": offset + len(items) < total}


def list_code_logs(db: sqlite3.Connection, code_id: str) -> list:
    """返回某个兑换码的全部兑换日志（最新在前），含用户信息。"""
    rows = db.execute(
        """
        SELECT rl.id, rl.code_id, rl.user_id, rl.amount, rl.created_at,
               u.username, u.real_name
        FROM redemption_logs rl
        LEFT JOIN users u ON u.id = rl.user_id
        WHERE rl.code_id = ?
        ORDER BY rl.created_at DESC, rl.rowid DESC
        """,
        (code_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_code(db: sqlite3.Connection, code_id: str) -> bool:
    """删除一个兑换码及它的兑换日志；返回是否真有删除。"""
    result = db.execute(
        "DELETE FROM redemption_logs WHERE code_id = ?",
        (code_id,),
    )
    deleted = db.execute(
        "DELETE FROM redemption_codes WHERE id = ?",
        (code_id,),
    ).rowcount
    db.commit()
    if result.rowcount or deleted:
        deleted = deleted or result.rowcount
    return bool(deleted)
