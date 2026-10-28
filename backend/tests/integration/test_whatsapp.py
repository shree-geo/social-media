"""Phase 4: WhatsApp Embedded Signup + Cloud API end to end, against a fake Graph API.

Like the real API, the fake accepts each Embedded Signup ``code`` once and rejects calls
without a valid ``appsecret_proof``.
"""

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
from app.integrations.meta import graph
from app.integrations.whatsapp.adapter import WhatsAppAdapter
from tests.integration.conftest import Jobs
from tests.integration.helpers import ClientFactory, _admin_client, _create_tenant, _owner_session, _super_admin_plan

pytestmark = pytest.mark.integration

APP_ID, SECRET, VERSION = "1234567890", "test-meta-app-secret", "v99.0"
BUSINESS_TOKEN = "business-integration-token"
WA_SCOPES = ["whatsapp_business_management", "whatsapp_business_messaging"]


@dataclass
class FakeWhatsAppGraph:
    waba: str = ""
    phone: str = ""
    platform_type: str = "NOT_APPLICABLE"
    granted_wabas: list[str] | None = None
    used_codes: set[str] = field(default_factory=set)
    subscribed: set[str] = field(default_factory=set)
    register_failures: list[dict[str, Any]] = field(default_factory=list)
    registered_pins: list[str] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    exchanges: int = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(f"/{VERSION}")
        params = dict(request.url.params)
        token = params.get("access_token", "")
        if token != f"{APP_ID}|{SECRET}":
            proof = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
            if params.get("appsecret_proof") != proof:
                return httpx.Response(400, json={"error": {"message": "Invalid appsecret_proof", "code": 100}})
        if path == "/oauth/access_token":
            code = params["code"]
            if code in self.used_codes:
                return httpx.Response(
                    400, json={"error": {"message": "This authorization code has been used", "code": 100}}
                )
            self.used_codes.add(code)
            self.exchanges += 1
            return httpx.Response(200, json={"access_token": BUSINESS_TOKEN})
        if path == "/debug_token":
            granted = self.granted_wabas if self.granted_wabas is not None else [self.waba]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_valid": True,
                        "app_id": APP_ID,
                        "user_id": "fb-wa-user",
                        "scopes": WA_SCOPES,
                        "granular_scopes": [{"scope": s, "target_ids": granted} for s in WA_SCOPES],
                    }
                },
            )
        if path == f"/{self.waba}/phone_numbers":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": self.phone,
                            "display_phone_number": "+977 980-0000000",
                            "verified_name": "Sharma Furniture",
                            "name_status": "PENDING_REVIEW",
                            "quality_rating": "GREEN",
                            "platform_type": self.platform_type,
                        }
                    ]
                },
            )
        if path == f"/{self.waba}/subscribed_apps":
            if request.method == "POST":
                self.subscribed.add(self.waba)
            elif request.method == "DELETE":
                self.subscribed.discard(self.waba)
            else:
                data = (
                    [{"whatsapp_business_api_data": {"id": APP_ID, "name": "SocialCommerce"}}]
                    if self.waba in self.subscribed
                    else []
                )
                return httpx.Response(200, json={"data": data})
            return httpx.Response(200, json={"success": True})
        if path == f"/{self.phone}/register":
            if self.register_failures:
                return httpx.Response(400, json={"error": self.register_failures.pop(0)})
            self.registered_pins.append(json.loads(request.content)["pin"])
            self.platform_type = "CLOUD_API"
            return httpx.Response(200, json={"success": True})
        if path == f"/{self.phone}/messages":
            self.sent.append({"token": token, **json.loads(request.content)})
            return httpx.Response(
                200, json={"messaging_product": "whatsapp", "messages": [{"id": f"wamid.out{len(self.sent)}"}]}
            )
        return httpx.Response(404, json={"error": {"message": f"unknown {path}", "code": 803}})


@pytest.fixture
def wa_graph(monkeypatch: pytest.MonkeyPatch, api_env: None) -> Iterator[FakeWhatsAppGraph]:
    from app.services import realtime

    for key, value in {
        "META_APP_ID": APP_ID,
        "META_APP_SECRET": SECRET,
        "META_GRAPH_API_VERSION": VERSION,
        "META_LOGIN_CONFIG_ID_WHATSAPP": "wa-config-1",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    fake = FakeWhatsAppGraph(
        waba=str(10**14 + int(new_id().hex[-8:], 16)), phone=str(2 * 10**14 + int(new_id().hex[-8:], 16))
    )
    monkeypatch.setattr(graph, "transport_factory", lambda: httpx.MockTransport(fake.handler))

    async def no_publish(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(realtime, "publish", no_publish)
    registry.register(WhatsAppAdapter())
    yield fake
    registry.unregister("whatsapp")
    get_settings.cache_clear()


async def _owner(make_client: ClientFactory, platform_db: AsyncEngine) -> tuple[httpx.AsyncClient, uuid.UUID]:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    return await _owner_session(make_client, created), uuid.UUID(str(created["tenant_id"]))


async def _start(owner: httpx.AsyncClient, mode: str = "new_number") -> dict[str, Any]:
    started = await owner.post("/api/v1/channels/setup-sessions", json={"provider": "whatsapp", "mode": mode})
    assert started.status_code == 201, started.text
    return dict(started.json())


async def _complete(
    owner: httpx.AsyncClient, setup: dict[str, Any], fake: FakeWhatsAppGraph, code: str | None
) -> httpx.Response:
    body: dict[str, Any] = {"state": setup["state"], "waba_id": fake.waba, "phone_number_id": fake.phone}
    if code:
        body["code"] = code
    return await owner.post(f"/api/v1/channels/setup-sessions/{setup['id']}/whatsapp", json=body)


async def test_new_number_signup_end_to_end(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph
) -> None:
    owner, tenant_id = await _owner(make_client, platform_db)
    setup = await _start(owner)
    assert setup["login_config_id"] == "wa-config-1"

    done = await _complete(owner, setup, wa_graph, code="code-1")
    assert done.status_code == 200, done.text
    assert done.json()["display_phone"] == "+977 980-0000000" and done.json()["name_status"] == "PENDING_REVIEW"
    assert wa_graph.waba in wa_graph.subscribed
    assert len(wa_graph.registered_pins) == 1 and len(wa_graph.registered_pins[0]) == 6

    card = (await owner.get("/api/v1/channels")).json()["items"][0]
    assert (card["provider"], card["health_status"], card["coexistence"]) == ("whatsapp", "healthy", False)

    async with platform_db.connect() as conn:
        creds = {
            r.credential_type: (r.channel_account_id, bytes(r.ciphertext))
            for r in await conn.execute(
                text(
                    "SELECT credential_type, channel_account_id, ciphertext FROM channel_credentials WHERE tenant_id = :t AND revoked_at IS NULL"
                ),
                {"t": tenant_id},
            )
        }
        session_token = (
            await conn.execute(
                text("SELECT temp_token_ciphertext FROM channel_setup_sessions WHERE id = :s"), {"s": setup["id"]}
            )
        ).scalar_one()
    assert creds["business_token"][0] is None  # shared by the WABA's numbers
    assert creds["two_step_pin"][0] is not None
    assert BUSINESS_TOKEN.encode() not in creds["business_token"][1]
    assert wa_graph.registered_pins[0].encode() not in creds["two_step_pin"][1]
    assert session_token is None


async def test_failed_registration_resumes_without_reusing_the_code(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    setup = await _start(owner)
    wa_graph.register_failures = [{"message": "Temporarily unavailable", "code": 2}]
    first = await _complete(owner, setup, wa_graph, code="code-2")
    assert first.status_code == 422
    card = (await owner.get("/api/v1/channels")).json()["items"][0]
    assert card["health_status"] == "action_needed"

    retry = await _complete(owner, setup, wa_graph, code=None)  # Meta's code is single-use
    assert retry.status_code == 200, retry.text
    assert wa_graph.exchanges == 1 and len(wa_graph.registered_pins) == 1
    assert (await owner.get("/api/v1/channels")).json()["items"][0]["health_status"] == "healthy"


async def test_pin_protected_number_explains_the_fix(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    wa_graph.register_failures = [{"message": "Two step verification PIN Mismatch", "code": 133005}]
    response = await _complete(owner, await _start(owner), wa_graph, code="code-3")
    assert response.json()["code"] == "pin_protected"
    assert "two-step verification" in response.json()["detail"]


async def test_coexistence_skips_registration(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    response = await _complete(owner, await _start(owner, mode="coexistence"), wa_graph, code="code-4")
    assert response.status_code == 200 and response.json()["coexistence"] is True
    assert wa_graph.registered_pins == []


async def test_signup_safety_checks(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    wa_graph.granted_wabas = ["some-other-waba"]
    assert (await _complete(owner, await _start(owner), wa_graph, code="code-5")).json()["code"] == "waba_not_shared"

    wa_graph.granted_wabas = None
    setup = await _start(owner)
    body = {"state": setup["state"], "code": "code-6", "waba_id": wa_graph.waba, "phone_number_id": "999999999999"}
    wrong_number = await owner.post(f"/api/v1/channels/setup-sessions/{setup['id']}/whatsapp", json=body)
    assert wrong_number.json()["code"] == "number_not_in_account"

    assert (await _complete(owner, await _start(owner), wa_graph, code="code-7")).status_code == 200
    other, _ = await _owner(make_client, platform_db)
    taken = await _complete(other, await _start(other), wa_graph, code="code-8")
    assert taken.json()["code"] == "number_connected_elsewhere"

    bad_mode = await owner.post("/api/v1/channels/setup-sessions", json={"provider": "whatsapp", "mode": "page"})
    assert bad_mode.status_code == 422


def _webhook(field_name: str, value: dict[str, Any], waba: str) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": waba, "changes": [{"field": field_name, "value": value}]}],
        }
    ).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-Hub-Signature-256": signature}


async def test_whatsapp_messages_reply_status_and_account_events(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph, jobs: Jobs
) -> None:
    owner, _ = await _owner(make_client, platform_db)
    await _complete(owner, await _start(owner), wa_graph, code="code-9")
    hook = await make_client()
    customer = f"97798{new_id().int % 10**8:08d}"
    now = str(int(datetime.now(UTC).timestamp()))

    raw, headers = _webhook(
        "messages",
        {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "9779800000000", "phone_number_id": wa_graph.phone},
            "contacts": [{"profile": {"name": "Hari Thapa"}, "wa_id": customer}],
            "messages": [
                {
                    "from": customer,
                    "id": "wamid.in1",
                    "timestamp": now,
                    "type": "text",
                    "text": {"body": "eSewa milchha?"},
                }
            ],
        },
        wa_graph.waba,
    )
    assert (await hook.post("/api/v1/webhooks/whatsapp", content=raw, headers=headers)).status_code == 200
    assert await jobs.run_all() == ["processed"]  # name and phone come with the message: no lookup job

    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]
    assert convo["provider"] == "whatsapp" and convo["customer"]["display_name"] == "Hari Thapa"
    profile = (await owner.get(f"/api/v1/customers/{convo['customer']['id']}")).json()
    assert profile["phone_e164"] == f"+{customer}"

    await owner.post(
        f"/api/v1/conversations/{convo['id']}/messages",
        json={"text": "Milchha!"},
        headers={"Idempotency-Key": f"k-{new_id().hex}"},
    )
    assert await jobs.run_all() == ["sent"]
    sent = wa_graph.sent[0]
    assert sent["token"] == BUSINESS_TOKEN and sent["to"] == customer and sent["text"]["body"] == "Milchha!"

    raw, headers = _webhook(
        "messages",
        {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": wa_graph.phone},
            "statuses": [{"id": "wamid.out1", "status": "read", "timestamp": now, "recipient_id": customer}],
        },
        wa_graph.waba,
    )
    await hook.post("/api/v1/webhooks/whatsapp", content=raw, headers=headers)
    await jobs.run_all()
    assert (await owner.get(f"/api/v1/conversations/{convo['id']}/messages")).json()["items"][0]["status"] == "read"

    for field_name, value in (
        (
            "phone_number_name_update",
            {
                "display_phone_number": "9779800000000",
                "decision": "APPROVED",
                "requested_verified_name": "Sharma Furniture Itahari",
            },
        ),
        (
            "phone_number_quality_update",
            {"display_phone_number": "9779800000000", "event": "FLAGGED", "current_limit": "TIER_1K"},
        ),
    ):
        raw, headers = _webhook(field_name, value, wa_graph.waba)
        await hook.post("/api/v1/webhooks/whatsapp", content=raw, headers=headers)
    assert await jobs.run_all() == ["processed", "processed"]
    card = (await owner.get("/api/v1/channels")).json()["items"][0]
    assert card["name"] == "Sharma Furniture Itahari" and card["name_status"] == "APPROVED"
    assert card["health_status"] == "action_needed" and "quality" in card["health_reason"]


async def test_disconnect_unsubscribes_and_revokes(
    make_client: ClientFactory, platform_db: AsyncEngine, wa_graph: FakeWhatsAppGraph, jobs: Jobs
) -> None:
    owner, tenant_id = await _owner(make_client, platform_db)
    await _complete(owner, await _start(owner), wa_graph, code="code-10")
    card = (await owner.get("/api/v1/channels")).json()["items"][0]
    assert (await owner.post(f"/api/v1/channels/{card['id']}/disconnect")).json()["status"] == "disconnected"
    assert wa_graph.waba not in wa_graph.subscribed
    async with platform_db.connect() as conn:
        active = (
            await conn.execute(
                text("SELECT count(*) FROM channel_credentials WHERE tenant_id = :t AND revoked_at IS NULL"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert active == 0
