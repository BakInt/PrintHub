"""cert 模块用户侧路由 /api/cert/*。

下单闭环不改任何现有接口：价格试算走 `/api/price`（file_ids 模式，证照计价在
主计价服务内部经钩子生效），支付走 `/api/payment/create`（balance），模块内无支付代码。
"""

import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

from ..database import get_db
from ..routers.deps import current_user
from . import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cert", tags=["cert"])


@router.get("/templates")
def list_templates(db=Depends(get_db)):
    """公开只读：只返回 enabled=1 的模板，门户卡片完全由该接口驱动。"""
    return service.list_templates(db)


@router.post("/generate")
async def generate(request: Request, db=Depends(get_db), user=Depends(current_user)):
    """生成证照打印件（multipart/form-data）。

    入参：template_code；cut_guides（可省，覆盖模板默认）；每槽位图片 `slot_<key>`；
    每槽位可选手动四点 JSON `quad_<key>`（归一化 0–1，顺序 TL,TR,BR,BL）。
    原始照片只存在于本请求的内存中，全程不落盘。
    """
    form = await request.form()
    template_code = form.get("template_code")
    if not isinstance(template_code, str) or not template_code:
        raise HTTPException(status_code=400, detail="缺少模板标识")
    template = service.get_template(db, template_code)
    if template is None or not bool(template["enabled"]):
        raise HTTPException(status_code=400, detail="该证照功能不存在或已下架")

    slot_uploads: dict[str, tuple[str | None, str | None, bytes]] = {}
    slot_quads: dict[str, list] = {}
    for key, value in form.multi_items():
        if key.startswith("slot_") and isinstance(value, UploadFile):
            data = await value.read()
            slot_uploads[key.removeprefix("slot_")] = (value.filename, value.content_type, data)
        elif key.startswith("quad_"):
            slot_key = key.removeprefix("quad_")
            try:
                quad = json.loads(value) if isinstance(value, str) else None
            except json.JSONDecodeError:
                quad = None
            if quad is not None:
                slot_quads[slot_key] = quad

    unknown_slots = [key for key in slot_uploads if key not in {s["key"] for s in json.loads(template["layout_json"]).get("slots", [])}]
    if unknown_slots:
        raise HTTPException(status_code=400, detail="存在模板未定义的槽位图片")

    cut_guides_override = None
    raw_guides = form.get("cut_guides")
    if isinstance(raw_guides, str) and raw_guides:
        cut_guides_override = raw_guides.strip().lower() in {"1", "true", "yes", "on"}

    service.check_daily_limit(db, user["id"])
    return service.create_cert_doc(db, user, template, slot_uploads, slot_quads, cut_guides_override)


@router.get("/docs")
def list_docs(limit: int = 10, offset: int = 0, db=Depends(get_db), user=Depends(current_user)):
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    return service.list_docs(db, user["id"], limit, offset)


@router.get("/docs/{doc_id}/preview")
def preview_doc(doc_id: str, db=Depends(get_db), user=Depends(current_user)):
    doc = service.get_doc(db, doc_id, user)
    pdf_path = service.doc_pdf_path(db, doc)
    filename = quote(f"证照打印件-{doc['template_code']}.pdf")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: str, db=Depends(get_db), user=Depends(current_user)):
    service.delete_doc(db, doc_id, user)
    return {"success": True}
