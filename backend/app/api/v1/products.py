"""Product catalogue and stock: /api/v1/products, /api/v1/tax-rates (spec §21)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.api import pagination
from app.api.deps import TenantContext, require
from app.core.exceptions import NotFound
from app.models import Inventory, Product, ProductPrice, ProductVariant, TaxRate, Tenant
from app.schemas.auth import StrictModel
from app.services import audit, catalogue

router = APIRouter(tags=["products"])

Reader = Annotated[TenantContext, Depends(require("product.read"))]
Writer = Annotated[TenantContext, Depends(require("product.write", write=True))]

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Qty = Annotated[Decimal, Field(max_digits=12, decimal_places=3)]


class VariantIn(StrictModel):
    name: str = Field(default="Default", max_length=100)
    sku: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9._/-]+$")
    price: Money
    opening_stock: Qty = Decimal("0")
    attributes: dict[str, str] | None = None


class ProductCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    unit: str = Field(default="pcs", max_length=20)
    tax_rate_id: uuid.UUID | None = None
    track_inventory: bool = True
    variants: list[VariantIn] = Field(min_length=1, max_length=50)


class ProductUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=20)
    tax_rate_id: uuid.UUID | None = None
    track_inventory: bool | None = None
    is_active: bool | None = None


class VariantUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=100)
    price: Money | None = None
    is_active: bool | None = None
    low_stock_threshold: Qty | None = None


class StockChange(StrictModel):
    change: Qty  # positive: received; negative: removed (damaged, counted less …)
    note: str | None = Field(default=None, max_length=500)


class VariantOut(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    is_default: bool
    is_active: bool
    price: Decimal | None
    stock: Decimal | None
    low_stock_threshold: Decimal | None
    attributes: dict[str, Any]


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    unit: str
    tax_rate_id: uuid.UUID | None
    tax_rate: Decimal | None
    track_inventory: bool
    is_active: bool
    variants: list[VariantOut]
    updated_at: datetime


class ProductPage(BaseModel):
    items: list[ProductOut]
    next_cursor: str | None


class TaxRateOut(BaseModel):
    id: uuid.UUID
    name: str
    rate: Decimal
    is_default: bool


async def _products_out(ctx: TenantContext, products: list[Product]) -> list[ProductOut]:
    if not products:
        return []
    tenant = await ctx.session.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    ids = [p.id for p in products]
    rows = await ctx.session.execute(
        select(ProductVariant, ProductPrice.amount, Inventory.quantity_on_hand, Inventory.low_stock_threshold)
        .outerjoin(
            ProductPrice,
            and_(
                ProductPrice.variant_id == ProductVariant.id,
                ProductPrice.currency == tenant.currency,
                ProductPrice.effective_to.is_(None),
            ),
        )
        .outerjoin(Inventory, Inventory.variant_id == ProductVariant.id)
        .where(ProductVariant.product_id.in_(ids))
        .order_by(ProductVariant.is_default.desc(), ProductVariant.name)
    )
    variants: dict[uuid.UUID, list[VariantOut]] = {}
    tracked = {p.id: p.track_inventory for p in products}
    for v, price, stock, threshold in rows:
        variants.setdefault(v.product_id, []).append(
            VariantOut(
                id=v.id,
                sku=v.sku,
                name=v.name,
                is_default=v.is_default,
                is_active=v.is_active,
                price=price,
                stock=stock if tracked[v.product_id] else None,
                low_stock_threshold=threshold,
                attributes=v.attributes,
            )
        )
    rates = dict(
        (await ctx.session.execute(select(TaxRate.id, TaxRate.rate).where(TaxRate.tenant_id == ctx.tenant_id))).all()
    )
    return [
        ProductOut(
            id=p.id,
            name=p.name,
            description=p.description,
            unit=p.unit,
            tax_rate_id=p.tax_rate_id,
            tax_rate=rates.get(p.tax_rate_id) if p.tax_rate_id else None,
            track_inventory=p.track_inventory,
            is_active=p.is_active,
            variants=variants.get(p.id, []),
            updated_at=p.updated_at,
        )
        for p in products
    ]


async def _product(ctx: TenantContext, product_id: uuid.UUID) -> Product:
    product = await ctx.session.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        raise NotFound()
    return product


@router.get("/tax-rates")
async def tax_rates(ctx: Reader) -> list[TaxRateOut]:
    rows = (
        await ctx.session.execute(
            select(TaxRate)
            .where(TaxRate.tenant_id == ctx.tenant_id, TaxRate.is_active.is_(True))
            .order_by(TaxRate.rate.desc())
        )
    ).scalars()
    return [TaxRateOut(id=r.id, name=r.name, rate=r.rate, is_default=r.is_default) for r in rows]


@router.get("/products")
async def list_products(
    ctx: Reader,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active: bool | None = None,  # None: all products (management); the order picker asks for active ones
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ProductPage:
    query = select(Product).where(Product.tenant_id == ctx.tenant_id, Product.deleted_at.is_(None))
    if active is not None:
        query = query.where(Product.is_active.is_(active))
    if q and q.strip():
        term = q.strip()
        query = query.where(
            or_(
                Product.name.ilike(f"%{term}%"),
                Product.id.in_(select(ProductVariant.product_id).where(func.lower(ProductVariant.sku) == term.lower())),
            )
        )
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(Product.updated_at < stamp, and_(Product.updated_at == stamp, Product.id < last_id)))
    products = list(
        (
            await ctx.session.execute(query.order_by(Product.updated_at.desc(), Product.id.desc()).limit(limit + 1))
        ).scalars()
    )
    page = products[:limit]
    return ProductPage(
        items=await _products_out(ctx, page),
        next_cursor=pagination.encode(page[-1].updated_at, page[-1].id) if len(products) > limit else None,
    )


@router.post("/products", status_code=201)
async def create_product(body: ProductCreate, ctx: Writer) -> ProductOut:
    product = await catalogue.create_product(
        ctx.session,
        tenant_id=ctx.tenant_id,
        plan_id=ctx.subscription.plan_id,
        user_id=ctx.user_id,
        name=body.name,
        description=body.description,
        unit=body.unit,
        tax_rate_id=body.tax_rate_id,
        track_inventory=body.track_inventory,
        variants=[
            catalogue.VariantInput(
                name=v.name, price=v.price, sku=v.sku, attributes=v.attributes, opening_stock=v.opening_stock
            )
            for v in body.variants
        ],
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(product)
    return (await _products_out(ctx, [product]))[0]


@router.get("/products/{product_id}")
async def get_product(product_id: uuid.UUID, ctx: Reader) -> ProductOut:
    return (await _products_out(ctx, [await _product(ctx, product_id)]))[0]


@router.patch("/products/{product_id}")
async def update_product(product_id: uuid.UUID, body: ProductUpdate, ctx: Writer) -> ProductOut:
    product = await _product(ctx, product_id)
    changes = body.model_dump(exclude_unset=True)
    if "tax_rate_id" in changes and changes["tax_rate_id"] is not None:
        rate = await ctx.session.get(TaxRate, changes["tax_rate_id"])
        if rate is None:
            raise catalogue.InvalidTaxRate()
    for key, value in changes.items():
        setattr(product, key, value)
    await ctx.session.flush()
    await audit.record(
        ctx.session,
        action="PRODUCT_UPDATED",
        actor_type="user",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        resource_type="product",
        resource_id=product.id,
        after={k: str(v) for k, v in changes.items()},
        request=ctx.request,
    )
    await ctx.session.refresh(product)
    return (await _products_out(ctx, [product]))[0]


@router.post("/products/{product_id}/variants", status_code=201)
async def add_variant(product_id: uuid.UUID, body: VariantIn, ctx: Writer) -> ProductOut:
    await catalogue.add_variant(
        ctx.session,
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        variant=catalogue.VariantInput(
            name=body.name, price=body.price, sku=body.sku, attributes=body.attributes, opening_stock=body.opening_stock
        ),
        user_id=ctx.user_id,
    )
    await ctx.session.flush()
    return await get_product(product_id, ctx)


@router.patch("/products/variants/{variant_id}")
async def update_variant(variant_id: uuid.UUID, body: VariantUpdate, ctx: Writer) -> ProductOut:
    variant = await ctx.session.get(ProductVariant, variant_id)
    if variant is None:
        raise NotFound()
    if body.price is not None:
        await catalogue.update_variant_price(
            ctx.session, tenant_id=ctx.tenant_id, variant_id=variant_id, amount=body.price, user_id=ctx.user_id
        )
    if body.name is not None:
        variant.name = body.name
    if body.is_active is not None:
        variant.is_active = body.is_active
    if "low_stock_threshold" in body.model_fields_set:
        stock = (await ctx.session.execute(select(Inventory).where(Inventory.variant_id == variant_id))).scalar_one()
        stock.low_stock_threshold = body.low_stock_threshold
    await ctx.session.flush()
    return await get_product(variant.product_id, ctx)


@router.post("/products/variants/{variant_id}/stock")
async def change_stock(variant_id: uuid.UUID, body: StockChange, ctx: Writer) -> ProductOut:
    variant = await ctx.session.get(ProductVariant, variant_id)
    if variant is None:
        raise NotFound()
    await catalogue.adjust_stock(
        ctx.session,
        tenant_id=ctx.tenant_id,
        variant_id=variant_id,
        delta=body.change,
        reason="adjustment",
        user_id=ctx.user_id,
        note=body.note,
    )
    await audit.record(
        ctx.session,
        action="STOCK_ADJUSTED",
        actor_type="user",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        resource_type="product_variant",
        resource_id=variant_id,
        after={"change": str(body.change), "note": body.note},
        request=ctx.request,
    )
    await ctx.session.flush()
    return await get_product(variant.product_id, ctx)
