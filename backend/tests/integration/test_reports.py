"""Phase 7: dashboard figures from real chats, orders and payments (spec §22-24)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.fakes import FakeAdapter, body, sign
from tests.integration.conftest import Jobs, connect_channel
from tests.integration.helpers import ClientFactory
from tests.integration.test_fulfilment import _order, _staff
from tests.integration.test_sales import _chair, _shop, key

pytestmark = pytest.mark.integration


async def test_dashboard_adds_up_chats_orders_payments_and_channels(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, tenant_id = await _shop(make_client, platform_db)
    channel = await connect_channel(platform_db, tenant_id)
    raw = body(
        {
            "kind": "message",
            "account": channel.external_id,
            "from": "9779812345678",
            "id": f"m-{new_id().hex}",
            "ts": datetime.now(UTC).isoformat(),
            "text": "Is the chair available?",
            "name": "Ram Sharma",
            "phone": "9779812345678",
        }
    )
    hook = await make_client()
    await hook.post(
        "/api/v1/webhooks/whatsapp",
        content=raw,
        headers={"Content-Type": "application/json", "X-Test-Signature": sign(raw)},
    )
    await jobs.run_all()
    convo = (await owner.get("/api/v1/conversations")).json()["items"][0]

    # A: from the WhatsApp chat, TikTok lead, 4,500.  B: phone order, 9,200, 5,000 paid.  C: still NEW.
    chair = (await _chair(owner))["variants"][0]
    a = (
        await owner.post(
            "/api/v1/orders",
            json={
                "conversation_id": convo["id"],
                "lead_source": "tiktok",
                "items": [{"variant_id": chair["id"], "quantity": "1"}],
            },
            headers=key(),
        )
    ).json()
    await owner.post(f"/api/v1/orders/{a['id']}/status", json={"status": "CONFIRMED"})
    b = await _order(owner)
    paid = await owner.post(
        f"/api/v1/orders/{b['id']}/payments", json={"amount": "5000", "method": "esewa"}, headers=key()
    )
    assert paid.status_code == 201, paid.text
    await _order(owner, confirm=False)

    response = await owner.get("/api/v1/reports/dashboard", params={"period": "today"})
    assert response.status_code == 200, response.text
    d = response.json()

    t = d["totals"]
    assert (Decimal(t["sales"]), t["sales_orders"], t["new_orders"]) == (Decimal("13700"), 2, 3)
    assert Decimal(t["received"]) == Decimal("5000")
    assert (t["messages_in"], t["new_customers"]) == (1, 3)
    assert d["window"]["bucket"] == "hour" and len(d["series"]) == 24
    assert sum(Decimal(p["sales"]) for p in d["series"]) == Decimal("13700")

    channels = {row["channel"]: row for row in d["channels"]}
    assert (channels["whatsapp"]["messages_in"], channels["whatsapp"]["orders"]) == (1, 1)
    assert Decimal(channels["whatsapp"]["sales"]) == Decimal("4500")
    assert (channels["phone"]["orders"], Decimal(channels["phone"]["sales"])) == (1, Decimal("9200"))
    sources = {row["lead_source"]: Decimal(row["sales"]) for row in d["lead_sources"]}
    assert sources == {None: Decimal("9200"), "tiktok": Decimal("4500")}
    assert (d["orders_by_status"]["CONFIRMED"], d["orders_by_status"]["NEW"]) == (2, 1)

    f = d["funnel"]
    assert (f["conversations"], f["converted_conversations"], f["orders"], Decimal(f["sales"])) == (
        1,
        1,
        1,
        Decimal("4500"),
    )
    s = d["snapshot"]
    assert (s["open_orders"], s["outstanding_orders"], Decimal(s["outstanding"])) == (3, 2, Decimal("8700"))
    assert (s["overdue_invoices"], s["deliveries_open"]) == (0, 0)
    assert d["buyers"] == {"total": 2, "returning": 0}
    assert Decimal(d["previous"]["sales"]) == 0

    # Only roles with report.read see the dashboard figures.
    sales_staff, _ = await _staff(make_client, owner, "SALES")
    assert (await sales_staff.get("/api/v1/reports/dashboard")).status_code == 403
    assert (await owner.get("/api/v1/reports/dashboard", params={"period": "yesterday"})).status_code == 422


async def test_dashboard_is_isolated_between_tenants(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    first, _ = await _shop(make_client, platform_db)
    await _order(first)
    second, _ = await _shop(make_client, platform_db)
    d = (await second.get("/api/v1/reports/dashboard", params={"period": "30d"})).json()
    assert (Decimal(d["totals"]["sales"]), d["totals"]["new_orders"], d["snapshot"]["open_orders"]) == (
        Decimal("0"),
        0,
        0,
    )
    assert d["window"]["bucket"] == "day" and len(d["series"]) == 30
