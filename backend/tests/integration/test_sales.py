"""Phase 5: catalogue, orders from chats, lifecycle with stock, invoices and PDFs (spec §16-§21)."""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.fakes import FakeAdapter, body, sign
from tests.integration.conftest import Jobs, connect_channel
from tests.integration.helpers import ClientFactory, _admin_client, _create_tenant, _owner_session, _super_admin_plan

pytestmark = pytest.mark.integration


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"k-{new_id().hex}"}


async def _shop(
    make_client: ClientFactory, platform_db: AsyncEngine, *, features: dict[str, int] | None = None
) -> tuple[httpx.AsyncClient, uuid.UUID]:
    admin = await _admin_client(make_client, platform_db)
    plan_id = await _super_admin_plan(platform_db)
    for feature, value in (features or {}).items():
        async with platform_db.begin() as conn:
            await conn.execute(
                text("INSERT INTO plan_features (id, plan_id, feature_key, limit_value) VALUES (:id, :p, :k, :v)"),
                {"id": new_id(), "p": plan_id, "k": feature, "v": value},
            )
    created = await _create_tenant(admin, plan_id)
    return await _owner_session(make_client, created), uuid.UUID(str(created["tenant_id"]))


async def _chair(owner: httpx.AsyncClient, stock: str = "50") -> dict[str, Any]:
    response = await owner.post(
        "/api/v1/products",
        json={
            "name": "Office chair",
            "unit": "pcs",
            "variants": [
                {"name": "Black", "sku": f"CH-BLK-{new_id().hex[-6:]}", "price": "4500", "opening_stock": stock},
                {"name": "Brown", "price": "4800", "opening_stock": "5"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_catalogue_variants_prices_stock_and_default_vat(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    owner, _ = await _shop(make_client, platform_db)
    rates = (await owner.get("/api/v1/tax-rates")).json()
    assert {r["name"]: r["is_default"] for r in rates} == {
        "VAT 13%": False,
        "No VAT": True,
    }  # tenant isn't VAT registered

    chair = await _chair(owner)
    black, brown = chair["variants"]
    assert (black["name"], black["price"], black["stock"]) == ("Black", "4500.00", "50.000")
    assert brown["sku"].startswith("SKU-")  # generated when the business has no codes
    assert chair["tax_rate"] == "0.00"

    found = (await owner.get("/api/v1/products", params={"q": black["sku"].lower()})).json()["items"]
    assert [p["id"] for p in found] == [chair["id"]]

    updated = (await owner.patch(f"/api/v1/products/variants/{black['id']}", json={"price": "4700"})).json()
    assert updated["variants"][0]["price"] == "4700.00"
    adjusted = (
        await owner.post(f"/api/v1/products/variants/{black['id']}/stock", json={"change": "-3", "note": "damaged"})
    ).json()
    assert adjusted["variants"][0]["stock"] == "47.000"

    duplicate = await owner.post(
        "/api/v1/products", json={"name": "X", "variants": [{"sku": black["sku"], "price": "1"}]}
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "sku_taken"


async def test_order_from_conversation_lifecycle_stock_and_invoice(
    make_client: ClientFactory,
    platform_db: AsyncEngine,
    fake_adapter: FakeAdapter,
    jobs: Jobs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, tenant_id = await _shop(make_client, platform_db)
    channel = await connect_channel(platform_db, tenant_id)
    raw = body(
        {
            "kind": "message",
            "account": channel.external_id,
            "from": "9779812345678",
            "id": f"m-{new_id().hex}",
            "ts": "2026-10-28T08:00:00+00:00",
            "text": "20 ota black chair",
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

    chair = await _chair(owner)
    black = chair["variants"][0]
    # VAT 13% on this product, prices exclusive (tenant default).
    vat = next(r for r in (await owner.get("/api/v1/tax-rates")).json() if r["name"] == "VAT 13%")
    await owner.patch(f"/api/v1/products/{chair['id']}", json={"tax_rate_id": vat["id"]})

    headers = key()
    payload = {
        "conversation_id": convo["id"],
        "lead_source": "tiktok",
        "items": [{"variant_id": black["id"], "quantity": "20", "discount_amount": "1000"}],
        "shipping_fee": "500",
        "delivery_address": {"line1": "Itahari-6", "district": "Sunsari"},
    }
    created = await owner.post("/api/v1/orders", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    order = created.json()
    assert (await owner.post("/api/v1/orders", json=payload, headers=headers)).json()["id"] == order["id"]  # idempotent

    assert order["customer"]["display_name"] == "Ram Sharma"
    assert (order["source_channel"], order["lead_source"]) == ("whatsapp", "tiktok")
    assert order["order_number"].startswith("ORD-2026-")
    line = order["lines"][0]
    assert (line["unit_price"], line["tax_amount"], line["line_total"]) == ("4500.00", "11570.00", "100570.00")
    totals = order["totals"]
    assert (totals["subtotal"], totals["tax_total"], totals["grand_total"]) == ("89000.00", "11570.00", "101070.00")
    assert order["allowed_next"] == ["CANCELLED", "CONFIRMED", "REJECTED"]

    async def stock() -> str:
        return str((await owner.get(f"/api/v1/products/{chair['id']}")).json()["variants"][0]["stock"])

    edited = await owner.patch(
        f"/api/v1/orders/{order['id']}", json={"items": [{"variant_id": black["id"], "quantity": "10"}]}
    )
    assert edited.json()["totals"]["grand_total"] == "51350.00"
    assert (await owner.post(f"/api/v1/orders/{order['id']}/status", json={"status": "DELIVERED"})).status_code == 409

    confirmed = (await owner.post(f"/api/v1/orders/{order['id']}/status", json={"status": "CONFIRMED"})).json()
    assert confirmed["status"] == "CONFIRMED" and await stock() == "40.000"
    locked = await owner.patch(
        f"/api/v1/orders/{order['id']}", json={"items": [{"variant_id": black["id"], "quantity": "1"}]}
    )
    assert locked.json()["code"] == "order_locked"

    from app.workers import queue

    rendered: list[str] = []

    async def capture(name: str, kwargs: dict[str, object], countdown: float | None) -> None:
        rendered.append(name)

    monkeypatch.setattr(queue, "dispatcher", capture)
    invoice = (await owner.post(f"/api/v1/orders/{order['id']}/invoice")).json()
    assert invoice["status"] == "ISSUED" and invoice["invoice_number"].startswith("INV-2026-")
    assert invoice["seller"]["business_name"] == "Sharma Furniture" and invoice["buyer"]["name"] == "Ram Sharma"
    assert invoice["totals"]["grand_total"] == "51350.00" and rendered == ["invoices.render_pdf"]
    assert (await owner.post(f"/api/v1/orders/{order['id']}/invoice")).json()["code"] == "invoice_exists"

    pdf = await owner.get(f"/api/v1/invoices/{invoice['id']}/pdf")
    assert (
        pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    )
    again = await owner.get(f"/api/v1/invoices/{invoice['id']}/pdf")  # now served from storage
    assert again.content == pdf.content

    blocked = await owner.post(
        f"/api/v1/orders/{order['id']}/status", json={"status": "CANCELLED", "reason": "changed mind"}
    )
    assert blocked.json()["code"] == "invoice_issued"
    no_reason = await owner.post(f"/api/v1/invoices/{invoice['id']}/cancel", json={"reason": ""})
    assert no_reason.status_code == 422
    cancelled_invoice = (
        await owner.post(f"/api/v1/invoices/{invoice['id']}/cancel", json={"reason": "wrong quantity"})
    ).json()
    assert cancelled_invoice["status"] == "CANCELLED"

    needs_reason = await owner.post(f"/api/v1/orders/{order['id']}/status", json={"status": "CANCELLED"})
    assert needs_reason.json()["code"] == "invalid_order"
    cancelled = (
        await owner.post(f"/api/v1/orders/{order['id']}/status", json={"status": "CANCELLED", "reason": "changed mind"})
    ).json()
    assert cancelled["status"] == "CANCELLED" and await stock() == "50.000"  # stock returned
    assert [h["to_status"] for h in cancelled["history"]] == ["NEW", "CONFIRMED", "CANCELLED"]

    profile = (await owner.get(f"/api/v1/customers/{order['customer']['id']}")).json()
    assert profile["sales"]["orders"] == 0 and [o["order_number"] for o in profile["orders"]] == [order["order_number"]]


async def test_issued_invoice_is_locked_in_the_database(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner, _ = await _shop(make_client, platform_db)
    customer = (await owner.post("/api/v1/customers", json={"display_name": "Walk-in buyer"})).json()
    variant = (await _chair(owner))["variants"][0]
    order = (
        await owner.post(
            "/api/v1/orders",
            json={
                "customer_id": customer["id"],
                "source_channel": "walk_in",
                "items": [{"variant_id": variant["id"], "quantity": "1"}],
            },
            headers=key(),
        )
    ).json()
    invoice = (await owner.post(f"/api/v1/orders/{order['id']}/invoice")).json()

    for statement in (
        "UPDATE invoices SET grand_total = 1 WHERE id = :i",
        "UPDATE invoices SET buyer_snapshot = '{}'::jsonb WHERE id = :i",
        "UPDATE invoice_items SET line_total = 1 WHERE invoice_id = :i",
        "DELETE FROM invoice_items WHERE invoice_id = :i",
    ):
        with pytest.raises(DBAPIError, match="cannot be changed"):
            async with platform_db.begin() as conn:  # even the RLS-bypassing role
                await conn.execute(text(statement), {"i": invoice["id"]})


async def test_walk_in_order_customer_360_and_merge_moves_orders(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    owner, _ = await _shop(make_client, platform_db)
    a = (await owner.post("/api/v1/customers", json={"display_name": "Sita Rai", "phone": "9801111111"})).json()
    b = (await owner.post("/api/v1/customers", json={"display_name": "Sita R", "phone": "9802222222"})).json()
    variant = (await _chair(owner))["variants"][0]
    for customer in (a, b):
        await owner.post(
            "/api/v1/orders",
            json={
                "customer_id": customer["id"],
                "source_channel": "phone",
                "items": [{"variant_id": variant["id"], "quantity": "2"}],
            },
            headers=key(),
        )
    merged = await owner.post(
        "/api/v1/customers/merge", json={"source_customer_id": b["id"], "target_customer_id": a["id"]}
    )
    assert merged.json()["moved"]["orders"] == 1
    summary = (await owner.get(f"/api/v1/customers/{a['id']}")).json()["sales"]
    assert summary["orders"] == 2 and summary["total_sales"] == "18000.00" and summary["outstanding"] == "18000.00"


async def test_sales_are_isolated_between_tenants(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner_a, _ = await _shop(make_client, platform_db)
    owner_b, _ = await _shop(make_client, platform_db)
    variant = (await _chair(owner_a))["variants"][0]
    customer_a = (await owner_a.post("/api/v1/customers", json={"display_name": "A buyer"})).json()
    order = (
        await owner_a.post(
            "/api/v1/orders",
            json={
                "customer_id": customer_a["id"],
                "source_channel": "phone",
                "items": [{"variant_id": variant["id"], "quantity": "1"}],
            },
            headers=key(),
        )
    ).json()
    invoice = (await owner_a.post(f"/api/v1/orders/{order['id']}/invoice")).json()

    assert (await owner_b.get("/api/v1/products")).json()["items"] == []
    assert (await owner_b.get(f"/api/v1/orders/{order['id']}")).status_code == 404
    assert (await owner_b.get(f"/api/v1/invoices/{invoice['id']}/pdf")).status_code == 404
    customer_b = (await owner_b.post("/api/v1/customers", json={"display_name": "B buyer"})).json()
    stolen = await owner_b.post(
        "/api/v1/orders",
        json={
            "customer_id": customer_b["id"],
            "source_channel": "phone",
            "items": [{"variant_id": variant["id"], "quantity": "1"}],
        },
        headers=key(),
    )
    assert stolen.json()["code"] == "invalid_order"  # tenant A's product is invisible to tenant B


async def test_plan_limits_and_roles(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner, _ = await _shop(make_client, platform_db, features={"max_products": 1, "max_monthly_orders": 1})
    variant = (await _chair(owner))["variants"][0]
    second = await owner.post("/api/v1/products", json={"name": "Table", "variants": [{"price": "9000"}]})
    assert second.json()["code"] == "plan_limit_exceeded"

    customer = (await owner.post("/api/v1/customers", json={"display_name": "Buyer"})).json()
    order = {
        "customer_id": customer["id"],
        "source_channel": "phone",
        "items": [{"variant_id": variant["id"], "quantity": "1"}],
    }
    assert (await owner.post("/api/v1/orders", json=order, headers=key())).status_code == 201
    assert (await owner.post("/api/v1/orders", json=order, headers=key())).json()["code"] == "plan_limit_exceeded"

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

    sales, accountant = await staff("SALES"), await staff("ACCOUNTANT")
    orders = (await sales.get("/api/v1/orders")).json()["items"]
    assert len(orders) == 1
    assert (
        await sales.post(f"/api/v1/orders/{orders[0]['id']}/invoice")
    ).status_code == 403  # invoices: accountant/manager
    assert (
        await accountant.post("/api/v1/products", json={"name": "X", "variants": [{"price": "1"}]})
    ).status_code == 403
    assert (await accountant.post(f"/api/v1/orders/{orders[0]['id']}/invoice")).status_code == 201
    assert Decimal((await accountant.get("/api/v1/invoices")).json()[0]["grand_total"]) == Decimal("4500.00")
