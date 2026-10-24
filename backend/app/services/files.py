import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from PyPDF2 import PdfReader

from ..config import get_settings
from .pdf_postprocess import flatten_pdf_smask
from .pricing import get_numeric_setting


ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}

# 公式预览图可被 LibreOffice 矢量渲染的图元格式；只有这些格式在无 MathType 环境仍能打印。
RENDERABLE_PREVIEW_EXTENSIONS = (".wmf", ".emf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".tif", ".tiff")


def inspect_ole_formula_risk(source: Path) -> dict:
    """探测 Office 文档中的 OLE 公式（MathType/公式3.0）是否带有可渲染预览图。

    背景：老式 OLE 公式（ProgID=Equation.*/DSMT4）以二进制对象嵌入，服务器无 MathType
    无法激活渲染；但 Word/WPS 通常同时保存一张 WMF/EMF 矢量预览图，LibreOffice 能直接
    渲染这张预览图，公式即可正常打印。若某文档只有 OLE 二进制而缺预览图，公式打印会丢失。

    返回 {ole_objects, preview_images, at_risk}；非 zip/docx 或读取失败时安全降级为无风险。
    """
    result = {"ole_objects": 0, "preview_images": 0, "at_risk": False}
    if source.suffix.lower() not in {".docx", ".pptx", ".xlsx"}:
        # 仅新式 OOXML 是 zip，能安全内省；老 .doc/.ppt/.xls 交给 LibreOffice 处理，不在此探测。
        return result
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            ole_objects = sum(1 for n in names if "/embeddings/oleObject" in n or "/embeddings/Microsoft_Equation" in n)
            preview_images = sum(
                1 for n in names if "/media/" in n and n.lower().endswith(RENDERABLE_PREVIEW_EXTENSIONS)
            )
    except (zipfile.BadZipFile, OSError):
        return result
    result["ole_objects"] = ole_objects
    result["preview_images"] = preview_images
    # 有 OLE 公式对象、却完全没有任何可渲染预览图时，判定为高风险（公式将无法打印）。
    result["at_risk"] = ole_objects > 0 and preview_images == 0
    return result


def display_filename(filename: str | None) -> str:
    cleaned = (filename or "document").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned or "document"


def validate_file_signature(path: Path, suffix: str) -> None:
    with path.open("rb") as handle:
        header = handle.read(8)
    signatures = {
        ".pdf": (b"%PDF",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        ".ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        ".pptx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    }
    if not any(header.startswith(signature) for signature in signatures.get(suffix, ())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容与扩展名不匹配")


def effective_max_file_size_mb(db: sqlite3.Connection | None = None) -> int:
    """文件大小限制以数据库设置（后台「系统设置」可改）为准，环境变量仅作缺省兜底。"""
    default = int(get_settings().max_file_size_mb)
    if db is None:
        return default
    try:
        return int(get_numeric_setting(db, "max_file_size_mb", default))
    except (TypeError, ValueError):
        return default


def effective_max_pages(db: sqlite3.Connection | None = None) -> int:
    """最大页数限制以数据库设置（后台「系统设置」可改）为准，环境变量仅作缺省兜底。"""
    default = int(get_settings().max_pages)
    if db is None:
        return default
    try:
        return int(get_numeric_setting(db, "max_pages", default))
    except (TypeError, ValueError):
        return default


def save_upload(upload: UploadFile, db: sqlite3.Connection | None = None) -> tuple[str, Path, float]:
    settings = get_settings()
    suffix = Path(display_filename(upload.filename)).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的文件格式")
    file_id = str(uuid4())
    target_dir = settings.upload_dir / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original{suffix}"
    max_bytes = effective_max_file_size_mb(db) * 1024 * 1024
    total = 0
    with target.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过大小限制")
            output.write(chunk)
    if total == 0:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件不能为空")
    try:
        validate_file_signature(target, suffix)
    except HTTPException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return file_id, target, round(total / 1024 / 1024, 2)


def convert_to_pdf(source: Path) -> Path:
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return source
    output_dir = source.parent
    if suffix in IMAGE_EXTENSIONS:
        from PIL import Image

        pdf_path = output_dir / "converted.pdf"
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.save(pdf_path, "PDF")
        return pdf_path
    if suffix in OFFICE_EXTENSIONS:
        libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
        if libreoffice is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="服务器未安装 LibreOffice，无法转换 Office 文档")
        profile_dir = tempfile.mkdtemp(prefix="lo-profile-")
        # 使用带 PDF 导出参数的过滤器，强制把所有用到的字体（含 fontconfig 替换后的字体）
        # 完整嵌入/子集嵌入到 PDF 中。这样打印端(lp/CUPS)只需按 PDF 内嵌字形渲染，
        # 不依赖打印机或 CUPS 是否认识中文、化学式下标、数学/图案符号，从根本上避免乱码。
        #   EmbedStandardFonts=true 连标准 14 字体也一并嵌入，杜绝下游替换
        #   UseTaggedPDF=true       生成带结构信息的 PDF，兼容性更好
        #   SelectPdfVersion=17     PDF 1.7，透明对象与字体子集兼容性更好（低版本 LO
        #                             不识别该值会整体转换失败，因此下面有逐级降级链）
        def _pdf_filter(version: str) -> str:
            return (
                "pdf:writer_pdf_Export:"
                '{"EmbedStandardFonts":{"type":"boolean","value":"true"},'
                '"UseTaggedPDF":{"type":"boolean","value":"true"},'
                '"SelectPdfVersion":{"type":"long","value":"' + version + '"}}'
            )

        # 逐级降级：PDF1.7 参数版 → PDF1.4 参数版 → 无参数默认导出。「转换成功」优先于
        # 「参数最优」；全部失败时以第一级的错误信息返回 422。三级共享 180 秒总预算，
        # 避免最坏情况把上传请求拖到 3×180 秒。
        attempts = [_pdf_filter("17"), _pdf_filter("0"), "pdf:writer_pdf_Export"]
        env = {
            **os.environ,
            "HOME": str(output_dir),
            "LANG": "zh_CN.UTF-8",
            "LC_ALL": "zh_CN.UTF-8",
        }
        try:
            first_error: str | None = None
            produced: Path | None = None
            deadline = time.monotonic() + 180
            for index, convert_target in enumerate(attempts):
                remaining = max(20, int(deadline - time.monotonic()))
                command = [
                    libreoffice,
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    "--nodefault",
                    f"-env:UserInstallation=file://{profile_dir}",
                    "--convert-to",
                    convert_target,
                    "--outdir",
                    str(output_dir),
                    str(source),
                ]
                result = subprocess.run(command, capture_output=True, text=True, timeout=remaining, check=False, env=env)
                produced = output_dir / f"{source.stem}.pdf"
                if result.returncode == 0 and produced.exists():
                    break
                message = (result.stderr or result.stdout or "LibreOffice 转换失败").strip()
                if first_error is None:
                    first_error = message
                produced = None
            if produced is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=first_error or "LibreOffice 转换失败")
            target = output_dir / "converted.pdf"
            produced.replace(target)
            # 拍平图像软遮罩(SMask)：LibreOffice 会给公式/透明图加 SMask，桌面驱动能合成，
            # 但 CUPS→pdftoraster 光栅化对 SMask 支持差、会整块丢弃图像，导致「预览正常、
            # 打印后化学式消失」。此处把带 SMask 的图像合成到白底、去遮罩，文字矢量层不动。
            flatten_pdf_smask(target)
            return target
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持转换该文件")


def page_count(pdf_path: Path, db: sqlite3.Connection | None = None) -> int:
    try:
        reader = PdfReader(str(pdf_path))
        count = len(reader.pages)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="无法读取 PDF 页数") from exc
    if count > effective_max_pages(db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="页数超过限制，请拆分后上传")
    return count


# ==================== 转换后字体自检（乱码可归因） ====================
# 目标：把「有时候打印乱码」从黑盒变成可报告、可归因的告警——
#   1) pdffonts 检查转换产物：有字体未嵌入（emb=no）→ 打印端必然字体替换，可能乱码；
#   2) 解析 Office 文档 fontTable/styles 列出请求的字体，比对容器已装字体与 fontconfig
#      映射表，缺失的字体名写进告警，管理员照单补装即可。
# 全部「尽力而为」：缺 pdffonts/fc-list（如 Windows 开发机）或任何异常都静默降级，
# 绝不阻断上传。

_FONTCONFIG_ALIASES_CONF = "/etc/fonts/conf.d/49-cloud-print-aliases.conf"
# fontconfig 系统级度量兼容映射（Debian 30-metric-aliases.conf 自动处理的常见
# Windows 字体 → Liberation/Carlito/Caladea），这些字体名「未安装但已被等价替换」，
# 不算缺失，避免告警噪音。
_METRIC_ALIASED_FONTS = {"arial", "times new roman", "courier new", "calibri", "cambria", "helvetica"}

_font_cache_lock = threading.Lock()
_installed_families_cache: set[str] | None = None
_aliased_families_cache: set[str] | None = None


def unembedded_pdf_fonts(pdf_path: Path) -> list[str]:
    """pdffonts 检查转换后的 PDF，返回未嵌入（emb=no）的字体名列表。"""
    pdffonts = shutil.which("pdffonts")
    if pdffonts is None:
        return []
    try:
        result = subprocess.run([pdffonts, str(pdf_path)], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    unembedded: list[str] = []
    for line in result.stdout.splitlines()[2:]:  # 跳过两行表头
        tokens = line.split()
        if len(tokens) < 8:
            continue
        # 列序：name type encoding emb sub uni object ID。字体名可含空格，从右侧数第 5 列是 emb。
        if tokens[-5].lower() == "no":
            unembedded.append(" ".join(tokens[:-7]))
    return unembedded


def _installed_font_families() -> set[str]:
    """fc-list 已安装字体族（小写）；进程内缓存，缺 fc-list 返回空集。"""
    global _installed_families_cache
    with _font_cache_lock:
        if _installed_families_cache is not None:
            return _installed_families_cache
    families: set[str] = set()
    fc_list = shutil.which("fc-list")
    if fc_list:
        try:
            result = subprocess.run([fc_list, ":", "family"], capture_output=True, text=True, timeout=30, check=False)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    for family in line.split(","):
                        cleaned = family.strip()
                        if cleaned:
                            families.add(cleaned.lower())
        except (OSError, subprocess.TimeoutExpired):
            families = set()
    with _font_cache_lock:
        _installed_families_cache = families
    return families


def _aliased_font_families() -> set[str]:
    """已被 fontconfig 映射接管的字体名（小写）：本系统别名配置 + 系统度量兼容映射。"""
    global _aliased_families_cache
    with _font_cache_lock:
        if _aliased_families_cache is not None:
            return _aliased_families_cache
    families = set(_METRIC_ALIASED_FONTS)
    conf = Path(_FONTCONFIG_ALIASES_CONF)
    if conf.exists():
        try:
            import xml.etree.ElementTree as ET

            root = ET.parse(conf).getroot()
            # 收集所有 <test name="family"><string>X</string> 里的 X：这些字体名都有映射去处。
            for test in root.iter("test"):
                if (test.get("name") or "") != "family":
                    continue
                for value in test.iter("string"):
                    text = (value.text or "").strip()
                    if text:
                        families.add(text.lower())
        except Exception:
            pass
    with _font_cache_lock:
        _aliased_families_cache = families
    return families


def document_requested_fonts(source: Path) -> list[str]:
    """从 docx/pptx 的 fontTable.xml、xlsx 的 styles.xml 提取文档请求的字体名（去重保序）。"""
    suffix = source.suffix.lower()
    fonts: list[str] = []
    try:
        with zipfile.ZipFile(source) as archive:
            targets = [name for name in archive.namelist() if name.endswith("fontTable.xml")]
            if suffix == ".xlsx" and "xl/styles.xml" in archive.namelist():
                targets.append("xl/styles.xml")
            for name in targets:
                content = archive.read(name).decode("utf-8", errors="ignore")
                if name.endswith("styles.xml"):
                    fonts.extend(re.findall(r'<name val="([^"]+)"', content))
                else:
                    fonts.extend(re.findall(r'(?:w:name|typeface)="([^"]+)"', content))
    except (zipfile.BadZipFile, OSError):
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for font in fonts:
        if font and font.lower() not in seen:
            seen.add(font.lower())
            unique.append(font)
    return unique


def audit_converted_fonts(pdf_path: Path, source: Path) -> tuple[str | None, str | None]:
    """转换后自检，返回 (未嵌入字体告警, 容器缺字体提示)；两者都可能为 None。任何异常安全降级。"""
    try:
        embed_warning = None
        unembedded = unembedded_pdf_fonts(pdf_path)
        if unembedded:
            preview = "、".join(unembedded[:8]) + ("等" if len(unembedded) > 8 else "")
            embed_warning = (
                f"转换后的 PDF 有 {len(unembedded)} 个字体未嵌入（{preview}），"
                "打印端可能出现字体替换乱码；建议在服务器补装对应字体，或让用户用 Word/WPS 另存为 PDF 后重新上传。"
            )
        missing_warning = None
        requested = document_requested_fonts(source)
        if requested:
            installed = _installed_font_families()
            aliased = _aliased_font_families()
            missing = [font for font in requested if font.lower() not in installed and font.lower() not in aliased]
            if missing:
                preview = "、".join(missing[:10]) + ("等" if len(missing) > 10 else "")
                missing_warning = (
                    f"文档使用了服务器未安装的字体：{preview}。转换时已用相近字体替代，"
                    "如打印出现符号/字符乱码，请在服务器补装上述字体后重新上传该文件。"
                )
        return embed_warning, missing_warning
    except Exception:
        return None, None
