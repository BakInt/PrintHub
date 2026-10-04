import sqlite3
from pathlib import Path
from uuid import uuid4

from pdf2image import convert_from_path

from ..config import get_settings
from .pricing import get_numeric_setting


def calculate_page_coverages(pdf_path: Path) -> list[float]:
    images = convert_from_path(str(pdf_path), dpi=72, fmt="png")
    if not images:
        return []
    coverages: list[float] = []
    for image in images:
        grayscale = image.convert("L")
        pixels = grayscale.getdata()
        total = grayscale.width * grayscale.height
        dark = sum(1 for pixel in pixels if pixel < 128)
        coverages.append(round((dark / total) * 100 if total else 0, 2))
    return coverages


def average_coverage(page_coverages: list[float]) -> float:
    if not page_coverages:
        return 0.0
    return round(sum(page_coverages) / len(page_coverages), 2)


def calculate_black_coverage_details(pdf_path: Path) -> tuple[float, list[float]]:
    page_coverages = calculate_page_coverages(pdf_path)
    return average_coverage(page_coverages), page_coverages


def calculate_black_coverage(pdf_path: Path) -> float:
    coverage, _page_coverages = calculate_black_coverage_details(pdf_path)
    return coverage


def safety_coverage_limit(db: sqlite3.Connection | None = None) -> float:
    """覆盖率阈值以数据库设置（后台「系统设置」可改）为准，环境变量仅作缺省兜底。"""
    default = float(get_settings().safety_coverage_limit)
    if db is None:
        return default
    try:
        return get_numeric_setting(db, "safety_coverage_limit", default)
    except (TypeError, ValueError):
        return default


def safety_result(coverage: float, db: sqlite3.Connection | None = None) -> tuple[bool, str | None]:
    limit = safety_coverage_limit(db)
    if coverage > limit:
        return False, f"黑色覆盖率 {coverage:.2f}% 超过 {limit:.0f}% 限制"
    return True, None


def create_alert(db, file_id: str, message: str) -> None:
    db.execute(
        "INSERT INTO alerts (id, file_id, level, message) VALUES (?, ?, 'warning', ?)",
        (str(uuid4()), file_id, message),
    )
