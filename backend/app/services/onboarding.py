"""Platform console: plans, tenant creation, subscription payments and renewal (spec §41-§42)."""

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.models import (
    Plan,
    PlanFeature,
    PlanPrice,
    Subscription,
    SubscriptionHistory,
    SubscriptionPayment,
    Tenant,
    TenantOnboarding,
    TenantSettings,
)
from app.services import audit, catalogue, numbering, users
from app.services.audit import RequestInfo
from app.services.subscriptions import effective_status, period_end, tenant_today
from app.services.users import LoginDetails


class PlanUnavailable(AppError):
    status, code, title = 422, "plan_unavailable", "This package or price is not available"


@dataclass(frozen=True)
class PlanPriceInput:
    billing_cycle: str
    amount: Decimal
    currency: str = "NPR"


@dataclass(frozen=True)
class PlanFeatureInput:
    feature_key: str
    limit_value: int | None = None
    enabled: bool = True


@dataclass(frozen=True)
class PaymentInput:
    amount: Decimal
    payment_method: str
    paid_at: datetime
    transaction_reference: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class NewTenantInput:
    business_name: str
    legal_name: str | None
    email: str | None
    phone: str | None
    address: dict[str, str] | None
    tax_number: str | None
    vat_registered: bool
    timezone: str
    numbering_period: str
    plan_id: uuid.UUID
    billing_cycle: str
    start_date: date
    expiry_date: date | None
    trial_days: int | None
    discount_amount: Decimal
    discount_reason: str | None
    grace_period_days: int
    owner_full_name: str
    owner_email: str
    owner_phone: str | None
    initial_payment: PaymentInput | None


@dataclass(frozen=True)
class CreatedTenant:
    tenant: Tenant
    subscription: Subscription
    owner_login: LoginDetails
    receipt_number: str | None


async def create_plan(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    description: str | None,
    prices: list[PlanPriceInput],
    features: list[PlanFeatureInput],
    actor_id: uuid.UUID,
    request: RequestInfo,
) -> Plan:
    if (await session.execute(select(Plan.id).where(Plan.code == code))).first():
        raise Conflict("A package with this code already exists.")
    plan = Plan(code=code, name=name, description=description)
    session.add(plan)
    await session.flush()
    session.add_all(
        PlanPrice(plan_id=plan.id, billing_cycle=p.billing_cycle, amount=p.amount, currency=p.currency) for p in prices
    )
    session.add_all(
        PlanFeature(plan_id=plan.id, feature_key=f.feature_key, limit_value=f.limit_value, enabled=f.enabled)
        for f in features
    )
    await audit.record(
        session,
        action="PLAN_CREATED",
        actor_type="platform_user",
        actor_id=actor_id,
        tenant_id=None,
        resource_type="plan",
        resource_id=plan.id,
        after={"code": code, "prices": [f"{p.billing_cycle}:{p.amount}" for p in prices]},
        request=request,
    )
    return plan


async def current_price(session: AsyncSession, plan_id: uuid.UUID, cycle: str, today: date) -> PlanPrice:
    plan = await session.get(Plan, plan_id)
    price = (
        await session.execute(
            select(PlanPrice)
            .where(
                PlanPrice.plan_id == plan_id,
                PlanPrice.billing_cycle == cycle,
                PlanPrice.is_active.is_(True),
                PlanPrice.effective_from <= today,
            )
            .order_by(PlanPrice.effective_from.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if plan is None or not plan.is_active or price is None:
        raise PlanUnavailable()
    return price


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "business"
    return f"{base}-{secrets.token_hex(3)}"


async def _history(
    session: AsyncSession,
    sub: Subscription,
    event: str,
    actor_id: uuid.UUID | None,
    *,
    from_status: str | None = None,
    from_plan: uuid.UUID | None = None,
    from_expiry: date | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        SubscriptionHistory(
            tenant_id=sub.tenant_id,
            subscription_id=sub.id,
            event_type=event,
            from_status=from_status,
            to_status=sub.status,
            from_plan_id=from_plan,
            to_plan_id=sub.plan_id,
            from_expiry_date=from_expiry,
            to_expiry_date=sub.expiry_date,
            reason=reason,
            actor_type="platform_user" if actor_id else "system",
            actor_id=actor_id,
        )
    )


async def _record_payment(
    session: AsyncSession,
    sub: Subscription,
    payment: PaymentInput,
    *,
    period_start: date,
    period_finish: date,
    actor_id: uuid.UUID,
    request: RequestInfo,
) -> str:
    receipt = await numbering.next_platform_number(session, "SUB", str(payment.paid_at.year))
    row = SubscriptionPayment(
        tenant_id=sub.tenant_id,
        subscription_id=sub.id,
        receipt_number=receipt,
        amount=payment.amount,
        currency=sub.currency,
        payment_method=payment.payment_method,
        transaction_reference=payment.transaction_reference,
        paid_at=payment.paid_at,
        period_start=period_start,
        period_end=period_finish,
        recorded_by=actor_id,
        notes=payment.notes,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        action="SUBSCRIPTION_PAYMENT_RECORDED",
        actor_type="platform_user",
        actor_id=actor_id,
        tenant_id=sub.tenant_id,
        resource_type="subscription_payment",
        resource_id=row.id,
        after={"receipt_number": receipt, "amount": str(payment.amount), "method": payment.payment_method},
        request=request,
    )
    return receipt


async def create_tenant(
    session: AsyncSession, data: NewTenantInput, *, actor_id: uuid.UUID, request: RequestInfo
) -> CreatedTenant:
    today = tenant_today(data.timezone)
    price = await current_price(session, data.plan_id, data.billing_cycle, today)

    tenant = Tenant(
        business_name=data.business_name,
        legal_name=data.legal_name,
        slug=_slug(data.business_name),
        email=data.email,
        phone=data.phone,
        address=data.address,
        tax_number=data.tax_number,
        vat_registered=data.vat_registered,
        currency=price.currency,
        timezone=data.timezone,
        numbering_period=data.numbering_period,
        created_by_platform_user_id=actor_id,
    )
    session.add(tenant)
    await session.flush()
    session.add_all([TenantSettings(tenant_id=tenant.id), TenantOnboarding(tenant_id=tenant.id)])
    await catalogue.ensure_default_tax_rates(session, tenant.id, data.vat_registered)

    if data.trial_days:
        trial_end = data.start_date + timedelta(days=data.trial_days - 1)
        status, expiry, trial_ends_at = "TRIAL", data.expiry_date or trial_end, trial_end
    else:
        status, expiry, trial_ends_at = (
            "ACTIVE",
            data.expiry_date or period_end(data.start_date, data.billing_cycle),
            None,
        )

    sub = Subscription(
        tenant_id=tenant.id,
        plan_id=data.plan_id,
        plan_price_id=price.id,
        price_amount=price.amount,
        currency=price.currency,
        billing_cycle=data.billing_cycle,
        discount_amount=data.discount_amount,
        discount_reason=data.discount_reason,
        status=status,
        trial_ends_at=trial_ends_at,
        start_date=data.start_date,
        expiry_date=expiry,
        grace_period_days=data.grace_period_days,
        created_by=actor_id,
    )
    session.add(sub)
    await session.flush()
    sub.status = effective_status(
        sub.status,
        trial_ends_at=sub.trial_ends_at,
        expiry_date=sub.expiry_date,
        grace_period_days=sub.grace_period_days,
        today=today,
    )
    await _history(session, sub, "created", actor_id)

    receipt = None
    if data.initial_payment:
        receipt = await _record_payment(
            session,
            sub,
            data.initial_payment,
            period_start=sub.start_date,
            period_finish=sub.expiry_date,
            actor_id=actor_id,
            request=request,
        )

    owner = await users.add_tenant_user(
        session,
        tenant_id=tenant.id,
        email=data.owner_email,
        full_name=data.owner_full_name,
        phone=data.owner_phone,
        role_code="OWNER",
        actor_type="platform_user",
        actor_id=actor_id,
        request=request,
    )
    await audit.record(
        session,
        action="TENANT_CREATED",
        actor_type="platform_user",
        actor_id=actor_id,
        tenant_id=tenant.id,
        resource_type="tenant",
        resource_id=tenant.id,
        after={
            "business_name": tenant.business_name,
            "plan_id": data.plan_id,
            "billing_cycle": data.billing_cycle,
            "status": sub.status,
            "expiry_date": sub.expiry_date.isoformat(),
        },
        request=request,
    )
    return CreatedTenant(tenant, sub, owner, receipt)


async def renew_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    payment: PaymentInput,
    actor_id: uuid.UUID,
    request: RequestInfo,
) -> tuple[Subscription, str]:
    """Record a payment for the next billing period and extend the expiry date."""
    sub = (
        await session.execute(select(Subscription).where(Subscription.id == subscription_id).with_for_update())
    ).scalar_one_or_none()
    if sub is None or sub.status == "CANCELLED":
        raise NotFound()
    tenant = await session.get(Tenant, sub.tenant_id)
    assert tenant is not None
    today = tenant_today(tenant.timezone)

    current = effective_status(
        sub.status,
        trial_ends_at=sub.trial_ends_at,
        expiry_date=sub.expiry_date,
        grace_period_days=sub.grace_period_days,
        today=today,
    )
    # Expired: the new period starts today. Otherwise it continues from the current expiry.
    start = today if current in ("EXPIRED", "TRIAL") else sub.expiry_date + timedelta(days=1)
    finish = period_end(start, sub.billing_cycle)

    from_status, from_expiry = sub.status, sub.expiry_date
    receipt = await _record_payment(
        session, sub, payment, period_start=start, period_finish=finish, actor_id=actor_id, request=request
    )
    sub.expiry_date = finish
    sub.trial_ends_at = None
    if sub.status != "SUSPENDED":  # payment alone does not lift a manual suspension
        sub.status = "ACTIVE"
    await _history(session, sub, "renewed", actor_id, from_status=from_status, from_expiry=from_expiry)
    await audit.record(
        session,
        action="SUBSCRIPTION_RENEWED",
        actor_type="platform_user",
        actor_id=actor_id,
        tenant_id=sub.tenant_id,
        resource_type="subscription",
        resource_id=sub.id,
        before={"status": from_status, "expiry_date": from_expiry.isoformat()},
        after={"status": sub.status, "expiry_date": finish.isoformat()},
        request=request,
    )
    return sub, receipt


class InvalidTransition(AppError):
    status, code, title = 409, "invalid_transition", "This change is not allowed in the current status"


async def _locked_subscription(session: AsyncSession, subscription_id: uuid.UUID) -> tuple[Subscription, Tenant]:
    sub = (
        await session.execute(select(Subscription).where(Subscription.id == subscription_id).with_for_update())
    ).scalar_one_or_none()
    tenant = await session.get(Tenant, sub.tenant_id) if sub else None
    if sub is None or tenant is None:
        raise NotFound()
    return sub, tenant


async def change_status(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    action: str,
    reason: str | None,
    actor_id: uuid.UUID,
    request: RequestInfo,
) -> Subscription:
    """Manual admin actions: ``suspend``, ``reactivate`` or ``cancel`` (ARCHITECTURE.md §8)."""
    sub, tenant = await _locked_subscription(session, subscription_id)
    before = sub.status
    if action == "suspend":
        if sub.status in ("SUSPENDED", "CANCELLED"):
            raise InvalidTransition()
        sub.status = "SUSPENDED"
    elif action == "reactivate":
        if sub.status != "SUSPENDED":
            raise InvalidTransition()
        # Back to whatever the dates say: ACTIVE, GRACE or EXPIRED.
        sub.status = effective_status(
            "ACTIVE",
            trial_ends_at=None,
            expiry_date=sub.expiry_date,
            grace_period_days=sub.grace_period_days,
            today=tenant_today(tenant.timezone),
        )
    elif action == "cancel":
        if sub.status == "CANCELLED":
            raise InvalidTransition()
        sub.status = "CANCELLED"
        sub.cancelled_at = datetime.now(UTC)
        sub.cancel_reason = reason
    else:
        raise InvalidTransition()

    await _history(session, sub, "status_changed", actor_id, from_status=before, reason=reason)
    await audit.record(
        session,
        action=f"SUBSCRIPTION_{action.upper()}",
        actor_type="platform_user",
        actor_id=actor_id,
        tenant_id=sub.tenant_id,
        resource_type="subscription",
        resource_id=sub.id,
        before={"status": before},
        after={"status": sub.status, "reason": reason},
        request=request,
    )
    return sub


async def recompute_statuses(session: AsyncSession, now: datetime | None = None) -> int:
    """Daily job: persist time-based transitions (TRIAL/ACTIVE → GRACE → EXPIRED). Returns rows changed."""
    rows = await session.execute(
        select(Subscription, Tenant.timezone)
        .join(Tenant, Tenant.id == Subscription.tenant_id)
        .where(Subscription.status.in_(("TRIAL", "ACTIVE", "GRACE")))
        .with_for_update(of=Subscription, skip_locked=True)
    )
    changed = 0
    for sub, timezone in rows:
        new = effective_status(
            sub.status,
            trial_ends_at=sub.trial_ends_at,
            expiry_date=sub.expiry_date,
            grace_period_days=sub.grace_period_days,
            today=tenant_today(timezone, now),
        )
        if new == sub.status:
            continue
        before, sub.status = sub.status, new
        await _history(session, sub, "status_changed", None, from_status=before)
        await audit.record(
            session,
            action="SUBSCRIPTION_STATUS_CHANGED",
            actor_type="system",
            actor_id=None,
            tenant_id=sub.tenant_id,
            resource_type="subscription",
            resource_id=sub.id,
            before={"status": before},
            after={"status": new},
        )
        changed += 1
    return changed
