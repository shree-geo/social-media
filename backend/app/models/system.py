"""Audit log, idempotency keys, document numbering, notifications, files (DATABASE.md §5-6)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, UUIDPrimaryKey, check_in

# Sentinel tenant id for platform-level sequences (subscription receipts).
PLATFORM_SEQUENCE_TENANT = uuid.UUID(int=0)


class AuditLog(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only: the runtime role has INSERT/SELECT only (see migration)."""

    __tablename__ = "audit_logs"
    # No INSERT ... RETURNING: RLS applies SELECT policies to returned rows, and pre-tenant
    # rows (tenant_id NULL, e.g. failed logins) are intentionally not readable by tenants.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint(check_in("actor_type", ("user", "platform_user", "system")), name="actor_type"),
        Index("ix_audit_logs_tenant_id_created_at", "tenant_id", text("created_at DESC")),
        Index("ix_audit_logs_tenant_id_resource", "tenant_id", "resource_type", "resource_id"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    actor_type: Mapped[str]
    actor_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    resource_type: Mapped[str | None]
    resource_id: Mapped[uuid.UUID | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    request_id: Mapped[str | None]


class IdempotencyKey(CreatedAt, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_keys_expires_at", "expires_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    scope: Mapped[str]
    actor_id: Mapped[uuid.UUID | None]
    request_hash: Mapped[str]
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None]
    expires_at: Mapped[datetime]


class DocumentSequence(Base):
    """Gap-free human-readable numbers per tenant, document type and period."""

    __tablename__ = "document_sequences"
    __table_args__ = (CheckConstraint(check_in("doc_type", ("ORD", "INV", "PAY", "DEL", "SUB")), name="doc_type"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(primary_key=True)
    period_key: Mapped[str] = mapped_column(primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))


class Notification(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "notifications"
    __extra_table_args__ = (
        Index(
            "ix_notifications_unread",
            "tenant_id",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str]
    title: Mapped[str]
    body: Mapped[str | None]
    resource_type: Mapped[str | None]
    resource_id: Mapped[uuid.UUID | None]
    read_at: Mapped[datetime | None]


class StoredObject(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key"),
        CheckConstraint("size_bytes >= 0", name="size_bytes"),
        CheckConstraint(check_in("scan_status", ("pending", "clean", "infected", "skipped")), name="scan_status"),
        Index("ix_stored_objects_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    storage_provider: Mapped[str] = mapped_column(server_default=text("'s3'"))
    bucket: Mapped[str]
    object_key: Mapped[str]
    mime_type: Mapped[str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str]
    purpose: Mapped[str]
    scan_status: Mapped[str] = mapped_column(server_default=text("'pending'"))
