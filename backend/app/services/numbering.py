"""Gap-free human-readable document numbers (ARCHITECTURE.md §15, DATABASE.md §6)."""

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import PLATFORM_SEQUENCE_TENANT


def nepali_fiscal_year_key(today: date) -> str:
    """Approximate Nepali fiscal year (starts 1 Shrawan, ~16 July AD) as ``2082-83``.

    The fiscal year that starts in mid-July of AD year Y is BS year Y + 57; before that
    date we are still in the year that started the previous July (Y + 56). A BS calendar
    library replaces the fixed 16 July boundary before invoice numbering goes live
    (open item, ARCHITECTURE.md §25).
    """
    fy_start = today.year + 57 if (today.month, today.day) >= (7, 16) else today.year + 56
    return f"{fy_start}-{(fy_start + 1) % 100:02d}"


def period_key(numbering_period: str, today: date) -> str:
    return nepali_fiscal_year_key(today) if numbering_period == "np_fiscal_year" else str(today.year)


async def next_number(session: AsyncSession, tenant_id: uuid.UUID, doc_type: str, period: str) -> str:
    """Allocate the next number in the caller's transaction (row lock serializes concurrent callers)."""
    value = (
        await session.execute(
            text(
                "INSERT INTO document_sequences (tenant_id, doc_type, period_key, next_value) "
                "VALUES (:tenant, :doc, :period, 2) "
                "ON CONFLICT (tenant_id, doc_type, period_key) "
                "DO UPDATE SET next_value = document_sequences.next_value + 1 "
                "RETURNING next_value - 1"
            ),
            {"tenant": tenant_id, "doc": doc_type, "period": period},
        )
    ).scalar_one()
    return f"{doc_type}-{period}-{value:06d}"


async def next_platform_number(session: AsyncSession, doc_type: str, period: str) -> str:
    return await next_number(session, PLATFORM_SEQUENCE_TENANT, doc_type, period)
