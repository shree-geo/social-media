"""Connected channels, encrypted credentials and raw webhook events (DATABASE.md §7)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

PROVIDERS = ("whatsapp", "messenger")
CONNECTION_STATUSES = ("pending", "connected", "error", "disconnected")
ACCOUNT_STATUSES = ("connected", "disconnected", "error")
HEALTH_STATUSES = ("healthy", "pending", "action_needed", "disconnected")
WEBHOOK_STATUSES = ("received", "processing", "processed", "ignored", "failed", "dead")


class ChannelConnection(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """One authorization grant (e.g. a WhatsApp Business Account or a Facebook login)."""

    __tablename__ = "channel_connections"
    __extra_table_args__ = (
        CheckConstraint(check_in("provider", PROVIDERS), name="provider"),
        CheckConstraint(check_in("status", CONNECTION_STATUSES), name="status"),
    )

    provider: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    external_business_id: Mapped[str | None]
    connected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    connected_at: Mapped[datetime | None]
    disconnected_at: Mapped[datetime | None]
    last_error: Mapped[str | None]


class ChannelAccount(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """A WhatsApp phone number or a Facebook Page that messages arrive on."""

    __tablename__ = "channel_accounts"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["channel_connections.tenant_id", "channel_connections.id"]
        ),
        CheckConstraint(check_in("provider", PROVIDERS), name="provider"),
        CheckConstraint(check_in("status", ACCOUNT_STATUSES), name="status"),
        CheckConstraint(check_in("health_status", HEALTH_STATUSES), name="health_status"),
        # A number/page can belong to only one tenant at a time.
        Index(
            "channel_accounts_provider_external_key",
            "provider",
            "external_account_id",
            unique=True,
            postgresql_where=text("status <> 'disconnected'"),
        ),
        Index("ix_channel_accounts_tenant_id_provider", "tenant_id", "provider"),
    )

    connection_id: Mapped[uuid.UUID]
    provider: Mapped[str]
    external_account_id: Mapped[str]
    display_name: Mapped[str | None]
    display_phone: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'connected'"))
    coexistence: Mapped[bool] = mapped_column(server_default=text("false"))
    name_status: Mapped[str | None]
    quality_rating: Mapped[str | None]
    health_status: Mapped[str] = mapped_column(server_default=text("'healthy'"))
    health_reason: Mapped[str | None]
    last_health_check_at: Mapped[datetime | None]
    last_webhook_at: Mapped[datetime | None]
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class ChannelCredential(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """Encrypted provider token (ARCHITECTURE.md §13). Never returned by any API."""

    __tablename__ = "channel_credentials"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["channel_connections.tenant_id", "channel_connections.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "channel_account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        CheckConstraint(check_in("token_status", ("valid", "expiring", "invalid", "revoked")), name="token_status"),
        Index(
            "channel_credentials_active_key",
            "connection_id",
            text("coalesce(channel_account_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "credential_type",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    connection_id: Mapped[uuid.UUID]
    channel_account_id: Mapped[uuid.UUID | None]
    credential_type: Mapped[str]
    ciphertext: Mapped[bytes]
    nonce: Mapped[bytes]
    key_version: Mapped[int] = mapped_column(Integer)
    token_status: Mapped[str] = mapped_column(server_default=text("'valid'"))
    expires_at: Mapped[datetime | None]
    last_checked_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class WebhookEvent(UUIDPrimaryKey, Base):
    """Raw provider delivery, stored before acknowledging. Not tenant-scoped (tenant unknown at receipt)."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        CheckConstraint(check_in("processing_status", WEBHOOK_STATUSES), name="processing_status"),
        Index("webhook_events_provider_payload_hash_key", "provider", "payload_hash", unique=True),
        Index(
            "webhook_events_provider_event_id_key",
            "provider",
            "provider_event_id",
            unique=True,
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
        Index(
            "ix_webhook_events_pending",
            "processing_status",
            "next_retry_at",
            postgresql_where=text("processing_status IN ('received', 'failed')"),
        ),
        Index("ix_webhook_events_received_at", "received_at"),
    )

    provider: Mapped[str]
    payload_hash: Mapped[str]
    provider_event_id: Mapped[str | None]
    event_type: Mapped[str | None]
    tenant_id: Mapped[uuid.UUID | None]
    channel_account_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any] | None]
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed_at: Mapped[datetime | None]
    processing_status: Mapped[str] = mapped_column(server_default=text("'received'"))
    retry_count: Mapped[int] = mapped_column(server_default=text("0"))
    next_retry_at: Mapped[datetime | None]
    error_message: Mapped[str | None]


class WebhookEventAttempt(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "webhook_event_attempts"
    __table_args__ = (CheckConstraint(check_in("outcome", ("ok", "retry", "dead")), name="outcome"),)

    webhook_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_events.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    outcome: Mapped[str]
    error_message: Mapped[str | None]
