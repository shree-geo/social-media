"""Leads: buying interest from a chat, phone call or walk-in, before it becomes an order.

A lead has an owner (staff member), a stage, the products the customer asked about and a
next follow-up. Converting it creates an order and closes the lead as WON in one step.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in
from app.models.catalogue import Quantity
from app.models.sales import LEAD_SOURCES, SOURCE_CHANNELS

OPEN_STAGES = ("NEW", "CONTACTED", "INTERESTED", "NEGOTIATING")
LEAD_STAGES = (*OPEN_STAGES, "WON", "LOST")
LOST_REASONS = ("price", "out_of_stock", "no_reply", "bought_elsewhere", "delivery_area", "not_serious", "other")
LEAD_EVENTS = (
    "created",
    "stage_changed",
    "assigned",
    "note",
    "followup_set",
    "items_changed",
    "converted",
    "lost",
    "reopened",
)
_OPEN_SQL = "stage IN ('NEW', 'CONTACTED', 'INTERESTED', 'NEGOTIATING')"


def _fk(table: str, column: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete=ondelete)


class Lead(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "leads"
    __extra_table_args__ = (
        _fk("customers", "customer_id"),
        _fk("conversations", "conversation_id"),
        _fk("channel_accounts", "channel_account_id"),
        _fk("orders", "won_order_id"),
        UniqueConstraint("tenant_id", "lead_number"),
        CheckConstraint(check_in("stage", LEAD_STAGES), name="stage"),
        CheckConstraint(check_in("source_channel", SOURCE_CHANNELS), name="source_channel"),
        CheckConstraint(f"lead_source IS NULL OR {check_in('lead_source', LEAD_SOURCES)}", name="lead_source"),
        CheckConstraint(f"lost_reason IS NULL OR {check_in('lost_reason', LOST_REASONS)}", name="lost_reason"),
        CheckConstraint("stage <> 'LOST' OR lost_reason IS NOT NULL", name="lost_needs_reason"),
        CheckConstraint("stage <> 'WON' OR won_order_id IS NOT NULL", name="won_needs_order"),
        CheckConstraint("expected_value >= 0", name="expected_value"),
        # One open lead per chat: a second "Create lead" opens the existing one.
        Index(
            "leads_conversation_open_key",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where=text(f"conversation_id IS NOT NULL AND {_OPEN_SQL}"),
        ),
        Index(
            "leads_won_order_key",
            "tenant_id",
            "won_order_id",
            unique=True,
            postgresql_where=text("won_order_id IS NOT NULL"),
        ),
        Index("ix_leads_tenant_id_stage", "tenant_id", "stage", text("updated_at DESC")),
        Index("ix_leads_tenant_id_created_at", "tenant_id", text("created_at DESC"), "id"),
        Index("ix_leads_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index(
            "ix_leads_followups",
            "tenant_id",
            "assigned_to_user_id",
            "next_followup_at",
            postgresql_where=text(f"next_followup_at IS NOT NULL AND {_OPEN_SQL}"),
        ),
    )

    lead_number: Mapped[str]
    customer_id: Mapped[uuid.UUID]
    conversation_id: Mapped[uuid.UUID | None]
    source_channel: Mapped[str]
    channel_account_id: Mapped[uuid.UUID | None]
    lead_source: Mapped[str | None]
    stage: Mapped[str] = mapped_column(server_default=text("'NEW'"))
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expected_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    currency: Mapped[str] = mapped_column(String(3))
    next_followup_at: Mapped[datetime | None]
    followup_note: Mapped[str | None]
    # Set by the follow-up job once it has alerted the owner, so each due follow-up alerts once.
    followup_alerted_at: Mapped[datetime | None]
    lost_reason: Mapped[str | None]
    lost_note: Mapped[str | None]
    won_order_id: Mapped[uuid.UUID | None]
    closed_at: Mapped[datetime | None]
    last_activity_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class LeadItem(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "lead_items"
    __extra_table_args__ = (
        _fk("leads", "lead_id", ondelete="CASCADE"),
        _fk("product_variants", "variant_id"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("unit_price >= 0", name="unit_price"),
        Index("ix_lead_items_lead", "tenant_id", "lead_id", "position"),
    )

    lead_id: Mapped[uuid.UUID]
    # NULL = something not in the catalogue yet ("blue sofa like in the photo").
    variant_id: Mapped[uuid.UUID | None]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    position: Mapped[int]


class LeadActivity(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "lead_activities"
    __extra_table_args__ = (
        _fk("leads", "lead_id", ondelete="CASCADE"),
        CheckConstraint(check_in("event", LEAD_EVENTS), name="event"),
        Index("ix_lead_activities_lead", "tenant_id", "lead_id", "created_at"),
    )

    lead_id: Mapped[uuid.UUID]
    event: Mapped[str]
    from_value: Mapped[str | None]
    to_value: Mapped[str | None]
    body: Mapped[str | None]
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
