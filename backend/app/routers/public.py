import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_db
from ..services.files import effective_max_file_size_mb, effective_max_pages
from ..services.pricing import calculate_files_price_detail, calculate_price_detail, promotion_summary

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
def health():
    return {"status": "ok"}


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
        "printer_name": printer_name,
        "printer_configured": printer is not None,
        "is_support_color": bool(printer["is_support_color"]) if printer else False,
        "is_support_auto_duplex": bool(printer["is_support_auto_duplex"]) if printer else False,
    }


@router.post("/price")
def price(payload: dict, db: sqlite3.Connection = Depends(get_db)):
    copies = int(payload.get("copies", 1))
    double_sided = bool(payload.get("double_sided", False))
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
        # 按份双面：file_settings 中指定的文件用其独立设置，未指定的回退到全局 double_sided。
        # 双面仅作用于该份文档自身正反面，单页文档在计价时自动折算为单面。
        file_settings = payload.get("file_settings")
        duplex_map = {}
        if isinstance(file_settings, list):
            for item in file_settings:
                if isinstance(item, dict) and item.get("file_id"):
                    duplex_map[str(item["file_id"])] = bool(item.get("double_sided", False))
        requested_duplex = {
            item["id"]: duplex_map[item["id"]] if item["id"] in duplex_map else double_sided
            for item in files
        }
        detail = calculate_files_price_detail(db, files, copies, requested_duplex)
    else:
        page_count = int(payload.get("page_count", 0))
        detail = calculate_price_detail(db, page_count, copies, double_sided)
    return detail
