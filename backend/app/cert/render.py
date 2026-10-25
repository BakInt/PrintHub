"""证照生成件图像管线：EXIF 矫正 → 裁剪 → 增强 → 重采样 → A4 合成 → PDF。

- 手动四点裁剪用纯 Pillow（`Image.transform(QUAD, ...)`）实现，不依赖 OpenCV，
  是自动识别失败时的体验下限保障（detect.py 的 OpenCV 只是可选增强）。
- PDF 组装零新增依赖：Pillow 逐页存单页 PDF（resolution=300.0，页尺寸自动为 A4）
  + PyPDF2 合并多页（现有依赖；与主程序打印前 300dpi 光栅化精度一致，打印端不二次降质）。
- 隐私红线：本模块只在调用方给的内存图像对象上工作，不落盘任何原始照片。
"""

import io
from pathlib import Path

from PIL import Image, ImageOps

# 打印分辨率：210mm→2480px、297mm→3508px（px = mm / 25.4 × dpi）。
CERT_DPI = 300.0
# 合成 PDF 内嵌 JPEG 质量。
CERT_JPEG_QUALITY = 92
# 裁剪细框颜色（打印件上的浅灰参考线，非 UI 颜色）。
CUT_GUIDE_GRAY = (200, 200, 200)
CUT_GUIDE_WIDTH_PX = 2


def mm_to_px(mm: float, dpi: float = CERT_DPI) -> int:
    return int(round(mm / 25.4 * dpi))


def load_image_bytes(data: bytes) -> Image.Image:
    """字节流 → RGB 图像（EXIF 方向矫正）。损坏/不支持格式抛 ValueError（中文提示）。"""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ValueError("图片无法识别，请使用 JPG/PNG 格式重新拍摄") from exc
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _validate_quad(quad: list) -> list[list[float]]:
    """校验手动四点：4 个 [x,y]、归一化 0–1；返回同序（TL,TR,BR,BL）浮点列表。"""
    if (
        not isinstance(quad, list)
        or len(quad) != 4
        or any(
            not isinstance(p, (list, tuple)) or len(p) != 2 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p)
            for p in quad
        )
    ):
        raise ValueError("裁剪区域坐标无效，请重新框选")
    return [[float(p[0]), float(p[1])] for p in quad]


def perspective_crop(image: Image.Image, quad_norm: list) -> Image.Image:
    """按归一化四点（顺序 TL,TR,BR,BL，顺时针）透视矫正裁剪。

    Pillow 的 QUAD 变换把「源四边形」映射到整张输出图，系数顺序为
    左上、左下、右下、右上，这里从输入的顺时针序换算过来。
    """
    points = _validate_quad(quad_norm)
    width, height = image.size
    src = [(p[0] * width, p[1] * height) for p in points]
    tl, tr, br, bl = src
    top = (tl[0] - tr[0]) ** 2 + (tl[1] - tr[1]) ** 2
    bottom = (bl[0] - br[0]) ** 2 + (bl[1] - br[1]) ** 2
    left = (tl[0] - bl[0]) ** 2 + (tl[1] - bl[1]) ** 2
    right = (tr[0] - br[0]) ** 2 + (tr[1] - br[1]) ** 2
    out_w = max(int(round(((top ** 0.5) + (bottom ** 0.5)) / 2)), 8)
    out_h = max(int(round(((left ** 0.5) + (right ** 0.5)) / 2)), 8)
    # QUAD 系数序：左上、左下、右下、右上。
    coeffs = (tl[0], tl[1], bl[0], bl[1], br[0], br[1], tr[0], tr[1])
    return image.transform((out_w, out_h), Image.Transform.QUAD, coeffs, resample=Image.Resampling.BILINEAR)


def enhance_image(image: Image.Image) -> Image.Image:
    """尽力而为的可读性增强（对比度拉伸，失败不阻断）。首版不做去阴影类重处理。"""
    try:
        return ImageOps.autocontrast(image, cutoff=1)
    except Exception:
        return image


def resize_for_slot(image: Image.Image, target_px: tuple[int, int], fit: str = "exact") -> tuple[Image.Image, tuple[int, int]]:
    """重采样到槽位目标像素。

    exact：精确缩放到目标尺寸（裁剪已保证长宽比，用于 1:1 卡片）；
    contain：在目标包围框内按原比例缩放居中（用于比例不定的整页照片），返回实际贴放尺寸。
    返回 (图像, 实际贴放尺寸)。
    """
    tw, th = target_px
    if fit == "contain":
        scale = min(tw / image.width, th / image.height)
        nw = max(int(round(image.width * scale)), 1)
        nh = max(int(round(image.height * scale)), 1)
        return image.resize((nw, nh), Image.Resampling.LANCZOS), (nw, nh)
    return image.resize((tw, th), Image.Resampling.LANCZOS), (tw, th)


def compose_page(layout: dict, slot_images: dict[str, Image.Image]) -> Image.Image:
    """按 layout_json 把各槽位图像合成一页白底位图（毫米坐标换算像素贴放）。"""
    page_w = mm_to_px(layout["page_size_mm"][0])
    page_h = mm_to_px(layout["page_size_mm"][1])
    page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    draw_guides = bool(layout.get("cut_guides"))
    placements: list[tuple[int, int, int, int]] = []
    for slot in layout.get("slots", []):
        image = slot_images.get(slot["key"])
        if image is None:
            continue
        box_px = (mm_to_px(slot["size_mm"][0]), mm_to_px(slot["size_mm"][1]))
        placed, actual = resize_for_slot(image, box_px, slot.get("fit", "exact"))
        box_x = mm_to_px(slot["position_mm"][0])
        box_y = mm_to_px(slot["position_mm"][1])
        paste_x = box_x + (box_px[0] - actual[0]) // 2
        paste_y = box_y + (box_px[1] - actual[1]) // 2
        page.paste(placed, (paste_x, paste_y))
        placements.append((paste_x, paste_y, paste_x + actual[0], paste_y + actual[1]))
    if draw_guides:
        from PIL import ImageDraw

        draw = ImageDraw.Draw(page)
        for rect in placements:
            draw.rectangle(rect, outline=CUT_GUIDE_GRAY, width=CUT_GUIDE_WIDTH_PX)
    return page


def _page_pdf_bytes(page: Image.Image) -> bytes:
    buffer = io.BytesIO()
    page.save(buffer, format="PDF", resolution=CERT_DPI, quality=CERT_JPEG_QUALITY)
    return buffer.getvalue()


def render_pdf_bytes(layout: dict, slot_images: dict[str, Image.Image]) -> tuple[bytes, int]:
    """合成整本 PDF。P0 模板均为单页（全部槽位排入同一页 A4）。

    返回 (pdf 字节, 页数)。多页预留：逐页存单页 PDF 后用 PyPDF2 合并（零新增依赖）。
    """
    page = compose_page(layout, slot_images)
    return _page_pdf_bytes(page), 1


def render_pdf_file(layout: dict, slot_images: dict[str, Image.Image], output: Path) -> int:
    """合成 PDF 并写入目标路径，返回页数。"""
    pdf_bytes, pages = render_pdf_bytes(layout, slot_images)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf_bytes)
    return pages


def render_pdf_multi(pages_layouts: list[dict], pages_slot_images: list[dict[str, Image.Image]], output: Path) -> int:
    """多页合成（预留）：Pillow 逐页存单页 PDF + PyPDF2 合并。"""
    import tempfile

    from PyPDF2 import PdfMerger

    merger = PdfMerger()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        parts = []
        for index, (layout, slot_images) in enumerate(zip(pages_layouts, pages_slot_images)):
            part = tmp_dir / f"page-{index}.pdf"
            page = compose_page(layout, slot_images)
            part.write_bytes(_page_pdf_bytes(page))
            parts.append(part)
        for part in parts:
            merger.append(str(part))
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as handle:
            merger.write(handle)
        merger.close()
    return len(pages_layouts)
