"""Deliveries and payments, both recorded by hand (DATABASE.md §12).

Payments are never edited: a mistake is voided (with a reason) and recorded again. Order and
invoice balances are recomputed from the recorded rows in the same transaction.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

DELIVERY_METHODS = ("own_staff", "courier", "customer_pickup")
DELIVERY_STATUSES = (
    "PENDING",
    "ASSIGNED",
    "PICKED_UP",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "FAILED",
    "RETURNED",
    "CANCELLED",
)
DELIVERY_CLOSED = ("DELIVERED", "FAILED", "RETURNED", "CANCELLED")
PAYMENT_TYPES = ("payment", "refund")
PAYMENT_METHODS = ("cash", "cod", "esewa", "khalti", "fonepay", "bank_transfer", "cheque", "other")
PAYMENT_STATUSES = ("recorded", "voided")


def _fk(table: str, column: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"])


class Delivery(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "deliveries"
    __extra_table_args__ = (
        _fk("orders", "order_id"),
        UniqueConstraint("tenant_id", "delivery_number"),
        CheckConstraint(check_in("delivery_method", DELIVERY_METHODS), name="delivery_method"),
        CheckConstraint(check_in("status", DELIVERY_STATUSES), name="status"),
        CheckConstraint("status <> 'DELIVERED' OR delivered_at IS NOT NULL", name="delivered_at"),
        CheckConstraint("cod_amount >= 0", name="cod_amount"),
        # One open attempt per order; a failed or returned attempt can be followed by a new one.
        Index(
            "deliveries_order_open_key",
            "order_id",
            unique=True,
            postgresql_where=text(f"status NOT IN ({', '.join(repr(s) for s in DELIVERY_CLOSED)})"),
        ),
        Index("ix_deliveries_tenant_id_status_date", "tenant_id", "status", "scheduled_date"),
        Index("ix_deliveries_tenant_id_assigned_to", "tenant_id", "assigned_to", "status"),
        Index("ix_deliveries_tenant_id_created_at", "tenant_id", text("created_at DESC"), "id"),
    )

    delivery_number: Mapped[str]
    order_id: Mapped[uuid.UUID]
    delivery_method: Mapped[str]
    courier_name: Mapped[str | None]
    tracking_reference: Mapped[str | None]
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    delivery_address: Mapped[dict[str, Any] | None]
    contact_name: Mapped[str | None]
    contact_phone: Mapped[str | None]
    cod_amount: Mapped[Decimal] = mapped_column(server_default=text("0"))
    status: Mapped[str]
    scheduled_date: Mapped[date | None]
    delivered_at: Mapped[datetime | None]
    delivery_notes: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class DeliveryStatusHistory(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "delivery_status_history"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "delivery_id"], ["deliveries.tenant_id", "deliveries.id"], ondelete="CASCADE"
        ),
        Index("ix_delivery_status_history_delivery", "tenant_id", "delivery_id", "created_at"),
    )

    delivery_id: Mapped[uuid.UUID]
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    note: Mapped[str | None]
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Payment(UUIDPrimaryKey, TenantOwned, Base):
    __tablename__ = "payments"
    __extra_table_args__ = (
        _fk("orders", "order_id"),
        _fk("invoices", "invoice_id"),
        _fk("customers", "customer_id"),
        _fk("deliveries", "delivery_id"),
        UniqueConstraint("tenant_id", "payment_number"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint(check_in("type", PAYMENT_TYPES), name="type"),
        CheckConstraint(check_in("payment_method", PAYMENT_METHODS), name="payment_method"),
        CheckConstraint(check_in("status", PAYMENT_STATUSES), name="status"),
        CheckConstraint(
            "status <> 'voided' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL)", name="void_reason"
        ),
        Index("ix_payments_tenant_id_order_id", "tenant_id", "order_id"),
        Index("ix_payments_tenant_id_paid_at", "tenant_id", text("paid_at DESC"), "id"),
        Index("ix_payments_tenant_id_method", "tenant_id", "payment_method", "paid_at"),
    )

    payment_number: Mapped[str]
    order_id: Mapped[uuid.UUID]
    invoice_id: Mapped[uuid.UUID | None]  # the live invoice when recorded; None for advance payments
    customer_id: Mapped[uuid.UUID]
    delivery_id: Mapped[uuid.UUID | None]  # COD collected on this delivery
    type: Mapped[str]
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    payment_method: Mapped[str]
    transaction_reference: Mapped[str | None]
    paid_at: Mapped[datetime]
    notes: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'recorded'"))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None]
    void_reason: Mapped[str | None]
