"""PDF 后处理：拍平图像软遮罩（SMask），确保打印链路不丢图。

背景（此系统的化学式打印消失根因）
--------------------------------------
LibreOffice 把 docx/Office 文档转 PDF 时，会给带透明的图像（尤其是老式 OLE 公式、
MathType/公式3.0 的 WMF/EMF 预览图，以及带 alpha 的插图）附加一层 /SMask 软遮罩来
表达透明。桌面打印机驱动、浏览器 PDF.js 能正确合成这层遮罩，所以「预览、直连打印」
都正常；但本系统走 CUPS → pdftoraster/Ghostscript 光栅化打印，这条管线对 /SMask
支持很差，会把带软遮罩的整块图像丢弃——表现为「预览正常、上传打印后化学式整块消失」。

修复策略
--------
在 LibreOffice 转出 PDF 之后、入库之前，遍历每页的图像 XObject，把带 /SMask 的图像
用 Pillow 按遮罩合成到纯白背景、丢弃 alpha，回写为不透明 JPEG，并删除 /SMask 引用。
这样公式图变成普通不透明图片，任何打印 RIP 都能稳定光栅化；文字矢量层完全不动，
仍可搜索/复制、清晰度不变。对 OLE 公式、WMF/EMF、透明 PNG 插图等一切来源通用，
且不改动原始文档内容与排版。

该后处理是「尽力而为」：任何异常都安全降级为返回原 PDF，绝不因后处理失败阻断上传。
"""
from __future__ import annotations

import io
from pathlib import Path


def _iter_image_xobjects(page):
    """产出页面里所有图像 XObject 的 (容器字典, 名称) —— 供原地修改。"""
    resources = page.get("/Resources")
    if not resources:
        return
    resources = resources.get_object()
    xobjects = resources.get("/XObject")
    if not xobjects:
        return
    xobjects = xobjects.get_object()
    for name in list(xobjects.keys()):
        try:
            xobj = xobjects[name].get_object()
        except Exception:
            continue
        if xobj.get("/Subtype") == "/Image":
            yield xobjects, name


def _compose_to_white(image) -> "object":
    """把可能带 alpha 的 PIL 图像合成到纯白背景并返回 RGB（无透明）。"""
    from PIL import Image

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return image.convert("RGB")


def _decode_image_stream(img_obj):
    """尽力把一个 PDF 图像/遮罩流解码为 PIL.Image；无法解码返回 None。

    覆盖最常见的两类编码：/DCTDecode(JPEG) 与 /FlateDecode(原始像素)。其余罕见滤镜
    （CCITT、JPX 等）返回 None，交由上层跳过——安全降级，绝不抛错阻断上传。
    """
    from PIL import Image

    try:
        width = int(img_obj["/Width"])
        height = int(img_obj["/Height"])
    except Exception:
        return None
    filt = img_obj.get("/Filter")
    filt = filt[0] if isinstance(filt, list) and filt else filt
    color = str(img_obj.get("/ColorSpace", "/DeviceRGB"))
    try:
        data = img_obj.get_data()
    except Exception:
        try:
            data = img_obj._data
        except Exception:
            return None
    try:
        if str(filt) == "/DCTDecode":
            return Image.open(io.BytesIO(data)).convert("RGB")
        # 其余按已解码原始像素处理（PyPDF2 get_data 会自动做 Flate 解压）
        if "Gray" in color or str(img_obj.get("/ColorSpace")) == "/DeviceGray":
            mode, expect = "L", width * height
        else:
            mode, expect = "RGB", width * height * 3
        if len(data) < expect:
            return None
        return Image.frombytes(mode, (width, height), data[:expect])
    except Exception:
        return None


def _manual_compose(xobj):
    """当 PyPDF2 内部解码失败时，手动读取图像与其 /SMask 并用 Pillow 合成到白底。"""
    base = _decode_image_stream(xobj)
    if base is None:
        return None
    smask = xobj.get("/SMask")
    if smask is not None:
        alpha = _decode_image_stream(smask.get_object())
        if alpha is not None:
            alpha = alpha.convert("L")
            if alpha.size != base.size:
                alpha = alpha.resize(base.size)
            base = base.convert("RGBA")
            base.putalpha(alpha)
    return _compose_to_white(base)


def flatten_pdf_smask(pdf_path: Path) -> bool:
    """就地拍平 pdf_path 中所有带 /SMask 的图像；成功改写返回 True，无改动/失败返回 False。

    仅当确有带 /SMask 的图像被合成时才重写文件，避免对普通 PDF 做无谓改动。
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter
        from PyPDF2.filters import _xobj_to_image
        from PyPDF2.generic import (
            ArrayObject,
            DecodedStreamObject,
            NameObject,
            NumberObject,
        )
        from PIL import Image
    except Exception:
        return False

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return False

    flattened = 0
    for page in reader.pages:
        try:
            for container, name in _iter_image_xobjects(page):
                xobj = container[name].get_object()
                if "/SMask" not in xobj:
                    continue
                composed = None
                # 首选 PyPDF2 内部解码：它会把 SMask 一并合成到可见图像。
                try:
                    _ext, data = _xobj_to_image(xobj)
                    composed = _compose_to_white(Image.open(io.BytesIO(data)))
                except Exception:
                    composed = None
                # 回退：内部解码失败时手动读原图+遮罩用 Pillow 合成，覆盖更多边界。
                if composed is None:
                    composed = _manual_compose(xobj)
                if composed is None:
                    continue
                # 用不透明 JPEG 重编码回写（质量 95，公式黑白细线足够清晰）
                buf = io.BytesIO()
                composed.save(buf, format="JPEG", quality=95)
                stream = container[name].get_object()
                stream._data = buf.getvalue()
                stream[NameObject("/Filter")] = NameObject("/DCTDecode")
                stream[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
                stream[NameObject("/BitsPerComponent")] = NumberObject(8)
                stream[NameObject("/Width")] = NumberObject(composed.width)
                stream[NameObject("/Height")] = NumberObject(composed.height)
                # 去掉软遮罩与可能残留的透明相关键，避免 RIP 再按透明处理
                for key in ("/SMask", "/Mask", "/Decode"):
                    if key in stream:
                        del stream[NameObject(key)]
                flattened += 1
        except Exception:
            # 单页异常不影响其余页
            continue

    if flattened == 0:
        return False

    try:
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        tmp_out = pdf_path.with_suffix(".flattened.pdf")
        with open(tmp_out, "wb") as fh:
            writer.write(fh)
        tmp_out.replace(pdf_path)
        return True
    except Exception:
        return False


def _darken_faint_content(image, white_keep: int = 235, black_at: int = 150):
    """加深偏灰的深色内容（如公式位图的灰色笔画），同时保护纸张白底不变脏。

    背景：老式 OLE/WMF 公式渲染出来的位图，其笔画往往是中等灰度（实测样本试卷公式笔画
    灰度铺满 80-180 区间，占全部深色像素约 1/3），而正文是纯黑。打印机会把中灰如实打成
    浅灰，于是「公式颜色很淡、正文正常」。这里对每页应用一条分段色调映射（LUT）：
      - 亮于 white_keep 的像素判为背景/留白，保持不变，避免整页发灰；
      - 暗于 black_at 的像素（正文 + 大部分公式笔画）直接压到纯黑，笔画变实；
      - 两者之间平滑过渡，避免出现硬边锯齿。
    仅加深不改变版式；对纯文本页几乎无副作用（正文本就 < black_at，映射后仍是黑）。

    默认参数 white_keep=235 / black_at=150 经样本试卷 300dpi 光栅化后实测标定：公式笔画
    由中灰压至纯黑、与正文一致，白底保持洁净，且 150-235 的平滑过渡保留了抗锯齿边缘，
    避免笔画发糊或加粗。
    """
    from PIL import Image

    # 构造 256 级灰度查找表：可直接用 Image.point 对 RGB 各通道套用。
    lut = []
    span = max(white_keep - black_at, 1)
    for v in range(256):
        if v >= white_keep:
            out = v  # 背景/接近白：保持
        elif v <= black_at:
            out = 0  # 深色与中灰：压黑
        else:
            # black_at..white_keep 之间：线性拉伸到 0..white_keep，平滑衔接
            out = int((v - black_at) / span * white_keep)
        lut.append(out)

    rgb = image.convert("RGB")
    # 三个通道套同一张灰度 LUT（内容近似灰阶，等效整体加深且不引入偏色）
    return rgb.point(lut * 3)


def rasterize_pdf_for_print(pdf_path, dpi: int = 300):
    """把 pdf_path 每页光栅化成不透明位图，重组为「纯图像 PDF」，返回新文件路径。

    为什么打印链路需要这一步（此系统化学式打印消失的根治手段）
    ----------------------------------------------------------------
    本系统打印是用 `lp` 把 PDF 提交给（通常是远端的）CUPS 打印服务器，最终由那台机器
    上的光栅化引擎（Ghostscript / cups-filters）把 PDF 转成打印机点阵。老式 OLE 公式、
    WMF/EMF 预览图、带透明的图元在不同版本的 RIP 上表现差异很大——桌面驱动/浏览器
    PDF.js 能正确合成，但远端 RIP 可能把整块公式图丢弃，于是「网页预览正常、直连电脑
    打印正常，一上传本系统打印公式就整块消失」。这一环在远端机器上，我们无法控制其软件版本。

    根治办法就是：**在提交打印前，先在本系统内用与远端无关的本地光栅器（poppler 的
    pdftoppm）把每一页都渲染成一张不透明大图，再重组成 PDF 送打印。** 这样打印端收到
    的每页只是一张普通图片，远端 RIP 只需画一张不透明位图即可，彻底消除 SMask/字体/
    图元的一切兼容性变量——效果等同于「电脑直连打印」（本地驱动同样是先整页光栅化）。

    约定与降级
    ----------
    - 仅用于打印提交，不改动入库/预览用的原始矢量 PDF（预览仍清晰可选可搜索）。
    - 页数、页序与原 PDF 完全一致，双面翻页语义不变。
    - 300 dpi 保证正文与公式细线打印清晰；纯位图会失去文字可复制性、体积增大，这是
      「稳定可打印」的必要代价，且只作用于打印副本。
    - 「尽力而为」：缺 pdftoppm / Pillow、或任何异常都返回 None，调用方回退为直接打印
      原 PDF，绝不因光栅化失败阻断打印。
    """
    import shutil
    import subprocess
    import tempfile

    # 调用方（dispatch_order_print → print_pdf）传入的可能是数据库里读出的字符串路径，
    # 这里统一规范成 Path，避免对 str 调用 .exists()/.with_name() 触发 AttributeError。
    pdf_path = Path(pdf_path)

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    if not pdf_path.exists():
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="print-raster-"))
    try:
        prefix = tmp_dir / "page"
        # -png 输出不带 alpha 的 RGB PNG；-r 控制分辨率。pdftoppm 是 poppler 自带的本地
        # 光栅器，与远端 CUPS 的 RIP 完全无关，可预测地产出不透明位图。
        result = subprocess.run(
            [pdftoppm, "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return None
        # 按文件名里的页码数字排序，避免个别 poppler 版本零填充位数不同导致 page-10 排在
        # page-2 之前而错乱页序。
        import re

        def _page_index(p: Path) -> int:
            m = re.search(r"-(\d+)\.png$", p.name)
            return int(m.group(1)) if m else 0

        pages = sorted(tmp_dir.glob("page-*.png"), key=_page_index)
        if not pages:
            return None
        images = []
        for page_png in pages:
            with Image.open(page_png) as img:
                # 强制不透明 RGB（去除任何 alpha），再加深偏灰的公式笔画，改善打印浓淡。
                images.append(_darken_faint_content(img))
        out_path = pdf_path.with_name(pdf_path.stem + ".print.pdf")
        images[0].save(
            out_path,
            "PDF",
            save_all=True,
            append_images=images[1:],
            resolution=float(dpi),
        )
        return out_path if out_path.exists() else None
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
