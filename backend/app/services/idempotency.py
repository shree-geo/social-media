"""``Idempotency-Key`` support for business-critical POSTs (spec §33, ARCHITECTURE.md §16).

Same key + same body → the stored response is replayed. Same key + different body → 422.
The key row is written in the same transaction as the action, so a failed action leaves
no key behind and the client can retry.
"""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict
from app.models import IdempotencyKey

TTL = timedelta(hours=24)


class IdempotencyKeyRequired(AppError):
    status, code, title = 400, "idempotency_key_required", "Idempotency-Key header is required"


class IdempotencyKeyReused(AppError):
    status, code, title = 422, "idempotency_key_reused", "This Idempotency-Key was used for a different request"


@dataclass(frozen=True)
class Replayed:
    status: int
    body: dict[str, Any]


def _hash(scope: str, body: BaseModel | dict[str, Any] | None) -> str:
    data = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    return hashlib.sha256(json.dumps([scope, data], sort_keys=True, default=str).encode()).hexdigest()


def validate_key(key: str | None) -> str:
    if not key or not 8 <= len(key) <= 128 or not key.isascii():
        raise IdempotencyKeyRequired()
    return key


async def run[T: BaseModel](
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    key: str | None,
    scope: str,
    actor_id: uuid.UUID,
    request_body: BaseModel | dict[str, Any] | None,
    status: int,
    action: Callable[[], Awaitable[T]],
) -> T | Replayed:
    key = validate_key(key)
    request_hash = _hash(scope, request_body)
    inserted = (
        await session.execute(
            insert(IdempotencyKey)
            .values(
                tenant_id=tenant_id,
                key=key,
                scope=scope,
                actor_id=actor_id,
                request_hash=request_hash,
                expires_at=datetime.now(UTC) + TTL,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "key"])
            .returning(IdempotencyKey.key)
        )
    ).scalar_one_or_none()

    if inserted is None:
        existing = (
            await session.execute(
                select(IdempotencyKey).where(IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key)
            )
        ).scalar_one()
        if existing.request_hash != request_hash or existing.scope != scope:
            raise IdempotencyKeyReused()
        if existing.response_body is None:
            raise Conflict("The original request is still being processed.")
        return Replayed(existing.response_status or status, existing.response_body)

    result = await action()
    row = (
        await session.execute(
            select(IdempotencyKey).where(IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key)
        )
    ).scalar_one()
    row.response_status = status
    row.response_body = result.model_dump(mode="json")
    return result
