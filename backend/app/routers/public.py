import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..database import get_db
from ..routers.orders import ensure_files_accessible
from ..routers.deps import optional_user
from ..services.files import effective_max_file_size_mb, effective_max_pages
from ..services.pricing import calculate_files_price_detail, calculate_price_detail, promotion_summary
from ..services.site_settings import favicon_response_payload, public_site_settings

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/site-settings")
def site_settings(db: sqlite3.Connection = Depends(get_db)):
    """公开站点配置：网页标题、favicon 地址、ICP 备案号。

    前端应用启动时拉取一次并全局应用（document.title、<link rel="icon">、底部备案条），
    登录页/前台/后台共用；字段留空表示使用前端默认值。
    """
    return public_site_settings(db)


@router.get("/site/favicon")
def site_favicon(db: sqlite3.Connection = Depends(get_db)):
    """输出后台上传的站点图标字节流（未设置时 404，前端回退默认图标）。

    地址带版本戳（?v=N），这里允许长缓存；重新上传后版本号变化即击穿缓存。
    """
    payload = favicon_response_payload(db)
    if payload is None:
        raise HTTPException(status_code=404, detail="未设置自定义图标")
    content, media_type = payload
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/ready")
def ready(db: sqlite3.Connection = Depends(get_db)):
    db.execute("SELECT 1").fetchone()
    return {"status": "ready"}


@router.get("/promotions")
def promotions(db: sqlite3.Connection = Depends(get_db)):
    return promotion_summary(db)


@router.get("/limits")
def limits(db: sqlite3.Connection = Depends(get_db)):
    """公开上传限制，供首页文案显示。

    取值与后端真实校验完全一致：数据库设置优先，环境变量仅作缺省兜底
    （见 `effective_max_file_size_mb` / `effective_max_pages`）。
    """
    return {
        "max_file_size_mb": effective_max_file_size_mb(db),
        "max_pages": effective_max_pages(db),
    }


@router.get("/print-options")
def print_options(db: sqlite3.Connection = Depends(get_db)):
    """【新增功能】打印能力选项：当前默认打印机是否支持「彩色打印」「自动双面打印」。

    首页打印操作页用它决定是否展示这两个选项——完全由后台「打印机管理」里为打印机配置的
    `is_support_color` / `is_support_auto_duplex` 驱动，前端不做任何硬编码判断。

    默认打印机未配置、或数据库里查不到该打印机的配置记录时，两项都返回 False
    （前端隐藏对应选项，等价于原有的打印行为，不影响未配置过的老部署）。

    安全修复（V-10.1）：该接口无鉴权，不再向匿名访客返回具体打印机名称
    （`printer_name` 字段已移除，前端本来也只消费两个能力布尔值）。
    """
    row = db.execute("SELECT value FROM settings WHERE key = 'default_printer'").fetchone()
    printer_name = (row["value"] if row else "") or ""
    printer = None
    if printer_name:
        printer = db.execute(
            "SELECT name, is_support_color, is_support_auto_duplex FROM printers WHERE name = ?",
            (printer_name,),
        ).fetchone()
    return {
        "printer_configured": printer is not None,
        "is_support_color": bool(printer["is_support_color"]) if printer else False,
        "is_support_auto_duplex": bool(printer["is_support_auto_duplex"]) if printer else False,
    }


@router.post("/price")
def price(payload: dict, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row | None = Depends(optional_user)):
    copies = int(payload.get("copies", 1))
    file_ids = payload.get("file_ids")
    if file_ids:
        if not isinstance(file_ids, list):
            raise HTTPException(status_code=400, detail="文件列表格式错误")
        if len(file_ids) != len(set(file_ids)):
            raise HTTPException(status_code=400, detail="文件列表存在重复项")
        placeholders = ",".join("?" for _ in file_ids)
        files = db.execute(f"SELECT * FROM files WHERE id IN ({placeholders})", file_ids).fetchall()
        if len(files) != len(set(file_ids)):
            raise HTTPException(status_code=404, detail="部分文件不存在")
        unsafe = [item for item in files if not bool(item["is_safe"])]
        if unsafe:
            raise HTTPException(status_code=400, detail="存在未通过安全检测的文件")
        # 安全修复（V-07）：计价同样禁止引用他人上传的文件。
        ensure_files_accessible(files, user)
        # 【新增功能】合并双面打印：True 时把全部文档合并为一个双面打印流计价——
        # 不同文档的页面按顺序连续排到纸张正反面（两份单页文档可打在同一张纸正反面）。
        merge_duplex = bool(payload.get("merge_duplex", False))
        detail = calculate_files_price_detail(db, files, copies, merge_duplex)
    else:
        page_count = int(payload.get("page_count", 0))
        double_sided = bool(payload.get("double_sided", False))
        detail = calculate_price_detail(db, page_count, copies, double_sided)
    return detail
