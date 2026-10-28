"""Orders: create (from a chat or by hand), edit while new, status lifecycle with stock (spec §16, §19).

Lifecycle (ARCHITECTURE.md §15):
    NEW → CONFIRMED → PROCESSING → READY_FOR_DELIVERY → OUT_FOR_DELIVERY → DELIVERED → RETURNED
    NEW/CONFIRMED/PROCESSING → CANCELLED,  NEW → REJECTED,  OUT_FOR_DELIVERY → READY_FOR_DELIVERY (failed)
Stock leaves on CONFIRMED and comes back on CANCELLED (after confirmation) or RETURNED.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.models import (
    Conversation,
    Customer,
    CustomerAddress,
    Invoice,
    Order,
    OrderItem,
    OrderStatusHistory,
    Tenant,
    TenantSettings,
)
from app.services import audit, catalogue, entitlements, money, numbering
from app.services.audit import RequestInfo
from app.services.subscriptions import tenant_today

TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"CONFIRMED", "CANCELLED", "REJECTED"}),
    "CONFIRMED": frozenset({"PROCESSING", "READY_FOR_DELIVERY", "CANCELLED"}),
    "PROCESSING": frozenset({"READY_FOR_DELIVERY", "CANCELLED"}),
    "READY_FOR_DELIVERY": frozenset({"OUT_FOR_DELIVERY", "DELIVERED"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED", "READY_FOR_DELIVERY"}),
    "DELIVERED": frozenset({"RETURNED"}),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
    "RETURNED": frozenset(),
}
STOCK_OUT = {"CONFIRMED"}
# Leaving these states puts stock back, but only if it was taken out (i.e. after confirmation).
STOCK_BACK = {"CANCELLED", "RETURNED"}
NEEDS_REASON = {"CANCELLED", "REJECTED", "RETURNED"}


class InvalidOrder(AppError):
    status, code, title = 422, "invalid_order", "This order can't be saved"


class InvalidTransition(AppError):
    status, code, title = 409, "invalid_status_change", "This status change isn't allowed"


@dataclass(frozen=True)
class ItemInput:
    variant_id: uuid.UUID
    quantity: Decimal
    unit_price: Decimal | None = None  # None: use the current price
    discount_amount: Decimal = Decimal("0")


async def _priced_items(session: AsyncSession, tenant_id: uuid.UUID, items: list[ItemInput]) -> list[OrderItem]:
    if not items:
        raise InvalidOrder("Add at least one product.")
    settings = await session.get(TenantSettings, tenant_id)
    inclusive = bool(settings and settings.prices_include_tax)
    info = await catalogue.variant_info(session, tenant_id, [i.variant_id for i in items])
    rows: list[OrderItem] = []
    for position, item in enumerate(items):
        found = info.get(item.variant_id)
        if found is None or not found.variant.is_active or not found.product.is_active or found.product.deleted_at:
            raise InvalidOrder("One of the products isn't available any more.")
        unit_price = item.unit_price if item.unit_price is not None else found.price
        if unit_price is None:
            raise InvalidOrder(f"{found.product.name} has no price yet. Enter a price.")
        line = money.LineInput(item.quantity, unit_price, item.discount_amount, found.tax_rate)
        try:
            amounts = money.line_amounts(line, prices_include_tax=inclusive)
        except money.InvalidLine as exc:
            raise InvalidOrder(f"{found.product.name}: {exc}") from None
        name = found.product.name if found.variant.is_default else f"{found.product.name} ({found.variant.name})"
        rows.append(
            OrderItem(
                tenant_id=tenant_id,
                variant_id=found.variant.id,
                product_name=name,
                sku=found.variant.sku,
                unit=found.product.unit,
                quantity=item.quantity,
                unit_price=money.money(unit_price),
                discount_amount=money.money(item.discount_amount),
                tax_rate=found.tax_rate,
                tax_amount=amounts.tax_amount,
                line_total=amounts.line_total,
                position=position,
            )
        )
    return rows


def _apply_totals(order: Order, items: list[OrderItem], inclusive: bool) -> None:
    lines = [
        (
            money.LineInput(i.quantity, i.unit_price, i.discount_amount, i.tax_rate),
            money.line_amounts(
                money.LineInput(i.quantity, i.unit_price, i.discount_amount, i.tax_rate), prices_include_tax=inclusive
            ),
        )
        for i in items
    ]
    t = money.totals(lines, shipping_fee=order.shipping_fee)
    order.subtotal, order.discount_total, order.tax_total, order.grand_total = (
        t.subtotal,
        t.discount_total,
        t.tax_total,
        t.grand_total,
    )
    order.amount_due = t.grand_total - order.amount_paid


async def _default_address(session: AsyncSession, customer_id: uuid.UUID) -> dict[str, Any] | None:
    address = (
        await session.execute(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == customer_id, CustomerAddress.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
    if address is None:
        return None
    return {
        k: getattr(address, k)
        for k in ("contact_name", "contact_phone", "line1", "area", "city", "district", "province", "landmark")
        if getattr(address, k)
    }


async def create_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID | None,
    user_id: uuid.UUID,
    items: list[ItemInput],
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    source_channel: str | None = None,
    lead_source: str | None = None,
    shipping_fee: Decimal = Decimal("0"),
    delivery_address: dict[str, Any] | None = None,
    notes: str | None = None,
    request: RequestInfo,
) -> Order:
    channel_account_id = None
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFound()
        customer_id, source_channel, channel_account_id = (
            conversation.customer_id,
            conversation.provider,
            conversation.channel_account_id,
        )
    if customer_id is None:
        raise InvalidOrder("Choose a customer.")
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise NotFound()
    if customer.status == "merged":
        raise InvalidOrder("This customer was merged into another record. Use that record instead.")

    tenant = await session.get(Tenant, tenant_id)
    settings = await session.get(TenantSettings, tenant_id)
    assert tenant is not None
    today = tenant_today(tenant.timezone)
    await entitlements.count_usage(
        session,
        tenant_id=tenant_id,
        plan_id=plan_id,
        metric="orders",
        key="max_monthly_orders",
        period_start=today.replace(day=1),
    )
    rows = await _priced_items(session, tenant_id, items)
    order = Order(
        tenant_id=tenant_id,
        order_number=await numbering.next_number(
            session, tenant_id, "ORD", numbering.period_key(tenant.numbering_period, today)
        ),
        customer_id=customer.id,
        source_channel=source_channel or "other",
        source_conversation_id=conversation_id,
        channel_account_id=channel_account_id,
        lead_source=lead_source,
        status="NEW",
        currency=tenant.currency,
        shipping_fee=money.money(shipping_fee),
        delivery_address=delivery_address or await _default_address(session, customer.id),
        notes=notes,
        created_by=user_id,
        amount_paid=Decimal("0"),
    )
    _apply_totals(order, rows, bool(settings and settings.prices_include_tax))
    session.add(order)
    await session.flush()
    for row in rows:
        row.order_id = order.id
    session.add_all(rows)
    session.add(
        OrderStatusHistory(
            tenant_id=tenant_id, order_id=order.id, from_status=None, to_status="NEW", changed_by=user_id
        )
    )
    customer.last_interaction_at = datetime.now(UTC)
    await audit.record(
        session,
        action="ORDER_CREATED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="order",
        resource_id=order.id,
        after={
            "order_number": order.order_number,
            "grand_total": str(order.grand_total),
            "source": order.source_channel,
        },
        request=request,
    )
    return order


async def order_items(session: AsyncSession, order_id: uuid.UUID) -> list[OrderItem]:
    return list(
        (
            await session.execute(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.position))
        ).scalars()
    )


async def _locked(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if order is None:
        raise NotFound()
    return order


async def update_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    items: list[ItemInput] | None,
    shipping_fee: Decimal | None,
    delivery_address: dict[str, Any] | None,
    notes: str | None,
    lead_source: str | None,
    request: RequestInfo,
) -> Order:
    order = await _locked(session, order_id)
    if (items is not None or shipping_fee is not None) and order.status != "NEW":
        raise Conflict("Items and prices can only be changed while the order is new.", code="order_locked")
    before = {"grand_total": str(order.grand_total)}
    if items is not None:
        rows = await _priced_items(session, tenant_id, items)
        await session.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
        for row in rows:
            row.order_id = order.id
        session.add_all(rows)
    else:
        rows = await order_items(session, order.id)
    if shipping_fee is not None:
        order.shipping_fee = money.money(shipping_fee)
    if delivery_address is not None:
        order.delivery_address = delivery_address
    if notes is not None:
        order.notes = notes
    if lead_source is not None:
        order.lead_source = lead_source or None
    settings = await session.get(TenantSettings, tenant_id)
    _apply_totals(order, rows, bool(settings and settings.prices_include_tax))
    await audit.record(
        session,
        action="ORDER_UPDATED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="order",
        resource_id=order.id,
        before=before,
        after={"grand_total": str(order.grand_total)},
        request=request,
    )
    return order


async def change_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    to_status: str,
    reason: str | None,
    user_id: uuid.UUID,
    request: RequestInfo,
) -> Order:
    order = await _locked(session, order_id)
    current = order.status
    if to_status not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(
            f"An order that is {current.lower().replace('_', ' ')} can't move to {to_status.lower().replace('_', ' ')}."
        )
    if to_status in NEEDS_REASON and not (reason and reason.strip()):
        raise InvalidOrder("Please give a reason.")
    if to_status in ("CANCELLED", "REJECTED"):
        live_invoice = (
            await session.execute(
                select(Invoice.invoice_number).where(Invoice.order_id == order.id, Invoice.status == "ISSUED")
            )
        ).scalar_one_or_none()
        if live_invoice:
            raise Conflict(f"Cancel invoice {live_invoice} first.", code="invoice_issued")

    items = await order_items(session, order.id)
    tracked = await catalogue.variant_info(session, tenant_id, [i.variant_id for i in items])
    stock_taken = current not in ("NEW",)  # stock left when the order was confirmed
    direction = (
        Decimal("-1") if to_status in STOCK_OUT else Decimal("1") if to_status in STOCK_BACK and stock_taken else None
    )
    if direction is not None:
        reason_code = {"CONFIRMED": "order_confirmed", "CANCELLED": "order_cancelled", "RETURNED": "order_returned"}[
            to_status
        ]
        for item in items:
            info = tracked.get(item.variant_id)
            if info is None or not info.product.track_inventory:
                continue
            await catalogue.adjust_stock(
                session,
                tenant_id=tenant_id,
                variant_id=item.variant_id,
                delta=direction * item.quantity,
                reason=reason_code,
                user_id=user_id,
                reference_type="order",
                reference_id=order.id,
                note=order.order_number,
            )

    now = datetime.now(UTC)
    order.status = to_status
    if to_status == "CONFIRMED":
        order.confirmed_at = now
    if to_status in ("CANCELLED", "REJECTED"):
        order.cancelled_at, order.cancel_reason = now, reason
    session.add(
        OrderStatusHistory(
            tenant_id=tenant_id,
            order_id=order.id,
            from_status=current,
            to_status=to_status,
            reason=reason,
            changed_by=user_id,
        )
    )
    await audit.record(
        session,
        action="ORDER_STATUS_CHANGED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="order",
        resource_id=order.id,
        before={"status": current},
        after={"status": to_status, "reason": reason},
        request=request,
    )
    return order
