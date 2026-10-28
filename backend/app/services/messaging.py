"""Outbound messages (ARCHITECTURE.md §12).

API: check permission + subscription + 24h window → store ``queued`` → enqueue after commit.
Worker: ``sending`` → adapter → ``sent`` (+ provider id) | retry transient | ``failed`` permanent.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import platform_sessionmaker, runtime_sessionmaker, set_tenant_context
from app.core.exceptions import AppError, NotFound
from app.core.logging import get_logger
from app.integrations import registry
from app.integrations.base import ChannelAccountRef, OutboundText, PermanentSendError, TransientSendError
from app.models import ChannelAccount, Conversation, CustomerIdentity, Message
from app.services import channels, realtime
from app.workers.queue import enqueue

log = get_logger(__name__)

CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)
MAX_SEND_ATTEMPTS = 5
MAX_TEXT_LENGTH = 4096


class WindowClosed(AppError):
    status, code, title = 409, "window_closed", "You can reply within 24 hours of the customer's last message"


class ChannelUnavailable(AppError):
    status, code, title = 409, "channel_unavailable", "This channel is not connected"


def window_open(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    return last_inbound_at is not None and (now or datetime.now(UTC)) - last_inbound_at < CUSTOMER_SERVICE_WINDOW


async def queue_text(
    session: AsyncSession, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, sender_user_id: uuid.UUID, body: str
) -> Message:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        raise NotFound()
    account = await session.get(ChannelAccount, conversation.channel_account_id)
    if account is None or account.status != "connected":
        raise ChannelUnavailable()
    if not window_open(conversation.last_inbound_at):
        raise WindowClosed()

    now = datetime.now(UTC)
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        channel_account_id=conversation.channel_account_id,
        direction="outbound",
        sender_type="user",
        sender_user_id=sender_user_id,
        message_type="text",
        body=body,
        status="queued",
        provider_timestamp=now,
    )
    session.add(message)
    conversation.last_message_at = now
    conversation.last_message_preview = body[:120]
    conversation.unread_count = 0  # replying means the agent has read the thread
    await session.flush()
    return message


async def _access_token(session: AsyncSession, account: ChannelAccount) -> str:
    token = await channels.access_token(session, account)
    if token is None:
        raise PermanentSendError("No credential for this channel", code="no_credential")
    return token


credential_aad = channels.credential_aad  # kept for existing imports


async def send(tenant_id: uuid.UUID, message_id: uuid.UUID) -> str:
    """Worker entry point. Returns the resulting status; ``retry`` means try again later."""
    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        message = (
            await session.execute(select(Message).where(Message.id == message_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        # Only "queued": a message left in "sending" may already have reached the customer.
        if message is None or message.status != "queued":
            return message.status if message else "missing"
        conversation = await session.get(Conversation, message.conversation_id)
        account = await session.get(ChannelAccount, message.channel_account_id)
        identity = await session.get(CustomerIdentity, conversation.customer_identity_id) if conversation else None
        adapter = registry.get(account.provider) if account else None
        message.status = "sending"
        message.send_attempts += 1
        attempts = message.send_attempts
        try:
            if conversation is None or account is None or identity is None or adapter is None:
                raise PermanentSendError("Channel is not available", code="channel_unavailable")
            if not window_open(conversation.last_inbound_at):
                raise PermanentSendError("24-hour window closed", code="window_closed")
            token = await _access_token(session, account)
        except PermanentSendError as exc:
            _fail(message, exc.code, str(exc))
            outcome = "failed"
        else:
            outcome = "pending"
        ref = (
            ChannelAccountRef(str(account.id), account.external_account_id, token)
            if outcome == "pending" and account
            else None
        )
        to = identity.provider_user_id if identity else ""
        text, conversation_id = message.body or "", message.conversation_id

    if ref is not None and adapter is not None:
        # Provider call happens outside the DB transaction (never hold locks during network I/O).
        try:
            result = await adapter.send_text(ref, to, OutboundText(text))
        except TransientSendError as exc:
            outcome = await _finish(tenant_id, message_id, retry=attempts < MAX_SEND_ATTEMPTS, error=exc)
        except PermanentSendError as exc:
            outcome = await _finish(tenant_id, message_id, retry=False, error=exc)
        else:
            outcome = await _finish(tenant_id, message_id, provider_message_id=result.provider_message_id)

    if outcome == "retry":
        await enqueue(
            "messages.send", countdown=send_retry_delay(attempts), tenant_id=str(tenant_id), message_id=str(message_id)
        )
    else:
        await realtime.publish(
            tenant_id, "message.status", conversation_id=conversation_id, message_id=message_id, status=outcome
        )
    return outcome


def _fail(message: Message, code: str | None, text: str) -> None:
    message.status = "failed"
    message.error_code = code
    message.error_message = text[:500]


async def _finish(
    tenant_id: uuid.UUID,
    message_id: uuid.UUID,
    *,
    provider_message_id: str | None = None,
    retry: bool = False,
    error: Exception | None = None,
) -> str:
    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        message = (
            await session.execute(select(Message).where(Message.id == message_id).with_for_update())
        ).scalar_one()
        if provider_message_id is not None:
            message.provider_message_id = provider_message_id
            if message.status in ("queued", "sending"):  # a status webhook may already have moved it on
                message.status = "sent"
                message.sent_at = datetime.now(UTC)
            return message.status
        if retry:
            message.status = "queued"
            message.error_message = str(error)[:500] if error else None
            return "retry"
        _fail(message, getattr(error, "code", None), str(error) if error else "send failed")
        return "failed"


def send_retry_delay(attempt: int) -> int:
    """Seconds: 5, 20, 80, 320 (exponential, before the 5th and last attempt)."""
    return int(5 * 4 ** (attempt - 1))


async def sweep_unsent(limit: int = 200) -> tuple[list[tuple[uuid.UUID, uuid.UUID]], int]:
    """Sweeper (system job, platform role).

    * ``queued`` for over a minute → re-enqueue (crash between commit and enqueue, broker down).
    * ``sending`` for over 10 minutes → ``failed`` with ``delivery_unknown``. The provider may or
      may not have delivered it, so we never resend automatically; the agent decides.
    """
    now = datetime.now(UTC)
    async with platform_sessionmaker()() as session, session.begin():
        stuck = (
            await session.execute(
                select(Message)
                .where(Message.status == "sending", Message.created_at < now - timedelta(minutes=10))
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).scalars()
        failed = 0
        for message in stuck:
            _fail(message, "delivery_unknown", "Sending did not finish. Check with the customer before resending.")
            failed += 1
        rows = await session.execute(
            select(Message.tenant_id, Message.id)
            .where(Message.status == "queued", Message.created_at < now - timedelta(minutes=1))
            .order_by(Message.created_at)
            .limit(limit)
        )
        return [(r.tenant_id, r.id) for r in rows], failed
