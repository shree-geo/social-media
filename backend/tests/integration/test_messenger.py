"""Phase 3: Connect Facebook Page wizard + Messenger end to end, against a fake Graph API.

The fake Graph serves Meta's documented response shapes and rejects any call whose
``appsecret_proof`` is missing or wrong, so the tests also prove every call is signed.
"""

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.ids import new_id
from app.integrations import registry
from app.integrations.messenger.adapter import MessengerAdapter
from app.integrations.meta import graph
from tests.integration.conftest import Jobs
from tests.integration.helpers import ClientFactory, _admin_client, _create_tenant, _owner_session, _super_admin_plan

pytestmark = pytest.mark.integration

APP_ID, SECRET, VERSION = "1234567890", "test-meta-app-secret", "v99.0"
USER_TOKEN, LONG_TOKEN = "short-user-token", "long-user-token"
ALL_SCOPES = ["pages_show_list", "pages_messaging", "pages_manage_metadata"]


@dataclass
class FakeGraph:
    """Minimal Graph API double keyed by method + path."""

    debug: dict[str, Any] = field(
        default_factory=lambda: {"is_valid": True, "app_id": APP_ID, "user_id": "fb-user-1", "scopes": ALL_SCOPES}
    )
    pages: list[dict[str, Any]] = field(default_factory=list)
    subscribed: set[str] = field(default_factory=set)
    fail_subscribe: set[str] = field(default_factory=set)
    sent: list[dict[str, Any]] = field(default_factory=list)
    profiles: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(f"/{VERSION}")
        params = dict(request.url.params)
        token = params.get("access_token", "")
        self.calls.append(f"{request.method} {path}")
        app_token = token == f"{APP_ID}|{SECRET}"
        if not app_token:
            proof = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
            if params.get("appsecret_proof") != proof:
                return httpx.Response(400, json={"error": {"message": "Invalid appsecret_proof", "code": 100}})

        if path == "/debug_token":
            info = (
                dict(self.debug)
                if params["input_token"] in (USER_TOKEN, LONG_TOKEN)
                else {"is_valid": True, "app_id": APP_ID}
            )
            return httpx.Response(200, json={"data": info})
        if path == "/oauth/access_token":
            assert params["fb_exchange_token"] == USER_TOKEN
            return httpx.Response(200, json={"access_token": LONG_TOKEN, "token_type": "bearer"})
        if path == "/me/accounts":
            assert token == LONG_TOKEN
            return httpx.Response(200, json={"data": self.pages})
        page = path.split("/")[1]
        if path.endswith("/subscribed_apps"):
            if request.method == "POST":
                if page in self.fail_subscribe:
                    return httpx.Response(403, json={"error": {"message": "Permissions error", "code": 200}})
                self.subscribed.add(page)
                return httpx.Response(200, json={"success": True})
            if request.method == "DELETE":
                self.subscribed.discard(page)
                return httpx.Response(200, json={"success": True})
            return httpx.Response(
                200, json={"data": [{"id": APP_ID, "name": "SocialCommerce"}] if page in self.subscribed else []}
            )
        if path.endswith("/messages") and request.method == "POST":
            body = json.loads(request.content)
            self.sent.append({"page": page, "token": token, **body})
            return httpx.Response(
                200, json={"recipient_id": body["recipient"]["id"], "message_id": f"m_out_{len(self.sent)}"}
            )
        if request.method == "GET" and page in self.profiles:
            return httpx.Response(200, json={"name": self.profiles[page], "id": page})
        return httpx.Response(404, json={"error": {"message": f"unknown {path}", "code": 803}})


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch, api_env: None) -> Iterator[FakeGraph]:
    from app.services import realtime

    for key, value in {
        "META_APP_ID": APP_ID,
        "META_APP_SECRET": SECRET,
        "META_GRAPH_API_VERSION": VERSION,
        "META_WEBHOOK_VERIFY_TOKEN": "verify-token",
        "META_LOGIN_CONFIG_ID_MESSENGER": "login-config-1",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    fake = FakeGraph()
    monkeypatch.setattr(graph, "transport_factory", lambda: httpx.MockTransport(fake.handler))

    async def no_publish(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(realtime, "publish", no_publish)
    registry.register(MessengerAdapter())
    yield fake
    registry.unregister("messenger")
    get_settings.cache_clear()


def _page(
    page_id: str, name: str, tasks: tuple[str, ...] = ("MANAGE", "MESSAGING", "CREATE_CONTENT")
) -> dict[str, Any]:
    return {"id": page_id, "name": name, "tasks": list(tasks), "access_token": f"page-token-{page_id}"}


async def _owner(
    make_client: ClientFactory, platform_db: AsyncEngine, max_pages: int | None = None
) -> tuple[httpx.AsyncClient, uuid.UUID]:
    admin = await _admin_client(make_client, platform_db)
    plan_id = await _super_admin_plan(platform_db)
    if max_pages is not None:
        async with platform_db.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO plan_features (id, plan_id, feature_key, limit_value) VALUES (:id, :p, 'max_messenger_pages', :n)"
                ),
                {"id": new_id(), "p": plan_id, "n": max_pages},
            )
    created = await _create_tenant(admin, plan_id)
    return await _owner_session(make_client, created), uuid.UUID(str(created["tenant_id"]))


async def _wizard(
    owner: httpx.AsyncClient, page_ids: list[str] | None = None
) -> tuple[dict[str, Any], httpx.Response | None]:
    started = await owner.post("/api/v1/channels/setup-sessions", json={"provider": "messenger"})
    assert started.status_code == 201, started.text
    setup = started.json()
    authorized = await owner.post(
        f"/api/v1/channels/setup-sessions/{setup['id']}/authorize",
        json={"state": setup["state"], "access_token": USER_TOKEN},
    )
    assert authorized.status_code == 200, authorized.text
    result = None
    if page_ids is not None:
        result = await owner.post(
            f"/api/v1/channels/setup-sessions/{setup['id']}/complete", json={"page_ids": page_ids}
        )
    return {"setup": setup, **authorized.json()}, result


def _uid() -> str:
    return new_id().hex[-10:]


async def test_connect_page_end_to_end(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph
) -> None:
    owner, tenant_id = await _owner(make_client, platform_db)
    shop, other = f"page-{_uid()}", f"page-{_uid()}"
    fake_graph.pages = [_page(shop, "Sharma Furniture"), _page(other, "Old Shop", tasks=("ANALYZE",))]

    wizard, result = await _wizard(owner, [shop])
    statuses = {p["name"]: p["status"] for p in wizard["pages"]}
    assert statuses == {"Sharma Furniture": "connectable", "Old Shop": "needs_full_control"}
    assert wizard["setup"]["app_id"] == APP_ID and wizard["setup"]["login_config_id"] == "login-config-1"

    assert result is not None and result.status_code == 200, result.text
    assert [r["ok"] for r in result.json()] == [True]
    assert shop in fake_graph.subscribed

    channels = (await owner.get("/api/v1/channels")).json()
    assert [(c["name"], c["status"], c["health_status"]) for c in channels["items"]] == [
        ("Sharma Furniture", "connected", "healthy")
    ]

    async with platform_db.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT ciphertext FROM channel_credentials WHERE tenant_id = :t AND revoked_at IS NULL"),
                {"t": tenant_id},
            )
        ).scalar_one()
        setup_row = (
            await conn.execute(
                text(
                    "SELECT status, temp_token_ciphertext, meta_session_info::text AS info FROM channel_setup_sessions WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).one()
    assert f"page-token-{shop}".encode() not in bytes(stored)  # encrypted at rest
    assert setup_row.status == "completed" and setup_row.temp_token_ciphertext is None  # user token wiped
    assert "token" not in setup_row.info


async def test_rejects_token_from_another_app_and_missing_permissions(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)

    async def authorize() -> httpx.Response:
        setup = (await owner.post("/api/v1/channels/setup-sessions", json={"provider": "messenger"})).json()
        return await owner.post(
            f"/api/v1/channels/setup-sessions/{setup['id']}/authorize",
            json={"state": setup["state"], "access_token": USER_TOKEN},
        )

    fake_graph.debug = {"is_valid": True, "app_id": "some-other-app", "scopes": ALL_SCOPES}
    assert (await authorize()).json()["code"] == "invalid_token"
    fake_graph.debug = {"is_valid": True, "app_id": APP_ID, "user_id": "u", "scopes": ["pages_show_list"]}
    assert (await authorize()).json()["code"] == "permissions_missing"


async def test_wrong_state_is_rejected(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    setup = (await owner.post("/api/v1/channels/setup-sessions", json={"provider": "messenger"})).json()
    response = await owner.post(
        f"/api/v1/channels/setup-sessions/{setup['id']}/authorize", json={"state": "x" * 20, "access_token": USER_TOKEN}
    )
    assert response.json()["code"] == "invalid_state"


async def test_plan_limit_and_page_owned_by_another_business(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph
) -> None:
    owner_a, _ = await _owner(make_client, platform_db, max_pages=1)
    p1, p2 = f"page-{_uid()}", f"page-{_uid()}"
    fake_graph.pages = [_page(p1, "Shop One"), _page(p2, "Shop Two")]
    _, result = await _wizard(owner_a, [p1, p2])
    assert result is not None and result.json()["code"] == "plan_limit_exceeded"
    _, result = await _wizard(owner_a, [p1])
    assert result is not None and result.status_code == 200

    owner_b, _ = await _owner(make_client, platform_db)
    wizard, result = await _wizard(owner_b, [p1])
    assert {p["id"]: p["status"] for p in wizard["pages"]}[p1] == "connected_elsewhere"
    assert result is not None and result.json()["code"] == "page_not_connectable"


async def test_subscribe_failure_changes_nothing(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    page = f"page-{_uid()}"
    fake_graph.pages = [_page(page, "Flaky Page")]
    fake_graph.fail_subscribe.add(page)
    _, result = await _wizard(owner, [page])
    assert result is not None and [r["ok"] for r in result.json()] == [False]
    assert (await owner.get("/api/v1/channels")).json()["items"] == []


def _signed_webhook(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-Hub-Signature-256": signature}


async def test_messenger_message_profile_reply_echo_and_read(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph, jobs: Jobs
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    page, psid = f"page-{_uid()}", f"psid-{_uid()}"
    fake_graph.pages = [_page(page, "Sharma Furniture")]
    fake_graph.profiles[psid] = "Gita Sharma"
    await _wizard(owner, [page])
    hook = await make_client()
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    raw, headers = _signed_webhook(
        {
            "object": "page",
            "entry": [
                {
                    "id": page,
                    "time": now_ms,
                    "messaging": [
                        {
                            "sender": {"id": psid},
                            "recipient": {"id": page},
                            "timestamp": now_ms,
                            "message": {"mid": "m_in_1", "text": "4 feet table cha?"},
                        }
                    ],
                }
            ],
        }
    )
    assert (await hook.post("/api/v1/webhooks/messenger", content=raw, headers=headers)).status_code == 200
    bad = await hook.post(
        "/api/v1/webhooks/messenger", content=raw, headers={**headers, "X-Hub-Signature-256": "sha256=00"}
    )
    assert bad.status_code == 401
    # Ingestion, then the name lookup it schedules (Messenger webhooks carry no name).
    assert await jobs.run_all() == ["processed", "profile"]

    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["provider"] == "messenger" and convo["customer"]["display_name"] == "Gita Sharma"

    await owner.post(
        f"/api/v1/conversations/{convo['id']}/messages",
        json={"text": "Cha! Rs 6,000."},
        headers={"Idempotency-Key": f"k-{_uid()}"},
    )
    assert await jobs.run_all() == ["sent"]
    sent = fake_graph.sent[0]
    assert sent["page"] == page and sent["token"] == f"page-token-{page}"
    assert sent["recipient"] == {"id": psid} and sent["messaging_type"] == "RESPONSE"

    # Echo of our own reply (app_id = ours) must not create a second message; then the customer reads it.
    later = now_ms + 60_000
    raw, headers = _signed_webhook(
        {
            "object": "page",
            "entry": [
                {
                    "id": page,
                    "time": later,
                    "messaging": [
                        {
                            "sender": {"id": page},
                            "recipient": {"id": psid},
                            "timestamp": later,
                            "message": {
                                "mid": "m_out_1",
                                "text": "Cha! Rs 6,000.",
                                "is_echo": True,
                                "app_id": int(APP_ID),
                            },
                        },
                        {
                            "sender": {"id": psid},
                            "recipient": {"id": page},
                            "timestamp": later,
                            "read": {"watermark": later},
                        },
                    ],
                }
            ],
        }
    )
    await hook.post("/api/v1/webhooks/messenger", content=raw, headers=headers)
    await jobs.run_all()
    messages = (await owner.get(f"/api/v1/conversations/{convo['id']}/messages")).json()["items"]
    assert [m["body"] for m in messages] == ["Cha! Rs 6,000.", "4 feet table cha?"]
    assert messages[0]["status"] == "read"


async def test_webhook_subscription_handshake(make_client: ClientFactory, fake_graph: FakeGraph) -> None:
    hook = await make_client()
    ok = await hook.get(
        "/api/v1/webhooks/messenger",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-token", "hub.challenge": "777"},
    )
    assert ok.text == "777"
    bad = await hook.get(
        "/api/v1/webhooks/messenger",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "777"},
    )
    assert bad.status_code == 401


def _signed_request(user_id: str, secret: str = SECRET) -> str:
    payload = (
        base64.urlsafe_b64encode(json.dumps({"algorithm": "HMAC-SHA256", "user_id": user_id}).encode())
        .decode()
        .rstrip("=")
    )
    sig = (
        base64.urlsafe_b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    return f"{sig}.{payload}"


async def test_deauthorize_flags_pages_and_disconnect_stops_messages(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_graph: FakeGraph, jobs: Jobs
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    page = f"page-{_uid()}"
    fake_graph.pages = [_page(page, "Sharma Furniture")]
    fake_graph.debug = {**fake_graph.debug, "user_id": f"fb-{_uid()}"}
    await _wizard(owner, [page])
    hook = await make_client()

    assert (
        await hook.post("/api/v1/webhooks/meta/deauthorize", data={"signed_request": _signed_request("x", "wrong")})
    ).status_code == 400
    deauth = await hook.post(
        "/api/v1/webhooks/meta/deauthorize", data={"signed_request": _signed_request(fake_graph.debug["user_id"])}
    )
    assert deauth.json() == {"affected": 1}
    card = (await owner.get("/api/v1/channels")).json()["items"][0]
    assert card["health_status"] == "action_needed" and "Reconnect" in card["health_reason"]

    deletion = await hook.post(
        "/api/v1/webhooks/meta/data-deletion", data={"signed_request": _signed_request("someone")}
    )
    assert deletion.status_code == 200 and "/data-deletion?code=" in deletion.json()["url"]

    disconnected = await owner.post(f"/api/v1/channels/{card['id']}/disconnect")
    assert disconnected.json()["status"] == "disconnected"
    assert page not in fake_graph.subscribed  # unsubscribed at Meta

    raw, headers = _signed_webhook(
        {
            "object": "page",
            "entry": [
                {
                    "id": page,
                    "time": 1,
                    "messaging": [
                        {
                            "sender": {"id": "psid-x"},
                            "recipient": {"id": page},
                            "timestamp": 1,
                            "message": {"mid": f"m_{_uid()}", "text": "hello?"},
                        }
                    ],
                }
            ],
        }
    )
    await hook.post("/api/v1/webhooks/messenger", content=raw, headers=headers)
    assert await jobs.run_all() == ["ignored"]  # no longer routed to this business
