import json
import logging
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..database import get_db
from ..services.files import (
    IMAGE_EXTENSIONS,
    OFFICE_EXTENSIONS,
    audit_converted_fonts,
    convert_to_pdf,
    display_filename,
    inspect_ole_formula_risk,
    page_count,
    save_upload,
)
from ..services.pdf_postprocess import pdf_has_image_masks
from ..services.safety import calculate_black_coverage_details, create_alert, safety_result
from .deps import optional_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["files"])


def ensure_file_readable(row: sqlite3.Row, user: sqlite3.Row | None) -> None:
    """安全修复（V-07）：文件只能被其属主（或管理员）读取。

    匿名访客上传的文件（user_id 为空）保持公开可读——访客打印流程的预览与
    安全检测轮询依赖它；已归属登录用户的文件，其他人访问一律 404（与不存在
    同响应，不泄露他人 file_id 的存在性）。
    """
    owner_id = row["user_id"]
    if owner_id is None:
        return
    if user is None or (not bool(user["is_admin"]) and owner_id != user["id"]):
        raise HTTPException(status_code=404, detail="文件不存在")


@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row | None = Depends(optional_user),
):
    original_name = display_filename(file.filename)
    file_id, stored_path, file_size = save_upload(file, db)
    # 探测老式 OLE 公式（MathType/公式3.0）是否缺少可渲染预览图；缺失则公式打印会丢失。
    formula_risk = inspect_ole_formula_risk(stored_path)
    formula_warning = None
    if formula_risk.get("at_risk"):
        formula_warning = (
            "文档包含公式对象但缺少可打印的预览图，公式可能无法正确打印。"
            "建议用 Word/WPS 打开后另存为 PDF 再上传，或将公式改为文本/图片。"
        )
    try:
        pdf_path = convert_to_pdf(stored_path)
        pages = page_count(pdf_path, db)
        coverage, page_coverages = calculate_black_coverage_details(pdf_path)
        is_safe, warning = safety_result(coverage, db)
    except HTTPException as exc:
        db.execute(
            """
            INSERT INTO files (id, user_id, original_name, stored_path, file_size, status, error_message, is_safe)
            VALUES (?, ?, ?, ?, ?, 'failed', ?, 0)
            """,
            (file_id, user["id"] if user else None, original_name, str(stored_path), file_size, exc.detail),
        )
        db.commit()
        raise
    except Exception as exc:
        # 安全修复（V-10.2）：畸形图片/损坏文档此前会抛未处理异常变成 500，
        # 这里统一转成 400 业务错误，真实原因进日志。
        logger.exception("文件转换/检测失败：%s", original_name)
        db.execute(
            """
            INSERT INTO files (id, user_id, original_name, stored_path, file_size, status, error_message, is_safe)
            VALUES (?, ?, ?, ?, ?, 'failed', ?, 0)
            """,
            (file_id, user["id"] if user else None, original_name, str(stored_path), file_size, "文件无法解析，请确认文件未损坏后重试"),
        )
        db.commit()
        raise HTTPException(status_code=400, detail="文件无法解析，请确认文件未损坏后重试") from exc
    # 【性能修复】条件光栅化标记：Office 转换件（公式/图元兼容性风险）与含 SMask/Mask
    # 遮罩的 PDF（远端 RIP 易丢图）打印前需整页光栅化；图片转换件与纯净 PDF 直接提交
    # 原文件，省掉每页 300dpi 光栅化耗时并保留文字矢量。旧数据缺列默认 1，行为不回退。
    source_suffix = stored_path.suffix.lower()
    if source_suffix in OFFICE_EXTENSIONS:
        needs_rasterize = 1
    elif source_suffix in IMAGE_EXTENSIONS:
        needs_rasterize = 0
    else:
        needs_rasterize = 1 if pdf_has_image_masks(pdf_path) else 0
    # 【乱码修复】转换后字体自检：pdffonts 查未嵌入字体；比对文档请求字体与容器已装
    # 字体，缺失的写告警供管理员补装。缺 pdffonts/fc-list（开发机）或异常时安全降级。
    font_embed_warning, font_missing_warning = audit_converted_fonts(pdf_path, stored_path)
    db.execute(
        """
        INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, page_coverages, is_safe, status, error_message, needs_rasterize)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
        """,
        (
            file_id,
            user["id"] if user else None,
            original_name,
            str(stored_path),
            str(pdf_path),
            pages,
            file_size,
            coverage,
            json.dumps(page_coverages),
            1 if is_safe else 0,
            warning,
            needs_rasterize,
        ),
    )
    if not is_safe and warning:
        create_alert(db, file_id, warning)
    if formula_warning:
        create_alert(db, file_id, formula_warning)
    if font_embed_warning:
        create_alert(db, file_id, font_embed_warning)
    if font_missing_warning:
        create_alert(db, file_id, font_missing_warning)
    db.commit()
    return {
        "success": True,
        "data": {
            "file_id": file_id,
            "file_name": original_name,
            "page_count": pages,
            "file_size": file_size,
            "black_coverage": coverage,
            "safe": is_safe,
            "warning_message": warning,
            "formula_warning": formula_warning,
            "font_warning": font_embed_warning,
            "missing_fonts_warning": font_missing_warning,
            "converted": Path(pdf_path) != Path(stored_path),
            "preview_url": f"/api/files/{file_id}/preview",
        },
    }


@router.get("/files/{file_id}/preview")
def preview_file(
    file_id: str,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row | None = Depends(optional_user),
):
    row = db.execute("SELECT user_id, pdf_path, original_name FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 安全修复（V-07）：预览同样做属主校验（匿名文件保持公开，见 ensure_file_readable）。
    ensure_file_readable(row, user)
    if not Path(row["pdf_path"]).exists():
        raise HTTPException(status_code=404, detail="预览文件不存在，可能已被管理员清理")
    filename = quote(f"{Path(row['original_name']).stem}.pdf")
    return FileResponse(
        row["pdf_path"],
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.post("/check-safety")
def check_safety(
    payload: dict,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row | None = Depends(optional_user),
):
    file_id = payload.get("file_id")
    row = db.execute("SELECT user_id, is_safe, black_coverage, error_message FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 安全修复（V-07）：安全检测结果同样按属主校验。
    ensure_file_readable(row, user)
    return {
        "safe": bool(row["is_safe"]),
        "black_coverage": row["black_coverage"],
        "warning_message": row["error_message"],
    }
