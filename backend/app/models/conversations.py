"""Conversations, messages, attachments and delivery events (DATABASE.md §9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

MESSAGE_TYPES = (
    "text",
    "image",
    "video",
    "audio",
    "document",
    "sticker",
    "location",
    "contacts",
    "interactive",
    "reaction",
    "unsupported",
)
MESSAGE_STATUSES = ("received", "queued", "sending", "sent", "delivered", "read", "failed")
SENDER_TYPES = ("customer", "user", "system", "external_app")


class Conversation(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """One thread per customer identity per channel account."""

    __tablename__ = "conversations"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "channel_account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_identity_id"], ["customer_identities.tenant_id", "customer_identities.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        CheckConstraint(check_in("status", ("open", "closed")), name="status"),
        CheckConstraint("unread_count >= 0", name="unread_count"),
        Index("conversations_identity_key", "tenant_id", "channel_account_id", "customer_identity_id", unique=True),
        Index("ix_conversations_inbox", "tenant_id", text("last_message_at DESC"), "id"),
        Index("ix_conversations_inbox_provider", "tenant_id", "provider", text("last_message_at DESC")),
        Index("ix_conversations_inbox_assignee", "tenant_id", "assigned_to_user_id", text("last_message_at DESC")),
        Index(
            "ix_conversations_inbox_unread",
            "tenant_id",
            text("last_message_at DESC"),
            postgresql_where=text("unread_count > 0"),
        ),
        Index("ix_conversations_tenant_id_customer_id", "tenant_id", "customer_id"),
    )

    channel_account_id: Mapped[uuid.UUID]
    customer_identity_id: Mapped[uuid.UUID]
    customer_id: Mapped[uuid.UUID]
    provider: Mapped[str]
    provider_conversation_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    last_message_at: Mapped[datetime | None]
    last_inbound_at: Mapped[datetime | None]
    last_message_preview: Mapped[str | None]
    unread_count: Mapped[int] = mapped_column(server_default=text("0"))
    classification: Mapped[str | None]


class Message(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "messages"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "channel_account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "reply_to_message_id"], ["messages.tenant_id", "messages.id"]),
        CheckConstraint(check_in("direction", ("inbound", "outbound")), name="direction"),
        CheckConstraint(check_in("sender_type", SENDER_TYPES), name="sender_type"),
        CheckConstraint(check_in("message_type", MESSAGE_TYPES), name="message_type"),
        CheckConstraint(check_in("status", MESSAGE_STATUSES), name="status"),
        CheckConstraint("direction = 'outbound' OR status = 'received'", name="inbound_status"),
        Index(
            "messages_provider_message_key",
            "channel_account_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        Index("ix_messages_thread", "tenant_id", "conversation_id", text("provider_timestamp DESC"), "id"),
        Index("ix_messages_unsent", "status", "created_at", postgresql_where=text("status IN ('queued', 'sending')")),
    )

    conversation_id: Mapped[uuid.UUID]
    channel_account_id: Mapped[uuid.UUID]
    direction: Mapped[str]
    sender_type: Mapped[str]
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    provider_message_id: Mapped[str | None]
    message_type: Mapped[str] = mapped_column(server_default=text("'text'"))
    body: Mapped[str | None]
    content: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    reply_to_message_id: Mapped[uuid.UUID | None]
    status: Mapped[str]
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
    send_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    provider_timestamp: Mapped[datetime] = mapped_column(server_default=text("now()"))
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]


class MessageAttachment(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "message_attachments"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], ondelete="CASCADE"),
        CheckConstraint(
            check_in("download_status", ("pending", "stored", "failed", "too_large")), name="download_status"
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(index=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stored_objects.id"))
    provider_media_id: Mapped[str | None]
    mime_type: Mapped[str | None]
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    filename: Mapped[str | None]
    caption: Mapped[str | None]
    download_status: Mapped[str] = mapped_column(server_default=text("'pending'"))


class MessageEvent(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "message_events"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], ondelete="CASCADE"),
        CheckConstraint(check_in("event_type", ("sent", "delivered", "read", "failed")), name="event_type"),
        Index("message_events_message_event_key", "message_id", "event_type", unique=True),
    )

    message_id: Mapped[uuid.UUID]
    event_type: Mapped[str]
    provider_timestamp: Mapped[datetime | None]
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
