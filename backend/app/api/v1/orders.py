"""Orders and invoices: /api/v1/orders, /api/v1/invoices (spec §16, §19, ARCHITECTURE.md §15)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select

from app.api import pagination
from app.api.deps import TenantContext, require
from app.api.v1.fulfilment import DeliveryOut, PaymentOut, deliveries_out, payments_out
from app.core.exceptions import NotFound
from app.models import Customer, Delivery, Invoice, InvoiceItem, Order, OrderStatusHistory, Payment
from app.models.sales import LEAD_SOURCES, ORDER_STATUSES, SOURCE_CHANNELS
from app.schemas.auth import StrictModel
from app.services import idempotency, invoices, orders
from app.workers.queue import enqueue

router = APIRouter(tags=["orders"])

OrderReader = Annotated[TenantContext, Depends(require("order.read"))]
OrderWriter = Annotated[TenantContext, Depends(require("order.write", write=True))]
InvoiceReader = Annotated[TenantContext, Depends(require("invoice.read"))]
InvoiceWriter = Annotated[TenantContext, Depends(require("invoice.write", write=True))]

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Status = Literal[ORDER_STATUSES]  # type: ignore[valid-type]
Source = Literal[SOURCE_CHANNELS]  # type: ignore[valid-type]
Lead = Literal[LEAD_SOURCES]  # type: ignore[valid-type]


class ItemIn(StrictModel):
    variant_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
    unit_price: Money | None = None  # omitted: the product's current price
    discount_amount: Money = Decimal("0")


class Address(StrictModel):
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=30)
    line1: str | None = Field(default=None, max_length=300)
    area: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    landmark: str | None = Field(default=None, max_length=200)


class OrderCreate(StrictModel):
    conversation_id: uuid.UUID | None = None  # "Create order" from a chat: customer and channel come from it
    customer_id: uuid.UUID | None = None
    source_channel: Source | None = None
    lead_source: Lead | None = None
    items: list[ItemIn] = Field(min_length=1, max_length=100)
    shipping_fee: Money = Decimal("0")
    delivery_address: Address | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _who(self) -> "OrderCreate":
        if not self.conversation_id and not self.customer_id:
            raise ValueError("conversation_id or customer_id is required")
        return self


class OrderUpdate(StrictModel):
    items: list[ItemIn] | None = Field(default=None, min_length=1, max_length=100)
    shipping_fee: Money | None = None
    delivery_address: Address | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lead_source: Lead | None = None


class StatusChange(StrictModel):
    status: Status
    reason: str | None = Field(default=None, max_length=500)


class CancelInvoice(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class Line(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID | None
    description: str
    sku: str | None
    unit: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal


class TotalsOut(BaseModel):
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    shipping_fee: Decimal
    grand_total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    payment_status: str


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    invoice_number: str | None
    status: str
    issue_date: date | None
    grand_total: Decimal


class StatusEvent(BaseModel):
    from_status: str | None
    to_status: str
    reason: str | None
    changed_by: uuid.UUID | None
    at: datetime


class OrderSummary(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    customer: dict[str, Any]
    source_channel: str
    lead_source: str | None
    grand_total: Decimal
    currency: str
    payment_status: str
    created_at: datetime


class OrderPage(BaseModel):
    items: list[OrderSummary]
    next_cursor: str | None


class OrderOut(OrderSummary):
    totals: TotalsOut
    lines: list[Line]
    delivery_address: dict[str, Any] | None
    notes: str | None
    source_conversation_id: uuid.UUID | None
    history: list[StatusEvent]
    invoices: list[InvoiceSummary]
    deliveries: list[DeliveryOut]  # empty without delivery.read
    payments: list[PaymentOut]  # empty without payment.read; includes voided rows
    allowed_next: list[str]
    version: int


class InvoiceOut(BaseModel):
    id: uuid.UUID
    invoice_number: str | None
    status: str
    order_id: uuid.UUID
    customer_id: uuid.UUID
    issue_date: date | None
    due_date: date | None
    totals: TotalsOut
    lines: list[Line]
    seller: dict[str, Any]
    buyer: dict[str, Any]
    cancel_reason: str | None


def _totals(row: Order | Invoice) -> TotalsOut:
    return TotalsOut(
        currency=row.currency,
        subtotal=row.subtotal,
        discount_total=row.discount_total,
        tax_total=row.tax_total,
        shipping_fee=row.shipping_fee,
        grand_total=row.grand_total,
        amount_paid=row.amount_paid,
        amount_due=row.amount_due,
        payment_status=row.payment_status,
    )


async def _order_out(ctx: TenantContext, order: Order) -> OrderOut:
    customer = await ctx.session.get(Customer, order.customer_id)
    items = await orders.order_items(ctx.session, order.id)
    history = (
        await ctx.session.execute(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order.id)
            .order_by(OrderStatusHistory.created_at)
        )
    ).scalars()
    order_invoices = (
        await ctx.session.execute(
            select(Invoice).where(Invoice.order_id == order.id).order_by(Invoice.created_at.desc())
        )
    ).scalars()
    order_deliveries: list[Delivery] = []
    if "delivery.read" in ctx.permissions:
        order_deliveries = list(
            (
                await ctx.session.execute(
                    select(Delivery).where(Delivery.order_id == order.id).order_by(Delivery.created_at.desc())
                )
            ).scalars()
        )
    order_payments: list[Payment] = []
    if "payment.read" in ctx.permissions:
        order_payments = list(
            (
                await ctx.session.execute(
                    select(Payment).where(Payment.order_id == order.id).order_by(Payment.paid_at.desc())
                )
            ).scalars()
        )
    allowed = orders.TRANSITIONS.get(order.status, frozenset())
    if await orders.open_delivery_for(ctx.session, order.id) is not None:
        allowed = allowed - orders.DELIVERY_DRIVEN  # the order follows its open delivery
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        customer={"id": order.customer_id, "display_name": customer.display_name if customer else ""},
        source_channel=order.source_channel,
        lead_source=order.lead_source,
        grand_total=order.grand_total,
        currency=order.currency,
        payment_status=order.payment_status,
        created_at=order.created_at,
        totals=_totals(order),
        lines=[
            Line(
                id=i.id,
                variant_id=i.variant_id,
                description=i.product_name,
                sku=i.sku,
                unit=i.unit,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount_amount=i.discount_amount,
                tax_rate=i.tax_rate,
                tax_amount=i.tax_amount,
                line_total=i.line_total,
            )
            for i in items
        ],
        delivery_address=order.delivery_address,
        notes=order.notes,
        source_conversation_id=order.source_conversation_id,
        history=[
            StatusEvent(
                from_status=h.from_status,
                to_status=h.to_status,
                reason=h.reason,
                changed_by=h.changed_by,
                at=h.created_at,
            )
            for h in history
        ],
        invoices=[
            InvoiceSummary(
                id=v.id,
                invoice_number=v.invoice_number,
                status=v.status,
                issue_date=v.issue_date,
                grand_total=v.grand_total,
            )
            for v in order_invoices
        ],
        deliveries=await deliveries_out(ctx.session, order_deliveries, history=True),
        payments=await payments_out(ctx.session, order_payments),
        allowed_next=sorted(allowed),
        version=order.version,
    )


async def _get_order(ctx: TenantContext, order_id: uuid.UUID) -> Order:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        raise NotFound()
    return order


def _items(body_items: list[ItemIn]) -> list[orders.ItemInput]:
    return [orders.ItemInput(i.variant_id, i.quantity, i.unit_price, i.discount_amount) for i in body_items]


@router.get("/orders")
async def list_orders(
    ctx: OrderReader,
    status: Status | None = None,
    customer_id: uuid.UUID | None = None,
    open_only: bool = False,
    q: Annotated[str | None, Query(max_length=60)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> OrderPage:
    query = (
        select(Order, Customer.display_name)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.tenant_id == ctx.tenant_id)
    )
    if status:
        query = query.where(Order.status == status)
    if open_only:
        query = query.where(Order.status.not_in(("DELIVERED", "CANCELLED", "REJECTED", "RETURNED")))
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    if q and q.strip():
        term = q.strip()
        query = query.where(or_(Order.order_number.ilike(f"%{term}%"), Customer.display_name.ilike(f"%{term}%")))
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(Order.created_at < stamp, and_(Order.created_at == stamp, Order.id < last_id)))
    rows = (await ctx.session.execute(query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    return OrderPage(
        items=[
            OrderSummary(
                id=o.id,
                order_number=o.order_number,
                status=o.status,
                customer={"id": o.customer_id, "display_name": name},
                source_channel=o.source_channel,
                lead_source=o.lead_source,
                grand_total=o.grand_total,
                currency=o.currency,
                payment_status=o.payment_status,
                created_at=o.created_at,
            )
            for o, name in page
        ],
        next_cursor=pagination.encode(page[-1][0].created_at, page[-1][0].id) if len(rows) > limit else None,
    )


@router.post("/orders", status_code=201, response_model=OrderOut)
async def create_order(
    body: OrderCreate,
    ctx: OrderWriter,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OrderOut | JSONResponse:
    async def action() -> OrderOut:
        order = await orders.create_order(
            ctx.session,
            tenant_id=ctx.tenant_id,
            plan_id=ctx.subscription.plan_id,
            user_id=ctx.user_id,
            items=_items(body.items),
            customer_id=body.customer_id,
            conversation_id=body.conversation_id,
            source_channel=body.source_channel,
            lead_source=body.lead_source,
            shipping_fee=body.shipping_fee,
            delivery_address=body.delivery_address.model_dump(exclude_none=True) if body.delivery_address else None,
            notes=body.notes,
            request=ctx.request,
        )
        await ctx.session.flush()
        await ctx.session.refresh(order)
        return await _order_out(ctx, order)

    result = await idempotency.run(
        ctx.session,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        scope="orders:create",
        actor_id=ctx.user_id,
        request_body=body,
        status=201,
        action=action,
    )
    if isinstance(result, idempotency.Replayed):
        return JSONResponse(result.body, status_code=result.status)
    return result


@router.get("/orders/{order_id}")
async def get_order(order_id: uuid.UUID, ctx: OrderReader) -> OrderOut:
    return await _order_out(ctx, await _get_order(ctx, order_id))


@router.patch("/orders/{order_id}")
async def update_order(order_id: uuid.UUID, body: OrderUpdate, ctx: OrderWriter) -> OrderOut:
    order = await orders.update_order(
        ctx.session,
        tenant_id=ctx.tenant_id,
        order_id=order_id,
        user_id=ctx.user_id,
        items=_items(body.items) if body.items is not None else None,
        shipping_fee=body.shipping_fee,
        delivery_address=body.delivery_address.model_dump(exclude_none=True) if body.delivery_address else None,
        notes=body.notes,
        lead_source=body.lead_source if "lead_source" in body.model_fields_set else None,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(order)
    return await _order_out(ctx, order)


@router.post("/orders/{order_id}/status")
async def change_status(order_id: uuid.UUID, body: StatusChange, ctx: OrderWriter) -> OrderOut:
    order = await orders.change_status(
        ctx.session,
        tenant_id=ctx.tenant_id,
        order_id=order_id,
        to_status=body.status,
        reason=body.reason,
        user_id=ctx.user_id,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(order)
    return await _order_out(ctx, order)


# --- invoices -------------------------------------------------------------------------------


async def _invoice_out(ctx: TenantContext, invoice: Invoice) -> InvoiceOut:
    items = (
        await ctx.session.execute(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.position)
        )
    ).scalars()
    return InvoiceOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        order_id=invoice.order_id,
        customer_id=invoice.customer_id,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        totals=_totals(invoice),
        lines=[
            Line(
                id=i.id,
                variant_id=None,
                description=i.description,
                sku=i.sku,
                unit=i.unit,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount_amount=i.discount_amount,
                tax_rate=i.tax_rate,
                tax_amount=i.tax_amount,
                line_total=i.line_total,
            )
            for i in items
        ],
        seller=invoice.seller_snapshot,
        buyer=invoice.buyer_snapshot,
        cancel_reason=invoice.cancel_reason,
    )


async def _get_invoice(ctx: TenantContext, invoice_id: uuid.UUID) -> Invoice:
    invoice = await ctx.session.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFound()
    return invoice


@router.post("/orders/{order_id}/invoice", status_code=201)
async def issue_invoice(order_id: uuid.UUID, ctx: InvoiceWriter, background: BackgroundTasks) -> InvoiceOut:
    invoice = await invoices.issue_from_order(
        ctx.session, tenant_id=ctx.tenant_id, order_id=order_id, user_id=ctx.user_id, request=ctx.request
    )
    # Render the PDF in the background after commit; downloading earlier renders it on demand.
    background.add_task(enqueue, "invoices.render_pdf", tenant_id=str(ctx.tenant_id), invoice_id=str(invoice.id))
    await ctx.session.refresh(invoice)
    return await _invoice_out(ctx, invoice)


@router.get("/invoices")
async def list_invoices(
    ctx: InvoiceReader,
    status: Literal["ISSUED", "CANCELLED"] | None = None,
    overdue: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[InvoiceSummary]:
    query = select(Invoice).where(Invoice.tenant_id == ctx.tenant_id, Invoice.status != "DRAFT")
    if status:
        query = query.where(Invoice.status == status)
    if overdue:
        query = query.where(Invoice.status == "ISSUED", Invoice.amount_due > 0, Invoice.due_date < func.current_date())
    rows = (await ctx.session.execute(query.order_by(Invoice.created_at.desc()).limit(limit))).scalars()
    return [
        InvoiceSummary(
            id=v.id,
            invoice_number=v.invoice_number,
            status=v.status,
            issue_date=v.issue_date,
            grand_total=v.grand_total,
        )
        for v in rows
    ]


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: uuid.UUID, ctx: InvoiceReader) -> InvoiceOut:
    return await _invoice_out(ctx, await _get_invoice(ctx, invoice_id))


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, ctx: InvoiceReader) -> Response:
    invoice = await _get_invoice(ctx, invoice_id)
    data = await invoices.pdf_bytes(ctx.session, invoice)
    filename = f"{invoice.invoice_number or 'invoice'}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(invoice_id: uuid.UUID, body: CancelInvoice, ctx: InvoiceWriter) -> InvoiceOut:
    invoice = await invoices.cancel(
        ctx.session,
        tenant_id=ctx.tenant_id,
        invoice_id=invoice_id,
        user_id=ctx.user_id,
        reason=body.reason,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(invoice)
    return await _invoice_out(ctx, invoice)
