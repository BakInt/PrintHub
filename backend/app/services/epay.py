import hashlib
import html
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from uuid import uuid4
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

from ..config import get_settings


PAYMENT_SETTING_KEYS = (
    "epay_gateway",
    "epay_pid",
    "epay_key",
    "public_base_url",
    "frontend_base_url",
)
EPAY_SUBMIT_URL = "https://your-epay-gateway.example.com/submit.php"
LEGACY_V8JISU_SUBMIT_URL = "https://legacy-epay-gateway.example.com/api/pay/submit"
EPAY_PAY_TYPES = {"alipay", "wxpay"}
PAYMENT_TYPE_LABELS = {"alipay": "支付宝", "wxpay": "微信"}
PLACEHOLDER_MARKERS = ("your-", "replace-", "your_", "replace_")
SUCCESS_TRADE_STATUSES = {"TRADE_SUCCESS", "SUCCESS"}


@dataclass(frozen=True)
class EpayRequest:
    gateway: str
    params: dict[str, str]
    submit_url: str


@dataclass(frozen=True)
class PaymentCompletion:
    order_id: str
    trade_no: str | None
    status: str
    paid_at: str | None
    already_paid: bool = False
    ignored: bool = False


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.strip().lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def normalize_epay_gateway(gateway: str | None) -> str:
    value = (gateway or EPAY_SUBMIT_URL).strip()
    if not value:
        return EPAY_SUBMIT_URL
    parsed = urlparse(value)
    if parsed.netloc == "legacy-epay-gateway.example.com":
        return EPAY_SUBMIT_URL
    if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path in {"", "/"}:
        return urlunparse(parsed._replace(path="/submit.php"))
    return value


def get_payment_settings(db=None) -> dict[str, str]:
    settings = get_settings()
    values = {
        "epay_gateway": settings.epay_gateway,
        "epay_pid": settings.epay_pid,
        "epay_key": settings.epay_key,
        "public_base_url": settings.public_base_url,
        "frontend_base_url": settings.frontend_base_url,
    }
    if db is not None:
        rows = db.execute(
            f"SELECT key, value FROM settings WHERE key IN ({','.join('?' for _ in PAYMENT_SETTING_KEYS)})",
            PAYMENT_SETTING_KEYS,
        ).fetchall()
        values.update({row["key"]: row["value"] for row in rows})
    values["epay_gateway"] = normalize_epay_gateway(values["epay_gateway"])
    return values


def epay_signature_payload(params: Mapping[str, object]) -> str:
    filtered = {k: str(v) for k, v in params.items() if k not in {"sign", "sign_type"} and str(v) != ""}
    return "&".join(f"{item}={filtered[item]}" for item in sorted(filtered))


def sign_params(params: Mapping[str, object], key: str) -> str:
    raw = epay_signature_payload(params) + key
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def validate_payment_settings(payment_settings: Mapping[str, str]) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    gateway = payment_settings.get("epay_gateway", "")
    public_base_url = payment_settings.get("public_base_url", "")
    frontend_base_url = payment_settings.get("frontend_base_url", "")
    if _is_placeholder(gateway) or "example.com" in gateway:
        errors.append("易支付网关未配置")
    if _is_placeholder(payment_settings.get("epay_pid")):
        errors.append("易支付商户 ID 未配置")
    if _is_placeholder(payment_settings.get("epay_key")):
        errors.append("易支付商户密钥未配置")
    if _is_placeholder(public_base_url) or "example.com" in public_base_url:
        errors.append("公网回调地址未配置")
    if _is_placeholder(frontend_base_url) or "example.com" in frontend_base_url:
        errors.append("前端返回地址未配置")
    if public_base_url.startswith(("http://localhost", "http://127.0.0.1")):
        warnings.append("本地回调地址仅适合自测，正式支付请配置公网 HTTPS 地址")
    if frontend_base_url.startswith(("http://localhost", "http://127.0.0.1")):
        warnings.append("本地前端返回地址仅适合自测，正式支付请配置公网 HTTPS 地址")
    if gateway and not normalize_epay_gateway(gateway).endswith("/submit.php"):
        warnings.append("易支付提交地址通常应以 /submit.php 结尾，请确认网关地址是否正确")
    return {"ready": not errors, "errors": errors, "warnings": warnings}


def _require_payment_settings(payment_settings: Mapping[str, str]) -> None:
    validation = validate_payment_settings(payment_settings)
    if validation["errors"]:
        raise HTTPException(status_code=400, detail="；".join(validation["errors"]))


def create_epay_request(order_id: str, amount: float, subject: str, payment_type: str, db=None) -> EpayRequest:
    if payment_type not in EPAY_PAY_TYPES:
        raise HTTPException(status_code=400, detail="支付方式仅支持支付宝或微信")
    payment_settings = get_payment_settings(db)
    _require_payment_settings(payment_settings)
    public_base_url = payment_settings["public_base_url"].rstrip("/")
    params = {
        "pid": payment_settings["epay_pid"],
        "type": payment_type,
        "out_trade_no": order_id,
        "notify_url": f"{public_base_url}/api/payment/notify",
        "return_url": f"{public_base_url}/api/payment/return/{order_id}",
        "name": subject,
        "money": f"{amount:.2f}",
        "sitename": get_settings().app_name,
    }
    params["sign"] = sign_params(params, payment_settings["epay_key"])
    params["sign_type"] = "MD5"
    gateway = normalize_epay_gateway(payment_settings.get("epay_gateway"))
    return EpayRequest(gateway=gateway, params=params, submit_url=f"/api/payment/submit/{order_id}")


def create_payment_params(order_id: str, amount: float, subject: str, payment_type: str, db=None) -> tuple[str, dict[str, str]]:
    request = create_epay_request(order_id, amount, subject, payment_type, db)
    return request.gateway, request.params


def create_payment_url(order_id: str, amount: float, subject: str, payment_type: str, db=None) -> str:
    return create_epay_request(order_id, amount, subject, payment_type, db).submit_url


def render_payment_submit_form(order_id: str, amount: float, subject: str, payment_type: str, db=None) -> str:
    payment_request = create_epay_request(order_id, amount, subject, payment_type, db)
    gateway = payment_request.gateway
    params = payment_request.params
    fields = "\n".join(
        f'<input type="hidden" name="{html.escape(key, quote=True)}" value="{html.escape(value, quote=True)}">'
        for key, value in params.items()
    )
    escaped_gateway = html.escape(gateway, quote=True)
    gateway_label = html.escape(urlparse(gateway).netloc or gateway)
    escaped_order_id = html.escape(order_id)
    escaped_subject = html.escape(subject)
    payment_label = html.escape(PAYMENT_TYPE_LABELS.get(payment_type, payment_type))
    escaped_amount = html.escape(f"{amount:.2f}")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>正在跳转支付</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f8fafc;
      color: #1e293b;
      font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    main {{
      width: min(92vw, 420px);
      padding: 28px;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
    }}
    h1 {{ margin: 0 0 10px; font-size: 22px; line-height: 1.3; }}
    p {{ margin: 0; color: #64748b; line-height: 1.7; }}
    dl {{
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 10px 12px;
      margin: 22px 0;
      padding: 16px;
      border-radius: 8px;
      background: #f8fafc;
      font-size: 14px;
    }}
    dt {{ color: #64748b; }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    button {{
      width: 100%;
      min-height: 44px;
      border: 0;
      border-radius: 8px;
      background: #2563eb;
      color: #fff;
      font-size: 15px;
      cursor: pointer;
    }}
    .hint {{ margin-top: 12px; font-size: 13px; text-align: center; }}
  </style>
</head>
<body>
  <main>
    <h1>正在跳转支付</h1>
    <p>订单已创建，系统会通过后端签名表单提交到易支付网关。</p>
    <dl>
      <dt>订单号</dt><dd>{escaped_order_id}</dd>
      <dt>订单名称</dt><dd>{escaped_subject}</dd>
      <dt>支付方式</dt><dd>{payment_label}</dd>
      <dt>支付金额</dt><dd>¥{escaped_amount}</dd>
      <dt>支付网关</dt><dd>{gateway_label}</dd>
    </dl>
    <form id="epay-submit" method="post" action="{escaped_gateway}">
    {fields}
      <button type="submit">继续支付</button>
    </form>
    <p class="hint">如果没有自动跳转，请点击按钮继续支付。</p>
  </main>
  <script>
    window.setTimeout(function () {{
      document.getElementById('epay-submit').submit()
    }}, 500)
  </script>
</body>
</html>"""


def verify_notify(params: Mapping[str, str], db=None) -> bool:
    payment_settings = get_payment_settings(db)
    signature = params.get("sign", "")
    return bool(signature) and signature == sign_params(params, payment_settings["epay_key"])


def build_success_notify_payload(order_id: str, amount: float, subject: str, payment_type: str, trade_no: str | None = None, db=None) -> dict[str, str]:
    request = create_epay_request(order_id, amount, subject, payment_type, db)
    payload = {
        **request.params,
        "trade_no": trade_no or f"SIM{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid4().hex[:6]}",
        "trade_status": "TRADE_SUCCESS",
    }
    payload["sign"] = sign_params(payload, get_payment_settings(db)["epay_key"])
    return payload


def apply_recharge_balance(db: Connection, order) -> None:
    if order["order_type"] != "recharge" or order["balance_applied_at"]:
        return
    if not order["user_id"]:
        raise HTTPException(status_code=400, detail="充值订单缺少用户信息")
    applied_at = datetime.utcnow().isoformat()
    cursor = db.execute(
        """
        UPDATE orders
        SET balance_applied_at = ?
        WHERE id = ? AND order_type = 'recharge' AND balance_applied_at IS NULL
        """,
        (applied_at, order["id"]),
    )
    if cursor.rowcount == 1:
        db.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (round(float(order["total_amount"]), 2), order["user_id"]),
        )


def complete_epay_payment(
    db: Connection,
    payload: Mapping[str, str],
    *,
    dispatch_callback=None,
    verify_signature: bool = True,
) -> PaymentCompletion:
    if verify_signature and not verify_notify(payload, db):
        raise HTTPException(status_code=400, detail="签名验证失败")

    order_id = payload.get("out_trade_no")
    if not order_id:
        raise HTTPException(status_code=400, detail="缺少易支付订单号")

    trade_status = str(payload.get("trade_status", "")).upper()
    if trade_status not in SUCCESS_TRADE_STATUSES:
        return PaymentCompletion(order_id=order_id, trade_no=payload.get("trade_no"), status="ignored", paid_at=None, ignored=True)

    trade_no = payload.get("trade_no")
    if not trade_no:
        raise HTTPException(status_code=400, detail="缺少易支付交易号")

    order = db.execute(
        """
        SELECT id, user_id, order_type, total_amount, status, paid_at, balance_applied_at, print_job_id, print_error, printed_at
        FROM orders
        WHERE id = ?
        """,
        (order_id,),
    ).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["status"] == "paid":
        if dispatch_callback is not None and not order["print_job_id"] and not order["print_error"] and not order["printed_at"]:
            dispatch_callback(db, order_id)
            db.commit()
            refreshed = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
            return PaymentCompletion(
                order_id=order_id,
                trade_no=trade_no,
                status=refreshed["status"] if refreshed else order["status"],
                paid_at=order["paid_at"],
                already_paid=True,
            )
        return PaymentCompletion(order_id=order_id, trade_no=trade_no, status=order["status"], paid_at=order["paid_at"], already_paid=True)
    if order["status"] in {"printing", "completed", "print_failed"}:
        return PaymentCompletion(order_id=order_id, trade_no=trade_no, status=order["status"], paid_at=order["paid_at"], already_paid=True)

    try:
        notify_amount = round(float(payload.get("money", "0")), 2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="支付金额格式错误") from exc
    if notify_amount != round(float(order["total_amount"]), 2):
        raise HTTPException(status_code=400, detail="支付金额不匹配")

    paid_at = datetime.utcnow().isoformat()
    raw_payload = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
    db.execute("UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ?", (paid_at, order_id))
    cursor = db.execute(
        "UPDATE payments SET status = 'paid', epay_trade_no = ?, paid_at = ?, raw_payload = ? WHERE order_id = ?",
        (trade_no, paid_at, raw_payload, order_id),
    )
    if cursor.rowcount == 0:
        db.execute(
            """
            INSERT INTO payments (id, order_id, epay_trade_no, amount, payment_method, status, paid_at, raw_payload)
            VALUES (?, ?, ?, ?, ?, 'paid', ?, ?)
            """,
            (str(uuid4()), order_id, trade_no, notify_amount, payload.get("type"), paid_at, raw_payload),
        )
    if order["order_type"] == "recharge":
        apply_recharge_balance(db, order)
    elif dispatch_callback is not None:
        dispatch_callback(db, order_id)
    db.commit()
    return PaymentCompletion(order_id=order_id, trade_no=trade_no, status="paid", paid_at=paid_at)
