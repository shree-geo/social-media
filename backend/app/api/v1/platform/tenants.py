"""Platform console: plans, tenants, subscriptions — /api/v1/platform/*"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.api.deps import PLATFORM_ADMINS, PLATFORM_ALL, PlatformContext, require_platform_role
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.models import MembershipRole, Plan, PlanFeature, PlanPrice, Role, Subscription, Tenant, TenantMembership, User
from app.schemas.auth import StrictModel
from app.schemas.platform import (
    LoginDetailsOut,
    PaymentIn,
    PlanCreate,
    PlanFeatureOut,
    PlanOut,
    PlanPriceOut,
    RenewalOut,
    SubscriptionOut,
    TenantCreate,
    TenantCreated,
    TenantListItem,
)
from app.services import onboarding, users
from app.services.login_messages import share_message
from app.services.subscriptions import effective_status, tenant_today
from app.services.users import LoginDetails

router = APIRouter(tags=["platform"])

Admin = Annotated[PlatformContext, Depends(require_platform_role(*PLATFORM_ADMINS))]
SuperAdmin = Annotated[PlatformContext, Depends(require_platform_role("PLATFORM_SUPER_ADMIN"))]
AnyStaff = Annotated[PlatformContext, Depends(require_platform_role(*PLATFORM_ALL))]


def _subscription_out(sub: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=sub.id,
        plan_id=sub.plan_id,
        status=sub.status,
        billing_cycle=sub.billing_cycle,
        price_amount=sub.price_amount,
        discount_amount=sub.discount_amount,
        currency=sub.currency,
        start_date=sub.start_date,
        expiry_date=sub.expiry_date,
        trial_ends_at=sub.trial_ends_at,
        grace_period_days=sub.grace_period_days,
    )


def _login_out(details: LoginDetails, full_name: str) -> LoginDetailsOut:
    settings = get_settings()
    login_url = f"{settings.app_base_url}/login"
    message = None
    if details.temporary_password and details.expires_at:
        message = share_message(
            app_name=settings.app_name,
            login_url=login_url,
            full_name=full_name,
            email=details.email,
            temporary_password=details.temporary_password,
            expires_at=details.expires_at,
        )
    return LoginDetailsOut(
        login_url=login_url,
        email=details.email,
        temporary_password=details.temporary_password,
        expires_at=details.expires_at,
        share_message=message,
    )


# --- plans -------------------------------------------------------------------------


async def _plan_out(ctx: PlatformContext, plan: Plan) -> PlanOut:
    prices = (await ctx.session.execute(select(PlanPrice).where(PlanPrice.plan_id == plan.id))).scalars().all()
    features = (await ctx.session.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id))).scalars().all()
    return PlanOut(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        description=plan.description,
        is_active=plan.is_active,
        prices=[
            PlanPriceOut(
                id=p.id,
                billing_cycle=p.billing_cycle,
                amount=p.amount,
                currency=p.currency,
                effective_from=p.effective_from,
                is_active=p.is_active,
            )
            for p in prices
        ],
        features=[
            PlanFeatureOut(feature_key=f.feature_key, limit_value=f.limit_value, enabled=f.enabled) for f in features
        ],
    )


@router.get("/plans")
async def list_plans(ctx: AnyStaff) -> list[PlanOut]:
    plans = (await ctx.session.execute(select(Plan).order_by(Plan.sort_order, Plan.name))).scalars().all()
    return [await _plan_out(ctx, plan) for plan in plans]


@router.post("/plans", status_code=201)
async def create_plan(body: PlanCreate, ctx: SuperAdmin) -> PlanOut:
    plan = await onboarding.create_plan(
        ctx.session,
        code=body.code,
        name=body.name,
        description=body.description,
        prices=[onboarding.PlanPriceInput(p.billing_cycle, p.amount, p.currency) for p in body.prices],
        features=[onboarding.PlanFeatureInput(f.feature_key, f.limit_value, f.enabled) for f in body.features],
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    await ctx.session.flush()
    return await _plan_out(ctx, plan)


# --- tenants -----------------------------------------------------------------------


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreate, ctx: Admin) -> TenantCreated:
    payment = body.initial_payment
    created = await onboarding.create_tenant(
        ctx.session,
        onboarding.NewTenantInput(
            business_name=body.business_name,
            legal_name=body.legal_name,
            email=body.email,
            phone=body.phone,
            address=body.address,
            tax_number=body.tax_number,
            vat_registered=body.vat_registered,
            timezone=body.timezone,
            numbering_period=body.numbering_period,
            plan_id=body.plan_id,
            billing_cycle=body.billing_cycle,
            start_date=body.start_date,
            expiry_date=body.expiry_date,
            trial_days=body.trial_days,
            discount_amount=body.discount_amount,
            discount_reason=body.discount_reason,
            grace_period_days=body.grace_period_days,
            owner_full_name=body.owner_full_name,
            owner_email=body.owner_email,
            owner_phone=body.owner_phone,
            initial_payment=onboarding.PaymentInput(
                amount=payment.amount,
                payment_method=payment.payment_method,
                paid_at=payment.paid_at,
                transaction_reference=payment.transaction_reference,
                notes=payment.notes,
            )
            if payment
            else None,
        ),
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    return TenantCreated(
        tenant_id=created.tenant.id,
        business_name=created.tenant.business_name,
        subscription=_subscription_out(created.subscription),
        receipt_number=created.receipt_number,
        owner_login=_login_out(created.owner_login, body.owner_full_name),
    )


@router.get("/tenants")
async def list_tenants(
    ctx: AnyStaff,
    status: Annotated[str | None, Query(pattern="^(TRIAL|ACTIVE|GRACE|EXPIRED|SUSPENDED|CANCELLED)$")] = None,
    expiring_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[TenantListItem]:
    sub = aliased(Subscription)
    rows = await ctx.session.execute(
        select(Tenant, sub, Plan.code)
        .outerjoin(sub, (sub.tenant_id == Tenant.id) & (sub.status != "CANCELLED"))
        .outerjoin(Plan, Plan.id == sub.plan_id)
        .where(Tenant.deleted_at.is_(None))
        .order_by(Tenant.created_at.desc())
        .limit(500)
    )
    items: list[TenantListItem] = []
    for tenant, subscription, plan_code in rows:
        today = tenant_today(tenant.timezone)
        current = None
        days = None
        if subscription is not None:
            current = effective_status(
                subscription.status,
                trial_ends_at=subscription.trial_ends_at,
                expiry_date=subscription.expiry_date,
                grace_period_days=subscription.grace_period_days,
                today=today,
            )
            days = (subscription.expiry_date - today).days
        if status and current != status:
            continue
        if expiring_within_days is not None and (days is None or not 0 <= days <= expiring_within_days):
            continue
        items.append(
            TenantListItem(
                tenant_id=tenant.id,
                business_name=tenant.business_name,
                status=tenant.status,
                plan_code=plan_code,
                subscription_status=current,
                expiry_date=subscription.expiry_date if subscription else None,
                days_remaining=days,
                created_at=tenant.created_at,
            )
        )
        if len(items) >= limit:
            break
    return items


@router.post("/tenants/{tenant_id}/owner/reset-login")
async def reset_owner_login(tenant_id: uuid.UUID, ctx: Admin) -> LoginDetailsOut:
    owner = (
        await ctx.session.execute(
            select(TenantMembership)
            .join(MembershipRole, MembershipRole.membership_id == TenantMembership.id)
            .join(Role, Role.id == MembershipRole.role_id)
            .where(TenantMembership.tenant_id == tenant_id, Role.code == "OWNER")
            .order_by(TenantMembership.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner is None:
        raise NotFound()
    details = await users.reset_login(
        ctx.session,
        tenant_id=tenant_id,
        user_id=owner.user_id,
        actor_type="platform_user",
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    user = await ctx.session.get(User, owner.user_id)
    return _login_out(details, user.full_name if user else "")


class StatusChange(StrictModel):
    action: Literal["suspend", "reactivate", "cancel"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/subscriptions/{subscription_id}/status")
async def change_subscription_status(subscription_id: uuid.UUID, body: StatusChange, ctx: Admin) -> SubscriptionOut:
    sub = await onboarding.change_status(
        ctx.session,
        subscription_id=subscription_id,
        action=body.action,
        reason=body.reason,
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    return _subscription_out(sub)


@router.post("/subscriptions/{subscription_id}/payments", status_code=201)
async def record_subscription_payment(subscription_id: uuid.UUID, body: PaymentIn, ctx: Admin) -> RenewalOut:
    sub, receipt = await onboarding.renew_subscription(
        ctx.session,
        subscription_id=subscription_id,
        payment=onboarding.PaymentInput(
            amount=body.amount,
            payment_method=body.payment_method,
            paid_at=body.paid_at,
            transaction_reference=body.transaction_reference,
            notes=body.notes,
        ),
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    return RenewalOut(subscription=_subscription_out(sub), receipt_number=receipt)
