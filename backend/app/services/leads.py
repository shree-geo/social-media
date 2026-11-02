"""Leads: buying interest tracked from first message to order.

Stages:
    NEW → CONTACTED → INTERESTED → NEGOTIATING   (staff move freely between open stages)
    any open stage → LOST (reason required) → reopened to an open stage
    any open stage → WON only by converting to an order (orders.create_order with lead_id)

Owner: whoever the chat is assigned to, otherwise whoever creates the lead. Assigning to
someone else needs ``lead.assign``; without it staff can only claim an unassigned lead.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Conversation,
    Customer,
    Lead,
    LeadActivity,
    LeadItem,
    Order,
    Tenant,
    TenantMembership,
)
from app.models.leads import LOST_REASONS, OPEN_STAGES
from app.services import audit, catalogue, money, numbering
from app.services.audit import RequestInfo
from app.services.subscriptions import tenant_today

UNSET: Any = object()  # "leave as is" for optional PATCH fields that may also be cleared with None


class InvalidLead(AppError):
    status, code, title = 422, "invalid_lead", "This lead can't be saved"


class InvalidStage(AppError):
    status, code, title = 409, "invalid_stage_change", "This stage change isn't allowed"


@dataclass(frozen=True)
class LeadItemInput:
    variant_id: uuid.UUID | None
    quantity: Decimal
    description: str | None = None  # required for lines without a product
    unit_price: Decimal | None = None  # None: the product's current price (0 for free-text lines)


def _now() -> datetime:
    return datetime.now(UTC)


def is_open(lead: Lead) -> bool:
    return lead.stage in OPEN_STAGES


async def _build_items(session: AsyncSession, tenant_id: uuid.UUID, items: list[LeadItemInput]) -> list[LeadItem]:
    if not items:
        raise InvalidLead("Add at least one product.")
    info = await catalogue.variant_info(session, tenant_id, [i.variant_id for i in items if i.variant_id])
    rows: list[LeadItem] = []
    for position, item in enumerate(items):
        if item.quantity <= 0:
            raise InvalidLead("Quantity must be more than zero.")
        if item.unit_price is not None and item.unit_price < 0:
            raise InvalidLead("Price can't be negative.")
        if item.variant_id is None:
            description = (item.description or "").strip()
            if not description:
                raise InvalidLead("Describe the item the customer wants.")
            price = item.unit_price if item.unit_price is not None else Decimal("0")
        else:
            found = info.get(item.variant_id)
            if found is None or found.product.deleted_at is not None:
                raise InvalidLead("One of the products isn't available any more.")
            name = found.product.name if found.variant.is_default else f"{found.product.name} ({found.variant.name})"
            description = name
            price = item.unit_price if item.unit_price is not None else (found.price or Decimal("0"))
        rows.append(
            LeadItem(
                tenant_id=tenant_id,
                variant_id=item.variant_id,
                description=description,
                quantity=item.quantity,
                unit_price=money.money(price),
                position=position,
            )
        )
    return rows


def _expected_value(rows: list[LeadItem]) -> Decimal:
    return money.money(sum((r.quantity * r.unit_price for r in rows), Decimal("0")))


async def items_of(session: AsyncSession, lead_id: uuid.UUID) -> list[LeadItem]:
    return list(
        (
            await session.execute(select(LeadItem).where(LeadItem.lead_id == lead_id).order_by(LeadItem.position))
        ).scalars()
    )


async def _check_member(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
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
        raise InvalidLead("Choose someone from your team.", code="invalid_assignee")


def _activity(
    lead: Lead,
    event: str,
    user_id: uuid.UUID | None,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
    body: str | None = None,
) -> LeadActivity:
    lead.last_activity_at = _now()
    return LeadActivity(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        event=event,
        from_value=from_value,
        to_value=to_value,
        body=body,
        actor_user_id=user_id,
    )


async def open_lead_for_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Lead | None:
    return (
        await session.execute(select(Lead).where(Lead.conversation_id == conversation_id, Lead.stage.in_(OPEN_STAGES)))
    ).scalar_one_or_none()


async def _locked(session: AsyncSession, lead_id: uuid.UUID, version: int | None = None) -> Lead:
    lead = (await session.execute(select(Lead).where(Lead.id == lead_id).with_for_update())).scalar_one_or_none()
    if lead is None:
        raise NotFound()
    if version is not None and version != lead.version:
        raise Conflict("Someone else changed this lead. Reload to see the latest.", code="lead_changed")
    return lead


async def _audit(
    session: AsyncSession,
    action: str,
    lead: Lead,
    user_id: uuid.UUID,
    request: RequestInfo,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        session,
        action=action,
        actor_type="user",
        actor_id=user_id,
        tenant_id=lead.tenant_id,
        resource_type="lead",
        resource_id=lead.id,
        before=before,
        after=after,
        request=request,
    )


# --- create -------------------------------------------------------------------------------


async def create_lead(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    can_assign: bool,
    items: list[LeadItemInput],
    conversation_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    source_channel: str | None = None,
    lead_source: str | None = None,
    assigned_to: Any = UNSET,  # UNSET: default owner; None: unassigned; a user id
    next_followup_at: datetime | None = None,
    followup_note: str | None = None,
    note: str | None = None,
    request: RequestInfo,
) -> Lead:
    conversation = None
    channel_account_id = None
    if conversation_id is not None:
        conversation = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        ).scalar_one_or_none()
        if conversation is None:
            raise NotFound()
        existing = await open_lead_for_conversation(session, conversation.id)
        if existing is not None:
            raise Conflict(
                f"This chat already has an open lead ({existing.lead_number}).",
                code="lead_exists",
                lead_id=str(existing.id),
            )
        customer_id, source_channel, channel_account_id = (
            conversation.customer_id,
            conversation.provider,
            conversation.channel_account_id,
        )
    if customer_id is None:
        raise InvalidLead("Choose a customer.")
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise NotFound()
    if customer.status == "merged":
        raise InvalidLead("This customer was merged into another record. Use that record instead.")

    if assigned_to is UNSET:
        owner = conversation.assigned_to_user_id if conversation and conversation.assigned_to_user_id else user_id
    else:
        owner = assigned_to
        if owner != user_id and not can_assign:
            raise Forbidden("Only managers can give a lead to someone else.", code="lead_assign_forbidden")
    await _check_member(session, tenant_id, owner)

    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    rows = await _build_items(session, tenant_id, items)
    lead = Lead(
        tenant_id=tenant_id,
        lead_number=await numbering.next_number(
            session, tenant_id, "LD", numbering.period_key(tenant.numbering_period, tenant_today(tenant.timezone))
        ),
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        source_channel=source_channel or "other",
        channel_account_id=channel_account_id,
        lead_source=lead_source,
        stage="NEW",
        assigned_to_user_id=owner,
        expected_value=_expected_value(rows),
        currency=tenant.currency,
        next_followup_at=next_followup_at,
        followup_note=followup_note,
        created_by=user_id,
        last_activity_at=_now(),
    )
    session.add(lead)
    await session.flush()
    for row in rows:
        row.lead_id = lead.id
    session.add_all(rows)
    session.add(_activity(lead, "created", user_id, to_value="NEW"))
    if owner is not None and owner != user_id:
        session.add(_activity(lead, "assigned", user_id, to_value=str(owner)))
    if next_followup_at is not None:
        session.add(_activity(lead, "followup_set", user_id, to_value=next_followup_at.isoformat(), body=followup_note))
    if note and note.strip():
        session.add(_activity(lead, "note", user_id, body=note.strip()))

    if conversation is not None:
        conversation.classification = "lead"
        if conversation.assigned_to_user_id is None and owner is not None:
            conversation.assigned_to_user_id = owner
    customer.last_interaction_at = _now()
    await _audit(
        session,
        "LEAD_CREATED",
        lead,
        user_id,
        request,
        after={"lead_number": lead.lead_number, "expected_value": str(lead.expected_value), "owner": owner},
    )
    return lead


# --- update -------------------------------------------------------------------------------


async def update_lead(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    user_id: uuid.UUID,
    version: int | None,
    items: list[LeadItemInput] | None = None,
    lead_source: Any = UNSET,
    next_followup_at: Any = UNSET,
    followup_note: Any = UNSET,
    request: RequestInfo,
) -> Lead:
    lead = await _locked(session, lead_id, version)
    if not is_open(lead):
        raise InvalidStage("Reopen the lead before changing it.", code="lead_closed")
    if items is not None:
        rows = await _build_items(session, tenant_id, items)
        before = str(lead.expected_value)
        await session.execute(delete(LeadItem).where(LeadItem.lead_id == lead.id))
        for row in rows:
            row.lead_id = lead.id
        session.add_all(rows)
        lead.expected_value = _expected_value(rows)
        session.add(_activity(lead, "items_changed", user_id, from_value=before, to_value=str(lead.expected_value)))
    if lead_source is not UNSET:
        lead.lead_source = lead_source
    if next_followup_at is not UNSET or followup_note is not UNSET:
        if next_followup_at is not UNSET:
            lead.next_followup_at = next_followup_at
            lead.followup_alerted_at = None
        if followup_note is not UNSET:
            lead.followup_note = followup_note
        session.add(
            _activity(
                lead,
                "followup_set",
                user_id,
                to_value=lead.next_followup_at.isoformat() if lead.next_followup_at else None,
                body=lead.followup_note,
            )
        )
    lead.last_activity_at = _now()
    await _audit(session, "LEAD_UPDATED", lead, user_id, request, after={"expected_value": str(lead.expected_value)})
    return lead


async def change_stage(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    to_stage: str,
    user_id: uuid.UUID,
    version: int | None,
    lost_reason: str | None = None,
    lost_note: str | None = None,
    request: RequestInfo,
) -> Lead:
    lead = await _locked(session, lead_id, version)
    current = lead.stage
    if to_stage == current:
        return lead
    if to_stage == "WON":
        raise InvalidStage("Convert the lead to an order to mark it won.", code="convert_to_win")
    if current == "WON":
        raise InvalidStage("This lead became an order and can't change.", code="lead_won")

    if to_stage == "LOST":
        if lost_reason not in LOST_REASONS:
            raise InvalidLead("Choose why the lead was lost.", code="lost_reason_required")
        lead.stage, lead.lost_reason, lead.lost_note = "LOST", lost_reason, (lost_note or "").strip() or None
        lead.closed_at = _now()
        lead.next_followup_at = None
        session.add(_activity(lead, "lost", user_id, from_value=current, to_value=lost_reason, body=lead.lost_note))
        action = "LEAD_LOST"
    elif to_stage in OPEN_STAGES:
        if current == "LOST":
            if lead.conversation_id is not None:
                other = await open_lead_for_conversation(session, lead.conversation_id)
                if other is not None:
                    raise Conflict(
                        f"This chat already has another open lead ({other.lead_number}).",
                        code="lead_exists",
                        lead_id=str(other.id),
                    )
            lead.stage, lead.lost_reason, lead.lost_note, lead.closed_at = to_stage, None, None, None
            session.add(_activity(lead, "reopened", user_id, from_value=current, to_value=to_stage))
            action = "LEAD_REOPENED"
        else:
            lead.stage = to_stage
            session.add(_activity(lead, "stage_changed", user_id, from_value=current, to_value=to_stage))
            action = "LEAD_STAGE_CHANGED"
    else:
        raise InvalidStage()
    await _audit(session, action, lead, user_id, request, before={"stage": current}, after={"stage": lead.stage})
    return lead


async def assign(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    assignee: uuid.UUID | None,
    user_id: uuid.UUID,
    can_assign: bool,
    request: RequestInfo,
) -> Lead:
    lead = await _locked(session, lead_id)
    before = lead.assigned_to_user_id
    if assignee == before:
        return lead
    # Without lead.assign: only claim an unassigned lead for yourself.
    if not can_assign and not (assignee == user_id and before is None):
        raise Forbidden("Only managers can give a lead to someone else.", code="lead_assign_forbidden")
    await _check_member(session, tenant_id, assignee)
    lead.assigned_to_user_id = assignee
    lead.followup_alerted_at = None  # the new owner gets the reminder
    session.add(
        _activity(
            lead,
            "assigned",
            user_id,
            from_value=str(before) if before else None,
            to_value=str(assignee) if assignee else None,
        )
    )
    await _audit(session, "LEAD_ASSIGNED", lead, user_id, request, before={"owner": before}, after={"owner": assignee})
    return lead


async def add_note(session: AsyncSession, *, lead_id: uuid.UUID, user_id: uuid.UUID, body: str) -> LeadActivity:
    lead = await _locked(session, lead_id)
    text = body.strip()
    if not text:
        raise InvalidLead("Write a note first.")
    activity = _activity(lead, "note", user_id, body=text)
    session.add(activity)
    await session.flush()
    return activity


# --- conversion ----------------------------------------------------------------------------


async def lock_for_conversion(session: AsyncSession, lead_id: uuid.UUID) -> Lead:
    """Called by orders.create_order before the order is built."""
    lead = await _locked(session, lead_id)
    if not is_open(lead):
        raise InvalidStage("This lead is already closed.", code="lead_closed")
    return lead


async def mark_won(
    session: AsyncSession, *, lead: Lead, order: Order, user_id: uuid.UUID, request: RequestInfo
) -> None:
    before = lead.stage
    lead.stage = "WON"
    lead.won_order_id = order.id
    lead.closed_at = _now()
    lead.next_followup_at = None
    session.add(_activity(lead, "converted", user_id, from_value=before, to_value=order.order_number))
    await _audit(
        session, "LEAD_WON", lead, user_id, request, before={"stage": before}, after={"order": order.order_number}
    )


# --- follow-up reminders (beat job) ---------------------------------------------------------


@dataclass(frozen=True)
class DueFollowup:
    tenant_id: uuid.UUID
    lead_id: uuid.UUID
    lead_number: str
    assigned_to_user_id: uuid.UUID | None


async def claim_due_followups(
    session: AsyncSession, now: datetime | None = None, limit: int = 500
) -> list[DueFollowup]:
    """Open leads whose follow-up time has come and whose owner hasn't been alerted yet.

    Runs as the platform role (all tenants). Marks them alerted in the same transaction, so
    each follow-up alerts once; changing the time or the owner re-arms it.
    """
    moment = now or _now()
    rows = list(
        (
            await session.execute(
                select(Lead)
                .where(
                    Lead.stage.in_(OPEN_STAGES),
                    Lead.next_followup_at.is_not(None),
                    Lead.next_followup_at <= moment,
                    Lead.followup_alerted_at.is_(None),
                )
                .order_by(Lead.next_followup_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for lead in rows:
        lead.followup_alerted_at = moment
    return [DueFollowup(r.tenant_id, r.id, r.lead_number, r.assigned_to_user_id) for r in rows]
