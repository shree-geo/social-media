"""Redis pub/sub fan-out used by the inbox event stream (ARCHITECTURE.md §14)."""

import asyncio

import pytest

from app.core.ids import new_id
from app.services import realtime

pytestmark = pytest.mark.integration


async def test_events_reach_only_the_same_tenant(api_env: None) -> None:
    tenant_a, tenant_b = new_id(), new_id()
    received: list[dict[str, object]] = []

    async def listen() -> None:
        async for event in realtime.subscribe(tenant_a):
            received.append(event)
            return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.3)  # let SUBSCRIBE register
    await realtime.publish(tenant_b, "message.created", conversation_id=new_id())  # other tenant: not delivered
    conversation_id = new_id()
    await realtime.publish(tenant_a, "message.created", conversation_id=conversation_id)
    await asyncio.wait_for(listener, timeout=5)
    await realtime.close()

    assert received == [{"type": "message.created", "conversation_id": str(conversation_id)}]
