import uuid

from app.core.database import platform_sessionmaker
from app.core.logging import get_logger
from app.services import channels, ingestion, invoices, messaging, onboarding
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


@celery_app.task(name="customers.fetch_profile")
def fetch_customer_profile(tenant_id: str, channel_account_id: str, provider_user_id: str) -> bool:
    return run_async(channels.fetch_profile(uuid.UUID(tenant_id), uuid.UUID(channel_account_id), provider_user_id))


@celery_app.task(name="channels.check_health")
def check_channel_health() -> dict[str, int]:
    """Daily: token still valid and our webhook subscription still in place for each Page."""
    counts = run_async(channels.check_health())
    log.info("channel_health_checked", **counts)
    return counts


async def _render_invoice_pdf(tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> bool:
    from app.core.database import runtime_sessionmaker, set_tenant_context
    from app.models import Invoice

    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        invoice = await session.get(Invoice, invoice_id)
        if invoice is None or invoice.pdf_object_id:
            return False
        await invoices.pdf_bytes(session, invoice)
    return True


@celery_app.task(name="invoices.render_pdf")
def render_invoice_pdf(tenant_id: str, invoice_id: str) -> bool:
    return run_async(_render_invoice_pdf(uuid.UUID(tenant_id), uuid.UUID(invoice_id)))
