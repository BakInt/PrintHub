"""站点设置服务：全站共用的站点级配置（网页标题 / 网站图标 / 备案号 / 登录锁定策略）。

存储复用 SQLite 的 `settings` 表（与计价、促销等业务设置同一张 key-value 表、同一套
「数据库优先，代码/config.json 兜底」约定）。管理员在后台「站点设置」页修改，前端在
应用启动时拉取 `GET /api/site-settings` 并全局应用（标题、favicon、备案条），保存后
立即生效并随数据库持久化。

登录锁定阈值/时长历史上是 config.json 部署级键（`login_lock_threshold` /
`login_lock_seconds`）；开放到后台配置后改为数据库设置（建库时从 config.json 播种，
之后以后台保存值为准，缺键/非法值时回退 config.json，兼容未迁移的旧库）。

网站图标不做文件落盘：上传的 .ico/.png 以 data URI 存进 `settings` 表（favicon 体积
小、随数据库整体备份恢复，且避开 uploads/ 缓存清理），由 `GET /api/site/favicon`
公开接口输出字节流，前端拿到的地址带版本戳（`?v=N`）以击穿浏览器缓存。
"""

import base64
import binascii
import sqlite3

from fastapi import HTTPException

from ..config import get_settings

SITE_TITLE_KEY = "site_title"
SITE_FAVICON_MODE_KEY = "site_favicon_mode"  # none | url | upload
SITE_FAVICON_URL_KEY = "site_favicon_url"  # mode=url 时的外链地址
SITE_FAVICON_DATA_KEY = "site_favicon_data"  # mode=upload 时的 data:image/...;base64,...
SITE_FAVICON_VERSION_KEY = "site_favicon_version"  # 整数版本戳，写进 favicon 地址防缓存
SITE_ICP_KEY = "site_icp_number"
LOGIN_LOCK_THRESHOLD_KEY = "login_lock_threshold"
LOGIN_LOCK_MINUTES_KEY = "login_lock_minutes"

FAVICON_MAX_BYTES = 200 * 1024
FAVICON_MEDIA_TYPES = {"png": "image/png", "ico": "image/x-icon"}
# PNG 与 ICO 的文件头魔数：扩展名只做提示，实际类型以文件头判定，避免改扩展名绕过。
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ICO_SIGNATURE = b"\x00\x00\x01\x00"


def _setting_value(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return default
    return str(row["value"])


def _write_setting(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _int_setting(db: sqlite3.Connection, key: str, fallback: int) -> int:
    """读整数设置：缺键、非整数或小于 1 一律回退默认值，绝不让脏数据打断登录。"""
    raw = _setting_value(db, key, "")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value >= 1 else fallback


def login_lock_threshold_of(db: sqlite3.Connection) -> int:
    """连续失败多少次锁定账号：数据库设置优先，缺省回退 config.json 部署级键。"""
    return _int_setting(db, LOGIN_LOCK_THRESHOLD_KEY, max(1, get_settings().login_lock_threshold))


def login_lock_seconds_of(db: sqlite3.Connection) -> int:
    """锁定时长（秒）：数据库按「分钟」存（后台表单单位），config.json 兜底值按秒换算。"""
    minutes = _int_setting(db, LOGIN_LOCK_MINUTES_KEY, max(1, get_settings().login_lock_seconds // 60))
    return minutes * 60


def favicon_url_of(db: sqlite3.Connection) -> str:
    """生效的 favicon 地址：upload → 内部输出接口（带版本戳）；url → 外链；未设置 → 空串。"""
    mode = _setting_value(db, SITE_FAVICON_MODE_KEY, "none")
    if mode == "upload":
        version = _setting_value(db, SITE_FAVICON_VERSION_KEY, "1")
        return f"/api/site/favicon?v={version}"
    if mode == "url":
        return _setting_value(db, SITE_FAVICON_URL_KEY, "")
    return ""


def public_site_settings(db: sqlite3.Connection) -> dict:
    """公开站点配置（无需登录）：前台/后台应用启动时拉取并全局应用。"""
    return {
        "site_title": _setting_value(db, SITE_TITLE_KEY, ""),
        "site_favicon_url": favicon_url_of(db),
        "site_icp_number": _setting_value(db, SITE_ICP_KEY, ""),
    }


def admin_site_settings(db: sqlite3.Connection) -> dict:
    """后台「站点设置」页回显：图标外链原值与生效地址分开返回（`site_favicon_effective_url`
    是真正应用到站点的地址，upload 模式下是内部输出接口；`site_favicon_url` 仅作表单回显）。"""
    return {
        "site_title": _setting_value(db, SITE_TITLE_KEY, ""),
        "site_favicon_mode": _setting_value(db, SITE_FAVICON_MODE_KEY, "none"),
        "site_favicon_url": _setting_value(db, SITE_FAVICON_URL_KEY, ""),
        "site_favicon_effective_url": favicon_url_of(db),
        "site_icp_number": _setting_value(db, SITE_ICP_KEY, ""),
        "login_lock_threshold": login_lock_threshold_of(db),
        "login_lock_minutes": login_lock_seconds_of(db) // 60,
    }


def save_site_settings(db: sqlite3.Connection, data: dict) -> dict:
    """保存站点设置（只更新传入的键），返回保存后的完整后台回显。

    约定：`site_favicon_mode=upload` 只能由上传接口写入（PUT 里只允许 none/url），
    避免出现「选了上传模式但库里没有任何图标数据」的悬空状态。
    """
    if "site_title" in data:
        _write_setting(db, SITE_TITLE_KEY, str(data["site_title"] or "").strip())
    if "site_icp_number" in data:
        _write_setting(db, SITE_ICP_KEY, str(data["site_icp_number"] or "").strip())
    if "login_lock_threshold" in data:
        _write_setting(db, LOGIN_LOCK_THRESHOLD_KEY, str(max(1, int(data["login_lock_threshold"]))))
    if "login_lock_minutes" in data:
        _write_setting(db, LOGIN_LOCK_MINUTES_KEY, str(max(1, int(data["login_lock_minutes"]))))

    mode = data.get("site_favicon_mode")
    if mode is not None:
        if mode == "upload":
            raise HTTPException(status_code=400, detail="请通过上传图标接口设置图标，不能直接保存 upload 模式")
        if mode == "url":
            url = str(data.get("site_favicon_url") or _setting_value(db, SITE_FAVICON_URL_KEY, "")).strip()
            if not url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="图标 URL 必须以 http:// 或 https:// 开头")
            _write_setting(db, SITE_FAVICON_URL_KEY, url)
        _write_setting(db, SITE_FAVICON_MODE_KEY, mode)
    elif data.get("site_favicon_url") is not None:
        # 只改 URL 不切模式：仅在当前已是 url 模式时生效，避免静默改变模式语义。
        if _setting_value(db, SITE_FAVICON_MODE_KEY, "none") == "url":
            url = str(data["site_favicon_url"]).strip()
            if not url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="图标 URL 必须以 http:// 或 https:// 开头")
            _write_setting(db, SITE_FAVICON_URL_KEY, url)

    db.commit()
    return admin_site_settings(db)


def _sniff_favicon(content: bytes) -> str:
    """按文件头判定图标类型，返回 media type；不认识的一律拒绝。"""
    if content.startswith(_PNG_SIGNATURE):
        return FAVICON_MEDIA_TYPES["png"]
    if content.startswith(_ICO_SIGNATURE):
        return FAVICON_MEDIA_TYPES["ico"]
    raise HTTPException(status_code=400, detail="图标内容必须是有效的 .ico 或 .png 图片")


def save_uploaded_favicon(db: sqlite3.Connection, filename: str, content: bytes) -> dict:
    """上传站点图标：校验大小与文件头后以 data URI 入库，版本戳 +1 并切换为 upload 模式。"""
    if not content:
        raise HTTPException(status_code=400, detail="图标文件为空")
    if len(content) > FAVICON_MAX_BYTES:
        raise HTTPException(status_code=400, detail="图标文件不能超过 200KB")
    suffix = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if suffix not in FAVICON_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 .ico / .png 图标文件")
    media_type = _sniff_favicon(content)
    encoded = base64.b64encode(content).decode("ascii")
    version = int(_setting_value(db, SITE_FAVICON_VERSION_KEY, "0") or 0) + 1
    _write_setting(db, SITE_FAVICON_DATA_KEY, f"data:{media_type};base64,{encoded}")
    _write_setting(db, SITE_FAVICON_VERSION_KEY, str(version))
    _write_setting(db, SITE_FAVICON_MODE_KEY, "upload")
    db.commit()
    return admin_site_settings(db)


def favicon_response_payload(db: sqlite3.Connection) -> tuple[bytes, str] | None:
    """`GET /api/site/favicon` 的输出：未设置返回 None（调用方 404）。"""
    data_uri = _setting_value(db, SITE_FAVICON_DATA_KEY, "")
    if not data_uri or not data_uri.startswith("data:") or "," not in data_uri:
        return None
    header, encoded = data_uri.split(",", 1)
    media_type = header[5:].split(";", 1)[0] or FAVICON_MEDIA_TYPES["png"]
    try:
        return base64.b64decode(encoded, validate=True), media_type
    except (binascii.Error, ValueError):
        return None
