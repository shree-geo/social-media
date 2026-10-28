"""Customers and Customer 360: /api/v1/customers (spec §7, §15)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.api import pagination
from app.api.deps import TenantContext, require
from app.core.exceptions import AppError, Conflict, NotFound
from app.models import (
    Conversation,
    Customer,
    CustomerAddress,
    CustomerDuplicateCandidate,
    CustomerIdentity,
    CustomerNote,
)
from app.schemas.auth import StrictModel
from app.services import audit, customers, phones

router = APIRouter(prefix="/customers", tags=["customers"])

Reader = Annotated[TenantContext, Depends(require("customer.read"))]
Writer = Annotated[TenantContext, Depends(require("customer.write", write=True))]
Merger = Annotated[TenantContext, Depends(require("customer.merge", write=True))]


class InvalidPhone(AppError):
    status, code, title = 422, "invalid_phone", "Enter a valid phone number, e.g. +977 98XXXXXXXX"


class StaleVersion(AppError):
    status, code, title = 409, "stale_version", "Someone else changed this customer. Reload and try again."


class CustomerListItem(BaseModel):
    id: uuid.UUID
    display_name: str
    phone_e164: str | None
    email: str | None
    channels: list[str]
    last_interaction_at: datetime | None


class CustomerPage(BaseModel):
    items: list[CustomerListItem]
    next_cursor: str | None


class IdentityOut(BaseModel):
    id: uuid.UUID
    provider: str
    channel_account_id: uuid.UUID | None
    profile_name: str | None
    phone_e164: str | None
    last_seen_at: datetime | None


class AddressOut(BaseModel):
    id: uuid.UUID
    label: str | None
    contact_name: str | None
    contact_phone: str | None
    line1: str | None
    area: str | None
    city: str | None
    district: str | None
    is_default: bool


class NoteOut(BaseModel):
    id: uuid.UUID
    body: str
    created_by: uuid.UUID | None
    created_at: datetime


class ConversationRef(BaseModel):
    id: uuid.UUID
    provider: str
    last_message_at: datetime | None
    last_message_preview: str | None


class Customer360(BaseModel):
    """Orders, invoices, deliveries and payments are added here as Phase 5-6 ship."""

    id: uuid.UUID
    display_name: str
    phone_e164: str | None
    email: str | None
    external_ref: str | None
    status: str
    merged_into_customer_id: uuid.UUID | None
    first_seen_at: datetime
    last_interaction_at: datetime | None
    version: int
    identities: list[IdentityOut]
    addresses: list[AddressOut]
    notes: list[NoteOut]
    conversations: list[ConversationRef]
    open_duplicates: int


class CustomerCreate(StrictModel):
    display_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    external_ref: str | None = Field(default=None, max_length=100)


class CustomerUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    external_ref: str | None = Field(default=None, max_length=100)


class NoteCreate(StrictModel):
    body: str = Field(min_length=1, max_length=5000)


class DuplicateOut(BaseModel):
    id: uuid.UUID
    score: Decimal
    reasons: list[Any]
    customer_a: CustomerListItem
    customer_b: CustomerListItem


class MergeRequest(StrictModel):
    source_customer_id: uuid.UUID  # this record is folded into the target
    target_customer_id: uuid.UUID


class MergeOut(BaseModel):
    merge_id: uuid.UUID
    target_customer_id: uuid.UUID
    moved: dict[str, int]


def _phone(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    normalized = phones.normalize(raw)
    if normalized is None:
        raise InvalidPhone()
    return normalized


async def _channels(ctx: TenantContext, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not ids:
        return {}
    rows = await ctx.session.execute(
        select(CustomerIdentity.customer_id, CustomerIdentity.provider)
        .where(CustomerIdentity.tenant_id == ctx.tenant_id, CustomerIdentity.customer_id.in_(ids))
        .distinct()
    )
    result: dict[uuid.UUID, list[str]] = {}
    for customer_id, provider in rows:
        result.setdefault(customer_id, []).append(provider)
    return {k: sorted(v) for k, v in result.items()}


def _item(c: Customer, channels: dict[uuid.UUID, list[str]]) -> CustomerListItem:
    return CustomerListItem(
        id=c.id,
        display_name=c.display_name,
        phone_e164=c.phone_e164,
        email=c.email,
        channels=channels.get(c.id, []),
        last_interaction_at=c.last_interaction_at,
    )


async def _active(ctx: TenantContext, customer_id: uuid.UUID) -> Customer:
    customer = await ctx.session.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise NotFound()
    return customer


@router.get("")
async def list_customers(
    ctx: Reader,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> CustomerPage:
    query = select(Customer).where(
        Customer.tenant_id == ctx.tenant_id, Customer.status == "active", Customer.deleted_at.is_(None)
    )
    if q and q.strip():
        term = q.strip()
        phone = phones.normalize(term)
        conditions = [Customer.display_name.ilike(f"%{term}%"), Customer.email == term]
        if phone:
            conditions.append(Customer.phone_e164 == phone)
            conditions.append(
                Customer.id.in_(
                    select(CustomerIdentity.customer_id).where(
                        CustomerIdentity.tenant_id == ctx.tenant_id, CustomerIdentity.phone_e164 == phone
                    )
                )
            )
        query = query.where(or_(*conditions))
    sort_key = func.coalesce(Customer.last_interaction_at, Customer.created_at)
    if cursor:
        stamp, last_id = pagination.decode(cursor)
        query = query.where(or_(sort_key < stamp, and_(sort_key == stamp, Customer.id < last_id)))
    rows = (
        (await ctx.session.execute(query.order_by(sort_key.desc(), Customer.id.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    page = rows[:limit]
    channels = await _channels(ctx, [c.id for c in page])
    last = page[-1] if page else None
    return CustomerPage(
        items=[_item(c, channels) for c in page],
        next_cursor=pagination.encode(last.last_interaction_at or last.created_at, last.id)
        if last and len(rows) > limit
        else None,
    )


@router.post("", status_code=201)
async def create_customer(body: CustomerCreate, ctx: Writer) -> Customer360:
    customer = Customer(
        tenant_id=ctx.tenant_id,
        display_name=body.display_name,
        phone_e164=_phone(body.phone),
        email=body.email,
        external_ref=body.external_ref,
        created_by=ctx.user_id,
    )
    ctx.session.add(customer)
    await ctx.session.flush()
    await customers.scan_duplicates(ctx.session, tenant_id=ctx.tenant_id, customer_id=customer.id)
    await audit.record(
        ctx.session,
        action="CUSTOMER_CREATED",
        actor_type="user",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        resource_type="customer",
        resource_id=customer.id,
        after={"display_name": customer.display_name},
        request=ctx.request,
    )
    return await get_customer(customer.id, ctx)


@router.get("/duplicates")
async def list_duplicates(ctx: Annotated[TenantContext, Depends(require("customer.merge"))]) -> list[DuplicateOut]:
    a, b = aliased(Customer), aliased(Customer)
    rows = (
        await ctx.session.execute(
            select(CustomerDuplicateCandidate, a, b)
            .join(a, a.id == CustomerDuplicateCandidate.customer_a_id)
            .join(b, b.id == CustomerDuplicateCandidate.customer_b_id)
            .where(
                CustomerDuplicateCandidate.tenant_id == ctx.tenant_id,
                CustomerDuplicateCandidate.status == "open",
                CustomerDuplicateCandidate.score >= customers.DUPLICATE_THRESHOLD,
                a.status == "active",
                b.status == "active",
            )
            .order_by(CustomerDuplicateCandidate.score.desc(), CustomerDuplicateCandidate.updated_at.desc())
            .limit(100)
        )
    ).all()
    channels = await _channels(ctx, [c.id for _, x, y in rows for c in (x, y)])
    return [
        DuplicateOut(
            id=d.id, score=d.score, reasons=d.reasons, customer_a=_item(x, channels), customer_b=_item(y, channels)
        )
        for d, x, y in rows
    ]


@router.post("/duplicates/{candidate_id}/dismiss", status_code=204)
async def dismiss_duplicate(candidate_id: uuid.UUID, ctx: Merger) -> None:
    candidate = await ctx.session.get(CustomerDuplicateCandidate, candidate_id)
    if candidate is None:
        raise NotFound()
    candidate.status = "dismissed"
    candidate.reviewed_by = ctx.user_id
    candidate.reviewed_at = datetime.now(UTC)


@router.post("/merge")
async def merge_customers(body: MergeRequest, ctx: Merger) -> MergeOut:
    record = await customers.merge(
        ctx.session,
        tenant_id=ctx.tenant_id,
        source_id=body.source_customer_id,
        target_id=body.target_customer_id,
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    return MergeOut(
        merge_id=record.id,
        target_customer_id=record.target_customer_id,
        moved={k: len(v) for k, v in record.snapshot.items() if isinstance(v, list)},
    )


@router.post("/merges/{merge_id}/undo", status_code=204)
async def undo_merge(merge_id: uuid.UUID, ctx: Merger) -> None:
    await customers.unmerge(
        ctx.session, tenant_id=ctx.tenant_id, merge_id=merge_id, actor_id=ctx.user_id, request=ctx.request
    )


@router.get("/{customer_id}")
async def get_customer(customer_id: uuid.UUID, ctx: Reader) -> Customer360:
    c = await _active(ctx, customer_id)
    session, tid = ctx.session, ctx.tenant_id
    identities = (
        await session.execute(
            select(CustomerIdentity).where(CustomerIdentity.tenant_id == tid, CustomerIdentity.customer_id == c.id)
        )
    ).scalars()
    addresses = (
        await session.execute(
            select(CustomerAddress).where(CustomerAddress.tenant_id == tid, CustomerAddress.customer_id == c.id)
        )
    ).scalars()
    notes = (
        await session.execute(
            select(CustomerNote)
            .where(CustomerNote.tenant_id == tid, CustomerNote.customer_id == c.id)
            .order_by(CustomerNote.created_at.desc())
            .limit(50)
        )
    ).scalars()
    conversations = (
        await session.execute(
            select(Conversation)
            .where(Conversation.tenant_id == tid, Conversation.customer_id == c.id)
            .order_by(Conversation.last_message_at.desc().nulls_last())
        )
    ).scalars()
    open_duplicates = (
        await session.execute(
            select(func.count())
            .select_from(CustomerDuplicateCandidate)
            .where(
                CustomerDuplicateCandidate.tenant_id == tid,
                CustomerDuplicateCandidate.status == "open",
                or_(CustomerDuplicateCandidate.customer_a_id == c.id, CustomerDuplicateCandidate.customer_b_id == c.id),
            )
        )
    ).scalar_one()
    return Customer360(
        id=c.id,
        display_name=c.display_name,
        phone_e164=c.phone_e164,
        email=c.email,
        external_ref=c.external_ref,
        status=c.status,
        merged_into_customer_id=c.merged_into_customer_id,
        first_seen_at=c.first_seen_at,
        last_interaction_at=c.last_interaction_at,
        version=c.version,
        identities=[
            IdentityOut(
                id=i.id,
                provider=i.provider,
                channel_account_id=i.channel_account_id,
                profile_name=i.profile_name,
                phone_e164=i.phone_e164,
                last_seen_at=i.last_seen_at,
            )
            for i in identities
        ],
        addresses=[
            AddressOut(
                id=a.id,
                label=a.label,
                contact_name=a.contact_name,
                contact_phone=a.contact_phone,
                line1=a.line1,
                area=a.area,
                city=a.city,
                district=a.district,
                is_default=a.is_default,
            )
            for a in addresses
        ],
        notes=[NoteOut(id=n.id, body=n.body, created_by=n.created_by, created_at=n.created_at) for n in notes],
        conversations=[
            ConversationRef(
                id=cv.id,
                provider=cv.provider,
                last_message_at=cv.last_message_at,
                last_message_preview=cv.last_message_preview,
            )
            for cv in conversations
        ],
        open_duplicates=open_duplicates,
    )


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    ctx: Writer,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Customer360:
    c = await _active(ctx, customer_id)
    if c.status != "active":
        raise Conflict("This customer was merged into another record.")
    if if_match is not None and if_match.strip('"') != str(c.version):
        raise StaleVersion()
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(c, "phone_e164" if k == "phone" else k) for k in changes}
    if "phone" in changes:
        c.phone_e164 = _phone(changes.pop("phone"))
    for key, value in changes.items():
        setattr(c, key, value)
    await ctx.session.flush()
    await customers.scan_duplicates(ctx.session, tenant_id=ctx.tenant_id, customer_id=c.id)
    await audit.record(
        ctx.session,
        action="CUSTOMER_UPDATED",
        actor_type="user",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        resource_type="customer",
        resource_id=c.id,
        before=before,
        after=body.model_dump(exclude_unset=True),
        request=ctx.request,
    )
    return await get_customer(c.id, ctx)


@router.post("/{customer_id}/notes", status_code=201)
async def add_note(customer_id: uuid.UUID, body: NoteCreate, ctx: Writer) -> NoteOut:
    c = await _active(ctx, customer_id)
    note = CustomerNote(tenant_id=ctx.tenant_id, customer_id=c.id, body=body.body, created_by=ctx.user_id)
    ctx.session.add(note)
    await ctx.session.flush()
    await ctx.session.refresh(note)
    return NoteOut(id=note.id, body=note.body, created_by=note.created_by, created_at=note.created_at)
