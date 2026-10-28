"""Plan limits and feature flags (ARCHITECTURE.md §8). The only place plan numbers are read."""

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models import PlanFeature, Product, TenantMembership, UsageRecord


class PlanLimitExceeded(AppError):
    status, code, title = 403, "plan_limit_exceeded", "Your package limit has been reached"


# Live counters for count-based limits. Period limits (monthly orders...) use usage_records.
_COUNTERS = {
    "max_products": lambda tenant_id: (
        select(func.count()).select_from(Product).where(Product.tenant_id == tenant_id, Product.deleted_at.is_(None))
    ),
    "max_users": lambda tenant_id: (
        select(func.count())
        .select_from(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id, TenantMembership.status == "active")
    ),
}


async def _feature(session: AsyncSession, plan_id: uuid.UUID | None, key: str) -> PlanFeature | None:
    if plan_id is None:
        return None
    return (
        await session.execute(select(PlanFeature).where(PlanFeature.plan_id == plan_id, PlanFeature.feature_key == key))
    ).scalar_one_or_none()


async def limit(session: AsyncSession, plan_id: uuid.UUID | None, key: str) -> int | None:
    """``None`` means unlimited (no row, or ``limit_value`` NULL)."""
    feature = await _feature(session, plan_id, key)
    return feature.limit_value if feature and feature.enabled else None


async def enabled(session: AsyncSession, plan_id: uuid.UUID | None, key: str) -> bool:
    feature = await _feature(session, plan_id, key)
    return bool(feature and feature.enabled)


async def require_capacity(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID | None, key: str, adding: int = 1
) -> None:
    maximum = await limit(session, plan_id, key)
    if maximum is None:
        return
    # Serialize concurrent additions for this tenant + limit inside the transaction.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"{tenant_id}:{key}"})
    current = (await session.execute(_COUNTERS[key](tenant_id))).scalar_one()
    if current + adding > maximum:
        raise PlanLimitExceeded(f"Your package allows {maximum}.", limit=key, maximum=maximum, current=current)


async def count_usage(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID | None, metric: str, key: str, period_start: date
) -> None:
    """Monthly limits (e.g. ``max_monthly_orders``): count one use, refusing when over the limit."""
    maximum = await limit(session, plan_id, key)
    period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    stmt = (
        insert(UsageRecord)
        .values(tenant_id=tenant_id, metric=metric, period_start=period_start, period_end=period_end, quantity=1)
        .on_conflict_do_update(
            index_elements=["tenant_id", "metric", "period_start"],
            set_={"quantity": UsageRecord.quantity + 1, "updated_at": func.now()},
        )
        .returning(UsageRecord.quantity)
    )
    used = (await session.execute(stmt)).scalar_one()
    if maximum is not None and used > maximum:
        raise PlanLimitExceeded(
            f"Your package allows {maximum} orders a month.", limit=key, maximum=maximum, current=used - 1
        )
