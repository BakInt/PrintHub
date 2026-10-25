"""文档两页合一（2-up）打印模块。

上传的文档经主程序上传管线转换成 PDF 后，把每**两页**文档内容旋转 90°
缩排到一页 A4 上：竖向文档 → 横向摆放（A4 竖版上下两栏）；横向文档 →
竖向摆放（A4 横版左右两栏）。输出为 300dpi 纯位图 PDF，走标准 files 表 /
计价 / 下单 / 打印链路（双面勾选复用 print_settings.merge_duplex）。

主程序挂接点：main.py 一行 import + 一行 include_router（隔离钩子）。
"""

import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image

from ..database import get_db
from ..routers.deps import current_user
from . import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/doc2up", tags=["doc2up"])


@router.post("/create")
def create_doc2up(
    payload: dict,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    """把已上传并转换好的 PDF 合成为两页合一打印件。

    入参 `{file_id}`：主程序 `POST /api/upload` 返回的文件 ID（Office/图片已转 PDF）。
    源文件须存在、通过安全检测且归属当前用户（或匿名访客上传）。
    返回 `{file_id, source_file_id, page_count, preview_url}`，preview 复用
    `/api/files/{id}/preview`（属主校验由该接口承担）。
    """
    file_id = payload.get("file_id")
    if not isinstance(file_id, str) or not file_id:
        raise HTTPException(status_code=400, detail="缺少文件 ID")
    # 模板启停控制：doc2up 在 cert_templates 里有登记行（见 cert/templates_seed.py），
    # 后台「证件照管理」停用后门户卡片消失、合成接口同步拒绝（延迟导入防加载环）。
    from ..cert import service as cert_service

    template = cert_service.get_template(db, "doc2up")
    if template is None or not bool(template["enabled"]):
        raise HTTPException(status_code=400, detail="两页合一打印功能已下架")
    return service.create_doc2up(db, user, file_id)


__all__ = ["router", "service", "Image"]
