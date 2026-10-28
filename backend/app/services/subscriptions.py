"""Subscription status rules and access levels (spec §42, ARCHITECTURE.md §8).

Status is recomputed from dates on read as well as by the daily job, so access is
correct even if the job runs late.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription

BillingCycle = Literal["monthly", "quarterly", "half_yearly", "yearly"]
_CYCLE_MONTHS: dict[str, int] = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


class Access(StrEnum):
    FULL = "full"  # TRIAL, ACTIVE, GRACE
    READ_ONLY = "read_only"  # EXPIRED: view and export, no changes
    BLOCKED = "blocked"  # SUSPENDED, CANCELLED, or no subscription


def effective_status(
    status: str, *, trial_ends_at: date | None, expiry_date: date, grace_period_days: int, today: date
) -> str:
    """Time-based transitions. Manual states (SUSPENDED, CANCELLED) and EXPIRED are kept as-is."""
    if status in ("SUSPENDED", "CANCELLED", "EXPIRED"):
        return status
    if status == "TRIAL":
        end = trial_ends_at or expiry_date
        return "TRIAL" if today <= end else "EXPIRED"
    # ACTIVE or GRACE
    if today <= expiry_date:
        return "ACTIVE"
    if today <= expiry_date + timedelta(days=grace_period_days):
        return "GRACE"
    return "EXPIRED"


def access_for(status: str | None) -> Access:
    if status in ("TRIAL", "ACTIVE", "GRACE"):
        return Access.FULL
    if status == "EXPIRED":
        return Access.READ_ONLY
    return Access.BLOCKED


def period_end(start: date, cycle: str) -> date:
    """Last day covered by one billing period starting on ``start`` (inclusive)."""
    return start + relativedelta(months=_CYCLE_MONTHS[cycle]) - timedelta(days=1)


def tenant_today(timezone: str, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()


@dataclass(frozen=True)
class SubscriptionState:
    subscription_id: uuid.UUID | None
    status: str | None
    access: Access
    plan_id: uuid.UUID | None
    expiry_date: date | None
    days_remaining: int | None


NO_SUBSCRIPTION = SubscriptionState(None, None, Access.BLOCKED, None, None, None)


async def current_state(session: AsyncSession, tenant_id: uuid.UUID, today: date) -> SubscriptionState:
    sub = (
        await session.execute(
            select(Subscription).where(Subscription.tenant_id == tenant_id, Subscription.status != "CANCELLED")
        )
    ).scalar_one_or_none()
    if sub is None:
        return NO_SUBSCRIPTION
    status = effective_status(
        sub.status,
        trial_ends_at=sub.trial_ends_at,
        expiry_date=sub.expiry_date,
        grace_period_days=sub.grace_period_days,
        today=today,
    )
    return SubscriptionState(
        subscription_id=sub.id,
        status=status,
        access=access_for(status),
        plan_id=sub.plan_id,
        expiry_date=sub.expiry_date,
        days_remaining=(sub.expiry_date - today).days,
    )
