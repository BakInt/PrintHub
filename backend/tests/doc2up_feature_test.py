"""两页合一（doc2up）模块专项验证脚本。

本脚本**不依赖 pycups / CUPS / poppler / FastAPI 应用**（光栅化函数注入假实现），
在 Windows 本地即可运行：

    cd backend
    python tests/doc2up_feature_test.py

覆盖点：
1. 竖向文档 → 旋转成横向，A4 竖版上下两栏（含旋转方向角点校验、裁切线、尺寸）。
2. 横向文档 → 旋转成竖向，A4 横版左右两栏。
3. 奇数页：最后一页单独占半版，另半版留白；页数 → 版面数 = ceil(页数/2)。
4. 黑色覆盖率计算（白 0 / 黑 100），合成后写入 files 表供覆盖率计价模式使用。
5. 服务端到端（注入假光栅化）：输出 PDF 有效（PyPDF2 可读、页数正确、A4 尺寸）、
   files 行字段（is_safe=1、needs_rasterize=0、page_coverages 列表、属主写入）。
6. 归属校验（他人文件 404）、未过安全检测 400、无页面 400、文件不存在 404。
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.TemporaryDirectory(prefix="doc2up_feature_test_")
os.environ["CONFIG_ROOT"] = _TMP.name

from PIL import Image  # noqa: E402
from PyPDF2 import PdfReader  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.doc2up import service  # noqa: E402

passed = 0
failed = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label} {extra}")


BASE_SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    real_name TEXT,
    email TEXT,
    phone TEXT UNIQUE,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    token_version INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    pdf_path TEXT,
    page_count INTEGER DEFAULT 0,
    file_size REAL DEFAULT 0,
    black_coverage REAL DEFAULT 0,
    page_coverages TEXT,
    is_safe INTEGER DEFAULT 1,
    status TEXT DEFAULT 'uploaded',
    error_message TEXT,
    needs_rasterize INTEGER DEFAULT 1,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE cert_templates (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    price REAL,
    enabled INTEGER DEFAULT 1,
    sort INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE cert_docs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    template_code TEXT NOT NULL,
    pdf_file_id TEXT NOT NULL,
    page_count INTEGER DEFAULT 1,
    used_manual_crop INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (pdf_file_id) REFERENCES files(id)
);
"""


def new_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(BASE_SCHEMA)
    return db


def add_user(db, user_id="u1", balance=10.0) -> sqlite3.Row:
    db.execute(
        "INSERT INTO users (id, username, password_hash, balance, real_name, phone) VALUES (?, ?, 'x', ?, '张三', ?)",
        (user_id, user_id, balance, f"13800{int(user_id[1:]):06d}"),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def a4_portrait(color_top=(220, 30, 30), color_bottom=(30, 30, 220)) -> Image.Image:
    """A4 比例竖版页（上/下两半异色，用于校验旋转方向）。"""
    image = Image.new("RGB", (420, 594), color_top)
    for y in range(297, 594):
        for x in range(420):
            image.putpixel((x, y), color_bottom)
    return image


def a4_landscape(color: tuple) -> Image.Image:
    return Image.new("RGB", (594, 420), color)


def test_compose_vertical() -> None:
    print("[1] 竖向文档 → A4 竖版上下两栏（旋转 90°）")
    red, blue = a4_portrait(), a4_portrait((30, 200, 30), (200, 120, 30))
    sheet = service.compose_sheet(service.rotate_page(red), service.rotate_page(blue), vertical=True)
    check("版面尺寸 A4 竖版 2480×3508", sheet.size == (service.A4_SHORT_PX, service.A4_LONG_PX), str(sheet.size))
    half = service.A4_LONG_PX // 2
    # 旋转 90° 顺时针：原上半（红）转到右半。上栏中心：左蓝右红。
    top_box = sheet.crop((0, 0, service.A4_SHORT_PX, half))
    check("上栏左半为原页下半颜色（蓝）", top_box.getpixel((service.A4_SHORT_PX // 4, half // 2))[:3] == (30, 30, 220))
    check("上栏右半为原页上半颜色（红）", top_box.getpixel((service.A4_SHORT_PX * 3 // 4, half // 2))[:3] == (220, 30, 30))
    bottom_box = sheet.crop((0, half, service.A4_SHORT_PX, service.A4_LONG_PX))
    check("下栏左半为绿", bottom_box.getpixel((service.A4_SHORT_PX // 4, half // 2))[:3] == (200, 120, 30))
    check("下栏右半为橙", bottom_box.getpixel((service.A4_SHORT_PX * 3 // 4, half // 2))[:3] == (30, 200, 30))
    check("半版交界为浅灰裁切线", sheet.getpixel((service.A4_SHORT_PX // 2, half))[:3] == service.CUT_LINE_GRAY)


def test_compose_horizontal() -> None:
    print("[2] 横向文档 → A4 横版左右两栏（旋转 90°）")
    sheet = service.compose_sheet(service.rotate_page(a4_landscape((200, 30, 30))), service.rotate_page(a4_landscape((30, 30, 200))), vertical=False)
    check("版面尺寸 A4 横版 3508×2480", sheet.size == (service.A4_LONG_PX, service.A4_SHORT_PX), str(sheet.size))
    half = service.A4_LONG_PX // 2
    check("左栏为第一页（红）", sheet.getpixel((half // 2, service.A4_SHORT_PX // 2))[:3] == (200, 30, 30))
    check("右栏为第二页（蓝）", sheet.getpixel((half + half // 2, service.A4_SHORT_PX // 2))[:3] == (30, 30, 200))
    check("半版交界为浅灰裁切线", sheet.getpixel((half, service.A4_SHORT_PX // 2))[:3] == service.CUT_LINE_GRAY)


def test_sheets_pairing() -> None:
    print("[3] 配对与奇数页")
    pages = [a4_portage_marker(i) for i in range(5)]
    sheets = list(service.sheets_from_pages(iter(pages)))
    check("5 页 → 3 版", len(sheets) == 3, str(len(sheets)))
    last = sheets[-1]
    half = service.A4_LONG_PX // 2
    bottom_box = last.crop((0, half, service.A4_SHORT_PX, service.A4_LONG_PX))
    colors = {bottom_box.getpixel((x, y))[:3] for x in (100, 1200, 2300) for y in (200, 900, 1500)}
    check("末版下半留白（白底）", colors == {(255, 255, 255)}, str(colors))
    mixed = list(service.sheets_from_pages(iter([a4_portage_marker(0), a4_landscape((9, 9, 9))])))
    check("混合方向按首页定版式（2 页 → 1 版）", len(mixed) == 1)


def a4_portage_marker(index: int) -> Image.Image:
    """A4 比例竖版纯色页（不同页不同色）。"""
    return Image.new("RGB", (420, 594), (10 * index % 250 + 5, 20 * index % 250, 30 * index % 250))


def test_coverage() -> None:
    print("[4] 黑色覆盖率")
    white = Image.new("RGB", (100, 100), (255, 255, 255))
    black = Image.new("RGB", (100, 100), (0, 0, 0))
    check("白纸覆盖率为 0", service.sheet_coverage(white) == 0.0)
    check("黑纸覆盖率为 100", service.sheet_coverage(black) == 100.0)


def test_create_end_to_end() -> None:
    print("[5] 合成服务端到端（注入假光栅化）")
    db = new_db()
    user = add_user(db)
    upload_root = Path(get_settings().upload_dir)
    source_pdf = upload_root / "src-tmp.pdf"
    source_pdf.parent.mkdir(parents=True, exist_ok=True)
    source_pdf.write_bytes(b"%PDF-1.4 dummy")

    db.execute(
        "INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, is_safe, status) VALUES (?, ?, '讲义.pdf', ?, ?, 3, 1, 'ready')",
        ("src1", user["id"], str(source_pdf), str(source_pdf)),
    )
    db.commit()

    fake_pages = [a4_portage_marker(i) for i in range(3)]
    original_rasterize = service.rasterize_pages
    service.rasterize_pages = lambda path, dpi=service.DOC2UP_DPI: iter(fake_pages)
    try:
        result = service.create_doc2up(db, user, "src1")
    finally:
        service.rasterize_pages = original_rasterize

    check("返回 file_id/page_count/preview_url", bool(result["file_id"]) and result["page_count"] == 2 and result["preview_url"].endswith("/preview"))
    row = db.execute("SELECT * FROM files WHERE id = ?", (result["file_id"],)).fetchone()
    check("files 入库 is_safe=1/ready/needs_rasterize=0", bool(row["is_safe"]) and row["status"] == "ready" and int(row["needs_rasterize"]) == 0)
    check("命名为 原名-两页合一.pdf", row["original_name"] == "讲义-两页合一.pdf", row["original_name"])
    check("属主为当前用户", row["user_id"] == user["id"])
    check("page_coverages 为 2 页列表", json.loads(row["page_coverages"]) and len(json.loads(row["page_coverages"])) == 2)
    # 合成件登记进 cert_docs（status='doc2up'）：供「证件照管理」独立单价经证照计价钩子生效，
    # 同时不计入证照保留期清理与每日生成上限（两处查询都只统计 status='active'）。
    reg = db.execute("SELECT * FROM cert_docs WHERE pdf_file_id = ?", (result["file_id"],)).fetchone()
    check(
        "cert_docs 登记行（doc2up/版面数）",
        reg is not None and reg["template_code"] == "doc2up" and reg["status"] == "doc2up" and reg["page_count"] == 2,
        f"reg={dict(reg) if reg else None}",
    )
    output = Path(row["pdf_path"])
    check("输出 PDF 落盘且可读（2 页）", output.exists() and len(PdfReader(str(output)).pages) == 2)
    box = PdfReader(str(output)).pages[0].mediabox
    check("输出页为 A4 尺寸", abs(float(box.width) - 2480 / 300 * 72) <= 1 and abs(float(box.height) - 3508 / 300 * 72) <= 1)

    print("[6] 校验与归属")
    other = add_user(db, "u2")
    try:
        service.create_doc2up(db, other, "src1")
        check("他人文件与不存在同响应 404", False)
    except Exception as exc:
        check("他人文件与不存在同响应 404", getattr(exc, "status_code", None) == 404)
    db.execute("UPDATE files SET is_safe = 0 WHERE id = 'src1'")
    db.commit()
    try:
        service.create_doc2up(db, user, "src1")
        check("未过安全检测 400", False)
    except Exception as exc:
        check("未过安全检测 400", getattr(exc, "status_code", None) == 400)
    db.execute("INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, is_safe, status) VALUES ('empty', ?, 'e.pdf', 'x', 'x', 0, 1, 'ready')", (user["id"],))
    db.commit()
    try:
        service.create_doc2up(db, user, "empty")
        check("无页面文件 400", False)
    except Exception as exc:
        check("无页面文件 400", getattr(exc, "status_code", None) == 400)
    try:
        service.create_doc2up(db, user, "nope")
        check("不存在文件 404", False)
    except Exception as exc:
        check("不存在文件 404", getattr(exc, "status_code", None) == 404)


def main() -> int:
    tests = [
        test_compose_vertical,
        test_compose_horizontal,
        test_sheets_pairing,
        test_coverage,
        test_create_end_to_end,
    ]
    for test in tests:
        try:
            test()
        except Exception:
            global failed
            failed += 1
            import traceback

            print(f"  [FAIL] {test.__name__} 抛出异常：")
            traceback.print_exc()
    print(f"\n两页合一模块专项测试：{passed} 通过，{failed} 失败")
    _TMP.cleanup()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
