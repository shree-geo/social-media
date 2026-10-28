import uuid

from app.core.database import platform_sessionmaker
from app.core.logging import get_logger
from app.services import ingestion, messaging, onboarding
from app.workers.celery_app import celery_app, run_async
from app.workers.queue import enqueue

log = get_logger(__name__)


@celery_app.task(name="system.ping")
def ping() -> str:
    """Smoke-test task used to verify the worker is consuming."""
    log.info("worker_ping")
    return "pong"


async def _recompute_subscription_statuses() -> int:
    async with platform_sessionmaker()() as session, session.begin():
        return await onboarding.recompute_statuses(session)


@celery_app.task(name="subscriptions.recompute_statuses")
def recompute_subscription_statuses() -> int:
    """Daily (beat). Status is also computed on read, so a late run never grants extra access."""
    changed = run_async(_recompute_subscription_statuses())
    log.info("subscription_statuses_recomputed", changed=changed)
    return changed


@celery_app.task(name="webhooks.process_event")
def process_webhook_event(event_id: str) -> str:
    return run_async(ingestion.process(uuid.UUID(event_id)))


@celery_app.task(name="messages.send")
def send_message(tenant_id: str, message_id: str) -> str:
    return run_async(messaging.send(uuid.UUID(tenant_id), uuid.UUID(message_id)))


async def _sweep() -> dict[str, int]:
    events = await ingestion.due_for_retry()
    for event_id in events:
        await enqueue("webhooks.process_event", event_id=str(event_id))
    queued, failed = await messaging.sweep_unsent()
    for tenant_id, message_id in queued:
        await enqueue("messages.send", tenant_id=str(tenant_id), message_id=str(message_id))
    return {"webhook_events": len(events), "messages_requeued": len(queued), "messages_failed": failed}


@celery_app.task(name="system.sweep")
def sweep() -> dict[str, int]:
    """Every minute: recover deliveries/messages left behind by crashes or broker outages."""
    counts = run_async(_sweep())
    if any(counts.values()):
        log.info("sweep", **counts)
    return counts
