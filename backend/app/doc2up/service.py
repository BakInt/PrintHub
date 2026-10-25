"""两页合一（2-up）合成逻辑：光栅化源 PDF → 每页旋转 90° → 两页拼一页 A4 → 300dpi PDF。

版式规则（用户需求）：
- 页面方向转换：竖向文档页 → 旋转成横向，摆到 A4 **竖版**上下两栏（每栏 210×148.5mm）；
  横向文档页 → 旋转成竖向，摆到 A4 **横版**左右两栏（每栏 148.5×210mm）。
  两种情况缩放比都是 1/√2 ≈ 70.7%，是 2-up 的自然几何。
- 一页 A4 打两页文档内容；页数为奇数时最后一页单独占半版（另半版留白）。
- 版式方向由**首页**决定，全部页统一旋转同一方向（混合方向文档中不匹配的页
  会横向躺放，与实体打印机 2-up 行为一致）。
- 半版交界处画一条浅灰裁切线，方便对半裁开。

内存安全：源 PDF 按 10 页一块光栅化（pdf2image/pdftoppm，现有依赖），合成页经
生成器逐张喂给 Pillow 的多页 PDF 保存，峰值内存只与块大小相关（≈10 页位图）。
"""

import json
import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageDraw

from ..config import get_settings

logger = logging.getLogger(__name__)

DOC2UP_DPI = 300.0
DOC2UP_JPEG_QUALITY = 92
CUT_LINE_GRAY = (200, 200, 200)
CUT_LINE_WIDTH_PX = 2
# 每块光栅化的源页数：控制峰值内存（10 页 300dpi RGB ≈ 260MB）。
RASTERIZE_CHUNK = 10

# cert_docs 登记行状态：与证照生成件的 'active' 区分——保留期清理线程与证照每日
# 生成上限都只统计 status='active'，doc2up 产物不受证照保留期约束（行为与登记前
# 一致）；计价钩子（cert/pricing.py）据登记行在模板设置了独立单价时按
# 单价 × 版面数 × 份数 重算。
DOC2UP_REGISTRY_STATUS = "doc2up"
# cert_docs.expires_at 非空约束的占位值（status != 'active' 永不进清理查询）。
DOC2UP_REGISTRY_EXPIRES_AT = "2999-01-01 00:00:00"

# A4 @300dpi：短边 210mm→2480px，长边 297mm→3508px。
A4_SHORT_PX = round(210 / 25.4 * DOC2UP_DPI)
A4_LONG_PX = round(297 / 25.4 * DOC2UP_DPI)


def rotate_page(image: Image.Image) -> Image.Image:
    """统一旋转 90°（顺时针）：竖版页转成横向、横版页转成竖向。"""
    return image.transpose(Image.Transpose.ROTATE_270)


def is_portrait(image: Image.Image) -> bool:
    return image.width <= image.height


def _fit_into(image: Image.Image, box_w: int, box_h: int) -> tuple[Image.Image, int, int]:
    """contain 缩放（保持比例）并在包围框内居中，返回 (图, 贴放 x, y)。"""
    scale = min(box_w / image.width, box_h / image.height)
    new_w = max(int(round(image.width * scale)), 1)
    new_h = max(int(round(image.height * scale)), 1)
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return resized, (box_w - new_w) // 2, (box_h - new_h) // 2


def compose_sheet(page_a: Image.Image, page_b: Image.Image | None, vertical: bool) -> Image.Image:
    """把（已旋转的）两页拼到一页 A4 上。

    vertical=True：A4 竖版上下两栏（竖向文档旋转后）；False：A4 横版左右两栏
    （横向文档旋转后）。page_b 为 None 时下半版/右半版留白。半版交界画浅灰裁切线。
    """
    if vertical:
        sheet_w, sheet_h = A4_SHORT_PX, A4_LONG_PX
        box_w, box_h = sheet_w, sheet_h // 2
    else:
        sheet_w, sheet_h = A4_LONG_PX, A4_SHORT_PX
        box_w, box_h = sheet_w // 2, sheet_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    a_img, a_x, a_y = _fit_into(page_a, box_w, box_h)
    sheet.paste(a_img, (a_x, a_y))
    if page_b is not None:
        b_img, b_x, b_y = _fit_into(page_b, box_w, box_h)
        if vertical:
            sheet.paste(b_img, (b_x, box_h + b_y))
        else:
            sheet.paste(b_img, (box_w + b_x, b_y))
    draw = ImageDraw.Draw(sheet)
    if vertical:
        draw.line([(0, box_h), (sheet_w, box_h)], fill=CUT_LINE_GRAY, width=CUT_LINE_WIDTH_PX)
    else:
        draw.line([(box_w, 0), (box_w, sheet_h)], fill=CUT_LINE_GRAY, width=CUT_LINE_WIDTH_PX)
    return sheet


def sheets_from_pages(pages):
    """页序列 → A4 版面序列（生成器）。

    版式方向由首页决定：竖向源 → A4 竖版上下两栏；横向源 → A4 横版左右两栏。
    """
    vertical: bool | None = None
    buffer: list[Image.Image] = []
    for page in pages:
        if vertical is None:
            vertical = is_portrait(page)
        buffer.append(rotate_page(page))
        if len(buffer) == 2:
            yield compose_sheet(buffer[0], buffer[1], vertical)
            buffer = []
    if buffer:
        yield compose_sheet(buffer[0], None, vertical)


def rasterize_pages(pdf_path: Path, dpi: float = DOC2UP_DPI):
    """按块光栅化源 PDF（pdf2image → pdftoppm，容器内可用；本地开发机无 poppler 时
    由测试注入假实现）。生成器产出 RGB 页位图。"""
    from pdf2image import convert_from_path
    from PyPDF2 import PdfReader

    total = len(PdfReader(str(pdf_path)).pages)
    for start in range(0, total, RASTERIZE_CHUNK):
        end = min(start + RASTERIZE_CHUNK, total)
        for image in convert_from_path(str(pdf_path), dpi=dpi, first_page=start + 1, last_page=end):
            yield image.convert("RGB")


def sheet_coverage(sheet: Image.Image) -> float:
    """单页黑色覆盖率（灰度 <128 像素占比，与主程序安全/计价口径一致）。"""
    histogram = sheet.convert("L").histogram()
    dark = sum(histogram[:128])
    total = sheet.width * sheet.height
    return round(dark / total * 100, 2) if total else 0.0


def create_doc2up(db: sqlite3.Connection, user: sqlite3.Row, file_id: str) -> dict:
    """把源文件（已转换好的 PDF）合成为两页合一打印件并入库。"""
    row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 归属校验（安全修复 V-07 同级）：自己的文件或匿名访客上传的文件。
    owner_id = row["user_id"]
    if owner_id is not None and owner_id != user["id"] and not bool(user["is_admin"]):
        raise HTTPException(status_code=404, detail="文件不存在")
    if not bool(row["is_safe"]):
        raise HTTPException(status_code=400, detail="源文件未通过安全检测，无法合成")
    if int(row["page_count"] or 0) < 1:
        raise HTTPException(status_code=400, detail="源文件没有可打印的页面")

    source_pdf = Path(row["pdf_path"])
    if not source_pdf.exists():
        raise HTTPException(status_code=404, detail="源文件已过期或被清理，请重新上传")

    pages = rasterize_pages(source_pdf)
    coverages: list[float] = []

    def track_sheets():
        for sheet in sheets_from_pages(pages):
            coverages.append(sheet_coverage(sheet))
            yield sheet

    sheet_iter = track_sheets()

    new_file_id = str(uuid4())
    output_path = Path(get_settings().upload_dir) / new_file_id / "converted.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    first_sheet = next(sheet_iter, None)
    if first_sheet is None:
        raise HTTPException(status_code=400, detail="源文件没有可打印的页面")
    first_sheet.save(
        str(output_path),
        format="PDF",
        resolution=DOC2UP_DPI,
        quality=DOC2UP_JPEG_QUALITY,
        save_all=True,
        append_images=sheet_iter,
    )

    sheet_count = len(coverages)
    average_coverage = round(sum(coverages) / sheet_count, 2) if coverages else 0.0
    original_name = Path(row["original_name"]).stem or "文档"
    display_name = f"{original_name}-两页合一.pdf"
    db.execute(
        """
        INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, page_coverages, is_safe, status, needs_rasterize)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'ready', 0)
        """,
        (
            new_file_id,
            user["id"],
            display_name,
            str(output_path),
            str(output_path),
            sheet_count,
            output_path.stat().st_size,
            average_coverage,
            json.dumps(coverages),
        ),
    )
    # 登记进 cert_docs（status='doc2up'）：后台「证件照管理」设置的独立单价经
    # 证照计价钩子对合成件生效；status 区分使其不计入证照保留期清理与每日上限。
    db.execute(
        """
        INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, used_manual_crop, status, expires_at)
        VALUES (?, ?, 'doc2up', ?, ?, 0, ?, ?)
        """,
        (str(uuid4()), user["id"], new_file_id, sheet_count, DOC2UP_REGISTRY_STATUS, DOC2UP_REGISTRY_EXPIRES_AT),
    )
    db.commit()
    logger.info(
        "两页合一合成成功 file=%s source=%s user=%s sheets=%s",
        new_file_id,
        file_id,
        user["id"],
        sheet_count,
    )
    return {
        "file_id": new_file_id,
        "source_file_id": file_id,
        "page_count": sheet_count,
        "preview_url": f"/api/files/{new_file_id}/preview",
    }
