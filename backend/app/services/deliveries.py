"""Manual delivery records: create, assign, status updates that move the order along (ARCHITECTURE.md §15).

Delivery lifecycle:
    PENDING/ASSIGNED → PICKED_UP → OUT_FOR_DELIVERY → DELIVERED → RETURNED
    PENDING/ASSIGNED → DELIVERED (customer pickup), → CANCELLED;  PICKED_UP/OUT_FOR_DELIVERY → FAILED
One open delivery per order; after FAILED a new attempt can be created.

The order follows its delivery: picked up / out for delivery → order OUT_FOR_DELIVERY, delivered →
DELIVERED, failed → back to READY_FOR_DELIVERY, returned → RETURNED (stock comes back).
"""

import uuid
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, NotFound
from app.models import Customer, Delivery, DeliveryStatusHistory, Order, Tenant, TenantMembership
from app.models.fulfilment import DELIVERY_CLOSED
from app.services import audit, money, numbering, orders, payments
from app.services.audit import RequestInfo
from app.services.subscriptions import tenant_today

TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"ASSIGNED", "PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}),
    "ASSIGNED": frozenset({"PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}),
    "PICKED_UP": frozenset({"OUT_FOR_DELIVERY", "DELIVERED", "FAILED"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED", "FAILED"}),
    "DELIVERED": frozenset({"RETURNED"}),
    "FAILED": frozenset(),
    "RETURNED": frozenset(),
    "CANCELLED": frozenset(),
}
NEEDS_NOTE = {"FAILED", "RETURNED", "CANCELLED"}
# Order status each delivery status leads to (None: the order stays where it is).
ORDER_TARGET: dict[str, str | None] = {
    "ASSIGNED": None,
    "PICKED_UP": "OUT_FOR_DELIVERY",
    "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
    "DELIVERED": "DELIVERED",
    "FAILED": "READY_FOR_DELIVERY",
    "RETURNED": "RETURNED",
    "CANCELLED": None,
}
DELIVERABLE_ORDER = {"CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY"}


class InvalidDelivery(AppError):
    status, code, title = 422, "invalid_delivery", "This delivery can't be saved"


def order_path(current: str, target: str) -> list[str]:
    """Shortest chain of allowed order steps from ``current`` to ``target`` (e.g. CONFIRMED → READY → OUT).

    Never passes through a stop state (cancelled, rejected, returned) on the way.
    """
    if current == target:
        return []
    seen, queue = {current}, deque([(current, list[str]())])
    while queue:
        state, path = queue.popleft()
        for step in sorted(orders.TRANSITIONS.get(state, frozenset())):
            if step == target:
                return [*path, step]
            if step not in seen and step not in orders.NEEDS_REASON:
                seen.add(step)
                queue.append((step, [*path, step]))
    return []


async def _check_assignee(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    member = (
        await session.execute(
            select(TenantMembership.id).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
                TenantMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise InvalidDelivery("Choose someone from your team.")


def _history(
    delivery: Delivery, from_status: str | None, to_status: str, note: str | None, user_id: uuid.UUID
) -> DeliveryStatusHistory:
    return DeliveryStatusHistory(
        tenant_id=delivery.tenant_id,
        delivery_id=delivery.id,
        from_status=from_status,
        to_status=to_status,
        note=note,
        changed_by=user_id,
    )


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    method: str,
    courier_name: str | None = None,
    tracking_reference: str | None = None,
    assigned_to: uuid.UUID | None = None,
    scheduled_date: date | None = None,
    cod_amount: Decimal | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    delivery_address: dict[str, Any] | None = None,
    notes: str | None = None,
    request: RequestInfo,
) -> Delivery:
    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if order is None:
        raise NotFound()
    if order.status not in DELIVERABLE_ORDER:
        raise InvalidDelivery(
            "Confirm the order first." if order.status == "NEW" else "This order can't be sent for delivery now."
        )
    if (current := await orders.open_delivery_for(session, order.id)) is not None:
        raise Conflict(f"Delivery {current.delivery_number} is still open for this order.", code="delivery_open")
    if method == "courier" and not (courier_name and courier_name.strip()):
        raise InvalidDelivery("Enter the courier's name.")
    await _check_assignee(session, tenant_id, assigned_to)

    tenant = await session.get(Tenant, tenant_id)
    customer = await session.get(Customer, order.customer_id)
    assert tenant is not None and customer is not None
    cod = money.money(order.amount_due if cod_amount is None else cod_amount)
    if cod < 0 or cod > order.amount_due:
        raise InvalidDelivery(f"Cash to collect can't be more than the {money.money(order.amount_due)} due.")
    status = "ASSIGNED" if assigned_to else "PENDING"
    delivery = Delivery(
        tenant_id=tenant_id,
        delivery_number=await numbering.next_number(
            session, tenant_id, "DEL", numbering.period_key(tenant.numbering_period, tenant_today(tenant.timezone))
        ),
        order_id=order.id,
        delivery_method=method,
        courier_name=courier_name if method == "courier" else None,
        tracking_reference=tracking_reference,
        assigned_to=assigned_to,
        delivery_address=delivery_address or order.delivery_address,
        contact_name=contact_name or customer.display_name,
        contact_phone=contact_phone or customer.phone_e164,
        cod_amount=cod,
        status=status,
        scheduled_date=scheduled_date,
        delivery_notes=notes,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(delivery)
    await session.flush()
    session.add(_history(delivery, None, status, None, user_id))
    await audit.record(
        session,
        action="DELIVERY_CREATED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="delivery",
        resource_id=delivery.id,
        after={"delivery_number": delivery.delivery_number, "order_number": order.order_number, "method": method},
        request=request,
    )
    return delivery


async def update(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    delivery_id: uuid.UUID,
    user_id: uuid.UUID,
    changes: dict[str, Any],
    request: RequestInfo,
) -> Delivery:
    """Edit details of an open delivery (assignee, courier, tracking, date, cash to collect, notes)."""
    delivery = await session.get(Delivery, delivery_id)
    if delivery is None:
        raise NotFound()
    if delivery.status in DELIVERY_CLOSED:
        raise Conflict("This delivery is closed and can't be changed.", code="delivery_closed")
    if "assigned_to" in changes:
        await _check_assignee(session, tenant_id, changes["assigned_to"])
        if delivery.status in ("PENDING", "ASSIGNED"):
            new_status = "ASSIGNED" if changes["assigned_to"] else "PENDING"
            if new_status != delivery.status:
                session.add(_history(delivery, delivery.status, new_status, None, user_id))
                delivery.status = new_status
    if "cod_amount" in changes and changes["cod_amount"] is not None:
        order = await session.get(Order, delivery.order_id)
        assert order is not None
        if money.money(changes["cod_amount"]) > order.amount_due:
            raise InvalidDelivery(f"Cash to collect can't be more than the {money.money(order.amount_due)} due.")
    before = {key: str(getattr(delivery, key)) for key in changes}
    for key, value in changes.items():
        setattr(delivery, key, value)
    delivery.updated_by = user_id
    await audit.record(
        session,
        action="DELIVERY_UPDATED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="delivery",
        resource_id=delivery.id,
        before=before,
        after={key: str(value) for key, value in changes.items()},
        request=request,
    )
    return delivery


async def change_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    delivery_id: uuid.UUID,
    to_status: str,
    note: str | None,
    user_id: uuid.UUID,
    permissions: frozenset[str],
    cod_collected: Decimal | None = None,
    request: RequestInfo,
) -> Delivery:
    delivery = await session.get(Delivery, delivery_id)
    if delivery is None:
        raise NotFound()
    # Lock the order first (same order as payments and orders) so concurrent updates queue up.
    order = (await session.execute(select(Order).where(Order.id == delivery.order_id).with_for_update())).scalar_one()
    await session.refresh(delivery)
    current = delivery.status
    if to_status not in TRANSITIONS.get(current, frozenset()):
        raise InvalidDelivery(
            f"A delivery that is {current.lower().replace('_', ' ')} can't be marked "
            f"{to_status.lower().replace('_', ' ')}."
        )
    if to_status in NEEDS_NOTE and not (note and note.strip()):
        raise InvalidDelivery("Please say what happened.")
    if cod_collected and to_status != "DELIVERED":
        raise InvalidDelivery("Cash can only be recorded when the delivery is done.")
    if cod_collected and "payment.write" not in permissions:
        raise Forbidden("You don't have permission to record payments.")

    target = ORDER_TARGET.get(to_status)
    path = order_path(order.status, target) if target else []
    if target and order.status != target and not path:
        raise InvalidDelivery(f"The order is {order.status.lower().replace('_', ' ')} and can't follow this delivery.")

    delivery.status, delivery.updated_by = to_status, user_id
    if to_status == "DELIVERED":
        delivery.delivered_at = datetime.now(UTC)
    session.add(_history(delivery, current, to_status, note, user_id))
    await session.flush()
    for step in path:
        await orders.change_status(
            session,
            tenant_id=tenant_id,
            order_id=order.id,
            to_status=step,
            reason=note or f"Delivery {delivery.delivery_number}",
            user_id=user_id,
            request=request,
            via_delivery=True,
        )
    if cod_collected:
        await payments.record(
            session,
            tenant_id=tenant_id,
            order_id=order.id,
            user_id=user_id,
            type="payment",
            amount=cod_collected,
            method="cod",
            delivery_id=delivery.id,
            notes=f"Collected on delivery {delivery.delivery_number}",
            cod_only="payment.read" not in permissions,
            request=request,
        )
    await audit.record(
        session,
        action="DELIVERY_STATUS_CHANGED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="delivery",
        resource_id=delivery.id,
        before={"status": current},
        after={"status": to_status, "note": note, "order_status": order.status},
        request=request,
    )
    return delivery
