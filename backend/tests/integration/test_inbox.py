"""Phase 2: webhook framework → identity resolution → unified inbox → replies (ARCHITECTURE.md §10-§12)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.fakes import FakeAdapter, PermanentSendError, TransientSendError, body, sign
from tests.integration.conftest import ConnectedChannel, Jobs, connect_channel
from tests.integration.helpers import ClientFactory, _admin_client, _create_tenant, _owner_session, _super_admin_plan

pytestmark = pytest.mark.integration

WEBHOOK = "/api/v1/webhooks/whatsapp"


def _now(offset_minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).isoformat()


def _msg(channel: ConnectedChannel, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": "message",
        "account": channel.external_id,
        "from": "9779812345678",
        "id": f"wamid.{new_id().hex[-16:]}",
        "ts": _now(),
        "text": "Do you have office chairs?",
        "name": "Ram Sharma",
        "phone": "9779812345678",
    }
    event.update(overrides)
    return event


async def _deliver(client: httpx.AsyncClient, raw: bytes, *, signature: str | None = None) -> httpx.Response:
    return await client.post(
        WEBHOOK,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Test-Signature": signature if signature is not None else sign(raw),
        },
    )


async def _tenant(make_client: ClientFactory, platform_db: AsyncEngine) -> tuple[httpx.AsyncClient, ConnectedChannel]:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    owner = await _owner_session(make_client, created)
    channel = await connect_channel(platform_db, uuid.UUID(str(created["tenant_id"])))
    return owner, channel


async def test_webhook_rejects_bad_signature_and_stores_nothing(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    hook = await make_client()
    raw = body({"kind": "message", "account": "x", "from": "1", "id": "evil", "ts": _now()})
    response = await _deliver(hook, raw, signature="0" * 64)
    assert response.status_code == 401
    assert jobs.queued == []
    async with platform_db.connect() as conn:
        stored = await conn.execute(text("SELECT count(*) FROM webhook_events WHERE payload::text LIKE '%evil%'"))
    assert stored.scalar() == 0


async def test_webhook_subscription_challenge(make_client: ClientFactory, fake_adapter: FakeAdapter) -> None:
    hook = await make_client()
    assert (await hook.get(WEBHOOK, params={"token": "verify-me", "challenge": "abc123"})).text == "abc123"
    assert (await hook.get(WEBHOOK, params={"token": "wrong", "challenge": "abc123"})).status_code == 401
    assert (await hook.get("/api/v1/webhooks/unknown-provider")).status_code == 404


async def test_inbound_message_creates_customer_conversation_and_inbox_entry(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    hook = await make_client()

    assert (await _deliver(hook, body(_msg(channel)))).json() == {"status": "ok"}
    assert await jobs.run_all() == ["processed"]

    inbox = (await owner.get("/api/v1/conversations")).json()["items"]
    assert len(inbox) == 1
    convo = inbox[0]
    assert convo["customer"]["display_name"] == "Ram Sharma"
    assert convo["unread_count"] == 1 and convo["window_open"] is True
    assert convo["last_message_preview"] == "Do you have office chairs?"

    messages = (await owner.get(f"/api/v1/conversations/{convo['id']}/messages")).json()["items"]
    assert [m["body"] for m in messages] == ["Do you have office chairs?"]
    assert messages[0]["direction"] == "inbound"

    customer = (await owner.get(f"/api/v1/customers/{convo['customer']['id']}")).json()
    assert customer["phone_e164"] == "+9779812345678"
    assert [i["provider"] for i in customer["identities"]] == ["whatsapp"]
    assert [c["id"] for c in customer["conversations"]] == [convo["id"]]


async def test_redelivery_and_repeated_message_ids_are_not_duplicated(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    hook = await make_client()
    first = _msg(channel)
    raw = body(first)

    await _deliver(hook, raw)
    await _deliver(hook, raw)  # identical redelivery → dropped at receipt
    assert len(jobs.queued) == 1
    # Same message inside a different delivery (Meta batches) → dropped at message level.
    await _deliver(hook, body(first, _msg(channel, text="And tables?")))
    await jobs.run_all()

    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["unread_count"] == 2
    texts = [m["body"] for m in (await owner.get(f"/api/v1/conversations/{convo['id']}/messages")).json()["items"]]
    assert sorted(texts) == ["And tables?", "Do you have office chairs?"]

    assert (await owner.post(f"/api/v1/conversations/{convo['id']}/read")).status_code == 204
    assert (await owner.get(f"/api/v1/conversations/{convo['id']}")).json()["unread_count"] == 0


async def test_out_of_order_delivery_does_not_rewind_thread(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    hook = await make_client()
    await _deliver(hook, body(_msg(channel, text="newer", ts=_now(0))))
    await _deliver(hook, body(_msg(channel, text="older", ts=_now(-5))))
    await jobs.run_all()
    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["last_message_preview"] == "newer"
    texts = [m["body"] for m in (await owner.get(f"/api/v1/conversations/{convo['id']}/messages")).json()["items"]]
    assert texts == ["newer", "older"]  # newest first by provider timestamp


async def test_known_phone_links_to_existing_customer(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    manual = (
        await owner.post("/api/v1/customers", json={"display_name": "Ram (walk-in)", "phone": "98-1234-5678"})
    ).json()
    assert manual["phone_e164"] == "+9779812345678"

    await _deliver(await make_client(), body(_msg(channel)))
    await jobs.run_all()
    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["customer"]["id"] == manual["id"]  # exact normalized phone → same customer
    assert len((await owner.get("/api/v1/customers")).json()["items"]) == 1


async def test_phone_typed_in_chat_suggests_duplicate_then_merge_and_undo(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    existing = (await owner.post("/api/v1/customers", json={"display_name": "Sita Rai", "phone": "9801111111"})).json()

    # A different person/identity (no phone from the provider) writes the same number in chat.
    await _deliver(
        await make_client(),
        body(
            _msg(
                channel, **{"from": "psid-777", "phone": None, "name": "Sita", "text": "My number is +977 980-1111111"}
            )
        ),
    )
    await jobs.run_all()
    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    new_customer = convo["customer"]["id"]
    assert new_customer != existing["id"]  # never auto-merged

    duplicates = (await owner.get("/api/v1/customers/duplicates")).json()
    assert len(duplicates) == 1 and "phone_in_message" in duplicates[0]["reasons"]

    merged = await owner.post(
        "/api/v1/customers/merge", json={"source_customer_id": new_customer, "target_customer_id": existing["id"]}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["moved"]["conversations"] == 1
    assert (await owner.get(f"/api/v1/conversations/{convo['id']}")).json()["customer"]["id"] == existing["id"]
    assert (await owner.get("/api/v1/customers/duplicates")).json() == []
    target = (await owner.get(f"/api/v1/customers/{existing['id']}")).json()
    assert len(target["identities"]) == 1 and len(target["conversations"]) == 1

    assert (await owner.post(f"/api/v1/customers/merges/{merged.json()['merge_id']}/undo")).status_code == 204
    assert (await owner.get(f"/api/v1/conversations/{convo['id']}")).json()["customer"]["id"] == new_customer


async def test_reply_is_queued_sent_and_status_updates_apply(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    hook = await make_client()
    await _deliver(hook, body(_msg(channel)))
    await jobs.run_all()
    convo_id = (await owner.get("/api/v1/conversations")).json()["items"][0]["id"]

    key = {"Idempotency-Key": f"send-{new_id().hex}"}
    reply = await owner.post(
        f"/api/v1/conversations/{convo_id}/messages", json={"text": "Yes, 20 in stock."}, headers=key
    )
    assert reply.status_code == 202 and reply.json()["status"] == "queued"
    replay = await owner.post(
        f"/api/v1/conversations/{convo_id}/messages", json={"text": "Yes, 20 in stock."}, headers=key
    )
    assert replay.json()["id"] == reply.json()["id"]  # replayed, not sent twice
    reused = await owner.post(f"/api/v1/conversations/{convo_id}/messages", json={"text": "Different"}, headers=key)
    assert reused.status_code == 422

    assert await jobs.run_all() == ["sent"]
    assert len(fake_adapter.sent) == 1
    sent = fake_adapter.sent[0]
    assert sent.to == "9779812345678" and sent.text == "Yes, 20 in stock."
    assert sent.account.access_token == "test-access-token"  # decrypted only for the provider call

    await _deliver(
        hook, body({"kind": "status", "account": channel.external_id, "id": "out-1", "status": "read", "ts": _now()})
    )
    await _deliver(
        hook,
        body({"kind": "status", "account": channel.external_id, "id": "out-1", "status": "delivered", "ts": _now()}),
    )
    await jobs.run_all()
    messages = (await owner.get(f"/api/v1/conversations/{convo_id}/messages")).json()["items"]
    assert messages[0]["body"] == "Yes, 20 in stock." and messages[0]["status"] == "read"  # never goes backwards


async def test_reply_requires_idempotency_key_and_open_window(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    await _deliver(await make_client(), body(_msg(channel, ts=(datetime.now(UTC) - timedelta(hours=25)).isoformat())))
    await jobs.run_all()
    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["window_open"] is False

    url = f"/api/v1/conversations/{convo['id']}/messages"
    assert (await owner.post(url, json={"text": "hi"})).json()["code"] == "idempotency_key_required"
    closed = await owner.post(url, json={"text": "hi"}, headers={"Idempotency-Key": f"k-{new_id().hex}"})
    assert closed.status_code == 409 and closed.json()["code"] == "window_closed"


async def test_transient_send_failure_retries_permanent_fails(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    await _deliver(await make_client(), body(_msg(channel)))
    await jobs.run_all()
    convo_id = (await owner.get("/api/v1/conversations")).json()["items"][0]["id"]

    fake_adapter.fail_next = [TransientSendError("timeout"), PermanentSendError("blocked", code="recipient_blocked")]
    await owner.post(
        f"/api/v1/conversations/{convo_id}/messages",
        json={"text": "a"},
        headers={"Idempotency-Key": f"k-{new_id().hex}"},
    )
    assert await jobs.run_all() == ["retry", "failed"]  # retry re-enqueued itself, then a permanent error
    message = (await owner.get(f"/api/v1/conversations/{convo_id}/messages")).json()["items"][0]
    assert message["status"] == "failed" and message["error_code"] == "recipient_blocked"
    assert fake_adapter.sent == []


async def test_status_before_message_is_retried(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    _, channel = await _tenant(make_client, platform_db)
    status = body({"kind": "status", "account": channel.external_id, "id": "not-yet", "status": "sent", "ts": _now()})
    await _deliver(await make_client(), status)
    assert await jobs.run_all() == ["failed"]
    async with platform_db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT processing_status, retry_count, next_retry_at IS NOT NULL AS scheduled "
                    "FROM webhook_events WHERE payload::text LIKE '%not-yet%'"
                )
            )
        ).one()
    assert (row.processing_status, row.retry_count, row.scheduled) == ("failed", 1, True)


async def test_unknown_account_is_ignored(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    await _deliver(
        await make_client(),
        body({"kind": "message", "account": "not-connected", "from": "1", "id": f"x-{new_id().hex}", "ts": _now()}),
    )
    assert await jobs.run_all() == ["ignored"]


async def test_inbox_is_isolated_between_tenants(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner_a, channel_a = await _tenant(make_client, platform_db)
    owner_b, _ = await _tenant(make_client, platform_db)
    await _deliver(await make_client(), body(_msg(channel_a)))
    await jobs.run_all()
    convo = (await owner_a.get("/api/v1/conversations")).json()["items"][0]

    assert (await owner_b.get("/api/v1/conversations")).json()["items"] == []
    assert (await owner_b.get(f"/api/v1/conversations/{convo['id']}")).status_code == 404
    assert (await owner_b.get(f"/api/v1/conversations/{convo['id']}/messages")).status_code == 404
    assert (await owner_b.get(f"/api/v1/customers/{convo['customer']['id']}")).status_code == 404
    send = await owner_b.post(
        f"/api/v1/conversations/{convo['id']}/messages",
        json={"text": "x"},
        headers={"Idempotency-Key": f"k-{new_id().hex}"},
    )
    assert send.status_code == 404


async def test_roles_on_inbox(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, channel = await _tenant(make_client, platform_db)
    await _deliver(await make_client(), body(_msg(channel)))
    await jobs.run_all()
    convo_id = (await owner.get("/api/v1/conversations")).json()["items"][0]["id"]

    async def staff(role: str) -> httpx.AsyncClient:
        created = (
            await owner.post(
                "/api/v1/users",
                json={"full_name": role, "email": f"{role.lower()}-{new_id().hex[-8:]}@example.com", "role": role},
            )
        ).json()
        client = await make_client()
        await client.post(
            "/api/v1/auth/login", json={"email": created["email"], "password": created["temporary_password"]}
        )
        await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": created["temporary_password"], "new_password": f"{role} long passphrase"},
        )
        return client

    viewer, delivery = await staff("VIEWER"), await staff("DELIVERY")
    assert (await viewer.get("/api/v1/conversations")).status_code == 200
    blocked = await viewer.post(
        f"/api/v1/conversations/{convo_id}/messages",
        json={"text": "x"},
        headers={"Idempotency-Key": f"k-{new_id().hex}"},
    )
    assert blocked.status_code == 403
    assert (await delivery.get("/api/v1/conversations")).status_code == 403


async def test_sweeper_fails_stuck_sends_instead_of_resending(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    from app.services import messaging

    owner, channel = await _tenant(make_client, platform_db)
    await _deliver(await make_client(), body(_msg(channel)))
    await jobs.run_all()
    convo_id = (await owner.get("/api/v1/conversations")).json()["items"][0]["id"]
    reply = await owner.post(
        f"/api/v1/conversations/{convo_id}/messages",
        json={"text": "stuck"},
        headers={"Idempotency-Key": f"k-{new_id().hex}"},
    )
    jobs.queued.clear()
    async with platform_db.begin() as conn:  # simulate a worker that died mid-send 15 minutes ago
        await conn.execute(
            text("UPDATE messages SET status = 'sending', created_at = now() - interval '15 minutes' WHERE id = :m"),
            {"m": reply.json()["id"]},
        )
    _, failed = await messaging.sweep_unsent()
    assert failed >= 1
    message = (await owner.get(f"/api/v1/conversations/{convo_id}/messages")).json()["items"][0]
    assert message["status"] == "failed" and message["error_code"] == "delivery_unknown"
    assert fake_adapter.sent == []
