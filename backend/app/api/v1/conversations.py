"""Unified inbox: /api/v1/conversations (spec §14, ARCHITECTURE.md §12)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.api import pagination
from app.api.deps import TenantContext, require
from app.core.exceptions import AppError, NotFound
from app.models import ChannelAccount, Conversation, Customer, Message, MessageAttachment, TenantMembership
from app.schemas.auth import StrictModel
from app.services import audit, idempotency, messaging, realtime
from app.workers.queue import enqueue

router = APIRouter(prefix="/conversations", tags=["inbox"])

Reader = Annotated[TenantContext, Depends(require("conversation.read"))]
Writer = Annotated[TenantContext, Depends(require("conversation.write", write=True))]


class CustomerSummary(BaseModel):
    id: uuid.UUID
    display_name: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    provider: str
    channel_account_id: uuid.UUID
    channel_name: str | None
    customer: CustomerSummary
    status: str
    last_message_preview: str | None
    last_message_at: datetime | None
    unread_count: int
    assigned_to_user_id: uuid.UUID | None
    window_open: bool
    window_closes_at: datetime | None  # end of the 24h reply window (None: customer never wrote)


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    next_cursor: str | None


class AttachmentOut(BaseModel):
    id: uuid.UUID
    mime_type: str | None
    filename: str | None
    caption: str | None
    download_status: str


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    sender_type: str
    sender_user_id: uuid.UUID | None
    message_type: str
    body: str | None
    status: str
    error_code: str | None
    error_message: str | None
    timestamp: datetime
    attachments: list[AttachmentOut]


class MessagePage(BaseModel):
    items: list[MessageOut]  # newest first
    next_cursor: str | None


class SendText(StrictModel):
    text: str = Field(min_length=1, max_length=messaging.MAX_TEXT_LENGTH)


class AssignRequest(StrictModel):
    user_id: uuid.UUID | None


class InvalidAssignee(AppError):
    status, code, title = 422, "invalid_assignee", "That person is not an active member of this business"


def _out(conversation: Conversation, customer: Customer, account: ChannelAccount) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        provider=conversation.provider,
        channel_account_id=conversation.channel_account_id,
        channel_name=account.display_name or account.display_phone,
        customer=CustomerSummary(id=customer.id, display_name=customer.display_name),
        status=conversation.status,
        last_message_preview=conversation.last_message_preview,
        last_message_at=conversation.last_message_at,
        unread_count=conversation.unread_count,
        assigned_to_user_id=conversation.assigned_to_user_id,
        window_open=messaging.window_open(conversation.last_inbound_at),
        window_closes_at=conversation.last_inbound_at + messaging.CUSTOMER_SERVICE_WINDOW
        if conversation.last_inbound_at
        else None,
    )


async def _get(ctx: TenantContext, conversation_id: uuid.UUID) -> Conversation:
    conversation = await ctx.session.get(Conversation, conversation_id)
    if conversation is None:  # RLS: other tenants' rows are invisible → 404
        raise NotFound()
    return conversation


@router.get("")
async def list_conversations(
    ctx: Reader,
    view: Literal["all", "unread", "mine", "unassigned"] = "all",
    provider: Literal["whatsapp", "messenger"] | None = None,
    customer_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ConversationPage:
    query = (
        select(Conversation, Customer, ChannelAccount)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(ChannelAccount, ChannelAccount.id == Conversation.channel_account_id)
        .where(Conversation.tenant_id == ctx.tenant_id, Conversation.last_message_at.is_not(None))
    )
    if view == "unread":
        query = query.where(Conversation.unread_count > 0)
    elif view == "mine":
        query = query.where(Conversation.assigned_to_user_id == ctx.user_id)
    elif view == "unassigned":
        query = query.where(Conversation.assigned_to_user_id.is_(None))
    if provider:
        query = query.where(Conversation.provider == provider)
    if customer_id:
        query = query.where(Conversation.customer_id == customer_id)
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(
            or_(
                Conversation.last_message_at < stamp,
                and_(Conversation.last_message_at == stamp, Conversation.id < last_id),
            )
        )
    rows = (
        await ctx.session.execute(
            query.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(limit + 1)
        )
    ).all()
    items = [_out(c, cu, a) for c, cu, a in rows[:limit]]
    next_cursor = (
        pagination.encode(rows[limit - 1][0].last_message_at, rows[limit - 1][0].id) if len(rows) > limit else None
    )
    return ConversationPage(items=items, next_cursor=next_cursor)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, ctx: Reader) -> ConversationOut:
    conversation = await _get(ctx, conversation_id)
    customer = await ctx.session.get(Customer, conversation.customer_id)
    account = await ctx.session.get(ChannelAccount, conversation.channel_account_id)
    assert customer is not None and account is not None
    return _out(conversation, customer, account)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    ctx: Reader,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MessagePage:
    await _get(ctx, conversation_id)
    query = select(Message).where(Message.tenant_id == ctx.tenant_id, Message.conversation_id == conversation_id)
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(
            or_(Message.provider_timestamp < stamp, and_(Message.provider_timestamp == stamp, Message.id < last_id))
        )
    messages = (
        (
            await ctx.session.execute(
                query.order_by(Message.provider_timestamp.desc(), Message.id.desc()).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    page = messages[:limit]
    attachments: dict[uuid.UUID, list[AttachmentOut]] = {}
    if page:
        for att in (
            await ctx.session.execute(
                select(MessageAttachment).where(MessageAttachment.message_id.in_([m.id for m in page]))
            )
        ).scalars():
            attachments.setdefault(att.message_id, []).append(
                AttachmentOut(
                    id=att.id,
                    mime_type=att.mime_type,
                    filename=att.filename,
                    caption=att.caption,
                    download_status=att.download_status,
                )
            )
    return MessagePage(
        items=[
            MessageOut(
                id=m.id,
                direction=m.direction,
                sender_type=m.sender_type,
                sender_user_id=m.sender_user_id,
                message_type=m.message_type,
                body=m.body,
                status=m.status,
                error_code=m.error_code,
                error_message=m.error_message,
                timestamp=m.provider_timestamp,
                attachments=attachments.get(m.id, []),
            )
            for m in page
        ],
        next_cursor=pagination.encode(page[-1].provider_timestamp, page[-1].id) if len(messages) > limit else None,
    )


@router.post("/{conversation_id}/read", status_code=204)
async def mark_read(conversation_id: uuid.UUID, ctx: Reader, background: BackgroundTasks) -> None:
    conversation = await _get(ctx, conversation_id)
    if conversation.unread_count:
        conversation.unread_count = 0
        # After commit, so other tabs refetch the committed state.
        background.add_task(realtime.publish, ctx.tenant_id, "conversation.updated", conversation_id=conversation.id)


@router.post("/{conversation_id}/assign")
async def assign(
    conversation_id: uuid.UUID, body: AssignRequest, ctx: Writer, background: BackgroundTasks
) -> ConversationOut:
    conversation = await _get(ctx, conversation_id)
    if body.user_id is not None:
        member = (
            await ctx.session.execute(
                select(TenantMembership.id).where(
                    TenantMembership.tenant_id == ctx.tenant_id,
                    TenantMembership.user_id == body.user_id,
                    TenantMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise InvalidAssignee()
    before = conversation.assigned_to_user_id
    conversation.assigned_to_user_id = body.user_id
    await audit.record(
        ctx.session,
        action="CONVERSATION_ASSIGNED",
        actor_type="user",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        resource_type="conversation",
        resource_id=conversation.id,
        before={"assigned_to": before},
        after={"assigned_to": body.user_id},
        request=ctx.request,
    )
    background.add_task(realtime.publish, ctx.tenant_id, "conversation.updated", conversation_id=conversation.id)
    return await get_conversation(conversation_id, ctx)


@router.post("/{conversation_id}/messages", status_code=202, response_model=MessageOut)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendText,
    ctx: Writer,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MessageOut | JSONResponse:
    async def action() -> MessageOut:
        message = await messaging.queue_text(
            ctx.session,
            tenant_id=ctx.tenant_id,
            conversation_id=conversation_id,
            sender_user_id=ctx.user_id,
            body=body.text,
        )
        # Background tasks run after the response, i.e. after the transaction committed.
        background.add_task(enqueue, "messages.send", tenant_id=str(ctx.tenant_id), message_id=str(message.id))
        return MessageOut(
            id=message.id,
            direction=message.direction,
            sender_type=message.sender_type,
            sender_user_id=message.sender_user_id,
            message_type=message.message_type,
            body=message.body,
            status=message.status,
            error_code=None,
            error_message=None,
            timestamp=message.provider_timestamp,
            attachments=[],
        )

    result = await idempotency.run(
        ctx.session,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        scope=f"conversation:{conversation_id}:send",
        actor_id=ctx.user_id,
        request_body=body,
        status=202,
        action=action,
    )
    if isinstance(result, idempotency.Replayed):
        return JSONResponse(result.body, status_code=result.status)
    return result
