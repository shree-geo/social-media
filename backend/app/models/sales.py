"""Orders and invoices (DATABASE.md §11).

Line items snapshot the product name, SKU and tax rate, so later product edits never
change past orders or invoices. Issued invoices are immutable (enforced by a trigger).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in
from app.models.catalogue import Quantity

ORDER_STATUSES = (
    "NEW",
    "CONFIRMED",
    "PROCESSING",
    "READY_FOR_DELIVERY",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
    "REJECTED",
    "RETURNED",
)
SOURCE_CHANNELS = ("whatsapp", "messenger", "phone", "walk_in", "other")
LEAD_SOURCES = ("tiktok", "facebook_post", "instagram", "referral", "walk_in", "other")
PAYMENT_STATUSES = ("UNPAID", "PARTIAL", "PAID", "REFUNDED")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "CANCELLED")
Rate = Numeric(5, 2)


def _fk(table: str, column: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete=ondelete)


class _Totals:
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(server_default=text("0"))
    shipping_fee: Mapped[Decimal] = mapped_column(server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(server_default=text("0"))
    amount_paid: Mapped[Decimal] = mapped_column(server_default=text("0"))
    amount_due: Mapped[Decimal] = mapped_column(server_default=text("0"))
    payment_status: Mapped[str] = mapped_column(server_default=text("'UNPAID'"))


class Order(UUIDPrimaryKey, TenantOwned, _Totals, Timestamps, Base):
    __tablename__ = "orders"
    __extra_table_args__ = (
        _fk("customers", "customer_id"),
        _fk("conversations", "source_conversation_id"),
        _fk("channel_accounts", "channel_account_id"),
        UniqueConstraint("tenant_id", "order_number"),
        CheckConstraint(check_in("status", ORDER_STATUSES), name="status"),
        CheckConstraint(check_in("source_channel", SOURCE_CHANNELS), name="source_channel"),
        CheckConstraint(f"lead_source IS NULL OR {check_in('lead_source', LEAD_SOURCES)}", name="lead_source"),
        CheckConstraint(check_in("payment_status", PAYMENT_STATUSES), name="payment_status"),
        CheckConstraint("grand_total >= 0 AND amount_paid >= 0 AND shipping_fee >= 0", name="amounts"),
        Index("ix_orders_tenant_id_created_at", "tenant_id", text("created_at DESC"), "id"),
        Index("ix_orders_tenant_id_status", "tenant_id", "status"),
        Index("ix_orders_tenant_id_customer_id", "tenant_id", "customer_id", text("created_at DESC")),
        Index("ix_orders_tenant_id_source_channel", "tenant_id", "source_channel", "created_at"),
        Index(
            "ix_orders_unpaid",
            "tenant_id",
            "payment_status",
            postgresql_where=text("payment_status IN ('UNPAID', 'PARTIAL')"),
        ),
    )

    order_number: Mapped[str]
    customer_id: Mapped[uuid.UUID]
    source_channel: Mapped[str]
    source_conversation_id: Mapped[uuid.UUID | None]
    channel_account_id: Mapped[uuid.UUID | None]
    lead_source: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'NEW'"))
    delivery_address: Mapped[dict[str, Any] | None]
    notes: Mapped[str | None]
    confirmed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class _Line:
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit_price: Mapped[Decimal]
    discount_amount: Mapped[Decimal] = mapped_column(server_default=text("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Rate)
    tax_amount: Mapped[Decimal]
    line_total: Mapped[Decimal]
    position: Mapped[int]


class OrderItem(UUIDPrimaryKey, TenantOwned, _Line, CreatedAt, Base):
    __tablename__ = "order_items"
    __extra_table_args__ = (
        _fk("orders", "order_id", ondelete="CASCADE"),
        _fk("product_variants", "variant_id"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("unit_price >= 0 AND discount_amount >= 0", name="amounts"),
        Index("ix_order_items_order", "tenant_id", "order_id", "position"),
        Index("ix_order_items_tenant_id_variant_id", "tenant_id", "variant_id"),
    )

    order_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID]
    product_name: Mapped[str]
    sku: Mapped[str]
    unit: Mapped[str]


class OrderStatusHistory(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "order_status_history"
    __extra_table_args__ = (
        _fk("orders", "order_id", ondelete="CASCADE"),
        Index("ix_order_status_history_order", "tenant_id", "order_id", "created_at"),
    )

    order_id: Mapped[uuid.UUID]
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    reason: Mapped[str | None]
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Invoice(UUIDPrimaryKey, TenantOwned, _Totals, Timestamps, Base):
    __tablename__ = "invoices"
    __extra_table_args__ = (
        _fk("orders", "order_id"),
        _fk("customers", "customer_id"),
        UniqueConstraint("tenant_id", "invoice_number"),
        CheckConstraint(check_in("status", INVOICE_STATUSES), name="status"),
        CheckConstraint("status = 'DRAFT' OR invoice_number IS NOT NULL", name="number_when_issued"),
        CheckConstraint(check_in("payment_status", PAYMENT_STATUSES), name="payment_status"),
        # MVP: one live invoice per order (cancel to reissue).
        Index("invoices_order_live_key", "order_id", unique=True, postgresql_where=text("status <> 'CANCELLED'")),
        Index("ix_invoices_tenant_id_status_due", "tenant_id", "status", "due_date"),
        Index("ix_invoices_tenant_id_created_at", "tenant_id", text("created_at DESC"), "id"),
    )

    invoice_number: Mapped[str | None]
    order_id: Mapped[uuid.UUID]
    customer_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(server_default=text("'DRAFT'"))
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    seller_snapshot: Mapped[dict[str, Any]]
    buyer_snapshot: Mapped[dict[str, Any]]
    pdf_object_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stored_objects.id"))
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime | None]
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class InvoiceItem(UUIDPrimaryKey, TenantOwned, _Line, CreatedAt, Base):
    __tablename__ = "invoice_items"
    __extra_table_args__ = (
        _fk("invoices", "invoice_id", ondelete="CASCADE"),
        _fk("order_items", "order_item_id"),
        Index("ix_invoice_items_invoice", "tenant_id", "invoice_id", "position"),
    )

    invoice_id: Mapped[uuid.UUID]
    order_item_id: Mapped[uuid.UUID | None]
    description: Mapped[str]
    sku: Mapped[str | None]
    unit: Mapped[str]
