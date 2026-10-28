"""Customers, their channel identities, addresses, notes, tags, duplicates and merges (DATABASE.md §8)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

IDENTITY_PROVIDERS = ("whatsapp", "messenger", "phone", "email")


def _customer_fk(column: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", column], ["customers.tenant_id", "customers.id"])


class Customer(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "customers"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "merged_into_customer_id"], ["customers.tenant_id", "customers.id"]),
        CheckConstraint(check_in("status", ("active", "merged")), name="status"),
        CheckConstraint("status <> 'merged' OR merged_into_customer_id IS NOT NULL", name="merged_into"),
        Index(
            "ix_customers_tenant_id_phone_e164",
            "tenant_id",
            "phone_e164",
            postgresql_where=text("status = 'active' AND deleted_at IS NULL"),
        ),
        Index("ix_customers_tenant_id_email", "tenant_id", "email"),
        Index("ix_customers_tenant_id_last_interaction_at", "tenant_id", text("last_interaction_at DESC NULLS LAST")),
        Index(
            "ix_customers_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
    )

    display_name: Mapped[str]
    phone_e164: Mapped[str | None]
    email: Mapped[str | None] = mapped_column(CITEXT)
    email_verified: Mapped[bool] = mapped_column(server_default=text("false"))
    external_ref: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    merged_into_customer_id: Mapped[uuid.UUID | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_interaction_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012  optimistic locking


class CustomerIdentity(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """How we know a customer on one channel. Messenger PSIDs are per Page, hence channel_account_id."""

    __tablename__ = "customer_identities"
    __extra_table_args__ = (
        _customer_fk("customer_id"),
        ForeignKeyConstraint(
            ["tenant_id", "channel_account_id"], ["channel_accounts.tenant_id", "channel_accounts.id"]
        ),
        CheckConstraint(check_in("provider", IDENTITY_PROVIDERS), name="provider"),
        Index(
            "customer_identities_channel_key",
            "tenant_id",
            "channel_account_id",
            "provider_user_id",
            unique=True,
            postgresql_where=text("channel_account_id IS NOT NULL"),
        ),
        Index(
            "customer_identities_contact_key",
            "tenant_id",
            "provider",
            "provider_user_id",
            unique=True,
            postgresql_where=text("channel_account_id IS NULL"),
        ),
        Index("ix_customer_identities_tenant_id_customer_id", "tenant_id", "customer_id"),
    )

    customer_id: Mapped[uuid.UUID]
    provider: Mapped[str]
    channel_account_id: Mapped[uuid.UUID | None]
    provider_user_id: Mapped[str]
    profile_name: Mapped[str | None]
    phone_e164: Mapped[str | None]
    is_verified: Mapped[bool] = mapped_column(server_default=text("false"))
    first_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[datetime | None]


class CustomerAddress(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "customer_addresses"
    __extra_table_args__ = (
        _customer_fk("customer_id"),
        Index("customer_addresses_default_key", "customer_id", unique=True, postgresql_where=text("is_default")),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    label: Mapped[str | None]
    contact_name: Mapped[str | None]
    contact_phone: Mapped[str | None]
    line1: Mapped[str | None]
    area: Mapped[str | None]
    city: Mapped[str | None]
    district: Mapped[str | None]
    province: Mapped[str | None]
    landmark: Mapped[str | None]
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))


class CustomerTag(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "customer_tags"
    __extra_table_args__ = (Index("customer_tags_name_key", "tenant_id", text("lower(name)"), unique=True),)

    name: Mapped[str]
    color: Mapped[str | None]


class CustomerTagLink(CreatedAt, Base):
    __tablename__ = "customer_tag_links"
    __table_args__ = (
        _customer_fk("customer_id"),
        ForeignKeyConstraint(
            ["tenant_id", "tag_id"], ["customer_tags.tenant_id", "customer_tags.id"], ondelete="CASCADE"
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)


class CustomerNote(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "customer_notes"
    __extra_table_args__ = (_customer_fk("customer_id"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    body: Mapped[str]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class CustomerDuplicateCandidate(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "customer_duplicate_candidates"
    __extra_table_args__ = (
        _customer_fk("customer_a_id"),
        _customer_fk("customer_b_id"),
        UniqueConstraint("tenant_id", "customer_a_id", "customer_b_id"),
        CheckConstraint("customer_a_id < customer_b_id", name="ordered_pair"),
        CheckConstraint(check_in("status", ("open", "merged", "dismissed")), name="status"),
        Index("ix_customer_duplicate_candidates_tenant_id_status", "tenant_id", "status"),
    )

    customer_a_id: Mapped[uuid.UUID]
    customer_b_id: Mapped[uuid.UUID]
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    reasons: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]


class CustomerMerge(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "customer_merges"
    __extra_table_args__ = (_customer_fk("source_customer_id"), _customer_fk("target_customer_id"))

    source_customer_id: Mapped[uuid.UUID]
    target_customer_id: Mapped[uuid.UUID]
    snapshot: Mapped[dict[str, Any]]
    merged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    merged_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reverted_at: Mapped[datetime | None]
