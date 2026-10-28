"""Audit log writer (ARCHITECTURE.md §19).

Always called inside the same transaction as the action it records, so an action
cannot commit without its audit row. Values are scrubbed of secrets before storing.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact_secrets
from app.models import AuditLog

ActorType = Literal["user", "platform_user", "system"]


@dataclass(frozen=True)
class RequestInfo:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def _clean(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    cleaned = dict(redact_secrets(None, "", {k: v for k, v in values.items()}))
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in cleaned.items()}


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: RequestInfo | None = None,
) -> None:
    info = request or RequestInfo()
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=_clean(before),
            after=_clean(after),
            ip=info.ip,
            user_agent=(info.user_agent or "")[:512] or None,
            request_id=info.request_id,
        )
    )
