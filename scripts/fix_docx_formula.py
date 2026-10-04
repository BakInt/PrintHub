#!/usr/bin/env python3
"""docx 公式健康诊断与批量修复工具。

用途
----
老式 Word/WPS 文档里的化学方程式、离子符号、数学公式常以 OLE 对象（MathType /
Microsoft 公式 3.0，ProgID=Equation.*/DSMT4）嵌入。这类对象在没有 MathType 的
环境（Linux 服务器、别人电脑、在线转换器）无法被“激活”，能否显示完全取决于文档
里那张 WMF/EMF 矢量预览图能否被下游工具渲染。

三种典型链路的表现：
- docx → PDF（本项目 LibreOffice + libwmf 转换）：LibreOffice 能直接光栅化 WMF/EMF
  预览图，公式可正常打印，**无需本脚本**。
- docx → Markdown/HTML（pandoc / mammoth 等）：这些工具不认识 WMF，会原样输出
  ![](media/imageX.wmf) 占位符，公式丢失。
- 换台没有 MathType 的电脑用 Word 打开：Word 尝试激活 OLE 失败，公式可能变空白。

本脚本把每个公式的 WMF/EMF 预览图渲染成 PNG 回填，并（默认）把 <w:object> 的 OLE
嵌入“降级”为纯图片：去掉 o:ole="t"、移除 <o:OLEObject> 节点、删除 oleObject*.bin
及其关系。降级后任何工具都只当它是一张普通图片，稳定显示、100% 可打印，且不再依赖
MathType。文字内容与排版位置保持不变。

功能
----
1. --check     只诊断：列出每个 docx 的 OLE 公式数、预览图数、格式和风险等级。
2. （默认）修复：把 WMF/EMF 预览图转 PNG 写回、OLE 降级为图片，生成 *_fixed.docx。

依赖
----
- 渲染 WMF/EMF -> PNG 需要 LibreOffice（soffice），本项目镜像已内置；
  也可用 ImageMagick(convert/magick)，脚本会自动探测可用转换器。
- 仅用 Python 标准库读写 docx（zip）。

用法
----
    python fix_docx_formula.py --check a.docx b.docx           # 仅诊断
    python fix_docx_formula.py 试卷.docx                        # 修复，生成 试卷_fixed.docx
    python fix_docx_formula.py --outdir out/ *.docx            # 批量修复到指定目录
    python fix_docx_formula.py --dpi 200 试卷.docx             # 提高 ImageMagick 渲染分辨率
    python fix_docx_formula.py --keep-ole 试卷.docx            # 只转 PNG，不降级 OLE(不推荐)

约束
----
不改动文档文字内容与排版结构，仅把公式预览图替换为可被任何工具识别的 PNG。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# document.xml / 关系文件里，指向公式预览图的图元格式
VECTOR_PREVIEW_EXT = (".wmf", ".emf")
RASTER_PREVIEW_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg")
OLE_MARKERS = ("/embeddings/oleobject", "/embeddings/microsoft_equation")


def _find_soffice() -> str | None:
    for name in ("libreoffice", "soffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _find_imagemagick() -> str | None:
    for name in ("convert", "magick"):
        path = shutil.which(name)
        if path:
            return path
    return None


def inspect(docx: Path) -> dict:
    """返回 docx 公式健康信息：ole 数、矢量预览图、位图预览图、风险等级。"""
    info = {
        "path": docx,
        "ole": 0,
        "vector_preview": [],
        "raster_preview": [],
        "risk": "ok",
    }
    try:
        with zipfile.ZipFile(docx) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        info["risk"] = f"error: {exc}"
        return info
    info["ole"] = sum(1 for n in names if any(m in n.lower() for m in OLE_MARKERS))
    info["vector_preview"] = [n for n in names if "/media/" in n and n.lower().endswith(VECTOR_PREVIEW_EXT)]
    info["raster_preview"] = [n for n in names if "/media/" in n and n.lower().endswith(RASTER_PREVIEW_EXT)]
    if info["ole"] > 0 and not info["vector_preview"] and not info["raster_preview"]:
        # 有公式对象但完全没有预览图：任何无 MathType 环境都无法还原，需人工另存。
        info["risk"] = "high"
    elif info["ole"] > 0 and info["vector_preview"]:
        # 有 WMF/EMF 预览图：PDF 打印链路可用；转 Markdown/HTML 或跨电脑建议先修复。
        info["risk"] = "convertible"
    return info


def _trim_and_measure(png_path: Path) -> tuple[bytes, tuple[int, int]] | None:
    """用 Pillow 裁掉 PNG 四周白边并返回 (裁剪后 PNG 字节, (宽px, 高px))。

    soffice 把小小的 WMF 渲染成整页 A4 PNG，公式只占中间一小块、四周全是白边。
    不裁剪就会因尺寸巨大而在文档里错位/看不见。Pillow 不可用时返回 None，调用方回退。

    关键：输出**不透明白底 RGB** PNG（丢弃 alpha 通道）。若保留透明通道，
    LibreOffice 导出 PDF 会为每张公式图额外生成一层 SMask 软遮罩。网页 PDF.js
    能正确合成透明，但 CUPS 打印端的光栅化管线（pdftoraster/Ghostscript）对
    SMask 支持差，会把公式整块丢弃——表现为“预览正常但打印时化学式消失”。
    合成到纯白背景并去 alpha，公式即为普通不透明图片，任何打印链路都稳定可见。
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    with Image.open(png_path) as img:
        # 先按可见内容（合成白底后）计算裁剪框，避免透明区域干扰白边判定
        flat = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat.paste(rgba, mask=rgba.split()[-1])  # 用 alpha 作蒙版合成到白底
        else:
            flat.paste(img.convert("RGB"))
        bg = Image.new("RGB", flat.size, (255, 255, 255))
        diff = ImageChops.difference(flat, bg)
        bbox = diff.getbbox()
        if not bbox:
            return None  # 整张纯白，判定渲染失败
        # 留 2px 边距，避免贴边裁掉笔画
        left, top, right, bottom = bbox
        left = max(0, left - 2)
        top = max(0, top - 2)
        right = min(flat.width, right + 2)
        bottom = min(flat.height, bottom + 2)
        cropped = flat.crop((left, top, right, bottom))  # 从扁平白底图裁剪，无 alpha
    import io

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue(), (cropped.width, cropped.height)


def _render_previews_to_png(vector_files: dict[str, bytes], dpi: int) -> dict[str, tuple[bytes, tuple[int, int] | None]]:
    """把 {内部路径: WMF/EMF 字节} 批量渲染为 {内部路径(.png): (PNG字节, 像素尺寸或None)}。

    优先用 LibreOffice 渲染（保真、无字体缺失），再用 Pillow 裁掉整页白边并测量像素尺寸；
    裁剪尺寸用于生成 DrawingML 的显示大小。ImageMagick 作为无 soffice 时的后备。
    """
    soffice = _find_soffice()
    magick = _find_imagemagick()
    if not soffice and not magick:
        raise RuntimeError("需要 LibreOffice(soffice) 或 ImageMagick(convert) 来渲染 WMF/EMF 预览图。")

    rendered: dict[str, tuple[bytes, tuple[int, int] | None]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for index, (member, data) in enumerate(vector_files.items()):
            src = tmp_dir / f"eq_{index}{Path(member).suffix.lower()}"
            src.write_bytes(data)
            png = src.with_suffix(".png")
            ok = False
            if soffice:
                profile = tempfile.mkdtemp(prefix="lo-fix-")
                try:
                    subprocess.run(
                        [
                            soffice, "--headless",
                            f"-env:UserInstallation=file://{profile}",
                            "--convert-to", "png", "--outdir", str(tmp_dir), str(src),
                        ],
                        capture_output=True, timeout=120, check=False,
                    )
                    ok = png.exists() and png.stat().st_size > 0
                finally:
                    shutil.rmtree(profile, ignore_errors=True)
            if not ok and magick:
                subprocess.run(
                    [magick, "-density", str(dpi), "-trim", "+repage", str(src), str(png)],
                    capture_output=True, timeout=120, check=False,
                )
                ok = png.exists() and png.stat().st_size > 0
            if not ok:
                continue
            out_name = str(Path(member).with_suffix(".png"))
            trimmed = _trim_and_measure(png)
            if trimmed:
                rendered[out_name] = trimmed  # (裁剪后字节, 像素尺寸)
            else:
                rendered[out_name] = (png.read_bytes(), None)  # 无 Pillow，整页图，尺寸走 VML style
    return rendered


def _emu_from_style(style: str) -> tuple[int, int]:
    """从 VML style（如 'height:15.8pt;width:51.9pt;'）解析尺寸并转为 EMU。

    1pt = 12700 EMU；1cm = 360000 EMU；1in = 914400 EMU；1px≈9525 EMU。
    解析失败时回退到一个稳妥的小尺寸（约 12pt 高、40pt 宽），避免图片塌成 0。
    """
    unit_emu = {"pt": 12700, "cm": 360000, "mm": 36000, "in": 914400, "px": 9525}
    dims = {}
    for key in ("width", "height"):
        m = re.search(rf"{key}\s*:\s*([0-9.]+)\s*([a-z%]*)", style, re.I)
        if m:
            val = float(m.group(1))
            unit = (m.group(2) or "pt").lower()
            dims[key] = int(val * unit_emu.get(unit, 12700))
    width = dims.get("width") or int(40 * 12700)
    height = dims.get("height") or int(12 * 12700)
    return width, height


def _demote_ole_to_picture(
    document_xml: str,
    rid_size_emu: dict[str, tuple[int, int]] | None = None,
    doc_id_start: int = 900000,
) -> str:
    """把 document.xml 里 <w:object> 的 OLE 嵌入替换为标准 DrawingML 内联图片。

    <w:object> 表示“内嵌 OLE 对象”，无 MathType 环境（LibreOffice、别人电脑的 Word）
    会尝试激活其中的 OLE 二进制（Equation.DSMT4），激活失败即显示空白。DrawingML
    (<w:drawing><wp:inline>...<a:blip>) 是现代 Word/WPS 原生的“内联图片”格式，
    LibreOffice、Word、pandoc、WPS 全部原生支持，稳定显示且不再依赖 MathType。

    对每个 <w:object>...</w:object>：读取内部 <v:imagedata r:id> 的关系 id，优先用
    rid_size_emu 给出的裁剪后真实尺寸（EMU），否则回退到 <v:shape style> 的原始尺寸，
    生成等价尺寸的 DrawingML 内联图片，整体替换 <w:object>。文字与排版位置不受影响。
    """
    counter = [doc_id_start]
    rid_size_emu = rid_size_emu or {}

    def _convert(match: re.Match) -> str:
        block = match.group(0)
        rid_m = re.search(r"<v:imagedata[^>]*r:id=\"([^\"]+)\"", block)
        if not rid_m:
            # 无预览图引用，无法转图片；保守起见原样保留，交由后续人工处理。
            return block
        rid = rid_m.group(1)
        # 显示尺寸优先用文档作者设定的 VML style（排版意图，单位 pt），最准确；
        # 仅当 style 缺失时才回退到裁剪后 PNG 的像素尺寸(EMU)。
        style_m = re.search(r"<v:shape[^>]*style=\"([^\"]*)\"", block)
        if style_m and ("width" in style_m.group(1) or "height" in style_m.group(1)):
            cx, cy = _emu_from_style(style_m.group(1))
        elif rid in rid_size_emu:
            cx, cy = rid_size_emu[rid]
        else:
            cx, cy = _emu_from_style("")
        counter[0] += 1
        did = counter[0]
        return (
            "<w:drawing>"
            f"<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
            f"<wp:extent cx=\"{cx}\" cy=\"{cy}\"/>"
            "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
            f"<wp:docPr id=\"{did}\" name=\"Formula{did}\"/>"
            "<wp:cNvGraphicFramePr>"
            "<a:graphicFrameLocks xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" noChangeAspect=\"1\"/>"
            "</wp:cNvGraphicFramePr>"
            "<a:graphic xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">"
            "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
            "<pic:pic xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
            "<pic:nvPicPr>"
            f"<pic:cNvPr id=\"{did}\" name=\"Formula{did}\"/>"
            "<pic:cNvPicPr/>"
            "</pic:nvPicPr>"
            "<pic:blipFill>"
            f"<a:blip r:embed=\"{rid}\"/>"
            "<a:stretch><a:fillRect/></a:stretch>"
            "</pic:blipFill>"
            "<pic:spPr>"
            f"<a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{cx}\" cy=\"{cy}\"/></a:xfrm>"
            "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
            "</pic:spPr>"
            "</pic:pic>"
            "</a:graphicData>"
            "</a:graphic>"
            "</wp:inline>"
            "</w:drawing>"
        )

    return re.sub(r"<w:object\b[^>]*>.*?</w:object>", _convert, document_xml, flags=re.S)


def _strip_ole_relationships(rels_xml: str) -> tuple[str, set[str]]:
    """从关系 XML 删除 oleObject 关系，返回 (新 XML, 被删的 .bin Target 集合)。"""
    removed: set[str] = set()

    def _drop(match: re.Match) -> str:
        tag = match.group(0)
        if "oleObject" in tag or "/oleObject" in tag.lower():
            tgt = re.search(r'Target="([^"]+)"', tag)
            if tgt:
                removed.add(tgt.group(1))
            return ""
        return tag

    new_xml = re.sub(r"<Relationship\b[^>]*/>", _drop, rels_xml)
    return new_xml, removed


def fix(docx: Path, outdir: Path | None, dpi: int, keep_ole: bool = False) -> Path | None:
    """把 docx 的 WMF/EMF 公式预览图转 PNG 回填并（默认）OLE 降级，生成 *_fixed.docx。"""
    info = inspect(docx)
    if not info["vector_preview"]:
        return None  # 无矢量预览图可修（要么无公式，要么已是位图/高风险）

    with zipfile.ZipFile(docx) as archive:
        vector_bytes = {m: archive.read(m) for m in info["vector_preview"]}
        all_entries = {i.filename: archive.read(i.filename) for i in archive.infolist()}
        orig_rels = archive.read("word/_rels/document.xml.rels").decode("utf-8", "replace")

    rendered = _render_previews_to_png(vector_bytes, dpi)
    if not rendered:
        raise RuntimeError(f"预览图渲染失败：{docx.name}")

    # WMF/EMF 预览图 -> PNG 的路径映射（media/image2.wmf -> media/image2.png）
    replaced_names = {old: str(Path(old).with_suffix(".png")) for old in vector_bytes}

    # 构建 rid -> DrawingML 显示尺寸(EMU)：rels 里 rId 指向 media/imageX.wmf，其裁剪后
    # 的 PNG 有真实像素尺寸，按 96 DPI 换算成 EMU（1px = 9525 EMU）。供 OLE 降级使用。
    rid_size_emu: dict[str, tuple[int, int]] = {}
    for m in re.finditer(r"<Relationship\b[^>]*/>", orig_rels):
        tag = m.group(0)
        rid = re.search(r'Id="([^"]+)"', tag)
        tgt = re.search(r'Target="([^"]+)"', tag)
        if not (rid and tgt and "/image" in tag):
            continue
        wmf_member = "word/" + tgt.group(1)
        png_member = str(Path(wmf_member).with_suffix(".png"))
        size = rendered.get(png_member, (b"", None))[1]
        if size:
            rid_size_emu[rid.group(1)] = (size[0] * 9525, size[1] * 9525)

    # 若降级 OLE，先算出要删除的 oleObject 关系与 .bin 文件
    dropped_bins: set[str] = set()
    if not keep_ole:
        rels_name = "word/_rels/document.xml.rels"
        if rels_name in all_entries:
            rels_text = all_entries[rels_name].decode("utf-8", "replace")
            rels_text, targets = _strip_ole_relationships(rels_text)
            all_entries[rels_name] = rels_text.encode("utf-8")
            # Target 形如 "embeddings/oleObject1.bin"，转成包内绝对路径 word/embeddings/...
            for tgt in targets:
                dropped_bins.add(str((Path("word") / tgt).as_posix()))

    new_entries: dict[str, bytes] = {}
    for name, data in all_entries.items():
        if name in dropped_bins:
            continue  # 删除 OLE 二进制，公式已由 PNG 图片承载
        if name in replaced_names:
            new_name = replaced_names[name]
            png_bytes = rendered.get(new_name, (data, None))[0]
            new_entries[new_name] = png_bytes
        elif name == "word/document.xml":
            text = data.decode("utf-8", "replace")
            for old, new in replaced_names.items():
                text = text.replace(Path(old).name, Path(new).name)
            if not keep_ole:
                text = _demote_ole_to_picture(text, rid_size_emu)
            new_entries[name] = text.encode("utf-8")
        elif name.endswith((".xml", ".rels")):
            text = data.decode("utf-8", "replace")
            for old, new in replaced_names.items():
                text = text.replace(Path(old).name, Path(new).name)
            if name == "[Content_Types].xml" and 'Extension="png"' not in text:
                text = text.replace(
                    "</Types>",
                    '<Default Extension="png" ContentType="image/png"/></Types>',
                )
            new_entries[name] = text.encode("utf-8")
        else:
            new_entries[name] = data

    target_dir = outdir or docx.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{docx.stem}_fixed.docx"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in new_entries.items():
            archive.writestr(name, data)
    return out_path


def _print_report(info: dict) -> None:
    name = info["path"].name
    risk = info["risk"]
    labels = {
        "ok": "无公式或无需处理",
        "convertible": "含公式(有矢量预览图)：PDF 打印可用；跨电脑/转 Markdown/HTML 建议先修复",
        "high": "高风险：有公式对象但无任何预览图，需用 Word/WPS 另存 PDF",
    }
    label = labels.get(risk, risk)
    print(f"[{name}]")
    print(f"  OLE 公式对象 : {info['ole']}")
    print(f"  矢量预览(WMF/EMF): {len(info['vector_preview'])}")
    print(f"  位图预览(PNG等) : {len(info['raster_preview'])}")
    print(f"  评估 : {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docx 公式健康诊断与批量修复工具")
    parser.add_argument("files", nargs="+", help="一个或多个 .docx 文件")
    parser.add_argument("--check", action="store_true", help="只诊断，不修复")
    parser.add_argument("--outdir", type=Path, default=None, help="修复输出目录（默认与源文件同目录）")
    parser.add_argument("--dpi", type=int, default=150, help="ImageMagick 渲染 DPI（LibreOffice 走默认矢量渲染）")
    parser.add_argument(
        "--keep-ole", action="store_true",
        help="只把 WMF/EMF 转 PNG，不把 OLE 降级为图片（不推荐，LibreOffice 可能仍空白）",
    )
    args = parser.parse_args(argv)

    exit_code = 0
    for raw in args.files:
        docx = Path(raw)
        if docx.suffix.lower() != ".docx" or not docx.exists():
            print(f"跳过（非 .docx 或不存在）: {raw}", file=sys.stderr)
            exit_code = 1
            continue
        info = inspect(docx)
        _print_report(info)
        if args.check:
            continue
        if info["risk"] == "high":
            print("  -> 无法自动修复：请在 Word/WPS 中打开后另存为 PDF 再使用。")
            continue
        if not info["vector_preview"]:
            print("  -> 无需修复。")
            continue
        try:
            out = fix(docx, args.outdir, args.dpi, keep_ole=args.keep_ole)
            print(f"  -> 已修复: {out}")
        except Exception as exc:  # noqa: BLE001 - 工具脚本，向用户直报原因
            print(f"  -> 修复失败: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
