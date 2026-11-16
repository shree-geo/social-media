"""Business settings an owner or admin changes in the app (``settings.manage``)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import TenantContext, require
from app.models import TenantSettings
from app.schemas.auth import StrictModel
from app.services import audit

router = APIRouter(prefix="/settings", tags=["settings"])

Manager = Annotated[TenantContext, Depends(require("settings.manage"))]
Editor = Annotated[TenantContext, Depends(require("settings.manage", write=True))]


class BusinessSettingsOut(BaseModel):
    orders_need_lead: bool


class BusinessSettingsUpdate(StrictModel):
    orders_need_lead: bool | None = None


async def _settings(ctx: TenantContext) -> TenantSettings:
    row = await ctx.session.get(TenantSettings, ctx.tenant_id)
    if row is None:  # businesses created before settings rows existed
        row = TenantSettings(tenant_id=ctx.tenant_id)
        ctx.session.add(row)
        await ctx.session.flush()
        await ctx.session.refresh(row)
    return row


@router.get("")
async def get_settings(ctx: Manager) -> BusinessSettingsOut:
    row = await _settings(ctx)
    return BusinessSettingsOut(orders_need_lead=row.orders_need_lead)


@router.patch("")
async def update_settings(body: BusinessSettingsUpdate, ctx: Editor) -> BusinessSettingsOut:
    row = await _settings(ctx)
    if body.orders_need_lead is not None and body.orders_need_lead != row.orders_need_lead:
        before = row.orders_need_lead
        row.orders_need_lead = body.orders_need_lead
        await audit.record(
            ctx.session,
            action="SETTINGS_CHANGED",
            actor_type="user",
            actor_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            resource_type="tenant_settings",
            resource_id=ctx.tenant_id,
            before={"orders_need_lead": before},
            after={"orders_need_lead": row.orders_need_lead},
            request=ctx.request,
        )
    return BusinessSettingsOut(orders_need_lead=row.orders_need_lead)
