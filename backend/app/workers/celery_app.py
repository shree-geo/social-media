"""Celery application: queues and beat schedule from ARCHITECTURE.md §17.

Tasks reuse the async service layer. Each worker process owns one event loop
(created at ``worker_process_init``) and runs coroutines on it via :func:`run_async`,
so async SQLAlchemy engines are never shared across loops.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, json=settings.app_env != "development")

from app.integrations.setup import register_enabled_adapters  # noqa: E402

register_enabled_adapters()

celery_app = Celery("socialcommerce", broker=str(settings.celery_broker_url), include=["app.workers.tasks"])

QUEUES = ("webhooks", "outbound", "media", "default", "pdf")

celery_app.conf.update(
    task_queues=[Queue(name) for name in QUEUES],
    task_default_queue="default",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    timezone="Asia/Kathmandu",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Times are Asia/Kathmandu (``timezone`` above). Sweepers and token checks are added with their modules.
        "system-sweep": {"task": "system.sweep", "schedule": 60.0},
        "channels-health-check": {"task": "channels.check_health", "schedule": crontab(hour=3, minute=0)},
        "subscriptions-recompute-statuses": {
            "task": "subscriptions.recompute_statuses",
            "schedule": crontab(hour=0, minute=15),
        },
    },
)

_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def _init_loop(**_: Any) -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)


@worker_process_shutdown.connect
def _close_loop(**_: Any) -> None:
    if _loop is not None:
        from app.core.database import dispose_engines

        _loop.run_until_complete(dispose_engines())
        _loop.close()


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = _loop or asyncio.get_event_loop_policy().get_event_loop()
    return loop.run_until_complete(coro)
