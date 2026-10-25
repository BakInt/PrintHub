"""证照打印模块（app/cert）专项验证脚本。

本脚本**不依赖 pycups / CUPS / FastAPI 应用**，在 Windows 本地即可运行：

    cd backend
    python tests/cert_feature_test.py

覆盖点（对应 doc/CERT_PRINT_PLAN.md 第 13 节）：
1. schema 播种幂等：重复执行结果一致；代码同步版式但保留后台改过的 price/enabled。
2. mm→px 换算与槽位定位（合成位图上按已知颜色采样，偏差 ≤ 1px）。
3. 手动四点透视变换（合成标准四边形样图验证角点映射与输出尺寸）。
4. PDF 组装（Pillow 单页 PDF + 页尺寸为 300dpi A4，PyPDF2 复核）。
5. 计价钩子三分支：独立价 / 回退 standard / 拒绝 coverage（覆盖率模式下证照件仍按标准价）。
6. 每日生成上限（超限 429）与不装 OpenCV 时的降级（本机无 cv2 即真实降级场景）。
7. 生成服务端到端：合成样图 + 手动四点 → files/cert_docs 入库、PDF 落盘、is_safe=1；
   识别失败路径返回 DETECT_FAILED（仅失败槽位）。
8. 清理任务：到期即清（磁盘文件必删）；跳过未支付/待派发订单引用；历史订单引用时
   files 行置 expired 保留外键完整性。
9. 属主校验：非属主与不存在同响应（404）。
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 隔离环境：临时配置目录（上传目录/设置都在里面），不污染真实配置。
_TMP = tempfile.TemporaryDirectory(prefix="cert_feature_test_")
os.environ["CONFIG_ROOT"] = _TMP.name

from PIL import Image  # noqa: E402
from PyPDF2 import PdfReader  # noqa: E402

from app.cert import detect, render, service  # noqa: E402
from app.cert.schema import ensure_schema  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.pricing import calculate_files_price_detail  # noqa: E402

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
CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    order_type TEXT DEFAULT 'print',
    total_amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    is_double_sided INTEGER DEFAULT 0,
    use_color INTEGER,
    merge_duplex INTEGER DEFAULT 0,
    copies INTEGER DEFAULT 1,
    payment_method TEXT DEFAULT 'wxpay',
    printer_name TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    print_job_id TEXT,
    print_error TEXT,
    sheet_count INTEGER DEFAULT 0,
    base_amount REAL,
    discount_amount REAL DEFAULT 0,
    pricing_detail TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    paid_at TEXT,
    balance_applied_at TEXT,
    printed_at TEXT
);
CREATE TABLE order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    is_double_sided INTEGER DEFAULT 0
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def new_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(BASE_SCHEMA)
    ensure_schema(db)
    return db


def add_user(db, user_id="u1", is_admin=0, balance=10.0) -> sqlite3.Row:
    db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, balance, real_name, phone) VALUES (?, ?, 'x', ?, ?, '张三', ?)",
        (user_id, user_id, is_admin, balance, f"13800{int(user_id[1:]):06d}"),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def solid_image(color, size=(1200, 800)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


def id_card_layout() -> dict:
    return json.loads(
        service.get_template(new_db(), "id_card")["layout_json"]
    )


def test_schema_seed_idempotent() -> None:
    print("[1] schema 播种幂等")
    db = new_db()
    ensure_schema(db)
    rows = db.execute("SELECT code, name, price, enabled FROM cert_templates ORDER BY code").fetchall()
    check("播种 3 个内置模板", len(rows) == 3, f"got {len(rows)}")
    check("含 id_card/hukou/doc2up", {r["code"] for r in rows} == {"id_card", "hukou", "doc2up"})
    # 后台改价/停用后，重新执行 ensure_schema 不得覆盖。
    db.execute("UPDATE cert_templates SET price = 1.5, enabled = 0 WHERE code = 'id_card'")
    db.commit()
    ensure_schema(db)
    row = db.execute("SELECT price, enabled, layout_json FROM cert_templates WHERE code = 'id_card'").fetchone()
    check("重复播种保留后台 price/enabled", row["price"] == 1.5 and row["enabled"] == 0)
    check("layout_json 可解析且含 card 元数据", "card" in json.loads(row["layout_json"]))
    # 已从种子里移除的内置模板（如旧版拆分的 hukou_personal/hukou_holder）应被清理。
    db.execute(
        "INSERT INTO cert_templates (id, code, name, layout_json, enabled) VALUES ('legacy', 'hukou_personal', '旧', '{}', 1)"
    )
    db.commit()
    ensure_schema(db)
    leftover = db.execute("SELECT COUNT(*) c FROM cert_templates WHERE code = 'hukou_personal'").fetchone()["c"]
    check("已移除的内置模板被清理", leftover == 0)
    for key, default in (("cert_retention_hours", "24"), ("cert_daily_generate_limit", "20")):
        value = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        check(f"设置键 {key} 已播种", value is not None and value["value"] == default)


def test_mm_to_px_and_placement() -> None:
    print("[2] mm→px 换算与槽位定位")
    check("210mm→2480px", render.mm_to_px(210) == 2480, str(render.mm_to_px(210)))
    check("297mm→3508px", render.mm_to_px(297) == 3508, str(render.mm_to_px(297)))
    check("85.6mm→1011px", render.mm_to_px(85.6) == 1011, str(render.mm_to_px(85.6)))
    check("54mm→638px", render.mm_to_px(54) == 638, str(render.mm_to_px(54)))

    db = new_db()
    layout = json.loads(service.get_template(db, "id_card")["layout_json"])
    front = Image.new("RGB", (1011, 638), (200, 30, 30))
    back = Image.new("RGB", (1011, 638), (30, 30, 200))
    page = render.compose_page(layout, {"front": front, "back": back})
    check("页面尺寸 2480×3508", page.size == (2480, 3508), str(page.size))
    front_slot = layout["slots"][0]
    cx = render.mm_to_px(front_slot["position_mm"][0]) + render.mm_to_px(85.6) // 2
    cy = render.mm_to_px(front_slot["position_mm"][1]) + render.mm_to_px(54) // 2
    check("正面槽位中心为红色", page.getpixel((cx, cy)) == (200, 30, 30), str(page.getpixel((cx, cy))))
    back_slot = layout["slots"][1]
    bx = render.mm_to_px(back_slot["position_mm"][0]) + render.mm_to_px(85.6) // 2
    by = render.mm_to_px(back_slot["position_mm"][1]) + render.mm_to_px(54) // 2
    check("反面槽位中心为蓝色", page.getpixel((bx, by)) == (30, 30, 200), str(page.getpixel((bx, by))))
    check("页面空白处为白底", page.getpixel((20, 20)) == (255, 255, 255))
    # 户口本 contain：户主页/个人页上下排布（与身份证正反面同页同理），照片按比例缩放居中。
    hukou = json.loads(service.get_template(db, "hukou")["layout_json"])
    slot_keys = [slot["key"] for slot in hukou["slots"]]
    check("户口本模板含 holder/personal 两个槽位", slot_keys == ["holder", "personal"], str(slot_keys))
    tall = Image.new("RGB", (800, 1600), (10, 200, 10))
    page2 = render.compose_page(hukou, {"holder": tall, "personal": tall})
    box_w = render.mm_to_px(95)
    box_h = render.mm_to_px(130)
    holder_center = page2.getpixel((render.mm_to_px(57.5) + box_w // 2, render.mm_to_px(13.5) + box_h // 2))
    personal_center = page2.getpixel((render.mm_to_px(57.5) + box_w // 2, render.mm_to_px(153.5) + box_h // 2))
    check("户主页槽位中心为绿色（上行）", holder_center == (10, 200, 10), str(holder_center))
    check("个人页槽位中心为绿色（下行）", personal_center == (10, 200, 10), str(personal_center))
    # 两框间隙（y=143.5~153.5mm）应为白底。
    gap = page2.getpixel((render.mm_to_px(57.5) + box_w // 2, render.mm_to_px(148.5)))
    check("上下两槽位之间留白（白底）", gap == (255, 255, 255), str(gap))


def test_manual_quad() -> None:
    print("[3] 手动四点透视变换")
    base = Image.new("RGB", (400, 300), (255, 255, 255))
    from PIL import ImageDraw

    ImageDraw.Draw(base).polygon([(50, 40), (350, 60), (340, 260), (60, 240)], fill=(0, 0, 0))
    quad = [[50 / 400, 40 / 300], [350 / 400, 60 / 300], [340 / 400, 260 / 300], [60 / 400, 240 / 300]]
    out = render.perspective_crop(base, quad)
    expected_w = int(round(((50 - 350) ** 2 + (40 - 60) ** 2) ** 0.5 / 2 + ((60 - 340) ** 2 + (240 - 260) ** 2) ** 0.5 / 2))
    expected_h = int(round(((50 - 60) ** 2 + (40 - 240) ** 2) ** 0.5 / 2 + ((350 - 340) ** 2 + (60 - 260) ** 2) ** 0.5 / 2))
    check("输出尺寸按四点边长均值", abs(out.width - expected_w) <= 1 and abs(out.height - expected_h) <= 1, f"{out.size} vs {(expected_w, expected_h)}")
    corners = [out.getpixel(p) for p in [(2, 2), (out.width - 3, 2), (out.width - 3, out.height - 3), (2, out.height - 3)]]
    check("四角映射到源四边形（均为黑色）", all(px == (0, 0, 0) for px in corners), str(corners))
    try:
        render.perspective_crop(base, [[0, 0], [1, 1]])
        check("非法四点被拒绝", False)
    except ValueError:
        check("非法四点被拒绝", True)


def test_pdf_assembly() -> None:
    print("[4] PDF 组装（300dpi A4 单页）")
    db = new_db()
    layout = json.loads(service.get_template(db, "id_card")["layout_json"])
    pdf_bytes, pages = render.render_pdf_bytes(layout, {"front": Image.new("RGB", (1011, 638), (128, 128, 128)), "back": Image.new("RGB", (1011, 638), (128, 128, 128))})
    check("返回 1 页", pages == 1)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    check("PyPDF2 可解析", len(reader.pages) == 1)
    box = reader.pages[0].mediabox
    width_pt = float(box.width)
    height_pt = float(box.height)
    check("页宽 ≈ A4 595pt", abs(width_pt - 2480 / 300 * 72) <= 1, str(width_pt))
    check("页高 ≈ A4 842pt", abs(height_pt - 3508 / 300 * 72) <= 1, str(height_pt))


def test_pricing_hook() -> None:
    print("[5] 计价钩子三分支")
    db = new_db()
    db.execute("INSERT INTO settings (key, value) VALUES ('pricing_mode', 'standard')")
    db.execute("INSERT INTO settings (key, value) VALUES ('single_price', '0.50')")
    db.commit()
    user = add_user(db)
    # 两个证照模板：一个独立价 2 元，一个未设价（回退标准 0.5/页）；再放一个普通文件。
    db.execute("UPDATE cert_templates SET price = 2.0 WHERE code = 'id_card'")
    db.commit()

    def add_file(file_id: str, pages: int, coverage: float = 0.0, cert_code: str | None = None, doc_status: str = "active") -> None:
        db.execute(
            "INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, is_safe, status, black_coverage, page_coverages) VALUES (?, ?, 'x', 'x', 'x', ?, 1, 'ready', ?, ?)",
            (file_id, user["id"], pages, coverage, json.dumps([coverage] * pages)),
        )
        if cert_code:
            db.execute(
                "INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid4()), user["id"], cert_code, file_id, pages, doc_status, (datetime.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")),
            )

    add_file("f-cert-price", 1, cert_code="id_card")
    add_file("f-cert-fallback", 1, cert_code="hukou")
    add_file("f-normal", 2, coverage=0.2)
    db.commit()

    files = db.execute("SELECT * FROM files WHERE id IN ('f-cert-price', 'f-normal')").fetchall()
    detail = calculate_files_price_detail(db, files, 2)
    # 证照独立价 2 元 × 2 份 + 普通文件 2 页 × 0.5 × 2 份 = 4 + 2 = 6
    check("独立价分支：2×2 + 普通 2×0.5×2 = 6", detail["amount"] == 6.0, str(detail["amount"]))
    check("pricing_detail 记录 cert_files", any(item["mode"] == "cert_template" and item["unit_price"] == 2.0 for item in detail.get("cert_files", [])), str(detail.get("cert_files")))

    files = db.execute("SELECT * FROM files WHERE id = 'f-cert-fallback'").fetchall()
    detail = calculate_files_price_detail(db, files, 1)
    check("未设价回退 standard 单面价（1×0.5）", detail["amount"] == 0.5, str(detail["amount"]))

    # doc2up（两页合一）登记行（status='doc2up'）：未设价 → 不进钩子，保持标准按页计价。
    add_file("f-doc2up", 3, coverage=0.2, cert_code="doc2up", doc_status="doc2up")
    db.commit()
    files = db.execute("SELECT * FROM files WHERE id = 'f-doc2up'").fetchall()
    detail = calculate_files_price_detail(db, files, 1)
    check("doc2up 未设价保持标准按页计价（3×0.5）", detail["amount"] == 1.5 and "cert_files" not in detail, str(detail.get("amount")))

    # 覆盖率模式下：证照件仍按标准价（不得落入 coverage_tiered），普通文件按覆盖率。
    db.execute("UPDATE settings SET value = 'coverage_tiered' WHERE key = 'pricing_mode'")
    db.commit()
    detail = calculate_files_price_detail(db, files, 1)
    doc2up_tiered = 0.10 * service_coverage_factor(0.2) * 3  # coverage_single_base_price 默认 0.10
    check("覆盖率模式下 doc2up 未设价仍按覆盖率计价", detail["amount"] == round(doc2up_tiered, 2) and "cert_files" not in detail, str(detail.get("amount")))
    # 设置独立单价后：单价 × 版面数 × 份数（与双面/覆盖率模式无关，同证照件规则）。
    db.execute("UPDATE cert_templates SET price = 0.3 WHERE code = 'doc2up'")
    db.commit()
    detail = calculate_files_price_detail(db, files, 2)
    check("doc2up 设价后按单价×版面数×份数（0.3×3×2）", detail["amount"] == 1.8, str(detail["amount"]))
    check(
        "doc2up 计价记入 cert_files",
        any(item["template_code"] == "doc2up" and item["unit_price"] == 0.3 for item in detail.get("cert_files", [])),
        str(detail.get("cert_files")),
    )
    db.execute("UPDATE cert_templates SET price = NULL WHERE code = 'doc2up'")
    db.commit()

    files = db.execute("SELECT * FROM files WHERE id IN ('f-cert-price', 'f-normal')").fetchall()
    detail = calculate_files_price_detail(db, files, 1)
    normal_amount = 0.10 * service_coverage_factor(0.2) * 2  # coverage_single_base_price 默认 0.10
    check("覆盖率模式下证照件按独立价而非覆盖率", detail["base_amount"] == round(2.0 + normal_amount, 2), f"{detail['base_amount']} vs {2.0 + normal_amount}")

    # 混合并计：无证照件时钩子零侵入（不携带 cert_files）。
    files = db.execute("SELECT * FROM files WHERE id = 'f-normal'").fetchall()
    detail = calculate_files_price_detail(db, files, 1)
    check("无证照件时结果不携带 cert_files", "cert_files" not in detail)


def service_coverage_factor(coverage: float) -> float:
    from app.services.pricing import coverage_factor

    return coverage_factor(coverage)


def test_daily_limit() -> None:
    print("[6] 每日生成上限")
    db = new_db()
    user = add_user(db)
    db.execute("UPDATE settings SET value = '2' WHERE key = 'cert_daily_generate_limit'")
    db.commit()
    try:
        service.check_daily_limit(db, user["id"])
        check("未达上限放行", True)
    except Exception as exc:
        check("未达上限放行", False, repr(exc))
    for index in range(2):
        db.execute(
            "INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, status, expires_at) VALUES (?, ?, 'id_card', ?, 1, 'active', '2999-01-01 00:00:00')",
            (f"doc{index}", user["id"], f"file{index}"),
        )
    db.commit()
    try:
        service.check_daily_limit(db, user["id"])
        check("达上限抛 429", False)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        check("达上限抛 429", status_code == 429, repr(status_code))
    # doc2up 登记行（status='doc2up'）不计入证照每日生成上限（两页合一保持不限次）。
    for index in range(3):
        db.execute(
            "INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, status, expires_at) VALUES (?, ?, 'doc2up', ?, 2, 'doc2up', '2999-01-01 00:00:00')",
            (f"d2u{index}", user["id"], f"file2up{index}"),
        )
    db.commit()
    count = service.daily_generate_count(db, user["id"])
    check("doc2up 登记行不计入每日上限计数", count == 2, str(count))
    # 0 = 不限制
    db.execute("UPDATE settings SET value = '0' WHERE key = 'cert_daily_generate_limit'")
    db.commit()
    try:
        service.check_daily_limit(db, user["id"])
        check("上限 0 视为不限制", True)
    except Exception as exc:
        check("上限 0 视为不限制", False, repr(exc))


def test_generate_end_to_end() -> None:
    print("[7] 生成服务端到端（无 OpenCV 降级 + 手动四点）")
    check("本机未安装 OpenCV（真实降级场景）", not detect.opencv_available())
    db = new_db()
    user = add_user(db)
    template = service.get_template(db, "id_card")

    # 黑底白框样图，四点取内框 → 手动裁剪路径（cv2 缺失时唯一路径）。
    base = Image.new("RGB", (2000, 1400), (255, 255, 255))
    from PIL import ImageDraw

    ImageDraw.Draw(base).rectangle([200, 200, 1800, 1200], fill=(20, 20, 20))
    buffer = io.BytesIO()
    base.save(buffer, format="JPEG")
    photo = buffer.getvalue()
    quad = [[200 / 2000, 200 / 1400], [1800 / 2000, 200 / 1400], [1800 / 2000, 1200 / 1400], [200 / 2000, 1200 / 1400]]

    result = service.create_cert_doc(
        db,
        user,
        template,
        {"front": ("f.jpg", "image/jpeg", photo), "back": ("b.jpg", "image/jpeg", photo)},
        {"front": quad, "back": quad},
    )
    check("返回 cert_doc_id/file_id/preview_url", bool(result["cert_doc_id"]) and bool(result["file_id"]) and result["preview_url"].endswith("/preview"))
    check("页数为 1", result["page_count"] == 1)
    file_row = db.execute("SELECT * FROM files WHERE id = ?", (result["file_id"],)).fetchone()
    check("files 入库 is_safe=1/ready", bool(file_row["is_safe"]) and file_row["status"] == "ready")
    check("coverage 为 NULL（计价保护）", file_row["black_coverage"] is None and file_row["page_coverages"] is None)
    pdf_path = Path(file_row["pdf_path"])
    check("PDF 已落盘且可解析", pdf_path.exists() and len(PdfReader(str(pdf_path)).pages) == 1)
    doc_row = db.execute("SELECT * FROM cert_docs WHERE id = ?", (result["cert_doc_id"],)).fetchone()
    check("cert_docs 入库 manual_crop=1", bool(doc_row["used_manual_crop"]))
    check("expires_at 按保留期写入", bool(doc_row["expires_at"]))

    # 识别失败路径：小图、无手动四点 → DETECT_FAILED（仅该槽位；back 携带四点走手动路径）。
    small = solid_image((10, 10, 10), size=(80, 60))
    try:
        service.create_cert_doc(db, user, template, {"front": ("s.jpg", "image/jpeg", small), "back": ("b.jpg", "image/jpeg", photo)}, {"back": quad})
        check("小图无四点 → DETECT_FAILED", False)
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        check("小图无四点 → DETECT_FAILED", isinstance(detail, dict) and detail.get("code") == "DETECT_FAILED" and detail.get("slots") == ["front"], repr(detail))

    # 未登录用户 Row 直接来自 db；属主校验：他人访问 404。
    other = add_user(db, "u2")
    try:
        service.get_doc(db, result["cert_doc_id"], other)
        check("非属主访问与不存在同响应 404", False)
    except Exception as exc:
        check("非属主访问与不存在同响应 404", getattr(exc, "status_code", None) == 404)
    got = service.get_doc(db, result["cert_doc_id"], user)
    check("属主可读取", got["id"] == result["cert_doc_id"])
    listing = service.list_docs(db, user["id"])
    check("docs 列表包含生成件", any(item["id"] == result["cert_doc_id"] for item in listing["items"]))


def test_cleanup() -> None:
    print("[8] 保留期清理（跳过未支付/待派发订单）")
    db = new_db()
    user = add_user(db)
    upload_root = Path(get_settings().upload_dir)

    def make_doc(doc_id: str, expired: bool = True, order_status: str | None = None) -> Path:
        file_id = f"file-{doc_id}"
        pdf_dir = upload_root / file_id
        pdf_dir.mkdir(parents=True, exist_ok=True)
        (pdf_dir / "converted.pdf").write_bytes(b"%PDF-1.4 test")
        db.execute(
            "INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, is_safe, status) VALUES (?, ?, 'x', ?, ?, 1, 1, 'ready')",
            (file_id, user["id"], str(pdf_dir / "converted.pdf"), str(pdf_dir / "converted.pdf")),
        )
        expires = "2000-01-01 00:00:00" if expired else "2999-01-01 00:00:00"
        db.execute(
            "INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, status, expires_at) VALUES (?, ?, 'id_card', ?, 1, 'active', ?)",
            (doc_id, user["id"], file_id, expires),
        )
        if order_status:
            db.execute("INSERT INTO orders (id, total_amount, status) VALUES (?, 1, ?)", (f"o-{doc_id}", order_status))
            db.execute("INSERT INTO order_items (id, order_id, file_id) VALUES (?, ?, ?)", (str(uuid4()), f"o-{doc_id}", file_id))
        db.commit()
        return pdf_dir

    pending_dir = make_doc("d-pending", order_status="pending")
    paid_dir = make_doc("d-paid", order_status="paid")
    done_dir = make_doc("d-done", order_status="completed")
    free_dir = make_doc("d-free")
    fresh_dir = make_doc("d-fresh", expired=False)

    cleaned = service.cleanup_expired_docs(db)
    check("清理 2 条（pending/paid 跳过，未到期跳过）", cleaned == 2, str(cleaned))
    check("未支付订单引用的文件保留", pending_dir.exists() and db.execute("SELECT COUNT(*) c FROM files WHERE id='file-d-pending'").fetchone()["c"] == 1)
    check("待派发订单引用的文件保留", paid_dir.exists() and db.execute("SELECT COUNT(*) c FROM files WHERE id='file-d-paid'").fetchone()["c"] == 1)
    check("未到期的不清理", fresh_dir.exists() and db.execute("SELECT COUNT(*) c FROM cert_docs WHERE id='d-fresh'").fetchone()["c"] == 1)
    check("无引用的文件行被删除", db.execute("SELECT COUNT(*) c FROM files WHERE id='file-d-free'").fetchone()["c"] == 0)
    check("无引用的磁盘文件被删除（隐私红线）", not free_dir.exists())
    done_row = db.execute("SELECT * FROM files WHERE id='file-d-done'").fetchone()
    check("历史订单引用的 files 行置 expired 且磁盘删除", done_row is not None and done_row["status"] == "expired" and not done_dir.exists())
    check("cert_docs 行全部清理（除未到期）", db.execute("SELECT COUNT(*) c FROM cert_docs WHERE id NOT IN ('d-fresh','d-pending','d-paid')").fetchone()["c"] == 0)

    # pending 订单支付完成后（置 completed），下一轮清理应放行。
    db.execute("UPDATE orders SET status = 'completed' WHERE id = 'o-d-pending'")
    db.commit()
    cleaned2 = service.cleanup_expired_docs(db)
    check("订单完成后放行清理", cleaned2 >= 1 and not pending_dir.exists())


def main() -> int:
    tests = [
        test_schema_seed_idempotent,
        test_mm_to_px_and_placement,
        test_manual_quad,
        test_pdf_assembly,
        test_pricing_hook,
        test_daily_limit,
        test_generate_end_to_end,
        test_cleanup,
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
    print(f"\n证照模块专项测试：{passed} 通过，{failed} 失败")
    _TMP.cleanup()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
