"""Deliveries and payments, recorded by hand: /api/v1/deliveries, /api/v1/payments (ARCHITECTURE.md §15)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import pagination
from app.api.deps import TenantContext, require
from app.core.exceptions import NotFound
from app.models import (
    Customer,
    Delivery,
    DeliveryStatusHistory,
    MembershipRole,
    Order,
    Payment,
    Role,
    TenantMembership,
    User,
)
from app.models.fulfilment import DELIVERY_CLOSED, DELIVERY_METHODS, DELIVERY_STATUSES, PAYMENT_METHODS
from app.schemas.auth import StrictModel
from app.services import deliveries, idempotency, payments
from app.services.subscriptions import tenant_today

router = APIRouter(tags=["deliveries", "payments"])

DeliveryReader = Annotated[TenantContext, Depends(require("delivery.read"))]
DeliveryWriter = Annotated[TenantContext, Depends(require("delivery.write", write=True))]
PaymentReader = Annotated[TenantContext, Depends(require("payment.read"))]
PaymentWriter = Annotated[TenantContext, Depends(require("payment.write", write=True))]
# Voiding needs full payment access; DELIVERY staff can record COD but never void.
PaymentVoider = Annotated[TenantContext, Depends(require("payment.write", "payment.read", write=True))]

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Method = Literal[DELIVERY_METHODS]  # type: ignore[valid-type]
DeliveryStatus = Literal[DELIVERY_STATUSES]  # type: ignore[valid-type]
PayMethod = Literal[PAYMENT_METHODS]  # type: ignore[valid-type]


# --- schemas ---------------------------------------------------------------------------------


class Address(StrictModel):
    line1: str | None = Field(default=None, max_length=300)
    area: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    landmark: str | None = Field(default=None, max_length=200)


class DeliveryCreate(StrictModel):
    method: Method
    courier_name: str | None = Field(default=None, max_length=100)
    tracking_reference: str | None = Field(default=None, max_length=100)
    assigned_to: uuid.UUID | None = None
    scheduled_date: date | None = None
    cod_amount: Money | None = None  # omitted: everything still due
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=30)
    delivery_address: Address | None = None
    notes: str | None = Field(default=None, max_length=1000)


class DeliveryUpdate(StrictModel):
    courier_name: str | None = Field(default=None, max_length=100)
    tracking_reference: str | None = Field(default=None, max_length=100)
    assigned_to: uuid.UUID | None = None
    scheduled_date: date | None = None
    cod_amount: Money | None = None
    contact_phone: str | None = Field(default=None, max_length=30)
    delivery_notes: str | None = Field(default=None, max_length=1000)


class DeliveryStatusChange(StrictModel):
    status: DeliveryStatus
    note: str | None = Field(default=None, max_length=500)
    cod_collected: Money | None = None  # cash collected on the doorstep, recorded as a COD payment


class PaymentCreate(StrictModel):
    type: Literal["payment", "refund"] = "payment"
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    method: PayMethod
    reference: str | None = Field(default=None, max_length=100)
    paid_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)
    delivery_id: uuid.UUID | None = None


class VoidPayment(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class Person(BaseModel):
    id: uuid.UUID
    name: str


class OrderRef(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    customer: Person
    grand_total: Decimal
    amount_due: Decimal
    currency: str


class DeliveryEvent(BaseModel):
    from_status: str | None
    to_status: str
    note: str | None
    at: datetime


class DeliveryOut(BaseModel):
    id: uuid.UUID
    delivery_number: str
    order: OrderRef
    method: str
    courier_name: str | None
    tracking_reference: str | None
    assigned_to: Person | None
    delivery_address: dict[str, Any] | None
    contact_name: str | None
    contact_phone: str | None
    cod_amount: Decimal
    status: str
    scheduled_date: date | None
    delivered_at: datetime | None
    notes: str | None
    allowed_next: list[str]
    history: list[DeliveryEvent]
    created_at: datetime


class DeliveryPage(BaseModel):
    items: list[DeliveryOut]
    next_cursor: str | None


class PaymentOut(BaseModel):
    id: uuid.UUID
    payment_number: str
    order: OrderRef
    delivery_id: uuid.UUID | None
    type: str
    amount: Decimal
    currency: str
    method: str
    reference: str | None
    paid_at: datetime
    notes: str | None
    status: str
    void_reason: str | None
    recorded_by: Person | None


class PaymentPage(BaseModel):
    items: list[PaymentOut]
    next_cursor: str | None


class StaffMember(BaseModel):
    user_id: uuid.UUID
    full_name: str
    roles: list[str]


# --- helpers ---------------------------------------------------------------------------------


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict((await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))).all())


async def _orders(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, OrderRef]:
    rows = await session.execute(
        select(Order, Customer.display_name).join(Customer, Customer.id == Order.customer_id).where(Order.id.in_(ids))
    )
    return {
        o.id: OrderRef(
            id=o.id,
            order_number=o.order_number,
            status=o.status,
            customer=Person(id=o.customer_id, name=name),
            grand_total=o.grand_total,
            amount_due=o.amount_due,
            currency=o.currency,
        )
        for o, name in rows
    }


async def deliveries_out(session: AsyncSession, rows: list[Delivery], *, history: bool = False) -> list[DeliveryOut]:
    if not rows:
        return []
    order_refs = await _orders(session, {d.order_id for d in rows})
    names = await _names(session, {d.assigned_to for d in rows})
    events: dict[uuid.UUID, list[DeliveryEvent]] = {}
    if history:
        for h in (
            await session.execute(
                select(DeliveryStatusHistory)
                .where(DeliveryStatusHistory.delivery_id.in_([d.id for d in rows]))
                .order_by(DeliveryStatusHistory.created_at)
            )
        ).scalars():
            events.setdefault(h.delivery_id, []).append(
                DeliveryEvent(from_status=h.from_status, to_status=h.to_status, note=h.note, at=h.created_at)
            )
    return [
        DeliveryOut(
            id=d.id,
            delivery_number=d.delivery_number,
            order=order_refs[d.order_id],
            method=d.delivery_method,
            courier_name=d.courier_name,
            tracking_reference=d.tracking_reference,
            assigned_to=Person(id=d.assigned_to, name=names.get(d.assigned_to, "")) if d.assigned_to else None,
            delivery_address=d.delivery_address,
            contact_name=d.contact_name,
            contact_phone=d.contact_phone,
            cod_amount=d.cod_amount,
            status=d.status,
            scheduled_date=d.scheduled_date,
            delivered_at=d.delivered_at,
            notes=d.delivery_notes,
            allowed_next=sorted(deliveries.TRANSITIONS.get(d.status, frozenset())),
            history=events.get(d.id, []),
            created_at=d.created_at,
        )
        for d in rows
    ]


async def payments_out(session: AsyncSession, rows: list[Payment]) -> list[PaymentOut]:
    if not rows:
        return []
    order_refs = await _orders(session, {p.order_id for p in rows})
    names = await _names(session, {p.recorded_by for p in rows})
    return [
        PaymentOut(
            id=p.id,
            payment_number=p.payment_number,
            order=order_refs[p.order_id],
            delivery_id=p.delivery_id,
            type=p.type,
            amount=p.amount,
            currency=p.currency,
            method=p.payment_method,
            reference=p.transaction_reference,
            paid_at=p.paid_at,
            notes=p.notes,
            status=p.status,
            void_reason=p.void_reason,
            recorded_by=Person(id=p.recorded_by, name=names.get(p.recorded_by, "")) if p.recorded_by else None,
        )
        for p in rows
    ]


async def _delivery(ctx: TenantContext, delivery_id: uuid.UUID) -> DeliveryOut:
    row = await ctx.session.get(Delivery, delivery_id)
    if row is None:
        raise NotFound()
    await ctx.session.refresh(row)
    return (await deliveries_out(ctx.session, [row], history=True))[0]


# --- deliveries ------------------------------------------------------------------------------


@router.get("/deliveries")
async def list_deliveries(
    ctx: DeliveryReader,
    view: Literal["open", "today", "mine", "all"] = "open",
    status: DeliveryStatus | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> DeliveryPage:
    query = select(Delivery).where(Delivery.tenant_id == ctx.tenant_id)
    if view != "all":
        query = query.where(Delivery.status.not_in(DELIVERY_CLOSED))
    if view == "today":
        query = query.where(
            or_(Delivery.scheduled_date.is_(None), Delivery.scheduled_date <= tenant_today(ctx.tenant.timezone))
        )
    if view == "mine":
        query = query.where(Delivery.assigned_to == ctx.user_id)
    if status:
        query = query.where(Delivery.status == status)
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(Delivery.created_at < stamp, and_(Delivery.created_at == stamp, Delivery.id < last_id)))
    rows = list(
        (
            await ctx.session.execute(query.order_by(Delivery.created_at.desc(), Delivery.id.desc()).limit(limit + 1))
        ).scalars()
    )
    page = rows[:limit]
    return DeliveryPage(
        items=await deliveries_out(ctx.session, page),
        next_cursor=pagination.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None,
    )


@router.get("/deliveries/staff")
async def delivery_staff(ctx: DeliveryWriter) -> list[StaffMember]:
    """Active team members a delivery can be assigned to."""
    rows = await ctx.session.execute(
        select(User.id, User.full_name, Role.code)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .outerjoin(MembershipRole, MembershipRole.membership_id == TenantMembership.id)
        .outerjoin(Role, Role.id == MembershipRole.role_id)
        .where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.status == "active")
        .order_by(User.full_name)
    )
    staff: dict[uuid.UUID, StaffMember] = {}
    for user_id, name, role in rows:
        member = staff.setdefault(user_id, StaffMember(user_id=user_id, full_name=name, roles=[]))
        if role:
            member.roles.append(role)
    # People in the DELIVERY role first: they are the usual choice.
    return sorted(staff.values(), key=lambda m: ("DELIVERY" not in m.roles, m.full_name.lower()))


@router.get("/deliveries/{delivery_id}")
async def get_delivery(delivery_id: uuid.UUID, ctx: DeliveryReader) -> DeliveryOut:
    return await _delivery(ctx, delivery_id)


@router.post("/orders/{order_id}/deliveries", status_code=201)
async def create_delivery(order_id: uuid.UUID, body: DeliveryCreate, ctx: DeliveryWriter) -> DeliveryOut:
    delivery = await deliveries.create(
        ctx.session,
        tenant_id=ctx.tenant_id,
        order_id=order_id,
        user_id=ctx.user_id,
        method=body.method,
        courier_name=body.courier_name,
        tracking_reference=body.tracking_reference,
        assigned_to=body.assigned_to,
        scheduled_date=body.scheduled_date,
        cod_amount=body.cod_amount,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        delivery_address=body.delivery_address.model_dump(exclude_none=True) if body.delivery_address else None,
        notes=body.notes,
        request=ctx.request,
    )
    await ctx.session.flush()
    return await _delivery(ctx, delivery.id)


@router.patch("/deliveries/{delivery_id}")
async def update_delivery(delivery_id: uuid.UUID, body: DeliveryUpdate, ctx: DeliveryWriter) -> DeliveryOut:
    await deliveries.update(
        ctx.session,
        tenant_id=ctx.tenant_id,
        delivery_id=delivery_id,
        user_id=ctx.user_id,
        changes=body.model_dump(exclude_unset=True),
        request=ctx.request,
    )
    await ctx.session.flush()
    return await _delivery(ctx, delivery_id)


@router.post("/deliveries/{delivery_id}/status")
async def change_delivery_status(
    delivery_id: uuid.UUID, body: DeliveryStatusChange, ctx: DeliveryWriter
) -> DeliveryOut:
    await deliveries.change_status(
        ctx.session,
        tenant_id=ctx.tenant_id,
        delivery_id=delivery_id,
        to_status=body.status,
        note=body.note,
        user_id=ctx.user_id,
        permissions=ctx.permissions,
        cod_collected=body.cod_collected,
        request=ctx.request,
    )
    await ctx.session.flush()
    return await _delivery(ctx, delivery_id)


# --- payments --------------------------------------------------------------------------------


@router.get("/payments")
async def list_payments(
    ctx: PaymentReader,
    method: PayMethod | None = None,
    type: Literal["payment", "refund"] | None = None,
    include_voided: bool = False,
    since: date | None = None,
    until: date | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> PaymentPage:
    query = select(Payment).where(Payment.tenant_id == ctx.tenant_id)
    if not include_voided:
        query = query.where(Payment.status == "recorded")
    if method:
        query = query.where(Payment.payment_method == method)
    if type:
        query = query.where(Payment.type == type)
    if since:
        query = query.where(Payment.paid_at >= since)
    if until:
        query = query.where(Payment.paid_at < until)
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(Payment.paid_at < stamp, and_(Payment.paid_at == stamp, Payment.id < last_id)))
    rows = list(
        (
            await ctx.session.execute(query.order_by(Payment.paid_at.desc(), Payment.id.desc()).limit(limit + 1))
        ).scalars()
    )
    page = rows[:limit]
    return PaymentPage(
        items=await payments_out(ctx.session, page),
        next_cursor=pagination.encode(page[-1].paid_at, page[-1].id) if len(rows) > limit else None,
    )


@router.post("/orders/{order_id}/payments", status_code=201, response_model=PaymentOut)
async def record_payment(
    order_id: uuid.UUID,
    body: PaymentCreate,
    ctx: PaymentWriter,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentOut | JSONResponse:
    async def action() -> PaymentOut:
        payment = await payments.record(
            ctx.session,
            tenant_id=ctx.tenant_id,
            order_id=order_id,
            user_id=ctx.user_id,
            type=body.type,
            amount=body.amount,
            method=body.method,
            reference=body.reference,
            paid_at=body.paid_at,
            notes=body.notes,
            delivery_id=body.delivery_id,
            cod_only="payment.read" not in ctx.permissions,
            request=ctx.request,
        )
        await ctx.session.flush()
        return (await payments_out(ctx.session, [payment]))[0]

    result = await idempotency.run(
        ctx.session,
        tenant_id=ctx.tenant_id,
        key=idempotency_key,
        scope=f"payments:{order_id}",
        actor_id=ctx.user_id,
        request_body=body,
        status=201,
        action=action,
    )
    if isinstance(result, idempotency.Replayed):
        return JSONResponse(result.body, status_code=result.status)
    return result


@router.post("/payments/{payment_id}/void")
async def void_payment(payment_id: uuid.UUID, body: VoidPayment, ctx: PaymentVoider) -> PaymentOut:
    payment = await payments.void(
        ctx.session,
        tenant_id=ctx.tenant_id,
        payment_id=payment_id,
        user_id=ctx.user_id,
        reason=body.reason,
        request=ctx.request,
    )
    await ctx.session.flush()
    return (await payments_out(ctx.session, [payment]))[0]
