"""Platform users, plans (packages), tenants and SaaS subscriptions (DATABASE.md §4)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

PLATFORM_ROLES = ("PLATFORM_SUPER_ADMIN", "PLATFORM_ADMIN", "PLATFORM_SUPPORT")
BILLING_CYCLES = ("monthly", "quarterly", "half_yearly", "yearly")
SUBSCRIPTION_STATUSES = ("TRIAL", "ACTIVE", "GRACE", "EXPIRED", "SUSPENDED", "CANCELLED")
SUBSCRIPTION_PAYMENT_METHODS = ("bank_transfer", "esewa", "khalti", "fonepay", "cash", "cheque", "other")
SUBSCRIPTION_EVENTS = ("created", "renewed", "plan_changed", "status_changed", "dates_changed")
NUMBERING_PERIODS = ("ad_year", "np_fiscal_year")


class PlatformUser(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "platform_users"
    __table_args__ = (CheckConstraint(check_in("role", PLATFORM_ROLES), name="role"),)

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str]
    full_name: Mapped[str]
    role: Mapped[str]
    must_change_password: Mapped[bool] = mapped_column(server_default=text("true"))
    temp_password_expires_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    mfa_secret_enc: Mapped[bytes | None]
    mfa_enabled_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]


class PlatformSetting(Timestamps, Base):
    """Platform-wide settings a super admin edits (one row). Shown on the public website."""

    __tablename__ = "platform_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    support_phone: Mapped[str | None] = mapped_column(String(30))
    support_email: Mapped[str | None] = mapped_column(CITEXT)
    updated_by_platform_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_users.id"))


class Plan(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class PlanPrice(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "plan_prices"
    __table_args__ = (
        UniqueConstraint("plan_id", "billing_cycle", "currency", "effective_from"),
        CheckConstraint(check_in("billing_cycle", BILLING_CYCLES), name="billing_cycle"),
        CheckConstraint("amount >= 0", name="amount"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    billing_cycle: Mapped[str]
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'NPR'"))
    amount: Mapped[Decimal]
    effective_from: Mapped[date] = mapped_column(server_default=text("CURRENT_DATE"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class PlanFeature(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    feature_key: Mapped[str]
    limit_value: Mapped[int | None]  # NULL = unlimited
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))


class Tenant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(check_in("status", ("active", "closed")), name="status"),
        CheckConstraint(check_in("numbering_period", NUMBERING_PERIODS), name="numbering_period"),
    )

    business_name: Mapped[str]
    legal_name: Mapped[str | None]
    slug: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None]
    address: Mapped[dict[str, Any] | None]
    tax_number: Mapped[str | None]
    vat_registered: Mapped[bool] = mapped_column(server_default=text("false"))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'NPR'"))
    timezone: Mapped[str] = mapped_column(server_default=text("'Asia/Kathmandu'"))
    numbering_period: Mapped[str] = mapped_column(server_default=text("'ad_year'"))
    logo_object_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"), index=True)
    created_by_platform_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_users.id"))
    deleted_at: Mapped[datetime | None]


class TenantSettings(Timestamps, Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    prices_include_tax: Mapped[bool] = mapped_column(server_default=text("false"))
    default_payment_due_days: Mapped[int] = mapped_column(server_default=text("0"))
    allow_negative_stock: Mapped[bool] = mapped_column(server_default=text("true"))
    invoice_footer: Mapped[str | None]
    extra: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class Subscription(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "subscriptions"
    __extra_table_args__ = (
        CheckConstraint(check_in("status", SUBSCRIPTION_STATUSES), name="status"),
        CheckConstraint(check_in("billing_cycle", BILLING_CYCLES), name="billing_cycle"),
        CheckConstraint("expiry_date >= start_date", name="dates"),
        CheckConstraint("grace_period_days BETWEEN 0 AND 60", name="grace_period_days"),
        CheckConstraint("price_amount >= 0 AND discount_amount >= 0", name="amounts"),
        # One current subscription per tenant.
        Index("subscriptions_current_key", "tenant_id", unique=True, postgresql_where=text("status <> 'CANCELLED'")),
        Index("ix_subscriptions_status_expiry_date", "status", "expiry_date"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    plan_price_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_prices.id"))
    price_amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    billing_cycle: Mapped[str]
    discount_amount: Mapped[Decimal] = mapped_column(server_default=text("0"))
    discount_reason: Mapped[str | None]
    status: Mapped[str]
    trial_ends_at: Mapped[date | None]
    start_date: Mapped[date]
    expiry_date: Mapped[date]
    grace_period_days: Mapped[int] = mapped_column(server_default=text("7"))
    auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    pending_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]
    notes: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_users.id"))


class SubscriptionHistory(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "subscription_history"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "subscription_id"], ["subscriptions.tenant_id", "subscriptions.id"]),
        CheckConstraint(check_in("event_type", SUBSCRIPTION_EVENTS), name="event_type"),
        CheckConstraint(check_in("actor_type", ("platform_user", "system")), name="actor_type"),
        Index("ix_subscription_history_subscription_id_created_at", "subscription_id", "created_at"),
    )

    subscription_id: Mapped[uuid.UUID]
    event_type: Mapped[str]
    from_status: Mapped[str | None]
    to_status: Mapped[str | None]
    from_plan_id: Mapped[uuid.UUID | None]
    to_plan_id: Mapped[uuid.UUID | None]
    from_expiry_date: Mapped[date | None]
    to_expiry_date: Mapped[date | None]
    reason: Mapped[str | None]
    actor_type: Mapped[str]
    actor_id: Mapped[uuid.UUID | None]


class SubscriptionPayment(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "subscription_payments"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "subscription_id"], ["subscriptions.tenant_id", "subscriptions.id"]),
        CheckConstraint(check_in("payment_method", SUBSCRIPTION_PAYMENT_METHODS), name="payment_method"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("period_end > period_start", name="period"),
        CheckConstraint("voided_at IS NULL OR void_reason IS NOT NULL", name="void_reason"),
        Index("ix_subscription_payments_tenant_id_paid_at", "tenant_id", text("paid_at DESC")),
    )

    subscription_id: Mapped[uuid.UUID]
    receipt_number: Mapped[str] = mapped_column(unique=True)
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    payment_method: Mapped[str]
    transaction_reference: Mapped[str | None]
    paid_at: Mapped[datetime]
    period_start: Mapped[date]
    period_end: Mapped[date]
    receipt_object_id: Mapped[uuid.UUID | None]
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_users.id"))
    notes: Mapped[str | None]
    voided_at: Mapped[datetime | None]
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_users.id"))
    void_reason: Mapped[str | None]


class UsageRecord(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "usage_records"
    __extra_table_args__ = (UniqueConstraint("tenant_id", "metric", "period_start"),)

    metric: Mapped[str]
    period_start: Mapped[date]
    period_end: Mapped[date]
    quantity: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
