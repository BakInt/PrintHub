from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator, model_validator


PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{4,20}$")


def normalize_payment_method_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("支付方式格式错误")
    aliases = {
        "alipay": "alipay",
        "ali": "alipay",
        "epay": "alipay",
        "wxpay": "wxpay",
        "wechat": "wxpay",
        "weixin": "wxpay",
        "wx": "wxpay",
        "balance": "balance",
    }
    payment_method = aliases.get(value.strip().lower())
    if payment_method is None:
        raise ValueError("支付方式仅支持微信、支付宝或余额")
    return payment_method


class UserOut(BaseModel):
    id: str
    username: str
    real_name: str | None = None
    email: str | None = None
    phone: str | None = None
    balance: float
    is_admin: bool
    is_active: bool = True


class AuthRequest(BaseModel):
    username: str = Field(min_length=4, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=64)
    captcha: str = Field(min_length=1, max_length=12)
    email: str | None = None
    phone: str | None = None


class AuthResponse(BaseModel):
    token: str = ""
    user: UserOut


class UserProfileUpdate(BaseModel):
    real_name: str = Field(min_length=1, max_length=40)
    phone: str = Field(min_length=11, max_length=11)

    @field_validator("real_name", mode="before")
    @classmethod
    def normalize_real_name(cls, value):
        if not isinstance(value, str):
            raise ValueError("姓名格式错误")
        name = value.strip()
        if not name:
            raise ValueError("请填写姓名")
        return name

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value):
        if not isinstance(value, str):
            raise ValueError("手机号格式错误")
        phone = value.strip()
        if not PHONE_PATTERN.fullmatch(phone):
            raise ValueError("手机号需为 11 位中国大陆手机号")
        return phone


class FilePrintSetting(BaseModel):
    """单份文档的独立打印设置：目前仅包含是否启用双面。

    双面按份独立生效：为某份多页文档单独开启双面，只影响这一份文档自身的正反面，
    不会与其它文档合并到同一张纸。
    """

    file_id: str
    double_sided: bool = False


class PrintSettings(BaseModel):
    double_sided: bool = False
    file_settings: list[FilePrintSetting] | None = None
    copies: int = Field(default=1, ge=1, le=99)
    printer_name: str | None = None
    contact_name: str | None = Field(default=None, max_length=40)
    contact_phone: str | None = Field(default=None, max_length=11)
    # 【新增功能】彩色打印开关：True=彩色（后端不得把文件转黑白），False=黑白。
    # 为 None 表示旧版前端没有携带该字段，后端完全按原有逻辑处理（兼容旧业务）。
    use_color: bool | None = None
    # 【新增功能】自动双面打印总开关，与前端「双面打印」选项同源。
    # 为 None 时沿用原有逻辑（全局 double_sided + 逐份 file_settings）；
    # 非 None 时作为「未单独设置的文件」的全局默认值（逐份 file_settings 仍然优先）。
    use_auto_duplex: bool | None = None

    def double_sided_map(self) -> dict[str, bool]:
        """把按份设置折算成 {file_id: bool} 映射。

        缺省时回退到全局 ``double_sided``（历史兼容），
        因此未在 ``file_settings`` 中出现的文件沿用全局开关。
        """
        if not self.file_settings:
            return {}
        return {item.file_id: item.double_sided for item in self.file_settings}

    @field_validator("contact_name", mode="before")
    @classmethod
    def normalize_contact_name(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("打印人姓名格式错误")
        name = value.strip()
        if not name:
            raise ValueError("请填写打印人姓名")
        return name

    @field_validator("contact_phone", mode="before")
    @classmethod
    def normalize_contact_phone(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("联系电话格式错误")
        phone = value.strip()
        if not PHONE_PATTERN.fullmatch(phone):
            raise ValueError("联系电话需为 11 位中国大陆手机号")
        return phone


class PaymentCreateRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=20)
    print_settings: PrintSettings
    payment_method: str

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment_method(cls, value):
        return normalize_payment_method_value(value)


class BalanceUpdate(BaseModel):
    amount: float = Field(ge=-10000, le=10000)


class BalanceSet(BaseModel):
    balance: float = Field(ge=0, le=100000)


class RechargeRequest(BaseModel):
    amount: float = Field(ge=1, le=2000)
    payment_method: str

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        amount = round(float(value), 2)
        if amount != float(value):
            raise ValueError("充值金额最多保留两位小数")
        return amount

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment_method(cls, value):
        payment_method = normalize_payment_method_value(value)
        if payment_method == "balance":
            raise ValueError("充值仅支持微信或支付宝")
        return payment_method


class RedeemRequest(BaseModel):
    """用户个人中心「兑换码充值」：提交兑换码兑换额度到余额。"""

    code: str = Field(min_length=1, max_length=64)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        code = str(value or "").strip().upper()
        if not code:
            raise ValueError("请输入兑换码")
        return code


class AdminRedemptionCreate(BaseModel):
    """后台手动新增单个兑换码。

    code 允许为空：留空（或不传）时由后端自动生成随机兑换码，
    与弹窗提示「自定义兑换码（留空随机生成）」保持一致，因此这里不设 min_length。
    其余字段（兑换面额、可用次数、有效期）仍保留校验。

    per_user_max_times（弹窗「每个用户最大兑换次数」开关 + 数字输入框）：
    0 = 关闭该限制，完全沿用原有「按 usable_count 总可用次数」的逻辑；
    N > 0 = 开启限制，同一个 user_id 最多只能兑换该兑换码 N 次。
    开启后是双重校验：既要通过 usable_count 的全局总次数校验，又要满足每用户次数上限，
    任一超限都直接拒绝；某用户已兑换次数通过兑换记录表 redemption_logs 统计。

    【新增功能】有效期两种互斥方式（弹窗里二选一，不允许同时生效）：
    - expiry_mode="days"（默认）：按 valid_days 天数计算，0 表示永久有效；
    - expiry_mode="date"：由 expire_date（原生日期控件提交的 YYYY-MM-DD）直接指定到期日期，
      这里只校验日期格式与真实性，具体到期时刻（当天 23:59:59）由
      app.services.redemption.normalize_expire_date() 归一化，并把 valid_days 强制归零。
    这样老前端（只传 valid_days、不传新字段）的行为完全不变。
    """

    code: str = Field(default="", max_length=64)
    amount: float = Field(gt=0, le=100000)
    usable_count: int = Field(default=1, ge=1, le=100000)
    valid_days: int = Field(default=0, ge=0, le=10000)
    per_user_max_times: int = Field(default=0, ge=0, le=100000)
    expiry_mode: str = Field(default="days")
    expire_date: str | None = Field(default=None, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def normalize_redemption_payload(cls, data):
        """兼容旧前端 + 归一两套有效期配置。

        1. 老的复选框 per_user_once=True 等价于「每用户最多 1 次」：旧版弹窗只提交布尔值，
           若直接丢弃会让限制静默失效，这里折算成 per_user_max_times=1。
        2. 有效期：expiry_mode 非 "date" 时一律按「按天数」处理并清空 expire_date，
           避免两种方式同时生效产生歧义；"date" 模式下 expire_date 必填且必须是
           真实存在的 YYYY-MM-DD，同时把 valid_days 归零。
        """
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("per_user_once") and not normalized.get("per_user_max_times"):
            normalized["per_user_max_times"] = 1

        mode = str(normalized.get("expiry_mode") or "days").strip().lower()
        if mode != "date":
            normalized["expiry_mode"] = "days"
            normalized["expire_date"] = None
            return normalized

        raw_date = normalized.get("expire_date")
        text = str(raw_date).strip() if raw_date is not None else ""
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("请选择有效的到期日期（格式 YYYY-MM-DD）") from exc
        normalized["expiry_mode"] = "date"
        normalized["expire_date"] = text
        # 指定到期日期模式下天数无意义，强制归零，保证 (valid_days, expires_at) 语义唯一。
        normalized["valid_days"] = 0
        return normalized

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        amount = round(float(value), 2)
        if amount <= 0:
            raise ValueError("兑换面额必须大于 0")
        return amount

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return str(value or "").strip().upper()


class AdminRedemptionBatchCreate(BaseModel):
    """后台批量生成随机兑换码。

    【新增功能】有效期与手动新增一致，支持「按天数」或「指定到期日期」二选一
    （expiry_mode + expire_date），默认仍是按天数，老前端行为不变。
    """

    count: int = Field(default=10, ge=1, le=1000)
    amount: float = Field(gt=0, le=100000)
    usable_count: int = Field(default=1, ge=1, le=100000)
    valid_days: int = Field(default=0, ge=0, le=10000)
    expiry_mode: str = Field(default="days")
    expire_date: str | None = Field(default=None, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def normalize_expiry(cls, data):
        """与 AdminRedemptionCreate 同一套有效期归一化规则（见上）。"""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        mode = str(normalized.get("expiry_mode") or "days").strip().lower()
        if mode != "date":
            normalized["expiry_mode"] = "days"
            normalized["expire_date"] = None
            return normalized

        raw_date = normalized.get("expire_date")
        text = str(raw_date).strip() if raw_date is not None else ""
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("请选择有效的到期日期（格式 YYYY-MM-DD）") from exc
        normalized["expiry_mode"] = "date"
        normalized["expire_date"] = text
        normalized["valid_days"] = 0
        return normalized

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        amount = round(float(value), 2)
        if amount <= 0:
            raise ValueError("兑换面额必须大于 0")
        return amount


class FileCacheCleanupRequest(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    include_order_files: bool = False
    dry_run: bool = True


class BackupCreateRequest(BaseModel):
    archive_format: str = Field(default="zip", pattern=r"^(zip|tar\.gz)$")


class BackupPolicyUpdate(BaseModel):
    enabled: bool = False
    frequency: str = Field(default="daily", pattern=r"^(daily|weekly)$")
    time: str = Field(default="03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=0, ge=0, le=6)
    retention_count: int = Field(default=7, ge=1, le=365)


class BulkDiscountRule(BaseModel):
    min_sheets: int = Field(ge=1, le=100000)
    discount: float = Field(gt=0, le=1)

    @field_validator("discount", mode="before")
    @classmethod
    def normalize_discount(cls, value):
        discount = float(value)
        if discount > 1 and discount <= 100:
            return discount / 100
        return discount


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=4, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=64)
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    balance: float = Field(default=0, ge=0, le=100000)
    is_admin: bool = False
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=4, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str | None = Field(default=None, min_length=8, max_length=64)
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    is_admin: bool | None = None
    is_active: bool | None = None


class SettingsUpdate(BaseModel):
    pricing_mode: str | None = Field(default=None, pattern="^(standard|coverage_tiered)$")
    single_price: float | None = Field(default=None, ge=0)
    duplex_price: float | None = Field(default=None, ge=0)
    coverage_single_base_price: float | None = Field(default=None, ge=0)
    coverage_duplex_base_price: float | None = Field(default=None, ge=0)
    bulk_discount_enabled: bool | None = None
    bulk_discount_rules: list[BulkDiscountRule] | None = None
    daily_limited_offer_enabled: bool | None = None
    daily_limited_offer_all_day: bool | None = None
    daily_limited_offer_start_time: str | None = Field(default=None, pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    daily_limited_offer_end_time: str | None = Field(default=None, pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    daily_limited_offer_sheet_quota: int | None = Field(default=None, ge=0, le=1000000)
    daily_limited_offer_discount: float | None = Field(default=None, gt=0, le=1)
    daily_limited_offer_free: bool | None = None
    min_balance: float | None = Field(default=None, ge=0)
    safety_coverage_limit: float | None = Field(default=None, ge=0, le=100)
    max_file_size_mb: int | None = Field(default=None, ge=1)
    max_pages: int | None = Field(default=None, ge=1)
    default_printer: str | None = Field(default=None, max_length=80)
    cups_allow_external_printers: bool | None = None
    cups_connection_mode: str | None = Field(default=None, pattern="^(bridge|host|custom_route)$")
    cups_network_interface: str | None = Field(default=None, max_length=32, pattern=r"^$|^[A-Za-z0-9_.:-]+$")
    cups_static_route_gateway: str | None = Field(default=None, max_length=64, pattern=r"^$|^[A-Za-z0-9_.:-]+$")
    cups_server: str | None = Field(default=None, max_length=255, pattern=r"^$|^[A-Za-z0-9._-]+(:\d+)?$")
    cups_user: str | None = Field(default=None, max_length=64)
    cups_password: str | None = Field(default=None, max_length=128)

    @field_validator("daily_limited_offer_discount", mode="before")
    @classmethod
    def normalize_daily_discount(cls, value):
        if value is None:
            return value
        discount = float(value)
        if discount > 1 and discount <= 100:
            return discount / 100
        return discount


class PrinterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    uri: str | None = Field(default=None, max_length=512)
    device: dict | None = None
    host: str | None = Field(default=None, max_length=253)
    connection_type: str | None = Field(default="ipp", max_length=40)
    queue_path: str | None = Field(default=None, max_length=160)
    driver: str = Field(default="everywhere", min_length=1, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=240)
    is_default: bool = False
    is_enabled: bool = True
    accepting_jobs: bool = True
    # 【新增功能】打印机属性：是否支持彩色打印 / 是否支持自动双面打印
    is_support_color: bool = False
    is_support_auto_duplex: bool = True


class PrinterImport(PrinterCreate):
    installed: bool = False


class PrinterFromTemplateRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=253)
    queue_name: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_.-]*$")
    display_name: str | None = Field(default=None, max_length=120)
    connection_type: str | None = Field(default=None, max_length=40)
    is_default: bool = False
    is_enabled: bool = True


class PrinterUpdate(BaseModel):
    new_name: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    uri: str | None = Field(default=None, min_length=1, max_length=512)
    host: str | None = Field(default=None, max_length=253)
    connection_type: str | None = Field(default=None, max_length=40)
    queue_path: str | None = Field(default=None, max_length=160)
    driver: str | None = Field(default=None, min_length=1, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=240)
    is_default: bool | None = None
    is_enabled: bool | None = None
    accepting_jobs: bool | None = None
    # 【新增功能】打印机属性：是否支持彩色打印 / 是否支持自动双面打印。
    # 为 None 表示本次请求没有携带该字段，后端保持数据库原值不变（兼容旧前端）。
    is_support_color: bool | None = None
    is_support_auto_duplex: bool | None = None


class PrinterEnabledUpdate(BaseModel):
    enabled: bool = True
    accepting_jobs: bool = True


class PrinterUriProbe(BaseModel):
    uri: str | None = Field(default=None, max_length=512)
    host: str | None = Field(default=None, max_length=253)
    connection_type: str | None = Field(default="ipp", max_length=40)
    queue_path: str | None = Field(default=None, max_length=160)


class PrinterTestResult(BaseModel):
    success: bool
    note: str | None = Field(default=None, max_length=240)


class PrinterTestPageRequest(BaseModel):
    copies: int = Field(default=1, ge=1, le=20)
    duplex: bool = False
    page_size: str = Field(default="A4", max_length=20)


class PaymentSettingsUpdate(BaseModel):
    epay_gateway: str = Field(min_length=1, max_length=512)
    epay_pid: str = Field(min_length=1, max_length=120)
    epay_key: str | None = Field(default=None, max_length=256)
    public_base_url: str = Field(min_length=1, max_length=512)
    frontend_base_url: str = Field(min_length=1, max_length=512)


class PaymentTestRequest(BaseModel):
    payment_method: str = "alipay"
    amount: float = Field(default=0.01, ge=0.01, le=100)

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment_method(cls, value):
        payment_method = normalize_payment_method_value(value)
        if payment_method == "balance":
            raise ValueError("测试支付仅支持微信或支付宝")
        return payment_method
