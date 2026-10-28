"""Provider webhooks: /api/v1/webhooks/{provider} (ARCHITECTURE.md §10).

Fast path only: verify signature → store raw delivery → enqueue → 200. No business
logic, no outbound calls. Mounted without CSRF (providers don't have our cookies).
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from app.core.database import runtime_sessionmaker
from app.core.exceptions import AppError, NotFound
from app.core.logging import get_logger
from app.integrations import registry
from app.integrations.base import WebhookRejected
from app.services import ingestion
from app.workers.queue import enqueue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger(__name__)

MAX_BODY_BYTES = 1024 * 1024


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "Payload too large"


class InvalidSignature(AppError):
    status, code, title = 401, "invalid_signature", "Invalid signature"


class InvalidPayload(AppError):
    status, code, title = 400, "invalid_payload", "Invalid payload"


def _adapter(provider: str):  # type: ignore[no-untyped-def]
    adapter = registry.get(provider)
    if adapter is None:
        raise NotFound()
    return adapter


@router.get("/{provider}")
async def verify_subscription(provider: str, request: Request) -> Response:
    challenge = _adapter(provider).verify_subscription_challenge(dict(request.query_params))
    if challenge is None:
        raise InvalidSignature("Verification failed")
    return PlainTextResponse(challenge)


@router.post("/{provider}")
async def receive(provider: str, request: Request) -> dict[str, str]:
    adapter = _adapter(provider)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise PayloadTooLarge()
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise PayloadTooLarge()

    try:
        adapter.validate_webhook(request.headers, raw)
    except WebhookRejected as exc:
        log.warning("webhook_rejected", provider=provider, reason=str(exc))
        raise InvalidSignature() from exc
    try:
        payload = ingestion.decode_json(raw)
    except ValueError as exc:
        raise InvalidPayload() from exc

    async with runtime_sessionmaker()() as session, session.begin():
        received = await ingestion.receive(session, provider=provider, raw_body=raw, payload=payload)
    if not received.duplicate:
        await enqueue("webhooks.process_event", event_id=str(received.event_id))
    return {"status": "ok"}
