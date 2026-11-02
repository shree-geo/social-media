"""Leads: chat → lead (products, owner, follow-up) → order; stages, assignment rules, reports."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.fakes import FakeAdapter, body, sign
from tests.integration.conftest import Jobs, connect_channel
from tests.integration.helpers import ClientFactory
from tests.integration.test_sales import _chair, _shop, key

pytestmark = pytest.mark.integration


async def _staff(make_client: ClientFactory, owner: httpx.AsyncClient, role: str) -> tuple[httpx.AsyncClient, str]:
    created = (
        await owner.post(
            "/api/v1/users",
            json={
                "full_name": f"{role.title()} Person",
                "email": f"{role.lower()}-{new_id().hex[-8:]}@example.com",
                "role": role,
            },
        )
    ).json()
    client = await make_client()
    await client.post("/api/v1/auth/login", json={"email": created["email"], "password": created["temporary_password"]})
    await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": created["temporary_password"], "new_password": f"{role} long passphrase"},
    )
    me = (await client.get("/api/v1/auth/me")).json()
    return client, me["user_id"]


async def _chat(
    make_client: ClientFactory, platform_db: AsyncEngine, tenant_id: uuid.UUID, jobs: Jobs
) -> dict[str, Any]:
    channel = await connect_channel(platform_db, tenant_id)
    raw = body(
        {
            "kind": "message",
            "account": channel.external_id,
            "from": "9779812345678",
            "id": f"m-{new_id().hex}",
            "ts": "2026-10-28T08:00:00+00:00",
            "text": "20 ota black chair ko price?",
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
    return dict((await _owner_conversations(make_client, platform_db, tenant_id))[0])


async def _owner_conversations(make_client: ClientFactory, platform_db: AsyncEngine, tenant_id: uuid.UUID) -> list[Any]:
    # The chat list as stored, independent of any client's filters.
    async with platform_db.connect() as conn:
        rows = (
            await conn.execute(text("SELECT id::text FROM conversations WHERE tenant_id = :t"), {"t": tenant_id})
        ).all()
    return [{"id": r[0]} for r in rows]


async def test_lead_from_chat_follow_up_and_convert_to_order(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, tenant_id = await _shop(make_client, platform_db)
    convo = await _chat(make_client, platform_db, tenant_id, jobs)
    sales, sales_id = await _staff(make_client, owner, "SALES")
    # The chat is Sita's (sales): the lead goes to her by default.
    await owner.post(f"/api/v1/conversations/{convo['id']}/assign", json={"user_id": sales_id})

    chair = await _chair(owner)
    black = chair["variants"][0]
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    created = await owner.post(
        "/api/v1/leads",
        json={
            "conversation_id": convo["id"],
            "lead_source": "tiktok",
            "items": [
                {"variant_id": black["id"], "quantity": "20"},
                {"description": "Matching footrest", "quantity": "2", "unit_price": "1500"},
            ],
            "next_followup_at": tomorrow,
            "note": "Wants delivery to Itahari",
        },
    )
    assert created.status_code == 201, created.text
    lead = created.json()
    assert lead["lead_number"].startswith("LD-")
    assert lead["stage"] == "NEW"
    assert lead["assigned_to"]["id"] == sales_id
    assert lead["source_channel"] == "whatsapp"
    assert lead["expected_value"] == "93000.00"  # 20 x 4500 + 2 x 1500
    assert lead["item_summary"] == "20 \N{MULTIPLICATION SIGN} Office chair +1 more"
    assert {a["event"] for a in lead["activities"]} >= {"created", "assigned", "followup_set", "note"}

    # The chat now carries its open lead and the "lead" label.
    chat = (await owner.get(f"/api/v1/conversations/{convo['id']}")).json()
    assert chat["classification"] == "lead"
    assert chat["open_lead"]["id"] == lead["id"]
    assert [c["id"] for c in (await owner.get("/api/v1/conversations?label=open_lead")).json()["items"]] == [
        convo["id"]
    ]

    # Only one open lead per chat.
    again = await owner.post(
        "/api/v1/leads", json={"conversation_id": convo["id"], "items": [{"variant_id": black["id"], "quantity": "1"}]}
    )
    assert again.status_code == 409 and again.json()["code"] == "lead_exists"
    assert again.json()["lead_id"] == lead["id"]

    # Sita sees it in "mine"; it isn't due yet.
    mine = (await sales.get("/api/v1/leads?view=mine")).json()["items"]
    assert [m["id"] for m in mine] == [lead["id"]]
    assert (await sales.get("/api/v1/leads/followups/count")).json() == {"overdue": 0, "today": 0}

    # Stages move freely while open; a stale version is rejected.
    moved = await sales.post(
        f"/api/v1/leads/{lead['id']}/stage", json={"stage": "NEGOTIATING", "version": lead["version"]}
    )
    assert moved.status_code == 200 and moved.json()["stage"] == "NEGOTIATING"
    stale = await sales.post(
        f"/api/v1/leads/{lead['id']}/stage", json={"stage": "INTERESTED", "version": lead["version"]}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "lead_changed"
    won_directly = await sales.post(f"/api/v1/leads/{lead['id']}/stage", json={"stage": "WON"})
    assert won_directly.json()["code"] == "convert_to_win"

    # Overdue follow-up shows up for the owner.
    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    await sales.patch(f"/api/v1/leads/{lead['id']}", json={"next_followup_at": past})
    assert (await sales.get("/api/v1/leads/followups/count")).json()["overdue"] == 1
    assert [d["id"] for d in (await sales.get("/api/v1/leads?view=mine&due=due")).json()["items"]] == [lead["id"]]

    # Convert: the order takes the lead's customer, chat and lead source; the lead becomes WON.
    order = await sales.post(
        "/api/v1/orders",
        json={"lead_id": lead["id"], "items": [{"variant_id": black["id"], "quantity": "20"}]},
        headers=key(),
    )
    assert order.status_code == 201, order.text
    assert order.json()["source_conversation_id"] == convo["id"]
    assert order.json()["lead_source"] == "tiktok"
    assert order.json()["lead"]["id"] == lead["id"]
    won = (await sales.get(f"/api/v1/leads/{lead['id']}")).json()
    assert won["stage"] == "WON" and won["won_order"]["id"] == order.json()["id"]
    assert won["next_followup_at"] is None
    assert won["activities"][0]["event"] == "converted"
    assert (await owner.get(f"/api/v1/conversations/{convo['id']}")).json()["open_lead"] is None

    # A closed lead can't be converted again or edited.
    twice = await sales.post(
        "/api/v1/orders",
        json={"lead_id": lead["id"], "items": [{"variant_id": black["id"], "quantity": "1"}]},
        headers=key(),
    )
    assert twice.status_code == 409 and twice.json()["code"] == "lead_closed"
    assert (await sales.patch(f"/api/v1/leads/{lead['id']}", json={"lead_source": "referral"})).json()[
        "code"
    ] == "lead_closed"

    # A new lead can be opened on the same chat now that the first one is closed.
    second = await owner.post(
        "/api/v1/leads", json={"conversation_id": convo["id"], "items": [{"variant_id": black["id"], "quantity": "1"}]}
    )
    assert second.status_code == 201


async def test_lost_reopen_assignment_rules_and_reports(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner, _ = await _shop(make_client, platform_db)
    sales, sales_id = await _staff(make_client, owner, "SALES")
    other, other_id = await _staff(make_client, owner, "SALES")
    manager, _ = await _staff(make_client, owner, "MANAGER")
    viewer, _ = await _staff(make_client, owner, "VIEWER")
    customer = (
        await owner.post("/api/v1/customers", json={"display_name": "Walk-in Buyer", "phone": "9801234567"})
    ).json()
    variant = (await _chair(owner))["variants"][0]
    new_lead = {
        "customer_id": customer["id"],
        "source_channel": "walk_in",
        "items": [{"variant_id": variant["id"], "quantity": "2"}],
    }

    # Sales staff create leads for themselves; they can't hand one to someone else.
    mine = await sales.post("/api/v1/leads", json=new_lead)
    assert mine.status_code == 201 and mine.json()["assigned_to"]["id"] == sales_id
    forbidden = await sales.post("/api/v1/leads", json={**new_lead, "assigned_to_user_id": other_id})
    assert forbidden.status_code == 403
    assert (
        await sales.post(f"/api/v1/leads/{mine.json()['id']}/assign", json={"user_id": other_id})
    ).status_code == 403

    # Unassigned leads can be claimed by sales; managers can reassign anything.
    pool = await manager.post("/api/v1/leads", json={**new_lead, "assigned_to_user_id": None})
    assert pool.json()["assigned_to"] is None
    assert [x["id"] for x in (await other.get("/api/v1/leads?view=unassigned")).json()["items"]] == [pool.json()["id"]]
    claimed = await other.post(f"/api/v1/leads/{pool.json()['id']}/assign", json={"user_id": other_id})
    assert claimed.status_code == 200 and claimed.json()["assigned_to"]["id"] == other_id
    handed = await manager.post(f"/api/v1/leads/{pool.json()['id']}/assign", json={"user_id": sales_id})
    assert handed.json()["assigned_to"]["id"] == sales_id
    assigned_events = [a for a in handed.json()["activities"] if a["event"] == "assigned"]
    assert assigned_events[0]["to_value"] == "Sales Person"  # names, not ids

    # Viewers read but don't write.
    assert (await viewer.get("/api/v1/leads")).status_code == 200
    assert (await viewer.post("/api/v1/leads", json=new_lead)).status_code == 403

    # Lost needs a reason; reopen clears it.
    lead_id = mine.json()["id"]
    no_reason = await sales.post(f"/api/v1/leads/{lead_id}/stage", json={"stage": "LOST"})
    assert no_reason.status_code == 422
    lost = await sales.post(
        f"/api/v1/leads/{lead_id}/stage", json={"stage": "LOST", "lost_reason": "price", "lost_note": "Found cheaper"}
    )
    assert lost.json()["stage"] == "LOST" and lost.json()["lost_reason"] == "price"
    reopened = await sales.post(f"/api/v1/leads/{lead_id}/stage", json={"stage": "CONTACTED"})
    assert reopened.json()["stage"] == "CONTACTED" and reopened.json()["lost_reason"] is None
    await sales.post(f"/api/v1/leads/{lead_id}/stage", json={"stage": "LOST", "lost_reason": "price"})

    # Notes land on the timeline.
    noted = await sales.post(f"/api/v1/leads/{pool.json()['id']}/notes", json={"body": "Called, will visit Friday"})
    assert noted.json()["activities"][0]["body"] == "Called, will visit Friday"

    # Win the other one.
    await sales.post(
        "/api/v1/orders",
        json={"lead_id": pool.json()["id"], "items": [{"variant_id": variant["id"], "quantity": "2"}]},
        headers=key(),
    )
    orders = (await owner.get("/api/v1/orders")).json()["items"]
    await owner.post(f"/api/v1/orders/{orders[0]['id']}/status", json={"status": "CONFIRMED"})

    board = (await owner.get("/api/v1/leads/board")).json()["columns"]
    assert [len(board[s]) for s in ("NEW", "WON", "LOST")] == [0, 1, 1]

    dash = (await owner.get("/api/v1/reports/dashboard?period=today")).json()
    leads = dash["leads"]
    assert dash["totals"]["new_leads"] == 2
    assert leads["created"] == 2 and leads["won"] == 1 and leads["lost"] == 1
    assert leads["win_rate"] == 0.5
    assert leads["won_value"] == "9000.00"
    assert leads["lost_reasons"] == {"price": 1}
    row = next(s for s in leads["staff"] if s["user_id"] == sales_id)
    assert (row["won"], row["lost"]) == (1, 1)
    walk_in = next(c for c in dash["channels"] if c["channel"] == "walk_in")
    assert walk_in["leads"] == 2


async def test_spam_label_hides_chat_and_merge_moves_leads(
    make_client: ClientFactory, platform_db: AsyncEngine, fake_adapter: FakeAdapter, jobs: Jobs
) -> None:
    owner, tenant_id = await _shop(make_client, platform_db)
    convo = await _chat(make_client, platform_db, tenant_id, jobs)
    labelled = await owner.post(f"/api/v1/conversations/{convo['id']}/classify", json={"label": "spam"})
    assert labelled.json()["classification"] == "spam"
    assert (await owner.get("/api/v1/conversations")).json()["items"] == []
    assert len((await owner.get("/api/v1/conversations?label=spam")).json()["items"]) == 1
    await owner.post(f"/api/v1/conversations/{convo['id']}/classify", json={"label": None})
    assert len((await owner.get("/api/v1/conversations?label=none")).json()["items"]) == 1

    a = (await owner.post("/api/v1/customers", json={"display_name": "Hari", "phone": "9803333333"})).json()
    b = (await owner.post("/api/v1/customers", json={"display_name": "Hari T", "phone": "9804444444"})).json()
    variant = (await _chair(owner))["variants"][0]
    await owner.post(
        "/api/v1/leads",
        json={
            "customer_id": b["id"],
            "source_channel": "phone",
            "items": [{"variant_id": variant["id"], "quantity": "1"}],
        },
    )
    merged = await owner.post(
        "/api/v1/customers/merge", json={"source_customer_id": b["id"], "target_customer_id": a["id"]}
    )
    assert merged.json()["moved"]["leads"] == 1
    assert len((await owner.get(f"/api/v1/leads?customer_id={a['id']}")).json()["items"]) == 1


async def test_followup_job_alerts_once(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    from app.core.database import platform_sessionmaker
    from app.services.leads import claim_due_followups

    owner, _ = await _shop(make_client, platform_db)
    customer = (await owner.post("/api/v1/customers", json={"display_name": "Gita"})).json()
    variant = (await _chair(owner))["variants"][0]
    lead = (
        await owner.post(
            "/api/v1/leads",
            json={
                "customer_id": customer["id"],
                "source_channel": "phone",
                "items": [{"variant_id": variant["id"], "quantity": "1"}],
                "next_followup_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            },
        )
    ).json()

    async def claimed() -> set[str]:
        async with platform_sessionmaker()() as session, session.begin():
            return {str(d.lead_id) for d in await claim_due_followups(session)}

    assert lead["id"] in await claimed()
    assert lead["id"] not in await claimed()  # alerted once
    # A new time re-arms it.
    await owner.patch(
        f"/api/v1/leads/{lead['id']}", json={"next_followup_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat()}
    )
    assert lead["id"] in await claimed()


async def test_leads_are_isolated_between_tenants(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    first, _ = await _shop(make_client, platform_db)
    second, _ = await _shop(make_client, platform_db)
    customer = (await first.post("/api/v1/customers", json={"display_name": "Private"})).json()
    variant = (await _chair(first))["variants"][0]
    lead = (
        await first.post(
            "/api/v1/leads",
            json={
                "customer_id": customer["id"],
                "source_channel": "phone",
                "items": [{"variant_id": variant["id"], "quantity": "1"}],
            },
        )
    ).json()
    assert (await second.get(f"/api/v1/leads/{lead['id']}")).status_code == 404
    assert (await second.get("/api/v1/leads")).json()["items"] == []
    assert (await second.post(f"/api/v1/leads/{lead['id']}/notes", json={"body": "x"})).status_code == 404
