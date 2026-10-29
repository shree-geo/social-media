"""Platform settings a super admin edits: /api/v1/platform/settings."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import PLATFORM_ALL, PlatformContext, require_platform_role
from app.models import PlatformSetting
from app.schemas.platform import SiteContact, SiteContactIn
from app.services import audit

router = APIRouter(tags=["platform"])

SuperAdmin = Annotated[PlatformContext, Depends(require_platform_role("PLATFORM_SUPER_ADMIN"))]
AnyStaff = Annotated[PlatformContext, Depends(require_platform_role(*PLATFORM_ALL))]


def _out(row: PlatformSetting | None) -> SiteContact:
    return SiteContact(
        support_phone=row.support_phone if row else None, support_email=row.support_email if row else None
    )


@router.get("/settings")
async def get_settings(ctx: AnyStaff) -> SiteContact:
    return _out(await ctx.session.get(PlatformSetting, 1))


@router.patch("/settings")
async def update_settings(body: SiteContactIn, ctx: SuperAdmin) -> SiteContact:
    row = await ctx.session.get(PlatformSetting, 1, with_for_update=True)
    before = _out(row).model_dump()
    if row is None:
        row = PlatformSetting(id=1)
        ctx.session.add(row)
    row.support_phone = body.support_phone.strip() if body.support_phone else None
    row.support_email = str(body.support_email) if body.support_email else None
    row.updated_by_platform_user_id = ctx.user_id
    await ctx.session.flush()
    after = _out(row)
    await audit.record(
        ctx.session,
        action="PLATFORM_SETTINGS_UPDATED",
        actor_type="platform_user",
        actor_id=ctx.user_id,
        tenant_id=None,
        resource_type="platform_settings",
        before=before,
        after=after.model_dump(),
        request=ctx.request,
    )
    return after
