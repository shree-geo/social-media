import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import StrictModel

BillingCycle = Literal["monthly", "quarterly", "half_yearly", "yearly"]
SubscriptionPaymentMethod = Literal["bank_transfer", "esewa", "khalti", "fonepay", "cash", "cheque", "other"]
Money = Decimal


class PlanPriceIn(StrictModel):
    billing_cycle: BillingCycle
    amount: Money = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="NPR", pattern=r"^[A-Z]{3}$")


class PlanFeatureIn(StrictModel):
    feature_key: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    limit_value: int | None = Field(default=None, ge=0)
    enabled: bool = True


class PlanCreate(StrictModel):
    code: str = Field(pattern=r"^PLAN_[A-Z0-9_]{2,40}$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    prices: list[PlanPriceIn] = Field(min_length=1)
    features: list[PlanFeatureIn] = Field(default_factory=list)


class PlanPriceOut(BaseModel):
    id: uuid.UUID
    billing_cycle: str
    amount: Money
    currency: str
    effective_from: date
    is_active: bool


class PlanFeatureOut(BaseModel):
    feature_key: str
    limit_value: int | None
    enabled: bool


class PlanOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    prices: list[PlanPriceOut]
    features: list[PlanFeatureOut]


class PaymentIn(StrictModel):
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: SubscriptionPaymentMethod
    paid_at: datetime
    transaction_reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class TenantCreate(StrictModel):
    business_name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: dict[str, str] | None = None
    tax_number: str | None = Field(default=None, max_length=30)
    vat_registered: bool = False
    timezone: str = "Asia/Kathmandu"
    numbering_period: Literal["ad_year", "np_fiscal_year"] = "ad_year"

    plan_id: uuid.UUID
    billing_cycle: BillingCycle
    start_date: date
    expiry_date: date | None = None
    trial_days: int | None = Field(default=None, ge=1, le=90)
    discount_amount: Money = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    discount_reason: str | None = Field(default=None, max_length=500)
    grace_period_days: int = Field(default=7, ge=0, le=60)

    owner_full_name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    owner_phone: str | None = Field(default=None, max_length=30)

    initial_payment: PaymentIn | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        from zoneinfo import available_timezones

        if value not in available_timezones():
            raise ValueError("unknown timezone")
        return value


class LoginDetailsOut(BaseModel):
    """Returned once. ``temporary_password`` is null when an existing login was linked."""

    login_url: str
    email: str
    temporary_password: str | None
    expires_at: datetime | None
    share_message: str | None


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    status: str
    billing_cycle: str
    price_amount: Money
    discount_amount: Money
    currency: str
    start_date: date
    expiry_date: date
    trial_ends_at: date | None
    grace_period_days: int


class TenantCreated(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    subscription: SubscriptionOut
    receipt_number: str | None
    owner_login: LoginDetailsOut


class TenantListItem(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    status: str
    plan_code: str | None
    subscription_status: str | None
    expiry_date: date | None
    days_remaining: int | None
    created_at: datetime


class RenewalOut(BaseModel):
    subscription: SubscriptionOut
    receipt_number: str


class SiteContact(BaseModel):
    """Support contact shown on the public website and login screens."""

    support_phone: str | None
    support_email: str | None


class SiteContactIn(StrictModel):
    support_phone: str | None = Field(default=None, max_length=30, pattern=r"^\+?[0-9 ()-]{6,30}$")
    support_email: EmailStr | None = None
