"""Connected channels and the connect wizard: /api/v1/channels (ONBOARDING_AND_CHANNEL_SETUP.md §6, §8, §12)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import TenantContext, require
from app.core.config import get_settings
from app.models import ChannelAccount, Message
from app.schemas.auth import StrictModel
from app.services import channels

router = APIRouter(prefix="/channels", tags=["channels"])

Viewer = Annotated[TenantContext, Depends(require("channel.manage"))]
Manager = Annotated[TenantContext, Depends(require("channel.manage", write=True))]


class ChannelOut(BaseModel):
    id: uuid.UUID
    provider: str
    name: str | None
    display_phone: str | None
    picture: str | None
    status: str
    health_status: str
    health_reason: str | None
    last_webhook_at: datetime | None
    messages_today: int


class ChannelsOut(BaseModel):
    items: list[ChannelOut]
    messenger_available: bool  # our Meta app is configured on this server
    messenger_limit: int | None
    messenger_used: int


class StartSetup(StrictModel):
    provider: Literal["messenger"]
    mode: Literal["page"] = "page"


class SetupStarted(BaseModel):
    id: uuid.UUID
    state: str
    expires_at: datetime
    app_id: str
    login_config_id: str
    graph_api_version: str


class Authorize(StrictModel):
    state: str = Field(min_length=10, max_length=200)
    access_token: str = Field(min_length=10, max_length=4096)  # short-lived user token from the login dialog


class PageOption(BaseModel):
    id: str
    name: str
    picture: str | None
    status: Literal["connectable", "connected_here", "connected_elsewhere", "needs_full_control"]


class Authorized(BaseModel):
    pages: list[PageOption]
    limit: int | None
    used: int


class Complete(StrictModel):
    page_ids: list[str] = Field(min_length=1, max_length=20)


class PageResultOut(BaseModel):
    page_id: str
    name: str
    ok: bool
    channel_account_id: uuid.UUID | None
    error_code: str | None
    message: str | None


@router.get("")
async def list_channels(ctx: Viewer) -> ChannelsOut:
    accounts = (
        (
            await ctx.session.execute(
                select(ChannelAccount)
                .where(ChannelAccount.tenant_id == ctx.tenant_id)
                .order_by(ChannelAccount.status, ChannelAccount.provider, ChannelAccount.display_name)
            )
        )
        .scalars()
        .all()
    )
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    counts: dict[Any, int] = dict(
        (
            await ctx.session.execute(
                select(Message.channel_account_id, func.count())
                .where(Message.tenant_id == ctx.tenant_id, Message.created_at >= midnight)
                .group_by(Message.channel_account_id)
            )
        ).all()
    )
    capacity = await channels.messenger_capacity(ctx.session, ctx.tenant_id, ctx.subscription.plan_id)
    return ChannelsOut(
        items=[
            ChannelOut(
                id=a.id,
                provider=a.provider,
                name=a.display_name,
                display_phone=a.display_phone,
                picture=(a.provider_metadata or {}).get("picture"),
                status=a.status,
                health_status=a.health_status,
                health_reason=a.health_reason,
                last_webhook_at=a.last_webhook_at,
                messages_today=counts.get(a.id, 0),
            )
            for a in accounts
        ],
        messenger_available=get_settings().meta_configured and bool(get_settings().meta_login_config_id_messenger),
        messenger_limit=capacity.maximum,
        messenger_used=capacity.used,
    )


@router.post("/setup-sessions", status_code=201)
async def start_setup(body: StartSetup, ctx: Manager) -> SetupStarted:
    settings = get_settings()
    if not settings.meta_login_config_id_messenger:
        raise channels.ChannelsNotConfigured()
    setup, state = await channels.start_setup(
        ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, provider=body.provider, mode=body.mode
    )
    return SetupStarted(
        id=setup.id,
        state=state,
        expires_at=setup.expires_at,
        app_id=settings.meta_app_id,
        login_config_id=settings.meta_login_config_id_messenger,
        graph_api_version=settings.meta_graph_api_version,
    )


@router.post("/setup-sessions/{setup_id}/authorize")
async def authorize(setup_id: uuid.UUID, body: Authorize, ctx: Manager) -> Authorized:
    _, pages, capacity = await channels.authorize_messenger(
        ctx.session,
        tenant_id=ctx.tenant_id,
        setup_id=setup_id,
        state=body.state,
        user_token=body.access_token,
        plan_id=ctx.subscription.plan_id,
    )
    return Authorized(pages=[PageOption(**p) for p in pages], limit=capacity.maximum, used=capacity.used)


@router.post("/setup-sessions/{setup_id}/complete")
async def complete(setup_id: uuid.UUID, body: Complete, ctx: Manager) -> list[PageResultOut]:
    results = await channels.complete_messenger(
        ctx.session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        setup_id=setup_id,
        page_ids=body.page_ids,
        plan_id=ctx.subscription.plan_id,
        request=ctx.request,
    )
    return [
        PageResultOut(
            page_id=r.page_id,
            name=r.name,
            ok=r.ok,
            channel_account_id=r.channel_account_id,
            error_code=r.error_code,
            message=r.message,
        )
        for r in results
    ]


@router.post("/setup-sessions/{setup_id}/cancel", status_code=204)
async def cancel(setup_id: uuid.UUID, ctx: Manager) -> None:
    await channels.cancel_setup(ctx.session, tenant_id=ctx.tenant_id, setup_id=setup_id)


@router.post("/{account_id}/disconnect")
async def disconnect(account_id: uuid.UUID, ctx: Manager) -> ChannelOut:
    account = await channels.disconnect(
        ctx.session, tenant_id=ctx.tenant_id, account_id=account_id, actor_id=ctx.user_id, request=ctx.request
    )
    return ChannelOut(
        id=account.id,
        provider=account.provider,
        name=account.display_name,
        display_phone=account.display_phone,
        picture=(account.provider_metadata or {}).get("picture"),
        status=account.status,
        health_status=account.health_status,
        health_reason=account.health_reason,
        last_webhook_at=account.last_webhook_at,
        messages_today=0,
    )
