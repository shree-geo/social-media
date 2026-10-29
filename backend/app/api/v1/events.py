"""Server-sent events for the inbox: GET /api/v1/events/stream (ARCHITECTURE.md §14)."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import SubscriptionBlocked, load_tenant_context, request_info, tenant_claims
from app.core.database import runtime_sessionmaker
from app.core.exceptions import Forbidden
from app.services import realtime
from app.services.subscriptions import Access

router = APIRouter(prefix="/events", tags=["events"])

HEARTBEAT_SECONDS = 15
# Event type → permission needed to receive it.
_EVENT_PERMISSIONS = {
    "message.created": "conversation.read",
    "message.status": "conversation.read",
    "conversation.updated": "conversation.read",
}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    # Authorize in a short transaction; never hold a DB transaction open for the stream.
    async with runtime_sessionmaker()() as session, session.begin():
        ctx = await load_tenant_context(
            session, tenant_claims(request), request_info(request), allow_password_change=False
        )
        if ctx.subscription.access is Access.BLOCKED:
            raise SubscriptionBlocked()
        tenant_id, permissions = ctx.tenant_id, ctx.permissions
    if "conversation.read" not in permissions:
        raise Forbidden()

    async def events() -> AsyncIterator[str]:
        yield "retry: 5000\n\n"
        source = realtime.subscribe(tenant_id).__aiter__()
        pending: asyncio.Task[dict[str, object]] | None = None
        try:
            while not await request.is_disconnected():
                pending = pending or asyncio.ensure_future(source.__anext__())
                done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
                if not done:
                    yield ": keep-alive\n\n"
                    continue
                event, pending = pending.result(), None
                needed = _EVENT_PERMISSIONS.get(str(event.get("type")))
                if needed and needed in permissions:
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        finally:
            if pending:
                # Cancelling the running __anext__ unwinds the generator (its finally unsubscribes);
                # aclose() on a generator that is still running would raise RuntimeError.
                pending.cancel()
            else:
                await source.aclose()  # type: ignore[attr-defined]

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
