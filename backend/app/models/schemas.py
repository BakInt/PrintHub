from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator


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
