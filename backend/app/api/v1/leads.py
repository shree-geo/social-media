"""Leads: /api/v1/leads — buying interest between a chat and an order."""

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select

from app.api import pagination
from app.api.deps import TenantContext, require
from app.core.exceptions import NotFound
from app.models import Customer, Lead, LeadActivity, LeadItem, MembershipRole, Order, Role, TenantMembership, User
from app.models.leads import LEAD_STAGES, LOST_REASONS, OPEN_STAGES
from app.models.sales import LEAD_SOURCES, SOURCE_CHANNELS
from app.schemas.auth import StrictModel
from app.services import leads, realtime
from app.services.subscriptions import tenant_today

router = APIRouter(prefix="/leads", tags=["leads"])

LeadReader = Annotated[TenantContext, Depends(require("lead.read"))]
LeadWriter = Annotated[TenantContext, Depends(require("lead.write", write=True))]

Stage = Literal[LEAD_STAGES]  # type: ignore[valid-type]
LostReason = Literal[LOST_REASONS]  # type: ignore[valid-type]
Source = Literal[SOURCE_CHANNELS]  # type: ignore[valid-type]
LeadSource = Literal[LEAD_SOURCES]  # type: ignore[valid-type]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


# --- schemas -------------------------------------------------------------------------------


class ItemIn(StrictModel):
    variant_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=300)
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
    unit_price: Money | None = None

    @model_validator(mode="after")
    def _what(self) -> "ItemIn":
        if self.variant_id is None and not (self.description or "").strip():
            raise ValueError("pick a product or describe the item")
        return self


class LeadCreate(StrictModel):
    conversation_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    source_channel: Source | None = None
    lead_source: LeadSource | None = None
    items: list[ItemIn] = Field(min_length=1, max_length=50)
    assigned_to_user_id: uuid.UUID | None = None  # omitted: chat's assignee, else you
    next_followup_at: datetime | None = None
    followup_note: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _who(self) -> "LeadCreate":
        if not self.conversation_id and not self.customer_id:
            raise ValueError("conversation_id or customer_id is required")
        return self


class LeadUpdate(StrictModel):
    version: int | None = None
    items: list[ItemIn] | None = Field(default=None, min_length=1, max_length=50)
    lead_source: LeadSource | None = None
    next_followup_at: datetime | None = None
    followup_note: str | None = Field(default=None, max_length=500)


class StageChange(StrictModel):
    stage: Stage
    version: int | None = None
    lost_reason: LostReason | None = None
    lost_note: str | None = Field(default=None, max_length=500)


class AssignIn(StrictModel):
    user_id: uuid.UUID | None


class NoteIn(StrictModel):
    body: str = Field(min_length=1, max_length=2000)


class Person(BaseModel):
    id: uuid.UUID
    full_name: str


class LeadSummary(BaseModel):
    id: uuid.UUID
    lead_number: str
    stage: str
    customer: dict[str, Any]
    conversation_id: uuid.UUID | None
    source_channel: str
    lead_source: str | None
    assigned_to: Person | None
    expected_value: Decimal
    currency: str
    item_summary: str
    next_followup_at: datetime | None
    followup_note: str | None
    lost_reason: str | None
    won_order: dict[str, Any] | None
    created_at: datetime
    last_activity_at: datetime
    version: int


class LeadItemOut(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit_price: Decimal


class ActivityOut(BaseModel):
    id: uuid.UUID
    event: str
    from_value: str | None
    to_value: str | None
    body: str | None
    actor: Person | None
    created_at: datetime


class LeadOut(LeadSummary):
    items: list[LeadItemOut]
    activities: list[ActivityOut]
    lost_note: str | None
    closed_at: datetime | None
    created_by: Person | None


class LeadPage(BaseModel):
    items: list[LeadSummary]
    next_cursor: str | None


class Board(BaseModel):
    columns: dict[str, list[LeadSummary]]


class StaffMember(BaseModel):
    user_id: uuid.UUID
    full_name: str
    roles: list[str]


class FollowupCount(BaseModel):
    overdue: int
    today: int


# --- helpers ---------------------------------------------------------------------------------


def _summary_text(items: list[LeadItem]) -> str:
    if not items:
        return ""

    def qty(q: Decimal) -> str:
        return f"{q.normalize():f}"

    first = f"{qty(items[0].quantity)} \u00d7 {items[0].description}"  # multiplication sign
    return first if len(items) == 1 else f"{first} +{len(items) - 1} more"


async def _people(ctx: TenantContext, ids: set[uuid.UUID]) -> dict[uuid.UUID, Person]:
    if not ids:
        return {}
    rows = await ctx.session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {uid: Person(id=uid, full_name=name) for uid, name in rows}


async def _summaries(ctx: TenantContext, rows: list[Lead]) -> list[LeadSummary]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    items: dict[uuid.UUID, list[LeadItem]] = {}
    for item in (
        await ctx.session.execute(
            select(LeadItem).where(LeadItem.lead_id.in_(ids)).order_by(LeadItem.lead_id, LeadItem.position)
        )
    ).scalars():
        items.setdefault(item.lead_id, []).append(item)
    customers = dict(
        (
            await ctx.session.execute(
                select(Customer.id, Customer.display_name).where(Customer.id.in_({r.customer_id for r in rows}))
            )
        ).all()
    )
    orders = dict(
        (
            await ctx.session.execute(
                select(Order.id, Order.order_number).where(
                    Order.id.in_({r.won_order_id for r in rows if r.won_order_id})
                )
            )
        ).all()
    )
    people = await _people(ctx, {r.assigned_to_user_id for r in rows if r.assigned_to_user_id})
    return [
        LeadSummary(
            id=r.id,
            lead_number=r.lead_number,
            stage=r.stage,
            customer={"id": r.customer_id, "display_name": customers.get(r.customer_id, "")},
            conversation_id=r.conversation_id,
            source_channel=r.source_channel,
            lead_source=r.lead_source,
            assigned_to=people.get(r.assigned_to_user_id) if r.assigned_to_user_id else None,
            expected_value=r.expected_value,
            currency=r.currency,
            item_summary=_summary_text(items.get(r.id, [])),
            next_followup_at=r.next_followup_at,
            followup_note=r.followup_note,
            lost_reason=r.lost_reason,
            won_order={"id": r.won_order_id, "order_number": orders.get(r.won_order_id)} if r.won_order_id else None,
            created_at=r.created_at,
            last_activity_at=r.last_activity_at,
            version=r.version,
        )
        for r in rows
    ]


async def lead_out(ctx: TenantContext, lead: Lead) -> LeadOut:
    (summary,) = await _summaries(ctx, [lead])
    items = await leads.items_of(ctx.session, lead.id)
    activities = list(
        (
            await ctx.session.execute(
                select(LeadActivity)
                .where(LeadActivity.lead_id == lead.id)
                .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
                .limit(200)
            )
        ).scalars()
    )
    people = await _people(
        ctx,
        {a.actor_user_id for a in activities if a.actor_user_id} | ({lead.created_by} if lead.created_by else set()),
    )
    # "assigned" activities store user ids; show names instead.
    assignee_ids = {uuid.UUID(v) for a in activities if a.event == "assigned" for v in (a.from_value, a.to_value) if v}
    names = {str(k): v.full_name for k, v in (await _people(ctx, assignee_ids)).items()}
    return LeadOut(
        **summary.model_dump(),
        items=[
            LeadItemOut(
                id=i.id,
                variant_id=i.variant_id,
                description=i.description,
                quantity=i.quantity,
                unit_price=i.unit_price,
            )
            for i in items
        ],
        activities=[
            ActivityOut(
                id=a.id,
                event=a.event,
                from_value=names.get(a.from_value or "", a.from_value) if a.event == "assigned" else a.from_value,
                to_value=names.get(a.to_value or "", a.to_value) if a.event == "assigned" else a.to_value,
                body=a.body,
                actor=people.get(a.actor_user_id) if a.actor_user_id else None,
                created_at=a.created_at,
            )
            for a in activities
        ],
        lost_note=lead.lost_note,
        closed_at=lead.closed_at,
        created_by=people.get(lead.created_by) if lead.created_by else None,
    )


def _items(body: list[ItemIn]) -> list[leads.LeadItemInput]:
    return [leads.LeadItemInput(i.variant_id, i.quantity, i.description, i.unit_price) for i in body]


def _day_bounds(ctx: TenantContext) -> tuple[datetime, datetime]:
    """Start and end of today in the business's timezone, as UTC instants."""
    tz = ZoneInfo(ctx.tenant.timezone)
    today = tenant_today(ctx.tenant.timezone)
    start = datetime.combine(today, time.min, tz).astimezone(UTC)
    return start, start + timedelta(days=1)


def _publish(background: BackgroundTasks, ctx: TenantContext, lead: Lead, event: str = "lead.updated") -> None:
    background.add_task(
        realtime.publish,
        ctx.tenant_id,
        event,
        lead_id=lead.id,
        conversation_id=lead.conversation_id,
        assigned_to_user_id=lead.assigned_to_user_id,
    )


async def _get(ctx: TenantContext, lead_id: uuid.UUID) -> Lead:
    lead = await ctx.session.get(Lead, lead_id)
    if lead is None:  # RLS hides other tenants' rows
        raise NotFound()
    return lead


# --- routes ----------------------------------------------------------------------------------


@router.get("")
async def list_leads(
    ctx: LeadReader,
    view: Literal["all", "mine", "unassigned"] = "all",
    stage: Annotated[str | None, Query(pattern="^(open|closed|NEW|CONTACTED|INTERESTED|NEGOTIATING|WON|LOST)$")] = None,
    due: Literal["overdue", "today", "due"] | None = None,
    channel: Source | None = None,
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> LeadPage:
    query = select(Lead).join(Customer, Customer.id == Lead.customer_id).where(Lead.tenant_id == ctx.tenant_id)
    if view == "mine":
        query = query.where(Lead.assigned_to_user_id == ctx.user_id)
    elif view == "unassigned":
        query = query.where(Lead.assigned_to_user_id.is_(None))
    if stage == "open":
        query = query.where(Lead.stage.in_(OPEN_STAGES))
    elif stage == "closed":
        query = query.where(Lead.stage.in_(("WON", "LOST")))
    elif stage:
        query = query.where(Lead.stage == stage)
    if channel:
        query = query.where(Lead.source_channel == channel)
    if customer_id:
        query = query.where(Lead.customer_id == customer_id)
    if conversation_id:
        query = query.where(Lead.conversation_id == conversation_id)
    if q and q.strip():
        term = q.strip()
        query = query.where(or_(Lead.lead_number.ilike(f"%{term}%"), Customer.display_name.ilike(f"%{term}%")))

    if due:
        # Follow-up lists: soonest first, no paging (an owner rarely has more than a screenful).
        start, end = _day_bounds(ctx)
        query = query.where(Lead.stage.in_(OPEN_STAGES), Lead.next_followup_at.is_not(None))
        if due == "overdue":
            query = query.where(Lead.next_followup_at < start)
        elif due == "today":
            query = query.where(Lead.next_followup_at >= start, Lead.next_followup_at < end)
        else:
            query = query.where(Lead.next_followup_at < end)
        rows = list((await ctx.session.execute(query.order_by(Lead.next_followup_at).limit(100))).scalars())
        return LeadPage(items=await _summaries(ctx, rows), next_cursor=None)

    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(Lead.created_at < stamp, and_(Lead.created_at == stamp, Lead.id < last_id)))
    rows = list(
        (await ctx.session.execute(query.order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit + 1))).scalars()
    )
    page = rows[:limit]
    return LeadPage(
        items=await _summaries(ctx, page),
        next_cursor=pagination.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None,
    )


@router.get("/board")
async def board(ctx: LeadReader, view: Literal["all", "mine"] = "all") -> Board:
    """Open leads by stage (most recently active first), plus leads closed in the last 30 days."""
    base = select(Lead).where(Lead.tenant_id == ctx.tenant_id)
    if view == "mine":
        base = base.where(Lead.assigned_to_user_id == ctx.user_id)
    since = datetime.now(UTC) - timedelta(days=30)
    columns: dict[str, list[LeadSummary]] = {}
    for stage in LEAD_STAGES:
        query = base.where(Lead.stage == stage)
        if stage in ("WON", "LOST"):
            query = query.where(Lead.closed_at >= since)
        rows = list((await ctx.session.execute(query.order_by(Lead.last_activity_at.desc()).limit(100))).scalars())
        columns[stage] = await _summaries(ctx, rows)
    return Board(columns=columns)


@router.get("/followups/count")
async def followup_count(ctx: LeadReader) -> FollowupCount:
    """Your open leads with a follow-up overdue or due today (for the menu badge)."""
    start, end = _day_bounds(ctx)
    overdue, today = (
        await ctx.session.execute(
            select(
                func.count().filter(Lead.next_followup_at < start),
                func.count().filter(Lead.next_followup_at >= start, Lead.next_followup_at < end),
            ).where(
                Lead.tenant_id == ctx.tenant_id,
                Lead.assigned_to_user_id == ctx.user_id,
                Lead.stage.in_(OPEN_STAGES),
                Lead.next_followup_at.is_not(None),
            )
        )
    ).one()
    return FollowupCount(overdue=overdue, today=today)


@router.get("/staff")
async def lead_staff(ctx: LeadReader) -> list[StaffMember]:
    """Team members a lead can be given to: active members who can work on leads."""
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
    sellers = {"OWNER", "ADMIN", "MANAGER", "SALES"}
    return sorted(
        (m for m in staff.values() if sellers & set(m.roles)),
        key=lambda m: ("SALES" not in m.roles, m.full_name.lower()),
    )


@router.post("", status_code=201)
async def create_lead(body: LeadCreate, ctx: LeadWriter, background: BackgroundTasks) -> LeadOut:
    lead = await leads.create_lead(
        ctx.session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        can_assign="lead.assign" in ctx.permissions,
        items=_items(body.items),
        conversation_id=body.conversation_id,
        customer_id=body.customer_id,
        source_channel=body.source_channel,
        lead_source=body.lead_source,
        assigned_to=body.assigned_to_user_id if "assigned_to_user_id" in body.model_fields_set else leads.UNSET,
        next_followup_at=body.next_followup_at,
        followup_note=body.followup_note,
        note=body.note,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(lead)
    _publish(background, ctx, lead, "lead.created")
    if lead.conversation_id:
        background.add_task(
            realtime.publish, ctx.tenant_id, "conversation.updated", conversation_id=lead.conversation_id
        )
    return await lead_out(ctx, lead)


@router.get("/{lead_id}")
async def get_lead(lead_id: uuid.UUID, ctx: LeadReader) -> LeadOut:
    return await lead_out(ctx, await _get(ctx, lead_id))


@router.patch("/{lead_id}")
async def update_lead(lead_id: uuid.UUID, body: LeadUpdate, ctx: LeadWriter, background: BackgroundTasks) -> LeadOut:
    fields = body.model_fields_set
    lead = await leads.update_lead(
        ctx.session,
        tenant_id=ctx.tenant_id,
        lead_id=lead_id,
        user_id=ctx.user_id,
        version=body.version,
        items=_items(body.items) if body.items is not None else None,
        lead_source=body.lead_source if "lead_source" in fields else leads.UNSET,
        next_followup_at=body.next_followup_at if "next_followup_at" in fields else leads.UNSET,
        followup_note=body.followup_note if "followup_note" in fields else leads.UNSET,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(lead)
    _publish(background, ctx, lead)
    return await lead_out(ctx, lead)


@router.post("/{lead_id}/stage")
async def change_stage(lead_id: uuid.UUID, body: StageChange, ctx: LeadWriter, background: BackgroundTasks) -> LeadOut:
    lead = await leads.change_stage(
        ctx.session,
        lead_id=lead_id,
        to_stage=body.stage,
        user_id=ctx.user_id,
        version=body.version,
        lost_reason=body.lost_reason,
        lost_note=body.lost_note,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(lead)
    _publish(background, ctx, lead)
    return await lead_out(ctx, lead)


@router.post("/{lead_id}/assign")
async def assign(lead_id: uuid.UUID, body: AssignIn, ctx: LeadWriter, background: BackgroundTasks) -> LeadOut:
    lead = await leads.assign(
        ctx.session,
        tenant_id=ctx.tenant_id,
        lead_id=lead_id,
        assignee=body.user_id,
        user_id=ctx.user_id,
        can_assign="lead.assign" in ctx.permissions,
        request=ctx.request,
    )
    await ctx.session.flush()
    await ctx.session.refresh(lead)
    _publish(background, ctx, lead, "lead.assigned")
    return await lead_out(ctx, lead)


@router.post("/{lead_id}/notes", status_code=201)
async def add_note(lead_id: uuid.UUID, body: NoteIn, ctx: LeadWriter, background: BackgroundTasks) -> LeadOut:
    await leads.add_note(ctx.session, lead_id=lead_id, user_id=ctx.user_id, body=body.body)
    lead = await _get(ctx, lead_id)
    await ctx.session.refresh(lead)
    _publish(background, ctx, lead)
    return await lead_out(ctx, lead)
