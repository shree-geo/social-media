"""Dashboard figures (spec §22-24): SQL aggregates over indexed columns, per tenant (ARCHITECTURE.md §20).

Definitions, so every number on the dashboard means one thing:

* **Sales** - grand total of orders created in the period that were confirmed and not cancelled,
  rejected or returned (``SALE_STATUSES``). A NEW order is a request, not yet a sale.
* **Received** - recorded payments minus recorded refunds with ``paid_at`` in the period.
* **Outstanding** - amount still due on live orders (confirmed onwards, not cancelled/rejected/returned).
* **Overdue** - amount due on issued invoices whose due date has passed.
* **Leads** - leads created in the period. **Win rate** - of leads closed (won or lost) in the
  period, the share that became an order. **Value won** - sales value of the orders those won
  leads became (cancelled orders excluded).
* Days follow the tenant's timezone (Asia/Kathmandu by default).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, case, distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.models import Conversation, Customer, Delivery, Invoice, Lead, Message, Order, Payment, User
from app.models.fulfilment import DELIVERY_CLOSED
from app.models.leads import LOST_REASONS, OPEN_STAGES
from app.models.sales import ORDER_STATUSES

Period = Literal["today", "7d", "30d", "this_month", "last_month", "90d"]
Bucket = Literal["hour", "day", "week"]

SALE_STATUSES = ("CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "OUT_FOR_DELIVERY", "DELIVERED")
OPEN_ORDER_STATUSES = ("NEW", "CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "OUT_FOR_DELIVERY")
ZERO = Decimal("0")


@dataclass(frozen=True)
class Window:
    """Half-open [start, end) in UTC-aware datetimes, plus the local dates it covers."""

    first_day: date
    last_day: date
    start: datetime
    end: datetime
    bucket: Bucket

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1

    def previous(self) -> "Window":
        """The same number of days immediately before this window."""
        last = self.first_day - timedelta(days=1)
        return window_for(last - timedelta(days=self.days - 1), last, self.start.tzinfo)  # type: ignore[arg-type]


def window_for(first_day: date, last_day: date, tz: ZoneInfo) -> Window:
    days = (last_day - first_day).days + 1
    bucket: Bucket = "hour" if days == 1 else "day" if days <= 62 else "week"
    return Window(
        first_day=first_day,
        last_day=last_day,
        start=datetime.combine(first_day, time.min, tz),
        end=datetime.combine(last_day + timedelta(days=1), time.min, tz),
        bucket=bucket,
    )


def resolve_period(period: Period, today: date, tz: ZoneInfo) -> Window:
    if period == "today":
        return window_for(today, today, tz)
    if period == "this_month":
        return window_for(today.replace(day=1), today, tz)
    if period == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return window_for(last.replace(day=1), last, tz)
    days = {"7d": 7, "30d": 30, "90d": 90}[period]
    return window_for(today - timedelta(days=days - 1), today, tz)


# --- result shapes -------------------------------------------------------------------


@dataclass
class Totals:
    sales: Decimal
    sales_orders: int
    received: Decimal
    new_orders: int
    new_customers: int
    messages_in: int
    new_leads: int


@dataclass
class Point:
    start: datetime
    sales: Decimal
    orders: int


@dataclass
class ChannelRow:
    channel: str
    messages_in: int
    conversations: int
    leads: int
    orders: int
    sales: Decimal


@dataclass
class SourceRow:
    lead_source: str | None
    orders: int
    sales: Decimal


@dataclass
class Funnel:
    conversations: int
    leads: int  # leads created from those chats
    converted_conversations: int
    orders: int
    sales: Decimal


@dataclass
class Snapshot:
    open_orders: int
    outstanding: Decimal
    outstanding_orders: int
    overdue: Decimal
    overdue_invoices: int
    deliveries_open: int
    deliveries_due_today: int
    delivered_in_period: int


@dataclass
class Buyers:
    total: int
    returning: int


@dataclass
class StaffLeads:
    user_id: uuid.UUID | None  # None: unassigned
    full_name: str
    open: int
    created: int  # leads they own that were created in the period
    won: int
    lost: int
    won_value: Decimal
    overdue_followups: int


@dataclass
class LeadStats:
    created: int
    open_now: int
    won: int
    lost: int
    win_rate: float | None  # won / (won + lost) for leads closed in the period
    won_value: Decimal
    avg_days_to_win: float | None
    lost_reasons: dict[str, int]
    staff: list[StaffLeads]


@dataclass
class Dashboard:
    window: Window
    currency: str
    totals: Totals
    previous: Totals
    series: list[Point]
    channels: list[ChannelRow]
    lead_sources: list[SourceRow]
    orders_by_status: dict[str, int]
    funnel: Funnel
    snapshot: Snapshot
    buyers: Buyers
    leads: LeadStats


# --- queries --------------------------------------------------------------------------


def _in(
    column: InstrumentedAttribute[datetime] | InstrumentedAttribute[datetime | None], w: Window
) -> ColumnElement[bool]:
    return and_(column >= w.start, column < w.end)


def _sales_orders(tenant_id: uuid.UUID, w: Window) -> Select[Order]:
    return select(Order).where(Order.tenant_id == tenant_id, _in(Order.created_at, w), Order.status.in_(SALE_STATUSES))


async def _totals(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> Totals:
    sale = Order.status.in_(SALE_STATUSES)
    orders = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((sale, Order.grand_total), else_=ZERO)), ZERO),
                func.count().filter(sale),
                func.count(),
            ).where(Order.tenant_id == tenant_id, _in(Order.created_at, w))
        )
    ).one()
    signed = case((Payment.type == "refund", -Payment.amount), else_=Payment.amount)
    received = (
        await session.execute(
            select(func.coalesce(func.sum(signed), ZERO)).where(
                Payment.tenant_id == tenant_id, Payment.status == "recorded", _in(Payment.paid_at, w)
            )
        )
    ).scalar_one()
    new_customers = (
        await session.execute(
            select(func.count()).where(
                Customer.tenant_id == tenant_id,
                Customer.deleted_at.is_(None),
                Customer.merged_into_customer_id.is_(None),
                _in(Customer.first_seen_at, w),
            )
        )
    ).scalar_one()
    messages_in = (
        await session.execute(
            select(func.count()).where(
                Message.tenant_id == tenant_id, Message.direction == "inbound", _in(Message.provider_timestamp, w)
            )
        )
    ).scalar_one()
    new_leads = (
        await session.execute(select(func.count()).where(Lead.tenant_id == tenant_id, _in(Lead.created_at, w)))
    ).scalar_one()
    return Totals(
        sales=orders[0],
        sales_orders=orders[1],
        received=received,
        new_orders=orders[2],
        new_customers=new_customers,
        messages_in=messages_in,
        new_leads=new_leads,
    )


async def _series(session: AsyncSession, tenant_id: uuid.UUID, w: Window, tz: str) -> list[Point]:
    """Sales per hour/day/week, with empty buckets filled so the chart has an even axis."""
    local = func.timezone(tz, Order.created_at)
    bucket = func.date_trunc(w.bucket, local).label("bucket")
    rows = (
        await session.execute(
            select(bucket, func.coalesce(func.sum(Order.grand_total), ZERO), func.count())
            .where(Order.tenant_id == tenant_id, _in(Order.created_at, w), Order.status.in_(SALE_STATUSES))
            .group_by(bucket)
        )
    ).all()
    found = {row[0]: (row[1], row[2]) for row in rows}
    zone = ZoneInfo(tz)
    step = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}[w.bucket]
    cursor = datetime.combine(w.first_day, time.min)
    if w.bucket == "week":
        cursor -= timedelta(days=cursor.weekday())  # date_trunc('week') starts on Monday
    points = []
    while cursor.replace(tzinfo=zone) < w.end:
        sales, count = found.get(cursor, (ZERO, 0))
        points.append(Point(start=cursor.replace(tzinfo=zone), sales=sales, orders=count))
        cursor += step
    return points


async def _channels(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> list[ChannelRow]:
    inbound = (
        await session.execute(
            select(Conversation.provider, func.count(), func.count(distinct(Message.conversation_id)))
            .join(
                Conversation,
                and_(Conversation.tenant_id == Message.tenant_id, Conversation.id == Message.conversation_id),
            )
            .where(Message.tenant_id == tenant_id, Message.direction == "inbound", _in(Message.provider_timestamp, w))
            .group_by(Conversation.provider)
        )
    ).all()
    sales = (
        await session.execute(
            select(Order.source_channel, func.count(), func.coalesce(func.sum(Order.grand_total), ZERO))
            .where(Order.tenant_id == tenant_id, _in(Order.created_at, w), Order.status.in_(SALE_STATUSES))
            .group_by(Order.source_channel)
        )
    ).all()
    lead_counts = (
        await session.execute(
            select(Lead.source_channel, func.count())
            .where(Lead.tenant_id == tenant_id, _in(Lead.created_at, w))
            .group_by(Lead.source_channel)
        )
    ).all()
    rows: dict[str, ChannelRow] = {}
    for provider, messages, conversations in inbound:
        rows[provider] = ChannelRow(provider, messages, conversations, 0, 0, ZERO)
    for channel, count in lead_counts:
        rows.setdefault(channel, ChannelRow(channel, 0, 0, 0, 0, ZERO)).leads = count
    for channel, count, total in sales:
        row = rows.setdefault(channel, ChannelRow(channel, 0, 0, 0, 0, ZERO))
        row.orders, row.sales = count, total
    return sorted(rows.values(), key=lambda r: (-r.sales, -r.messages_in, r.channel))


async def _lead_sources(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> list[SourceRow]:
    rows = (
        await session.execute(
            select(Order.lead_source, func.count(), func.coalesce(func.sum(Order.grand_total), ZERO))
            .where(Order.tenant_id == tenant_id, _in(Order.created_at, w), Order.status.in_(SALE_STATUSES))
            .group_by(Order.lead_source)
        )
    ).all()
    return sorted((SourceRow(*row) for row in rows), key=lambda r: -r.sales)


async def _orders_by_status(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Order.status, func.count())
            .where(Order.tenant_id == tenant_id, _in(Order.created_at, w))
            .group_by(Order.status)
        )
    ).all()
    found = dict(rows)
    return {status: found.get(status, 0) for status in ORDER_STATUSES}


async def _funnel(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> Funnel:
    """Chats with a customer message in the period → those that led to an order → orders → sales."""
    chats = (
        select(Message.conversation_id.label("id"))
        .where(Message.tenant_id == tenant_id, Message.direction == "inbound", _in(Message.provider_timestamp, w))
        .distinct()
        .subquery()
    )
    conversations = (await session.execute(select(func.count()).select_from(chats))).scalar_one()
    from_chat = (
        await session.execute(
            select(
                func.count(distinct(Order.source_conversation_id)),
                func.count(),
                func.coalesce(func.sum(Order.grand_total), ZERO),
            ).where(
                Order.tenant_id == tenant_id,
                _in(Order.created_at, w),
                Order.status.in_(SALE_STATUSES),
                Order.source_conversation_id.in_(select(chats.c.id)),
            )
        )
    ).one()
    leads_from_chats = (
        await session.execute(
            select(func.count()).where(
                Lead.tenant_id == tenant_id,
                _in(Lead.created_at, w),
                Lead.conversation_id.in_(select(chats.c.id)),
            )
        )
    ).scalar_one()
    return Funnel(conversations, leads_from_chats, from_chat[0], from_chat[1], from_chat[2])


async def _leads(session: AsyncSession, tenant_id: uuid.UUID, w: Window, now: datetime) -> LeadStats:
    created_in = _in(Lead.created_at, w)
    closed_in = _in(Lead.closed_at, w)
    won_value_expr = case(
        (and_(Lead.stage == "WON", closed_in, Order.status.in_(SALE_STATUSES)), Order.grand_total), else_=ZERO
    )
    overdue = and_(Lead.stage.in_(OPEN_STAGES), Lead.next_followup_at.is_not(None), Lead.next_followup_at < now)
    per_owner = (
        await session.execute(
            select(
                Lead.assigned_to_user_id,
                func.count().filter(Lead.stage.in_(OPEN_STAGES)),
                func.count().filter(created_in),
                func.count().filter(Lead.stage == "WON", closed_in),
                func.count().filter(Lead.stage == "LOST", closed_in),
                func.coalesce(func.sum(won_value_expr), ZERO),
                func.count().filter(overdue),
                func.avg(
                    case(
                        (
                            and_(Lead.stage == "WON", closed_in),
                            func.extract("epoch", Lead.closed_at - Lead.created_at) / 86400,
                        ),
                        else_=None,
                    )
                ),
            )
            .outerjoin(Order, and_(Order.tenant_id == Lead.tenant_id, Order.id == Lead.won_order_id))
            .where(Lead.tenant_id == tenant_id)
            .group_by(Lead.assigned_to_user_id)
        )
    ).all()
    names = dict(
        (
            await session.execute(select(User.id, User.full_name).where(User.id.in_({r[0] for r in per_owner if r[0]})))
        ).all()
    )
    staff = [
        StaffLeads(
            user_id=r[0],
            full_name=names.get(r[0], "") if r[0] else "Unassigned",
            open=r[1],
            created=r[2],
            won=r[3],
            lost=r[4],
            won_value=r[5],
            overdue_followups=r[6],
        )
        for r in per_owner
        if any(r[1:5]) or r[6]
    ]
    staff.sort(key=lambda s: (-s.won_value, -s.won, -s.open, s.full_name))
    won = sum(s.won for s in staff)
    lost = sum(s.lost for s in staff)
    won_days = [(r[3], r[7]) for r in per_owner if r[3] and r[7] is not None]
    avg_days = sum(float(d) * n for n, d in won_days) / won if won and won_days else None
    reasons = dict(
        (
            await session.execute(
                select(Lead.lost_reason, func.count())
                .where(Lead.tenant_id == tenant_id, Lead.stage == "LOST", closed_in)
                .group_by(Lead.lost_reason)
            )
        ).all()
    )
    return LeadStats(
        created=sum(s.created for s in staff),
        open_now=sum(s.open for s in staff),
        won=won,
        lost=lost,
        win_rate=won / (won + lost) if won + lost else None,
        won_value=sum((s.won_value for s in staff), ZERO),
        avg_days_to_win=round(avg_days, 1) if avg_days is not None else None,
        lost_reasons={r: reasons[r] for r in LOST_REASONS if reasons.get(r)},
        staff=staff,
    )


async def _snapshot(session: AsyncSession, tenant_id: uuid.UUID, w: Window, today: date) -> Snapshot:
    open_orders = (
        await session.execute(
            select(func.count()).where(Order.tenant_id == tenant_id, Order.status.in_(OPEN_ORDER_STATUSES))
        )
    ).scalar_one()
    outstanding = (
        await session.execute(
            select(func.coalesce(func.sum(Order.amount_due), ZERO), func.count()).where(
                Order.tenant_id == tenant_id, Order.status.in_(SALE_STATUSES), Order.amount_due > 0
            )
        )
    ).one()
    overdue = (
        await session.execute(
            select(func.coalesce(func.sum(Invoice.amount_due), ZERO), func.count()).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == "ISSUED",
                Invoice.due_date < today,
                Invoice.amount_due > 0,
            )
        )
    ).one()
    is_open = Delivery.status.not_in(DELIVERY_CLOSED)
    deliveries = (
        await session.execute(
            select(
                func.count().filter(is_open),
                func.count().filter(and_(is_open, Delivery.scheduled_date <= today)),
                func.count().filter(and_(Delivery.status == "DELIVERED", _in(Delivery.delivered_at, w))),
            ).where(Delivery.tenant_id == tenant_id)
        )
    ).one()
    return Snapshot(
        open_orders=open_orders,
        outstanding=outstanding[0],
        outstanding_orders=outstanding[1],
        overdue=overdue[0],
        overdue_invoices=overdue[1],
        deliveries_open=deliveries[0],
        deliveries_due_today=deliveries[1],
        delivered_in_period=deliveries[2],
    )


async def _buyers(session: AsyncSession, tenant_id: uuid.UUID, w: Window) -> Buyers:
    """Customers who bought in the period, and how many of them had bought before it."""
    buyers = _sales_orders(tenant_id, w).with_only_columns(Order.customer_id.label("id")).distinct().subquery()
    earlier = select(literal(1)).where(
        Order.tenant_id == tenant_id,
        Order.customer_id == buyers.c.id,
        Order.created_at < w.start,
        Order.status.in_(SALE_STATUSES),
    )
    row = (await session.execute(select(func.count(), func.count().filter(earlier.exists())).select_from(buyers))).one()
    return Buyers(total=row[0], returning=row[1])


async def dashboard(
    session: AsyncSession, *, tenant_id: uuid.UUID, timezone: str, currency: str, window: Window, today: date
) -> Dashboard:
    return Dashboard(
        window=window,
        currency=currency,
        totals=await _totals(session, tenant_id, window),
        previous=await _totals(session, tenant_id, window.previous()),
        series=await _series(session, tenant_id, window, timezone),
        channels=await _channels(session, tenant_id, window),
        lead_sources=await _lead_sources(session, tenant_id, window),
        orders_by_status=await _orders_by_status(session, tenant_id, window),
        funnel=await _funnel(session, tenant_id, window),
        snapshot=await _snapshot(session, tenant_id, window, today),
        buyers=await _buyers(session, tenant_id, window),
        leads=await _leads(session, tenant_id, window, datetime.now(window.start.tzinfo)),
    )
