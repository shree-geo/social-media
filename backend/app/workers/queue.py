"""Enqueue background jobs by name without importing Celery into request code.

Tests replace :data:`dispatcher` to capture jobs and run them inline.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

# Task name → queue (ARCHITECTURE.md §17).
TASK_QUEUES = {
    "webhooks.process_event": "webhooks",
    "messages.send": "outbound",
}


async def _celery_dispatch(name: str, kwargs: dict[str, Any], countdown: float | None) -> None:
    from app.workers.celery_app import celery_app

    # Publishing to Redis is blocking I/O; keep it off the event loop.
    await asyncio.to_thread(
        celery_app.send_task, name, kwargs=kwargs, queue=TASK_QUEUES.get(name, "default"), countdown=countdown
    )


dispatcher: Callable[[str, dict[str, Any], float | None], Awaitable[None]] = _celery_dispatch


async def enqueue(name: str, *, countdown: float | None = None, **kwargs: Any) -> None:
    """Best effort: if the broker is down, the sweepers re-enqueue from the database state."""
    try:
        await dispatcher(name, kwargs, countdown)
    except Exception:
        log.warning("enqueue_failed", task=name, exc_info=True)
