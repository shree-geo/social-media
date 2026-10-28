from app.core.database import platform_sessionmaker
from app.core.logging import get_logger
from app.services import onboarding
from app.workers.celery_app import celery_app, run_async

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
