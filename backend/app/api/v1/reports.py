"""Dashboard and reports: GET /api/v1/reports/dashboard (spec §22-24)."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.deps import TenantContext, require
from app.services import reports
from app.services.subscriptions import tenant_today

router = APIRouter(prefix="/reports", tags=["reports"])

ReportReader = Annotated[TenantContext, Depends(require("report.read"))]


@router.get("/dashboard")
async def dashboard(ctx: ReportReader, period: reports.Period = "7d") -> reports.Dashboard:
    tz = ctx.tenant.timezone
    today = tenant_today(tz)
    return await reports.dashboard(
        ctx.session,
        tenant_id=ctx.tenant_id,
        timezone=tz,
        currency=ctx.tenant.currency,
        window=reports.resolve_period(period, today, ZoneInfo(tz)),
        today=today,
    )
