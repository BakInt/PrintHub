"""证照计价分支：被主计价服务调用的唯一钩子 `apply_cert_pricing`。

规则（方案第 9 节）：
- 命中 `cert_docs.pdf_file_id` 的文件按模板重算该项金额：
  `cert_templates.price` 非空 → 单价 × 页数 × 份数；为空 → 回退 standard 单面价（按页）；
- doc2up（两页合一）登记行（`cert_docs.status='doc2up'`，见 doc2up/service.py）例外：
  只有模板设置了独立单价才进钩子（单价 × 版面数 × 份数）；未设价时保持主程序
  标准计价（含 coverage_tiered 按版面覆盖率），与登记前行为完全一致；
- 任何情况下证照件不得落入 `coverage_tiered`（其 coverage 为 NULL，照片页覆盖率无意义）；
- 多文件混合下单逐文件分支后求和；价格一律服务端计算。

为避免与 `services/pricing.py` 的循环导入（主计价服务顶层不引 cert，本模块也不在
顶层引主计价服务），对主计价模块的复用一律放在函数内延迟导入——调用发生时
`services.pricing` 必然已完成初始化。
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def _load_cert_price_map(db: sqlite3.Connection, file_ids: list[str]) -> dict[str, sqlite3.Row]:
    if not file_ids:
        return {}
    placeholders = ",".join("?" for _ in file_ids)
    rows = db.execute(
        f"""
        SELECT d.pdf_file_id AS file_id, d.template_code AS code, t.price AS price, t.name AS name
        FROM cert_docs d
        LEFT JOIN cert_templates t ON t.code = d.template_code
        WHERE d.pdf_file_id IN ({placeholders}) AND d.status IN ('active', 'doc2up')
        """,
        file_ids,
    ).fetchall()
    return {
        row["file_id"]: row
        for row in rows
        # doc2up 登记行未设独立单价时跳过：交回主程序标准/覆盖率计价（行为与登记前一致）。
        if row["code"] != "doc2up" or row["price"] is not None
    }


def _standard_single_price(db: sqlite3.Connection) -> float:
    row = db.execute("SELECT value FROM settings WHERE key = 'single_price'").fetchone()
    try:
        return float(row["value"]) if row is not None else 0.5
    except (TypeError, ValueError):
        return 0.5


def apply_cert_pricing(db: sqlite3.Connection, files: list[sqlite3.Row], copies: int, result: dict) -> dict:
    """在 `calculate_files_price_detail()` 标准计价完成后调用，重算证照件金额并回填 detail。

    没有证照件时原样返回（零开销短路）。
    """
    cert_map = _load_cert_price_map(db, [row["id"] for row in files])
    if not cert_map:
        return result

    from ..services.pricing import (
        _merged_duplex_base_amount,
        _price_detail,
        best_bulk_discount,
        calculate_file_base_amount,
        calculate_price,
        daily_limited_offer_discount,
        get_pricing_mode,
    )

    copy_count = max(int(copies or 1), 1)
    pricing_mode = get_pricing_mode(db)
    standard_single_price = _standard_single_price(db)

    cert_items: list[dict] = []
    cert_total = 0.0
    for file_row in files:
        info = cert_map.get(file_row["id"])
        if info is None:
            continue
        pages = max(int(file_row["page_count"] or 0), 0)
        if info["price"] is not None:
            unit_price = float(info["price"])
            mode = "cert_template"
        else:
            # 回退 standard 单面价（按页），与站点定价模式无关（覆盖率模式对照片页无意义）。
            unit_price = standard_single_price
            mode = "cert_standard"
        amount = round(pages * copy_count * unit_price, 2)
        cert_total += amount
        cert_items.append(
            {
                "file_id": file_row["id"],
                "template_code": info["code"],
                "template_name": info["name"] or info["code"],
                "mode": mode,
                "unit_price": unit_price,
                "amount": amount,
            }
        )

    non_cert_files = [row for row in files if row["id"] not in cert_map]
    if result.get("merge_duplex") and non_cert_files:
        # 合并双面单里的非证照部分保持原合并口径；证照件按上述分支重算。
        non_cert_amount = _merged_duplex_base_amount(db, non_cert_files, copy_count, pricing_mode)
    else:
        non_cert_amount = sum(
            calculate_file_base_amount(db, row, copy_count, False, pricing_mode) for row in non_cert_files
        )

    base_amount = round(non_cert_amount + cert_total, 2)
    sheet_count = int(result.get("sheet_count") or 0)
    new_detail = _price_detail(
        base_amount,
        sheet_count,
        pricing_mode,
        [best_bulk_discount(db, sheet_count), daily_limited_offer_discount(db, sheet_count)],
    )
    new_detail["merge_duplex"] = bool(result.get("merge_duplex"))
    new_detail["total_pages"] = result.get("total_pages")
    new_detail["cert_files"] = cert_items
    logger.info(
        "证照计价生效 files=%s copies=%s base=%s",
        [item["file_id"] for item in cert_items],
        copy_count,
        base_amount,
    )
    return new_detail
