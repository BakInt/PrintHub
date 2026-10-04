import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..database import get_db
from ..services.files import convert_to_pdf, display_filename, inspect_ole_formula_risk, page_count, save_upload
from ..services.safety import calculate_black_coverage_details, create_alert, safety_result
from .deps import optional_user

router = APIRouter(prefix="/api", tags=["files"])


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
    db.execute(
        """
        INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, page_coverages, is_safe, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)
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
        ),
    )
    if not is_safe and warning:
        create_alert(db, file_id, warning)
    if formula_warning:
        create_alert(db, file_id, formula_warning)
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
            "converted": Path(pdf_path) != Path(stored_path),
            "preview_url": f"/api/files/{file_id}/preview",
        },
    }


@router.get("/files/{file_id}/preview")
def preview_file(file_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT pdf_path, original_name FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not Path(row["pdf_path"]).exists():
        raise HTTPException(status_code=404, detail="预览文件不存在，可能已被管理员清理")
    filename = quote(f"{Path(row['original_name']).stem}.pdf")
    return FileResponse(
        row["pdf_path"],
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.post("/check-safety")
def check_safety(payload: dict, db: sqlite3.Connection = Depends(get_db)):
    file_id = payload.get("file_id")
    row = db.execute("SELECT is_safe, black_coverage, error_message FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {
        "safe": bool(row["is_safe"]),
        "black_coverage": row["black_coverage"],
        "warning_message": row["error_message"],
    }
