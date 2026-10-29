"""Phase 6: manual deliveries and payments, balances, and the order following its delivery (spec §20, §21)."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.integration.helpers import ClientFactory
from tests.integration.test_sales import _chair, _shop, key

pytestmark = pytest.mark.integration


async def _order(owner: httpx.AsyncClient, *, quantity: str = "2", confirm: bool = True) -> dict[str, Any]:
    customer = (await owner.post("/api/v1/customers", json={"display_name": "Gita Thapa"})).json()
    variant = (await _chair(owner))["variants"][0]  # Rs. 4,500, no VAT
    order = (
        await owner.post(
            "/api/v1/orders",
            json={
                "customer_id": customer["id"],
                "source_channel": "phone",
                "items": [{"variant_id": variant["id"], "quantity": quantity}],
                "shipping_fee": "200",
            },
            headers=key(),
        )
    ).json()
    if confirm:
        order = (await owner.post(f"/api/v1/orders/{order['id']}/status", json={"status": "CONFIRMED"})).json()
    return dict(order)


async def _staff(make_client: ClientFactory, owner: httpx.AsyncClient, role: str) -> tuple[httpx.AsyncClient, str]:
    name = f"{role.title()} {new_id().hex[-4:]}"
    created = (
        await owner.post(
            "/api/v1/users",
            json={"full_name": name, "email": f"{role.lower()}-{new_id().hex[-8:]}@example.com", "role": role},
        )
    ).json()
    client = await make_client()
    await client.post("/api/v1/auth/login", json={"email": created["email"], "password": created["temporary_password"]})
    await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": created["temporary_password"], "new_password": f"{role} long passphrase"},
    )
    staff = (await owner.get("/api/v1/deliveries/staff")).json()
    return client, next(m["user_id"] for m in staff if m["full_name"] == name)


async def test_advance_delivery_with_cod_and_balances(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner, _ = await _shop(make_client, platform_db)
    order = await _order(owner)  # 2 x 4,500 + 200 delivery = 9,200
    oid = order["id"]

    advance = await owner.post(
        f"/api/v1/orders/{oid}/payments",
        json={"amount": "1000", "method": "esewa", "reference": "ES-889"},
        headers=key(),
    )
    assert advance.status_code == 201, advance.text
    assert advance.json()["payment_number"].startswith("PAY-")
    too_much = await owner.post(
        f"/api/v1/orders/{oid}/payments", json={"amount": "9000", "method": "cash"}, headers=key()
    )
    assert too_much.json()["code"] == "invalid_payment"
    totals = (await owner.get(f"/api/v1/orders/{oid}")).json()["totals"]
    assert (totals["amount_paid"], totals["amount_due"], totals["payment_status"]) == ("1000.00", "8200.00", "PARTIAL")

    rider, rider_id = await _staff(make_client, owner, "DELIVERY")
    delivery = (
        await owner.post(f"/api/v1/orders/{oid}/deliveries", json={"method": "own_staff", "assigned_to": rider_id})
    ).json()
    assert delivery["status"] == "ASSIGNED" and delivery["cod_amount"] == "8200.00"  # defaults to what's due
    assert delivery["contact_name"] == "Gita Thapa"
    second = await owner.post(f"/api/v1/orders/{oid}/deliveries", json={"method": "customer_pickup"})
    assert second.json()["code"] == "delivery_open"

    detail = (await owner.get(f"/api/v1/orders/{oid}")).json()
    assert "OUT_FOR_DELIVERY" not in detail["allowed_next"] and "DELIVERED" not in detail["allowed_next"]
    direct = await owner.post(f"/api/v1/orders/{oid}/status", json={"status": "READY_FOR_DELIVERY"})
    assert direct.status_code == 200  # steps before the delivery leaves are still the shop's
    blocked = await owner.post(f"/api/v1/orders/{oid}/status", json={"status": "OUT_FOR_DELIVERY"})
    assert blocked.json()["code"] == "delivery_open"

    mine = (await rider.get("/api/v1/deliveries", params={"view": "mine"})).json()["items"]
    assert [d["id"] for d in mine] == [delivery["id"]]
    out = await rider.post(f"/api/v1/deliveries/{delivery['id']}/status", json={"status": "OUT_FOR_DELIVERY"})
    assert out.json()["order"]["status"] == "OUT_FOR_DELIVERY"
    # The rider may record cash collected on their own delivery, but nothing else.
    other = await rider.post(f"/api/v1/orders/{oid}/payments", json={"amount": "10", "method": "esewa"}, headers=key())
    assert other.status_code == 403
    done = await rider.post(
        f"/api/v1/deliveries/{delivery['id']}/status", json={"status": "DELIVERED", "cod_collected": "8200"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["delivered_at"] is not None

    detail = (await owner.get(f"/api/v1/orders/{oid}")).json()
    assert detail["status"] == "DELIVERED"
    assert [h["to_status"] for h in detail["history"]] == [
        "NEW",
        "CONFIRMED",
        "READY_FOR_DELIVERY",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
    ]
    assert detail["totals"]["payment_status"] == "PAID" and detail["totals"]["amount_due"] == "0.00"
    cod = next(p for p in detail["payments"] if p["method"] == "cod")
    assert cod["delivery_id"] == delivery["id"] and cod["amount"] == "8200.00"
    assert [e["to_status"] for e in detail["deliveries"][0]["history"]] == ["ASSIGNED", "OUT_FOR_DELIVERY", "DELIVERED"]

    # The invoice made afterwards carries the paid amount; voiding a payment updates both.
    invoice = (await owner.post(f"/api/v1/orders/{oid}/invoice")).json()
    assert invoice["totals"]["payment_status"] == "PAID"
    assert (
        await rider.post(f"/api/v1/payments/{advance.json()['id']}/void", json={"reason": "typo"})
    ).status_code == 403
    voided = await owner.post(f"/api/v1/payments/{advance.json()['id']}/void", json={"reason": "Wrong eSewa reference"})
    assert voided.json()["status"] == "voided"
    again = await owner.post(f"/api/v1/payments/{advance.json()['id']}/void", json={"reason": "again"})
    assert again.json()["code"] == "payment_voided"
    invoice = (await owner.get(f"/api/v1/invoices/{invoice['id']}")).json()
    assert (invoice["totals"]["amount_due"], invoice["totals"]["payment_status"]) == ("1000.00", "PARTIAL")
    listed = (await owner.get("/api/v1/payments")).json()["items"]
    assert [p["method"] for p in listed] == ["cod"]  # voided rows are hidden by default
    summary = (await owner.get(f"/api/v1/customers/{detail['customer']['id']}")).json()["sales"]
    assert summary["outstanding"] == "1000.00"


async def test_failed_attempt_retry_cancel_and_return(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner, _ = await _shop(make_client, platform_db)
    order = await _order(owner, quantity="1")
    oid = order["id"]
    first = (
        await owner.post(f"/api/v1/orders/{oid}/deliveries", json={"method": "courier", "courier_name": "Pathao"})
    ).json()
    await owner.post(f"/api/v1/deliveries/{first['id']}/status", json={"status": "PICKED_UP"})
    no_note = await owner.post(f"/api/v1/deliveries/{first['id']}/status", json={"status": "FAILED"})
    assert no_note.json()["code"] == "invalid_delivery"
    failed = await owner.post(
        f"/api/v1/deliveries/{first['id']}/status", json={"status": "FAILED", "note": "Customer not home"}
    )
    assert failed.json()["order"]["status"] == "READY_FOR_DELIVERY"

    retry = (await owner.post(f"/api/v1/orders/{oid}/deliveries", json={"method": "customer_pickup"})).json()
    picked = await owner.post(f"/api/v1/deliveries/{retry['id']}/status", json={"status": "DELIVERED"})
    assert picked.json()["order"]["status"] == "DELIVERED"
    returned = await owner.post(
        f"/api/v1/deliveries/{retry['id']}/status", json={"status": "RETURNED", "note": "Wrong colour"}
    )
    assert returned.json()["order"]["status"] == "RETURNED"
    stock = (await owner.get("/api/v1/products")).json()["items"][0]["variants"][0]["stock"]
    assert stock == "50.000"  # went out on confirm, came back on return

    # A return recorded on the order itself also closes the delivered delivery.
    third = await _order(owner, quantity="1")
    drop = (await owner.post(f"/api/v1/orders/{third['id']}/deliveries", json={"method": "customer_pickup"})).json()
    await owner.post(f"/api/v1/deliveries/{drop['id']}/status", json={"status": "DELIVERED"})
    await owner.post(f"/api/v1/orders/{third['id']}/status", json={"status": "RETURNED", "reason": "Broken leg"})
    assert (await owner.get(f"/api/v1/deliveries/{drop['id']}")).json()["status"] == "RETURNED"

    # Cancelling an order closes its open delivery.
    other = await _order(owner, quantity="1")
    pending = (await owner.post(f"/api/v1/orders/{other['id']}/deliveries", json={"method": "own_staff"})).json()
    assert pending["status"] == "PENDING"
    await owner.post(f"/api/v1/orders/{other['id']}/status", json={"status": "CANCELLED", "reason": "Changed mind"})
    assert (await owner.get(f"/api/v1/deliveries/{pending['id']}")).json()["status"] == "CANCELLED"
    unconfirmed = await _order(owner, confirm=False)
    early = await owner.post(f"/api/v1/orders/{unconfirmed['id']}/deliveries", json={"method": "own_staff"})
    assert early.json()["detail"] == "Confirm the order first."


async def test_refunds_and_payment_rows_are_immutable(
    make_client: ClientFactory, platform_db: AsyncEngine, runtime_db: AsyncEngine
) -> None:
    owner, tenant_id = await _shop(make_client, platform_db)
    order = await _order(owner, quantity="1")  # 4,700
    oid = order["id"]
    paid = (
        await owner.post(f"/api/v1/orders/{oid}/payments", json={"amount": "4700", "method": "cash"}, headers=key())
    ).json()
    over = await owner.post(
        f"/api/v1/orders/{oid}/payments", json={"type": "refund", "amount": "5000", "method": "cash"}, headers=key()
    )
    assert over.json()["code"] == "invalid_payment"
    refund = await owner.post(
        f"/api/v1/orders/{oid}/payments", json={"type": "refund", "amount": "4700", "method": "cash"}, headers=key()
    )
    assert refund.status_code == 201
    assert (await owner.get(f"/api/v1/orders/{oid}")).json()["totals"]["payment_status"] == "REFUNDED"
    blocked = await owner.post(f"/api/v1/payments/{paid['id']}/void", json={"reason": "mistake"})
    assert blocked.json()["code"] == "refund_exists"

    replay_key = key()
    first = await owner.post(
        f"/api/v1/orders/{oid}/payments", json={"amount": "100", "method": "cash"}, headers=replay_key
    )
    replay = await owner.post(
        f"/api/v1/orders/{oid}/payments", json={"amount": "100", "method": "cash"}, headers=replay_key
    )
    assert first.json()["id"] == replay.json()["id"]

    async with runtime_db.connect() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})
        for statement in ("UPDATE payments SET amount = 1 WHERE id = :p", "DELETE FROM payments WHERE id = :p"):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with conn.begin_nested() if conn.in_transaction() else conn.begin():
                    await conn.execute(text(statement), {"p": paid["id"]})


async def test_deliveries_and_payments_are_isolated(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    owner_a, _ = await _shop(make_client, platform_db)
    owner_b, _ = await _shop(make_client, platform_db)
    order = await _order(owner_a)
    delivery = (await owner_a.post(f"/api/v1/orders/{order['id']}/deliveries", json={"method": "own_staff"})).json()
    payment = (
        await owner_a.post(
            f"/api/v1/orders/{order['id']}/payments", json={"amount": "10", "method": "cash"}, headers=key()
        )
    ).json()
    assert (await owner_b.get(f"/api/v1/deliveries/{delivery['id']}")).status_code == 404
    assert (await owner_b.post(f"/api/v1/payments/{payment['id']}/void", json={"reason": "steal"})).status_code == 404
    assert (await owner_b.get("/api/v1/payments")).json()["items"] == []
    assert (await owner_b.get("/api/v1/deliveries", params={"view": "all"})).json()["items"] == []
    _, rider_b = await _staff(make_client, owner_b, "DELIVERY")
    cross = await owner_a.patch(f"/api/v1/deliveries/{delivery['id']}", json={"assigned_to": rider_b})
    assert cross.json()["code"] == "invalid_delivery"  # someone from another business can't be assigned
