"""Webhook ingestion pipeline (ARCHITECTURE.md §10).

receive():  store the raw delivery (dedup by payload hash) → caller enqueues processing.
process():  parse with the provider adapter → for each normalized event: route to the
            tenant → resolve customer → upsert conversation → insert message (dedup by
            provider message id) / apply status → publish real-time event.

Each event runs in its own tenant-scoped transaction on the runtime role, so RLS
applies to everything the pipeline writes.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import runtime_sessionmaker, set_tenant_context
from app.core.logging import get_logger
from app.integrations import registry
from app.integrations.base import InboundMessage, MessageStatusUpdate, NormalizedEvent, ReadReceipt
from app.models import (
    ChannelAccount,
    Conversation,
    Customer,
    CustomerIdentity,
    Message,
    MessageAttachment,
    MessageEvent,
    WebhookEvent,
    WebhookEventAttempt,
)
from app.services import customers, realtime
from app.workers.queue import enqueue

log = get_logger(__name__)

MAX_ATTEMPTS = 8
PREVIEW_LENGTH = 120
# Outbound status only moves forward; "failed" can replace anything below "delivered".
_STATUS_RANK = {"queued": 0, "sending": 1, "sent": 2, "delivered": 3, "read": 4}


class RetryLater(Exception):
    """Transient condition (e.g. a status for a message we haven't stored yet)."""


@dataclass(frozen=True)
class Received:
    event_id: uuid.UUID
    duplicate: bool


def payload_hash(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


async def receive(session: AsyncSession, *, provider: str, raw_body: bytes, payload: dict[str, Any]) -> Received:
    adapter = registry.get(provider)
    digest = payload_hash(raw_body)
    stmt = (
        insert(WebhookEvent)
        .values(
            provider=provider,
            payload_hash=digest,
            provider_event_id=adapter.provider_event_id(payload) if adapter else None,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["provider", "payload_hash"])
        .returning(WebhookEvent.id)
    )
    event_id = (await session.execute(stmt)).scalar_one_or_none()
    if event_id is not None:
        return Received(event_id, duplicate=False)
    existing = (
        await session.execute(
            select(WebhookEvent.id).where(WebhookEvent.provider == provider, WebhookEvent.payload_hash == digest)
        )
    ).scalar_one()
    return Received(existing, duplicate=True)


def _preview(message: InboundMessage) -> str:
    if message.text:
        return message.text[:PREVIEW_LENGTH]
    return f"[{message.message_type}]"


async def _route(session: AsyncSession, provider: str, external_id: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = (
        await session.execute(
            text("SELECT tenant_id, channel_account_id FROM route_channel_account(:p, :e)"),
            {"p": provider, "e": external_id},
        )
    ).first()
    return (row.tenant_id, row.channel_account_id) if row else None


async def _conversation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    channel_account_id: uuid.UUID,
    identity_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> Conversation:
    stmt = (
        insert(Conversation)
        .values(
            tenant_id=tenant_id,
            channel_account_id=channel_account_id,
            customer_identity_id=identity_id,
            customer_id=customer_id,
            provider=provider,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "channel_account_id", "customer_identity_id"])
    )
    await session.execute(stmt)
    return (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_account_id == channel_account_id,
                Conversation.customer_identity_id == identity_id,
            )
            .with_for_update()
        )
    ).scalar_one()


async def _handle_message(
    session: AsyncSession, provider: str, tenant_id: uuid.UUID, account_id: uuid.UUID, event: InboundMessage
) -> dict[str, Any] | None:
    resolved = await customers.resolve_channel_identity(
        session,
        tenant_id=tenant_id,
        provider=provider,
        channel_account_id=account_id,
        provider_user_id=event.provider_user_id,
        profile_name=None if event.is_echo else event.profile_name,
        phone=None if event.is_echo else event.phone,
        seen_at=event.timestamp,
    )
    conversation = await _conversation(
        session,
        tenant_id=tenant_id,
        provider=provider,
        channel_account_id=account_id,
        identity_id=resolved.identity_id,
        customer_id=resolved.customer_id,
    )

    reply_to_id = None
    if event.reply_to_provider_message_id:
        reply_to_id = (
            await session.execute(
                select(Message.id).where(
                    Message.channel_account_id == account_id,
                    Message.provider_message_id == event.reply_to_provider_message_id,
                )
            )
        ).scalar_one_or_none()

    inserted = (
        await session.execute(
            insert(Message)
            .values(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                channel_account_id=account_id,
                direction="outbound" if event.is_echo else "inbound",
                sender_type="external_app" if event.is_echo else "customer",
                provider_message_id=event.provider_message_id,
                message_type=event.message_type,
                body=event.text,
                content=dict(event.extra),
                reply_to_message_id=reply_to_id,
                status="sent" if event.is_echo else "received",
                provider_timestamp=event.timestamp,
                sent_at=event.timestamp if event.is_echo else None,
            )
            .on_conflict_do_nothing(
                index_elements=["channel_account_id", "provider_message_id"],
                index_where=text("provider_message_id IS NOT NULL"),
            )
            .returning(Message.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        return None  # already stored: provider redelivery

    for media in event.media:
        session.add(
            MessageAttachment(
                tenant_id=tenant_id,
                message_id=inserted,
                provider_media_id=media.provider_media_id,
                mime_type=media.mime_type,
                filename=media.filename,
                caption=media.caption,
            )
        )

    # Out-of-order deliveries must not move the thread backwards.
    if conversation.last_message_at is None or event.timestamp >= conversation.last_message_at:
        conversation.last_message_at = event.timestamp
        conversation.last_message_preview = _preview(event)
    if not event.is_echo:
        if conversation.last_inbound_at is None or event.timestamp > conversation.last_inbound_at:
            conversation.last_inbound_at = event.timestamp
        conversation.unread_count += 1
        conversation.status = "open"
        await session.execute(
            update(Customer)
            .where(Customer.id == resolved.customer_id)
            .values(last_interaction_at=event.timestamp, version=Customer.version + 1)
        )
        await customers.suggest_from_message_text(
            session, tenant_id=tenant_id, customer_id=resolved.customer_id, text_body=event.text
        )
    return {
        "type": "message.created",
        "conversation_id": conversation.id,
        "message_id": inserted,
        "customer_id": resolved.customer_id,
        "new_customer": resolved.created,
    }


async def _handle_status(
    session: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, event: MessageStatusUpdate
) -> dict[str, Any] | None:
    message = (
        await session.execute(
            select(Message)
            .where(Message.channel_account_id == account_id, Message.provider_message_id == event.provider_message_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if message is None:
        if not event.retry_if_unknown:
            return None  # receipt for a message we never stored (e.g. sent before connecting)
        # Status can arrive before our send transaction stored the provider id.
        raise RetryLater(f"status for unknown message {event.provider_message_id}")

    await session.execute(
        insert(MessageEvent)
        .values(
            tenant_id=tenant_id,
            message_id=message.id,
            event_type=event.status,
            provider_timestamp=event.timestamp,
            payload={"error_code": event.error_code} if event.error_code else {},
        )
        .on_conflict_do_nothing(index_elements=["message_id", "event_type"])
    )
    if event.status == "failed":
        if _STATUS_RANK.get(message.status, -1) < _STATUS_RANK["delivered"]:
            message.status = "failed"
            message.error_code = event.error_code
            message.error_message = event.error_message
    elif _STATUS_RANK[event.status] > _STATUS_RANK.get(message.status, -1):
        message.status = event.status
    timestamp_column = {"sent": "sent_at", "delivered": "delivered_at", "read": "read_at"}.get(event.status)
    if timestamp_column and getattr(message, timestamp_column) is None:
        setattr(message, timestamp_column, event.timestamp)
    return {
        "type": "message.status",
        "conversation_id": message.conversation_id,
        "message_id": message.id,
        "status": message.status,
    }


async def _handle_read(
    session: AsyncSession, tenant_id: uuid.UUID, account_id: uuid.UUID, event: ReadReceipt
) -> dict[str, Any] | None:
    """Mark our replies in this chat up to the watermark as read (never moves a status backwards)."""
    conversation_id = (
        await session.execute(
            select(Conversation.id)
            .join(CustomerIdentity, CustomerIdentity.id == Conversation.customer_identity_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_account_id == account_id,
                CustomerIdentity.provider_user_id == event.provider_user_id,
            )
        )
    ).scalar_one_or_none()
    if conversation_id is None:
        return None
    result = await session.execute(
        update(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "outbound",
            Message.status.in_(("sent", "delivered")),
            Message.provider_timestamp <= event.watermark,
        )
        .values(status="read", read_at=event.watermark)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        return None
    return {"type": "message.status", "conversation_id": conversation_id, "status": "read"}


async def _process_one(provider: str, event: NormalizedEvent) -> str:
    """Returns ``processed`` or ``ignored``. Raises :class:`RetryLater` for transient conditions."""
    if not isinstance(event, InboundMessage | MessageStatusUpdate | ReadReceipt):
        return "ignored"  # account-level events are handled by the channel health checks

    async with runtime_sessionmaker()() as session, session.begin():
        routed = await _route(session, provider, event.channel_external_id)
        if routed is None:
            log.info("webhook_unknown_account", provider=provider)
            return "ignored"
        tenant_id, account_id = routed
        await set_tenant_context(session, tenant_id)
        await session.execute(
            update(ChannelAccount).where(ChannelAccount.id == account_id).values(last_webhook_at=datetime.now(UTC))
        )
        if isinstance(event, InboundMessage):
            published = await _handle_message(session, provider, tenant_id, account_id, event)
        elif isinstance(event, ReadReceipt):
            published = await _handle_read(session, tenant_id, account_id, event)
        else:
            published = await _handle_status(session, tenant_id, account_id, event)

    if published:
        if (
            isinstance(event, InboundMessage)
            and published.get("new_customer")
            and not event.profile_name
            and not event.is_echo
        ):
            # Messenger webhooks carry no name; look it up once for new customers.
            await enqueue(
                "customers.fetch_profile",
                tenant_id=str(tenant_id),
                channel_account_id=str(account_id),
                provider_user_id=event.provider_user_id,
            )
        event_type = published.pop("type")
        await realtime.publish(tenant_id, event_type, **published)
    return "processed"


async def process(event_id: uuid.UUID) -> str:
    """Process one stored delivery. Safe to call repeatedly (every step is idempotent)."""
    async with runtime_sessionmaker()() as session, session.begin():
        row = (
            await session.execute(select(WebhookEvent).where(WebhookEvent.id == event_id).with_for_update())
        ).scalar_one_or_none()
        if row is None or row.processing_status in ("processed", "ignored", "dead"):
            return row.processing_status if row else "missing"
        row.processing_status = "processing"
        provider, payload, attempt_no = row.provider, row.payload or {}, row.retry_count + 1

    started = datetime.now(UTC)
    adapter = registry.get(provider)
    outcome, error = "ok", None
    statuses: list[str] = []
    try:
        if adapter is None:
            statuses = ["ignored"]
        else:
            for event in adapter.parse_webhook(payload):
                statuses.append(await _process_one(provider, event))
    except RetryLater as exc:
        outcome, error = "retry", str(exc)
    except Exception as exc:
        log.exception("webhook_processing_failed", provider=provider)
        outcome, error = "retry", f"{type(exc).__name__}: {exc}"[:500]

    async with runtime_sessionmaker()() as session, session.begin():
        row = (
            await session.execute(select(WebhookEvent).where(WebhookEvent.id == event_id).with_for_update())
        ).scalar_one()
        if outcome == "ok":
            row.processing_status = "processed" if "processed" in statuses else "ignored"
            row.processed_at = datetime.now(UTC)
            row.error_message = None
        else:
            row.retry_count = attempt_no
            if attempt_no >= MAX_ATTEMPTS:
                row.processing_status, outcome = "dead", "dead"
            else:
                row.processing_status = "failed"
                row.next_retry_at = datetime.now(UTC) + retry_delay(attempt_no)
            row.error_message = error
        session.add(
            WebhookEventAttempt(
                webhook_event_id=event_id,
                attempt_no=attempt_no,
                started_at=started,
                finished_at=datetime.now(UTC),
                outcome=outcome,
                error_message=error,
            )
        )
        return row.processing_status


def retry_delay(attempt_no: int) -> timedelta:
    """Exponential backoff: 10s, 20s, 40s ... capped at 30 minutes."""
    return timedelta(seconds=min(10 * 2 ** (attempt_no - 1), 1800))


async def due_for_retry(limit: int = 200) -> list[uuid.UUID]:
    """Sweeper: deliveries never picked up (worker/broker down) or failed and due again."""
    now = datetime.now(UTC)
    async with runtime_sessionmaker()() as session, session.begin():
        rows = await session.execute(
            select(WebhookEvent.id)
            .where(
                (
                    (WebhookEvent.processing_status == "received")
                    & (WebhookEvent.received_at < now - timedelta(minutes=2))
                )
                | ((WebhookEvent.processing_status == "failed") & (WebhookEvent.next_retry_at <= now))
                # A worker died mid-delivery; every step is idempotent, so reprocessing is safe.
                | (
                    (WebhookEvent.processing_status == "processing")
                    & (WebhookEvent.received_at < now - timedelta(minutes=10))
                )
            )
            .order_by(WebhookEvent.received_at)
            .limit(limit)
        )
        return list(rows.scalars().all())


def decode_json(raw_body: bytes) -> dict[str, Any]:
    value = json.loads(raw_body)
    if not isinstance(value, dict):
        raise ValueError("webhook payload must be a JSON object")
    return value
