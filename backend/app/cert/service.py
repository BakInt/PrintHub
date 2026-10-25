"""cert 模块业务逻辑：模板查询、生成（校验/每日上限/入库）、生成件查询与删除。

隐私红线：槽位照片以请求内存中的字节流直接进入图像管线，全程不落盘任何原始照片。
生成件写 `files` 表（is_safe=1，系统按固定版式合成的受信产物，不走外部上传检测管线），
并通过 `cert_docs` 关联；计价保护见 pricing.py（coverage 恒为 NULL，不落入覆盖率计价）。
"""

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from ..config import get_settings
from ..services.files import effective_max_file_size_mb
from . import detect, render

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# 照片短边低于目标像素该比例时判定为过小（识别失败路径，引导重拍或手动裁剪）。
MIN_PHOTO_RATIO = 0.6


def get_cert_int_setting(db: sqlite3.Connection, key: str, default: int) -> int:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return int(float(row["value"]))
    except (TypeError, ValueError):
        return default


def retention_hours(db: sqlite3.Connection) -> int:
    return max(0, get_cert_int_setting(db, "cert_retention_hours", 24))


def daily_generate_limit(db: sqlite3.Connection) -> int:
    return max(0, get_cert_int_setting(db, "cert_daily_generate_limit", 20))


def daily_generate_count(db: sqlite3.Connection, user_id: str) -> int:
    row = db.execute(
        """
        SELECT COUNT(*) AS n FROM cert_docs
        WHERE user_id = ? AND status = 'active'
          AND date(created_at, 'localtime') = date('now', 'localtime')
        """,
        (user_id,),
    ).fetchone()
    return int(row["n"] or 0)


def check_daily_limit(db: sqlite3.Connection, user_id: str) -> None:
    limit = daily_generate_limit(db)
    if limit <= 0:
        return
    used = daily_generate_count(db, user_id)
    if used >= limit:
        raise HTTPException(status_code=429, detail=f"今日证照生成次数已达上限（{limit} 次），请明天再试")


def get_template(db: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM cert_templates WHERE code = ?", (code,)).fetchone()


def template_payload(row: sqlite3.Row) -> dict:
    """把模板行转成公开接口载荷（含版式摘要与门户卡片元数据）。"""
    layout = json.loads(row["layout_json"])
    price = row["price"]
    return {
        "code": row["code"],
        "name": row["name"],
        "slots": [
            {"key": slot["key"], "label": slot["label"], "size_mm": slot["size_mm"]}
            for slot in layout.get("slots", [])
        ],
        "page_count": 1,
        "cut_guides": bool(layout.get("cut_guides")),
        "price": price,
        "price_mode": "template" if price is not None else "standard",
        "card": layout.get("card", {}),
        "sort": row["sort"],
    }


def list_templates(db: sqlite3.Connection, only_enabled: bool = True) -> list[dict]:
    sql = "SELECT * FROM cert_templates"
    if only_enabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY sort, code"
    return [template_payload(row) for row in db.execute(sql).fetchall()]


def _slot_target_box_px(slot: dict) -> tuple[int, int]:
    return (render.mm_to_px(slot["size_mm"][0]), render.mm_to_px(slot["size_mm"][1]))


def _photo_too_small(image, slot: dict) -> bool:
    box_w, box_h = _slot_target_box_px(slot)
    return min(image.size) < MIN_PHOTO_RATIO * min(box_w, box_h)


def _slot_aspect(slot: dict) -> float:
    """槽位目标长宽比（w/h），作为自动识别的置信度过滤条件。

    contain 槽位（照片比例由拍摄决定）同样用包围框比例过滤：真实证照页比例
    与包围框设计比例接近，偏差过大的轮廓大概率不是证件主体，交回手动裁剪。
    """
    width_mm, height_mm = slot["size_mm"]
    return float(width_mm) / float(height_mm) if height_mm else 0.0


def create_cert_doc(
    db: sqlite3.Connection,
    user: sqlite3.Row,
    template_row: sqlite3.Row,
    slot_uploads: dict[str, tuple[str | None, str | None, bytes]],
    slot_quads: dict[str, list],
    cut_guides: bool | None = None,
) -> dict:
    """生成证照打印件。

    slot_uploads：{槽位 key: (filename, content_type, 字节)}；slot_quads：{槽位 key: 归一化四点}；
    cut_guides：可选，覆盖模板的裁剪细框默认值。
    自动识别失败且该槽位无手动四点时抛 400，detail = {"code": "DETECT_FAILED", "slots": [...]}。
    """
    layout = json.loads(template_row["layout_json"])
    if cut_guides is not None:
        layout["cut_guides"] = cut_guides
    slot_defs = layout.get("slots", [])
    missing = [slot["key"] for slot in slot_defs if slot["key"] not in slot_uploads]
    if missing:
        labels = {slot["key"]: slot["label"] for slot in slot_defs}
        raise HTTPException(status_code=400, detail=f"请上传{','.join(labels.get(k, k) for k in missing)}照片")

    max_bytes = effective_max_file_size_mb(db) * 1024 * 1024
    processed: dict[str, object] = {}
    failed_slots: list[str] = []
    used_manual_crop = False
    for slot in slot_defs:
        key = slot["key"]
        filename, content_type, data = slot_uploads[key]
        if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="图片无法识别，请使用 JPG/PNG 格式重新拍摄")
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"{slot['label']}照片过大，请压缩后重试")
        try:
            image = render.load_image_bytes(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        quad = slot_quads.get(key)
        if quad is not None:
            try:
                image = render.perspective_crop(image, quad)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            used_manual_crop = True
        else:
            # 照片过小直接走识别失败路径（引导重拍或手动裁剪），不再尝试自动识别。
            if _photo_too_small(image, slot):
                failed_slots.append(key)
                continue
            detected = detect.detect_card_quad(image, _slot_aspect(slot))
            if detected is None:
                failed_slots.append(key)
                continue
            image = render.perspective_crop(image, detected)
        processed[key] = render.enhance_image(image)

    if failed_slots:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DETECT_FAILED",
                "message": "自动识别失败，请重拍或手动框选证件边缘",
                "slots": failed_slots,
            },
        )

    pdf_bytes, pages = render.render_pdf_bytes(layout, processed)

    settings = get_settings()
    file_id = str(uuid4())
    doc_id = str(uuid4())
    pdf_dir = Path(settings.upload_dir) / file_id
    pdf_path = pdf_dir / "converted.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)

    original_name = f"证照打印件-{template_row['name']}.pdf"
    db.execute(
        """
        INSERT INTO files (id, user_id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, page_coverages, is_safe, status, needs_rasterize)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 1, 'ready', 0)
        """,
        (
            file_id,
            user["id"],
            original_name,
            str(pdf_path),
            str(pdf_path),
            pages,
            len(pdf_bytes),
        ),
    )
    expires_at = (datetime.utcnow() + timedelta(hours=retention_hours(db))).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        INSERT INTO cert_docs (id, user_id, template_code, pdf_file_id, page_count, used_manual_crop, status, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (doc_id, user["id"], template_row["code"], file_id, pages, 1 if used_manual_crop else 0, expires_at),
    )
    db.commit()
    # 日志脱敏：只记 id/模板/结果，绝不记照片内容。
    logger.info("证照生成成功 doc=%s template=%s user=%s manual_crop=%s pages=%s", doc_id, template_row["code"], user["id"], used_manual_crop, pages)
    return {
        "cert_doc_id": doc_id,
        "file_id": file_id,
        "page_count": pages,
        "preview_url": f"/api/cert/docs/{doc_id}/preview",
        "expires_at": expires_at,
    }


def list_docs(db: sqlite3.Connection, user_id: str, limit: int = 10, offset: int = 0) -> dict:
    total = db.execute("SELECT COUNT(*) AS n FROM cert_docs WHERE user_id = ?", (user_id,)).fetchone()["n"]
    rows = db.execute(
        """
        SELECT d.id, d.template_code, d.pdf_file_id, d.page_count, d.status, d.created_at, d.expires_at,
               f.original_name, t.name AS template_name
        FROM cert_docs d
        LEFT JOIN files f ON f.id = d.pdf_file_id
        LEFT JOIN cert_templates t ON t.code = d.template_code
        WHERE d.user_id = ?
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "template_code": row["template_code"],
            "template_name": row["template_name"] or row["template_code"],
            "file_id": row["pdf_file_id"],
            "file_name": row["original_name"],
            "page_count": row["page_count"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "preview_url": f"/api/cert/docs/{row['id']}/preview",
        }
        for row in rows
    ]
    return {"items": items, "total": int(total or 0), "has_more": offset + len(items) < int(total or 0)}


def get_doc(db: sqlite3.Connection, doc_id: str, user: sqlite3.Row) -> sqlite3.Row:
    """属主校验：非属主与「不存在」返回同一响应（沿用安全修复 V-07 同级防护）。"""
    row = db.execute("SELECT * FROM cert_docs WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="生成件不存在")
    if row["user_id"] != user["id"] and not bool(user["is_admin"]):
        raise HTTPException(status_code=404, detail="生成件不存在")
    return row


def doc_pdf_path(db: sqlite3.Connection, doc: sqlite3.Row) -> Path:
    file_row = db.execute("SELECT pdf_path FROM files WHERE id = ?", (doc["pdf_file_id"],)).fetchone()
    if file_row is None or not file_row["pdf_path"]:
        raise HTTPException(status_code=404, detail="生成件已过期，请重新生成")
    pdf_path = Path(file_row["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="生成件已过期，请重新生成")
    return pdf_path


def _file_in_active_order(db: sqlite3.Connection, file_id: str) -> bool:
    row = db.execute(
        """
        SELECT 1 FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.file_id = ? AND o.status IN ('pending', 'paid')
        LIMIT 1
        """,
        (file_id,),
    ).fetchone()
    return row is not None


def _file_referenced_by_any_order(db: sqlite3.Connection, file_id: str) -> bool:
    row = db.execute("SELECT 1 FROM order_items WHERE file_id = ? LIMIT 1", (file_id,)).fetchone()
    return row is not None


def _purge_doc(db: sqlite3.Connection, doc: sqlite3.Row) -> None:
    """删除生成件：磁盘文件必删（隐私红线）；files 行仅在没有订单引用时可删，
    被历史订单引用时置 status='expired' 保留外键完整性（预览自然 404）。"""
    file_id = doc["pdf_file_id"]
    file_row = db.execute("SELECT pdf_path FROM files WHERE id = ?", (file_id,)).fetchone()
    db.execute("DELETE FROM cert_docs WHERE id = ?", (doc["id"],))
    if file_row is not None:
        if _file_referenced_by_any_order(db, file_id):
            db.execute("UPDATE files SET status = 'expired' WHERE id = ?", (file_id,))
        else:
            db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    db.commit()
    if file_row is not None and file_row["pdf_path"]:
        upload_root = Path(get_settings().upload_dir).resolve()
        target = Path(file_row["pdf_path"]).resolve()
        # 上传根目录校验（沿用主程序缓存清理的防护约定），只在根目录内整目录删除。
        if upload_root in target.parents:
            shutil.rmtree(target.parent, ignore_errors=True)


def delete_doc(db: sqlite3.Connection, doc_id: str, user: sqlite3.Row) -> None:
    doc = get_doc(db, doc_id, user)
    if _file_in_active_order(db, doc["pdf_file_id"]):
        raise HTTPException(status_code=400, detail="生成件正在打印队列中，暂时无法删除")
    _purge_doc(db, doc)


def cleanup_expired_docs(db: sqlite3.Connection) -> int:
    """清理到期生成件（清理线程每小时调用）。跳过仍被未支付/待派发订单引用的文件。"""
    rows = db.execute(
        """
        SELECT * FROM cert_docs
        WHERE status = 'active' AND expires_at <= datetime('now')
        """
    ).fetchall()
    cleaned = 0
    for doc in rows:
        if _file_in_active_order(db, doc["pdf_file_id"]):
            continue
        try:
            _purge_doc(db, doc)
            cleaned += 1
        except Exception:
            logger.exception("证照生成件清理失败 doc=%s", doc["id"])
    return cleaned
