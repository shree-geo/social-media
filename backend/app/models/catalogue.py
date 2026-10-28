"""Products, variants, prices, tax rates and stock (DATABASE.md §10).

Every product has at least one variant (``is_default``); orders always reference a
variant, so "products without options" and "products with options" work the same way.
``inventory.quantity_on_hand`` is a cache of the sum of ``inventory_transactions``.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

Quantity = Numeric(12, 3)
STOCK_REASONS = ("initial", "adjustment", "order_confirmed", "order_cancelled", "order_returned")


class ProductCategory(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "product_categories"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "parent_id"], ["product_categories.tenant_id", "product_categories.id"]),
        Index("product_categories_name_key", "tenant_id", text("lower(name)"), unique=True),
    )

    parent_id: Mapped[uuid.UUID | None]
    name: Mapped[str]


class TaxRate(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "tax_rates"
    __extra_table_args__ = (
        CheckConstraint("rate BETWEEN 0 AND 100", name="rate"),
        Index("tax_rates_default_key", "tenant_id", unique=True, postgresql_where=text("is_default")),
    )

    name: Mapped[str]
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Product(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "products"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "category_id"], ["product_categories.tenant_id", "product_categories.id"]),
        ForeignKeyConstraint(["tenant_id", "tax_rate_id"], ["tax_rates.tenant_id", "tax_rates.id"]),
        Index("ix_products_tenant_id_is_active", "tenant_id", "is_active"),
        Index("ix_products_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    name: Mapped[str]
    description: Mapped[str | None]
    category_id: Mapped[uuid.UUID | None]
    tax_rate_id: Mapped[uuid.UUID | None]
    unit: Mapped[str] = mapped_column(server_default=text("'pcs'"))
    track_inventory: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    deleted_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class ProductVariant(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "product_variants"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], ondelete="CASCADE"),
        Index("product_variants_sku_key", "tenant_id", text("lower(sku)"), unique=True),
        Index("product_variants_default_key", "product_id", unique=True, postgresql_where=text("is_default")),
        Index("ix_product_variants_tenant_id_product_id", "tenant_id", "product_id"),
    )

    product_id: Mapped[uuid.UUID]
    sku: Mapped[str]
    name: Mapped[str]  # "Default", "Black / 4 ft"
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ProductPrice(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    """Price history; the current price has ``effective_to IS NULL``."""

    __tablename__ = "product_prices"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"], ["product_variants.tenant_id", "product_variants.id"], ondelete="CASCADE"
        ),
        CheckConstraint("amount >= 0", name="amount"),
        Index(
            "product_prices_current_key",
            "variant_id",
            "currency",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
    )

    variant_id: Mapped[uuid.UUID]
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal]
    effective_from: Mapped[datetime] = mapped_column(server_default=text("now()"))
    effective_to: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ProductImage(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "product_images"
    __extra_table_args__ = (
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], ondelete="CASCADE"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(index=True)
    object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_objects.id"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class Inventory(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "inventory"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"], ["product_variants.tenant_id", "product_variants.id"], ondelete="CASCADE"
        ),
        Index("inventory_variant_key", "variant_id", unique=True),
    )

    variant_id: Mapped[uuid.UUID]
    quantity_on_hand: Mapped[Decimal] = mapped_column(Quantity, server_default=text("0"))
    low_stock_threshold: Mapped[Decimal | None] = mapped_column(Quantity)


class InventoryTransaction(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    """Append-only stock movements; ``inventory`` is their running total."""

    __tablename__ = "inventory_transactions"
    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"], ["product_variants.tenant_id", "product_variants.id"], ondelete="CASCADE"
        ),
        CheckConstraint("quantity_delta <> 0", name="quantity_delta"),
        CheckConstraint(check_in("reason", STOCK_REASONS), name="reason"),
        Index("ix_inventory_transactions_variant", "tenant_id", "variant_id", text("created_at DESC")),
    )

    variant_id: Mapped[uuid.UUID]
    quantity_delta: Mapped[Decimal] = mapped_column(Quantity)
    reason: Mapped[str]
    reference_type: Mapped[str | None]
    reference_id: Mapped[uuid.UUID | None]
    note: Mapped[str | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
