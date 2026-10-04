import os
import shutil
import sqlite3
import subprocess
import tempfile
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
        pdf_filter = (
            "pdf:writer_pdf_Export:"
            '{"EmbedStandardFonts":{"type":"boolean","value":"true"},'
            '"UseTaggedPDF":{"type":"boolean","value":"true"},'
            '"SelectPdfVersion":{"type":"long","value":"0"}}'
        )
        command = [
            libreoffice,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--nodefault",
            f"-env:UserInstallation=file://{profile_dir}",
            "--convert-to",
            pdf_filter,
            "--outdir",
            str(output_dir),
            str(source),
        ]
        env = {
            **os.environ,
            "HOME": str(output_dir),
            "LANG": "zh_CN.UTF-8",
            "LC_ALL": "zh_CN.UTF-8",
        }
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False, env=env)
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "LibreOffice 转换失败").strip()
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)
            produced = output_dir / f"{source.stem}.pdf"
            if not produced.exists():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未生成 PDF 文件")
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
