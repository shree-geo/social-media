"""Real-time fan-out over Redis pub/sub (ARCHITECTURE.md §14).

Events carry ids and minimal fields only; the browser refetches through the normal
REST endpoints, so authorization is always applied there.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(str(get_settings().redis_url))
    return _client


def channel(tenant_id: uuid.UUID) -> str:
    return f"tenant:{tenant_id}:events"


async def publish(tenant_id: uuid.UUID, event_type: str, **data: Any) -> None:
    payload = json.dumps(
        {"type": event_type, **{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()}}
    )
    try:
        await _redis().publish(channel(tenant_id), payload)
    except Exception:
        # Real-time is an optimisation; the UI falls back to polling.
        log.warning("realtime_publish_failed", event_type=event_type, exc_info=True)


async def subscribe(tenant_id: uuid.UUID) -> AsyncIterator[dict[str, Any]]:
    pubsub = Redis.from_url(str(get_settings().redis_url)).pubsub()
    await pubsub.subscribe(channel(tenant_id))
    try:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
