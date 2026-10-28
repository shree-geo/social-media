"""Product catalogue and stock (spec §21, DATABASE.md §10)."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.models import (
    Inventory,
    InventoryTransaction,
    Product,
    ProductPrice,
    ProductVariant,
    TaxRate,
    Tenant,
    TenantSettings,
)
from app.services import audit, entitlements
from app.services.audit import RequestInfo


class NotEnoughStock(AppError):
    status, code, title = 409, "not_enough_stock", "Not enough stock"


class InvalidTaxRate(AppError):
    status, code, title = 422, "invalid_tax_rate", "Unknown tax rate"


@dataclass(frozen=True)
class VariantInput:
    name: str
    price: Decimal
    sku: str | None = None
    attributes: dict[str, Any] | None = None
    opening_stock: Decimal = Decimal("0")


async def ensure_default_tax_rates(session: AsyncSession, tenant_id: uuid.UUID, vat_registered: bool) -> None:
    exists = (await session.execute(select(TaxRate.id).where(TaxRate.tenant_id == tenant_id).limit(1))).first()
    if exists:
        return
    session.add_all(
        [
            TaxRate(tenant_id=tenant_id, name="VAT 13%", rate=Decimal("13.00"), is_default=vat_registered),
            TaxRate(tenant_id=tenant_id, name="No VAT", rate=Decimal("0.00"), is_default=not vat_registered),
        ]
    )


async def _default_tax_rate(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await session.execute(select(TaxRate.id).where(TaxRate.tenant_id == tenant_id, TaxRate.is_default.is_(True)))
    ).scalar_one_or_none()


def _new_sku() -> str:
    return f"SKU-{secrets.token_hex(3).upper()}"


async def _sku_taken(session: AsyncSession, tenant_id: uuid.UUID, sku: str) -> bool:
    return bool(
        (
            await session.execute(
                select(ProductVariant.id).where(
                    ProductVariant.tenant_id == tenant_id, func.lower(ProductVariant.sku) == sku.lower()
                )
            )
        ).first()
    )


async def _set_price(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    currency: str,
    amount: Decimal,
    user_id: uuid.UUID,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        update(ProductPrice)
        .where(
            ProductPrice.variant_id == variant_id,
            ProductPrice.currency == currency,
            ProductPrice.effective_to.is_(None),
        )
        .values(effective_to=now)
    )
    await session.flush()
    session.add(
        ProductPrice(
            tenant_id=tenant_id,
            variant_id=variant_id,
            currency=currency,
            amount=amount,
            effective_from=now,
            created_by=user_id,
        )
    )


async def _add_variant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product: Product,
    variant: VariantInput,
    is_default: bool,
    currency: str,
    user_id: uuid.UUID,
) -> ProductVariant:
    sku = (variant.sku or "").strip() or _new_sku()
    if await _sku_taken(session, tenant_id, sku):
        raise Conflict(f"The code {sku} is already used by another product.", code="sku_taken")
    row = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=sku,
        name=variant.name.strip() or "Default",
        attributes=variant.attributes or {},
        is_default=is_default,
    )
    session.add(row)
    await session.flush()
    await _set_price(
        session, tenant_id=tenant_id, variant_id=row.id, currency=currency, amount=variant.price, user_id=user_id
    )
    session.add(Inventory(tenant_id=tenant_id, variant_id=row.id, quantity_on_hand=Decimal("0")))
    await session.flush()
    if variant.opening_stock:
        await adjust_stock(
            session,
            tenant_id=tenant_id,
            variant_id=row.id,
            delta=variant.opening_stock,
            reason="initial",
            user_id=user_id,
        )
    return row


async def create_product(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID | None,
    user_id: uuid.UUID,
    name: str,
    description: str | None,
    unit: str,
    tax_rate_id: uuid.UUID | None,
    track_inventory: bool,
    variants: list[VariantInput],
    request: RequestInfo,
) -> Product:
    await entitlements.require_capacity(session, tenant_id=tenant_id, plan_id=plan_id, key="max_products")
    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    if tax_rate_id is not None:
        rate = await session.get(TaxRate, tax_rate_id)
        if rate is None or not rate.is_active:
            raise InvalidTaxRate()
    product = Product(
        tenant_id=tenant_id,
        name=name.strip(),
        description=description,
        unit=unit,
        tax_rate_id=tax_rate_id or await _default_tax_rate(session, tenant_id),
        track_inventory=track_inventory,
    )
    session.add(product)
    await session.flush()
    for index, variant in enumerate(variants or []):
        await _add_variant(
            session,
            tenant_id=tenant_id,
            product=product,
            variant=variant,
            is_default=index == 0,
            currency=tenant.currency,
            user_id=user_id,
        )
    await audit.record(
        session,
        action="PRODUCT_CREATED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="product",
        resource_id=product.id,
        after={"name": product.name, "variants": len(variants)},
        request=request,
    )
    return product


async def update_variant_price(
    session: AsyncSession, *, tenant_id: uuid.UUID, variant_id: uuid.UUID, amount: Decimal, user_id: uuid.UUID
) -> None:
    variant = await session.get(ProductVariant, variant_id)
    tenant = await session.get(Tenant, tenant_id)
    if variant is None or tenant is None:
        raise NotFound()
    await _set_price(
        session, tenant_id=tenant_id, variant_id=variant_id, currency=tenant.currency, amount=amount, user_id=user_id
    )


async def add_variant(
    session: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID, variant: VariantInput, user_id: uuid.UUID
) -> ProductVariant:
    product = await session.get(Product, product_id)
    tenant = await session.get(Tenant, tenant_id)
    if product is None or product.deleted_at is not None or tenant is None:
        raise NotFound()
    return await _add_variant(
        session,
        tenant_id=tenant_id,
        product=product,
        variant=variant,
        is_default=False,
        currency=tenant.currency,
        user_id=user_id,
    )


async def adjust_stock(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    delta: Decimal,
    reason: str,
    user_id: uuid.UUID | None,
    note: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> Decimal:
    """Record a stock movement and update the cached level (row-locked, so concurrent orders add up)."""
    if delta == 0:
        return Decimal("0")
    stock = (
        await session.execute(select(Inventory).where(Inventory.variant_id == variant_id).with_for_update())
    ).scalar_one_or_none()
    if stock is None:
        raise NotFound()
    new_level = stock.quantity_on_hand + delta
    if new_level < 0:
        settings = await session.get(TenantSettings, tenant_id)
        if settings is not None and not settings.allow_negative_stock:
            raise NotEnoughStock(f"Only {stock.quantity_on_hand.normalize()} left in stock.")
    session.add(
        InventoryTransaction(
            tenant_id=tenant_id,
            variant_id=variant_id,
            quantity_delta=delta,
            reason=reason,
            note=note,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=user_id,
        )
    )
    stock.quantity_on_hand = new_level
    return new_level


@dataclass(frozen=True)
class VariantInfo:
    variant: ProductVariant
    product: Product
    price: Decimal | None
    tax_rate: Decimal
    stock: Decimal | None


async def variant_info(
    session: AsyncSession, tenant_id: uuid.UUID, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VariantInfo]:
    """Variants with their product, current price, tax rate and stock, for pricing orders."""
    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    rows = await session.execute(
        select(ProductVariant, Product, ProductPrice.amount, TaxRate.rate, Inventory.quantity_on_hand)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(
            ProductPrice,
            (ProductPrice.variant_id == ProductVariant.id)
            & (ProductPrice.currency == tenant.currency)
            & ProductPrice.effective_to.is_(None),
        )
        .outerjoin(TaxRate, TaxRate.id == Product.tax_rate_id)
        .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
        .where(ProductVariant.tenant_id == tenant_id, ProductVariant.id.in_(variant_ids))
    )
    return {
        v.id: VariantInfo(v, p, price, rate if rate is not None else Decimal("0"), stock if p.track_inventory else None)
        for v, p, price, rate, stock in rows
    }
