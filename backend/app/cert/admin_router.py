"""cert 模块管理侧路由 /api/admin/cert-templates/* 与 /api/admin/cert-settings。

复用主程序 `deps.admin_user` 鉴权；不往 admin.py 里加代码（隔离约束）。
P0 后台只改价格与启停；版式（layout_json）与卡片文案随代码发布。
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_db
from ..routers.deps import admin_user
from . import service
from .templates_seed import CERT_SETTINGS_DEFAULTS

router = APIRouter(prefix="/api/admin", tags=["cert-admin"])

MAX_TEMPLATE_PRICE = 100000
MAX_RETENTION_HOURS = 24 * 365
MAX_DAILY_LIMIT = 100000


def _admin_template_payload(row: sqlite3.Row) -> dict:
    payload = service.template_payload(row)
    payload["enabled"] = bool(row["enabled"])
    payload["layout_json"] = row["layout_json"]
    return payload


@router.get("/cert-templates")
def admin_list_templates(db=Depends(get_db), _admin=Depends(admin_user)):
    rows = db.execute("SELECT * FROM cert_templates ORDER BY sort, code").fetchall()
    return [_admin_template_payload(row) for row in rows]


@router.patch("/cert-templates/{code}")
def admin_update_template(code: str, payload: dict, db=Depends(get_db), _admin=Depends(admin_user)):
    """改 price / enabled。price 传 null = 清空独立价、回退标准按页计价。

    所有模板（含 doc2up 两页合一）统一支持独立单价：证照件按 单价×页数（1 页/套）、
    doc2up 合成件按 单价×版面数（经 cert_docs 登记行进入证照计价钩子，见 6.10）。
    """
    row = service.get_template(db, code)
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    updates: list[tuple[str, object]] = []
    if "price" in payload:
        price = payload["price"]
        if price is not None:
            if not isinstance(price, (int, float)) or not (0 < float(price) <= MAX_TEMPLATE_PRICE):
                raise HTTPException(status_code=400, detail=f"模板单价需为 0–{MAX_TEMPLATE_PRICE} 之间的数值")
            price = round(float(price), 2)
        updates.append(("price", price))
    if "enabled" in payload:
        updates.append(("enabled", 1 if payload["enabled"] else 0))
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    for column, value in updates:
        db.execute(f"UPDATE cert_templates SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?", (value, code))
    db.commit()
    return _admin_template_payload(service.get_template(db, code))


def _cert_settings_payload(db: sqlite3.Connection) -> dict:
    return {
        "cert_retention_hours": service.retention_hours(db),
        "cert_daily_generate_limit": service.daily_generate_limit(db),
    }


@router.get("/cert-settings")
def admin_get_settings(db=Depends(get_db), _admin=Depends(admin_user)):
    return _cert_settings_payload(db)


@router.put("/cert-settings")
def admin_update_settings(payload: dict, db=Depends(get_db), _admin=Depends(admin_user)):
    retention = payload.get("cert_retention_hours")
    limit = payload.get("cert_daily_generate_limit")
    updates: dict[str, str] = {}
    if retention is not None:
        if not isinstance(retention, int) or not (0 <= retention <= MAX_RETENTION_HOURS):
            raise HTTPException(status_code=400, detail=f"保留时长需为 0–{MAX_RETENTION_HOURS} 之间的整数小时")
        updates["cert_retention_hours"] = str(retention)
    if limit is not None:
        if not isinstance(limit, int) or not (0 <= limit <= MAX_DAILY_LIMIT):
            raise HTTPException(status_code=400, detail=f"每日生成上限需为 0–{MAX_DAILY_LIMIT} 之间的整数（0 为不限制）")
        updates["cert_daily_generate_limit"] = str(limit)
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的设置")
    for key, value in updates.items():
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    db.commit()
    return _cert_settings_payload(db)


__all__ = ["router", "CERT_SETTINGS_DEFAULTS"]
