"""Manual payment records: record, refund, void (ARCHITECTURE.md §15, DATABASE.md §12).

Rows are never edited; a mistake is voided with a reason and recorded again. After every insert or
void the order (and its live invoice) balance is recomputed from the recorded rows, with the order
row locked, in the same transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, NotFound
from app.models import Delivery, Invoice, Order, Payment, Tenant
from app.services import audit, money, numbering
from app.services.audit import RequestInfo
from app.services.subscriptions import tenant_today

METHOD_LABEL = {
    "cash": "Cash",
    "cod": "Cash on delivery",
    "esewa": "eSewa",
    "khalti": "Khalti",
    "fonepay": "Fonepay",
    "bank_transfer": "Bank transfer",
    "cheque": "Cheque",
    "other": "Other",
}


class InvalidPayment(AppError):
    status, code, title = 422, "invalid_payment", "This payment can't be recorded"


async def _locked_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one_or_none()
    if order is None:
        raise NotFound()
    return order


async def refresh_balance(session: AsyncSession, order: Order) -> money.Balance:
    """Recompute amount_paid/amount_due/payment_status on the order and its live invoice."""
    sums = dict(
        (
            await session.execute(
                select(Payment.type, func.coalesce(func.sum(Payment.amount), 0))
                .where(Payment.order_id == order.id, Payment.status == "recorded")
                .group_by(Payment.type)
            )
        ).all()
    )
    b = money.balance(order.grand_total, paid=Decimal(sums.get("payment", 0)), refunded=Decimal(sums.get("refund", 0)))
    order.amount_paid, order.amount_due, order.payment_status = b.amount_paid, b.amount_due, b.payment_status
    invoice = (
        await session.execute(select(Invoice).where(Invoice.order_id == order.id, Invoice.status == "ISSUED"))
    ).scalar_one_or_none()
    if invoice is not None:
        invoice.amount_paid = b.amount_paid
        invoice.amount_due = money.money(invoice.grand_total - b.amount_paid)
        invoice.payment_status = b.payment_status
    return b


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    type: str,
    amount: Decimal,
    method: str,
    reference: str | None = None,
    paid_at: datetime | None = None,
    notes: str | None = None,
    delivery_id: uuid.UUID | None = None,
    cod_only: bool = False,
    request: RequestInfo,
) -> Payment:
    """``cod_only``: the recorder may only record cash collected on a delivery assigned to them (DELIVERY role)."""
    order = await _locked_order(session, order_id)
    amount = money.money(amount)
    if amount <= 0:
        raise InvalidPayment("Enter an amount more than zero.")
    now = datetime.now(UTC)
    paid_at = paid_at or now
    if paid_at > now + timedelta(minutes=5):
        raise InvalidPayment("The payment date can't be in the future.")

    delivery = None
    if delivery_id is not None:
        delivery = await session.get(Delivery, delivery_id)
        if delivery is None or delivery.order_id != order.id:
            raise NotFound()
    if cod_only and (type != "payment" or method != "cod" or delivery is None or delivery.assigned_to != user_id):
        raise Forbidden("You can only record cash collected on your own deliveries.")

    if type == "payment":
        if order.status in ("CANCELLED", "REJECTED"):
            raise InvalidPayment("This order was cancelled. Record a refund instead if money was returned.")
        if amount > order.amount_due:
            raise InvalidPayment(f"That's more than the {money.money(order.amount_due)} still due on this order.")
    elif amount > order.amount_paid:
        raise InvalidPayment(f"A refund can't be more than the {money.money(order.amount_paid)} paid.")

    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    invoice_id = (
        await session.execute(select(Invoice.id).where(Invoice.order_id == order.id, Invoice.status == "ISSUED"))
    ).scalar_one_or_none()
    payment = Payment(
        tenant_id=tenant_id,
        payment_number=await numbering.next_number(
            session, tenant_id, "PAY", numbering.period_key(tenant.numbering_period, tenant_today(tenant.timezone))
        ),
        order_id=order.id,
        invoice_id=invoice_id,
        customer_id=order.customer_id,
        delivery_id=delivery_id,
        type=type,
        amount=amount,
        currency=order.currency,
        payment_method=method,
        transaction_reference=reference,
        paid_at=paid_at,
        notes=notes,
        status="recorded",
        recorded_by=user_id,
    )
    session.add(payment)
    await session.flush()
    b = await refresh_balance(session, order)
    await audit.record(
        session,
        action="PAYMENT_RECORDED" if type == "payment" else "REFUND_RECORDED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="payment",
        resource_id=payment.id,
        after={
            "payment_number": payment.payment_number,
            "order_number": order.order_number,
            "amount": str(amount),
            "method": method,
            "order_payment_status": b.payment_status,
        },
        request=request,
    )
    return payment


async def void(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payment_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
    request: RequestInfo,
) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise NotFound()
    order = await _locked_order(session, payment.order_id)
    await session.refresh(payment)  # read again under the order lock
    if payment.status != "recorded":
        raise Conflict("This payment was already voided.", code="payment_voided")
    if payment.type == "payment" and payment.amount > order.amount_paid:
        raise Conflict("Void the refund on this order first.", code="refund_exists")
    payment.status = "voided"
    payment.voided_by, payment.voided_at, payment.void_reason = user_id, datetime.now(UTC), reason
    await session.flush()
    b = await refresh_balance(session, order)
    await audit.record(
        session,
        action="PAYMENT_VOIDED",
        actor_type="user",
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="payment",
        resource_id=payment.id,
        before={"status": "recorded", "amount": str(payment.amount)},
        after={"status": "voided", "reason": reason, "order_payment_status": b.payment_status},
        request=request,
    )
    return payment
