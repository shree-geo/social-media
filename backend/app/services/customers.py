"""Customer identity resolution, duplicate suggestions, merge and unmerge (ARCHITECTURE.md §11).

Never merges automatically on names. Strong signals (same channel identity, same
normalized phone) link; weaker signals only create "possible duplicate" suggestions
for a user with ``customer.merge`` to review.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.models import (
    Conversation,
    Customer,
    CustomerAddress,
    CustomerDuplicateCandidate,
    CustomerIdentity,
    CustomerMerge,
    CustomerNote,
    CustomerTagLink,
    Invoice,
    Order,
)
from app.services import audit, phones
from app.services.audit import RequestInfo

DUPLICATE_THRESHOLD = Decimal("0.6")


class MergeNotAllowed(AppError):
    status, code, title = 409, "merge_not_allowed", "These customers cannot be merged"


@dataclass(frozen=True)
class ResolvedCustomer:
    customer_id: uuid.UUID
    identity_id: uuid.UUID
    created: bool  # a new customer record was created


async def _lock(session: AsyncSession, key: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})


async def resolve_channel_identity(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    channel_account_id: uuid.UUID,
    provider_user_id: str,
    profile_name: str | None,
    phone: str | None,
    seen_at: datetime,
) -> ResolvedCustomer:
    """Find or create the customer behind an inbound channel identity.

    1. Known identity on this channel account → that customer.
    2. Provider gave a phone and an active customer has exactly that number → link.
    3. Otherwise create a new customer and scan for possible duplicates.
    """
    # Serialize concurrent first messages from the same person (parallel webhook workers).
    await _lock(session, f"identity:{channel_account_id}:{provider_user_id}")

    identity = (
        await session.execute(
            select(CustomerIdentity).where(
                CustomerIdentity.tenant_id == tenant_id,
                CustomerIdentity.channel_account_id == channel_account_id,
                CustomerIdentity.provider_user_id == provider_user_id,
            )
        )
    ).scalar_one_or_none()
    phone_e164 = phones.normalize(phone)

    if identity is not None:
        identity.last_seen_at = seen_at
        if profile_name and identity.profile_name != profile_name:
            identity.profile_name = profile_name
        customer = await session.get(Customer, identity.customer_id)
        if customer is not None and customer.status == "merged" and customer.merged_into_customer_id:
            # Identity left behind on a merged record (should not happen after merge, but be safe).
            identity.customer_id = customer.merged_into_customer_id
        return ResolvedCustomer(identity.customer_id, identity.id, created=False)

    customer_id: uuid.UUID | None = None
    if phone_e164:
        matches = (
            (
                await session.execute(
                    select(Customer.id).where(
                        Customer.tenant_id == tenant_id,
                        Customer.status == "active",
                        Customer.deleted_at.is_(None),
                        Customer.phone_e164 == phone_e164,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(matches) == 1:  # ambiguous (shared phone) → don't guess
            customer_id = matches[0]

    created = customer_id is None
    if customer_id is None:
        customer = Customer(
            tenant_id=tenant_id,
            display_name=profile_name or phone_e164 or "Unknown customer",
            phone_e164=phone_e164,
            first_seen_at=seen_at,
            last_interaction_at=seen_at,
        )
        session.add(customer)
        await session.flush()
        customer_id = customer.id

    identity = CustomerIdentity(
        tenant_id=tenant_id,
        customer_id=customer_id,
        provider=provider,
        channel_account_id=channel_account_id,
        provider_user_id=provider_user_id,
        profile_name=profile_name,
        phone_e164=phone_e164,
        is_verified=True,  # authenticated by the provider
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    session.add(identity)
    await session.flush()

    if created:
        await scan_duplicates(session, tenant_id=tenant_id, customer_id=customer_id)
    return ResolvedCustomer(customer_id, identity.id, created=created)


# --- duplicate suggestions ------------------------------------------------------------


async def _suggest(
    session: AsyncSession, tenant_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID, score: Decimal, reason: str
) -> None:
    if a == b:
        return
    low, high = sorted((a, b))
    stmt = insert(CustomerDuplicateCandidate).values(
        tenant_id=tenant_id, customer_a_id=low, customer_b_id=high, score=score, reasons=[reason]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["tenant_id", "customer_a_id", "customer_b_id"],
            set_={
                "score": func.greatest(CustomerDuplicateCandidate.score, stmt.excluded.score),
                "reasons": text(
                    "(SELECT jsonb_agg(DISTINCT r) FROM jsonb_array_elements("
                    "customer_duplicate_candidates.reasons || excluded.reasons) r)"
                ),
                "updated_at": func.now(),
            },
            where=CustomerDuplicateCandidate.status == "open",
        )
    )


async def _customers_with_phone(session: AsyncSession, tenant_id: uuid.UUID, phone_e164: str) -> list[uuid.UUID]:
    """Active customers that have this phone anywhere: profile, identities or addresses."""
    rows = await session.execute(
        select(Customer.id)
        .where(Customer.tenant_id == tenant_id, Customer.status == "active", Customer.deleted_at.is_(None))
        .where(
            or_(
                Customer.phone_e164 == phone_e164,
                Customer.id.in_(
                    select(CustomerIdentity.customer_id).where(
                        CustomerIdentity.tenant_id == tenant_id, CustomerIdentity.phone_e164 == phone_e164
                    )
                ),
                Customer.id.in_(
                    select(CustomerAddress.customer_id).where(
                        CustomerAddress.tenant_id == tenant_id, CustomerAddress.contact_phone == phone_e164
                    )
                ),
            )
        )
    )
    return list(rows.scalars().all())


async def scan_duplicates(session: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> None:
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.status != "active":
        return
    if customer.phone_e164:
        for other in await _customers_with_phone(session, tenant_id, customer.phone_e164):
            await _suggest(session, tenant_id, customer_id, other, Decimal("0.85"), "same_phone")
    if customer.email:
        others = await session.execute(
            select(Customer.id).where(
                Customer.tenant_id == tenant_id,
                Customer.status == "active",
                Customer.email == customer.email,
                Customer.id != customer_id,
            )
        )
        for other in others.scalars():
            await _suggest(session, tenant_id, customer_id, other, Decimal("0.9"), "same_email")


async def suggest_from_message_text(
    session: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, text_body: str | None
) -> None:
    """A phone number the customer typed in chat that belongs to another customer → suggestion, not a link."""
    for number in phones.extract(text_body):
        for other in await _customers_with_phone(session, tenant_id, number):
            await _suggest(session, tenant_id, customer_id, other, Decimal("0.8"), "phone_in_message")


# --- merge / unmerge ------------------------------------------------------------------

# Tables whose rows follow the customer on merge. Deliveries and payments join this
# list when their module ships (same mechanism). Invoices keep their printed buyer
# (``buyer_snapshot``); only the internal link moves.
_MOVABLE: tuple[tuple[str, Any], ...] = (
    ("customer_identities", CustomerIdentity),
    ("conversations", Conversation),
    ("customer_addresses", CustomerAddress),
    ("customer_notes", CustomerNote),
    ("orders", Order),
    ("invoices", Invoice),
)


async def merge(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    actor_id: uuid.UUID,
    request: RequestInfo,
) -> CustomerMerge:
    if source_id == target_id:
        raise MergeNotAllowed("Choose two different customers.")
    for cid in sorted((source_id, target_id)):
        await _lock(session, f"customer:{cid}")
    source = await session.get(Customer, source_id)
    target = await session.get(Customer, target_id)
    if source is None or target is None:
        raise NotFound()
    if source.status != "active" or target.status != "active":
        raise MergeNotAllowed("One of these customers was already merged.")

    snapshot: dict[str, list[str]] = {}
    for table, model in _MOVABLE:
        ids = list(
            (
                await session.execute(
                    select(model.id).where(model.tenant_id == tenant_id, model.customer_id == source_id)
                )
            )
            .scalars()
            .all()
        )
        if ids:
            await session.execute(update(model).where(model.id.in_(ids)).values(customer_id=target_id))
        snapshot[table] = [str(i) for i in ids]

    # Tags: union, without duplicating links the target already has.
    source_tags = set(
        (
            await session.execute(
                select(CustomerTagLink.tag_id).where(
                    CustomerTagLink.tenant_id == tenant_id, CustomerTagLink.customer_id == source_id
                )
            )
        )
        .scalars()
        .all()
    )
    target_tags = set(
        (
            await session.execute(
                select(CustomerTagLink.tag_id).where(
                    CustomerTagLink.tenant_id == tenant_id, CustomerTagLink.customer_id == target_id
                )
            )
        )
        .scalars()
        .all()
    )
    added = source_tags - target_tags
    session.add_all(CustomerTagLink(customer_id=target_id, tag_id=t, tenant_id=tenant_id) for t in added)
    snapshot["added_tags"] = [str(t) for t in added]

    # Keep any contact details the target is missing.
    filled: dict[str, Any] = {}
    for column in ("phone_e164", "email", "external_ref"):
        if getattr(target, column) is None and getattr(source, column) is not None:
            filled[column] = getattr(source, column)
            setattr(target, column, getattr(source, column))
    snapshot["filled_fields"] = list(filled)

    source.status = "merged"
    source.merged_into_customer_id = target_id
    if source.last_interaction_at and (
        target.last_interaction_at is None or source.last_interaction_at > target.last_interaction_at
    ):
        target.last_interaction_at = source.last_interaction_at

    low, high = sorted((source_id, target_id))
    await session.execute(
        update(CustomerDuplicateCandidate)
        .where(
            CustomerDuplicateCandidate.tenant_id == tenant_id,
            CustomerDuplicateCandidate.customer_a_id == low,
            CustomerDuplicateCandidate.customer_b_id == high,
        )
        .values(status="merged", reviewed_by=actor_id, reviewed_at=datetime.now(UTC))
    )

    record = CustomerMerge(
        tenant_id=tenant_id,
        source_customer_id=source_id,
        target_customer_id=target_id,
        snapshot=snapshot,
        merged_by=actor_id,
    )
    session.add(record)
    await session.flush()
    await audit.record(
        session,
        action="CUSTOMER_MERGED",
        actor_type="user",
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="customer",
        resource_id=target_id,
        before={"source_customer_id": source_id},
        after={"merge_id": record.id, "moved": {k: len(v) for k, v in snapshot.items()}},
        request=request,
    )
    return record


async def unmerge(
    session: AsyncSession, *, tenant_id: uuid.UUID, merge_id: uuid.UUID, actor_id: uuid.UUID, request: RequestInfo
) -> CustomerMerge:
    """Move the snapshotted rows back. Rows created on the target after the merge stay there."""
    record = await session.get(CustomerMerge, merge_id)
    if record is None:
        raise NotFound()
    if record.reverted_at is not None:
        raise Conflict("This merge was already undone.")
    source = await session.get(Customer, record.source_customer_id)
    if source is None or source.status != "merged":
        raise MergeNotAllowed("The merged customer record is no longer available.")

    for table, model in _MOVABLE:
        ids = [uuid.UUID(i) for i in record.snapshot.get(table, [])]
        if ids:
            await session.execute(
                update(model)
                .where(model.id.in_(ids), model.customer_id == record.target_customer_id)
                .values(customer_id=record.source_customer_id)
            )
    added = [uuid.UUID(t) for t in record.snapshot.get("added_tags", [])]
    if added:
        await session.execute(
            delete(CustomerTagLink).where(
                CustomerTagLink.customer_id == record.target_customer_id, CustomerTagLink.tag_id.in_(added)
            )
        )

    source.status = "active"
    source.merged_into_customer_id = None
    record.reverted_at = datetime.now(UTC)
    record.reverted_by = actor_id
    await audit.record(
        session,
        action="CUSTOMER_UNMERGED",
        actor_type="user",
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="customer",
        resource_id=record.source_customer_id,
        after={"merge_id": record.id},
        request=request,
    )
    return record
