"""Shared integration helpers: platform admin, packages, tenants and logged-in owners."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from app.core.security import hash_password

ClientFactory = Callable[[], Awaitable[httpx.AsyncClient]]
ADMIN_PASSWORD = "platform admin passphrase"


async def _platform_admin(platform_db: AsyncEngine) -> str:
    email = f"admin-{new_id().hex[-12:]}@example.com"
    async with platform_db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO platform_users (id, email, password_hash, full_name, role, must_change_password) "
                "VALUES (:id, :email, :hash, 'Admin', 'PLATFORM_ADMIN', false)"
            ),
            {"id": new_id(), "email": email, "hash": hash_password(ADMIN_PASSWORD)},
        )
    return email


async def _super_admin_plan(platform_db: AsyncEngine, max_users: int | None = None) -> uuid.UUID:
    plan_id = new_id()
    async with platform_db.begin() as conn:
        await conn.execute(
            text("INSERT INTO plans (id, code, name) VALUES (:id, :code, 'Business')"),
            {"id": plan_id, "code": f"PLAN_T{plan_id.hex[-10:].upper()}"},
        )
        await conn.execute(
            text("INSERT INTO plan_prices (id, plan_id, billing_cycle, amount) VALUES (:id, :p, 'yearly', 24000)"),
            {"id": new_id(), "p": plan_id},
        )
        if max_users is not None:
            await conn.execute(
                text(
                    "INSERT INTO plan_features (id, plan_id, feature_key, limit_value) VALUES (:id, :p, 'max_users', :n)"
                ),
                {"id": new_id(), "p": plan_id, "n": max_users},
            )
    return plan_id


async def _admin_client(make_client: ClientFactory, platform_db: AsyncEngine) -> httpx.AsyncClient:
    client = await make_client()
    email = await _platform_admin(platform_db)
    response = await client.post("/api/v1/platform/auth/login", json={"email": email, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return client


async def _create_tenant(
    admin: httpx.AsyncClient, plan_id: uuid.UUID, *, start: date | None = None, payment: bool = True
) -> dict[str, object]:
    owner_email = f"owner-{new_id().hex[-12:]}@example.com"
    body: dict[str, object] = {
        "business_name": "Sharma Furniture",
        "phone": "+9779800000000",
        "plan_id": str(plan_id),
        "billing_cycle": "yearly",
        "start_date": (start or date.today()).isoformat(),
        "owner_full_name": "Ram Sharma",
        "owner_email": owner_email,
    }
    if payment:
        body["initial_payment"] = {
            "amount": "24000.00",
            "payment_method": "esewa",
            "paid_at": datetime.now(UTC).isoformat(),
            "transaction_reference": "ESW-123",
        }
    response = await admin.post("/api/v1/platform/tenants", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    data["owner_email"] = owner_email
    return data


async def _owner_session(make_client: ClientFactory, created: dict[str, object]) -> httpx.AsyncClient:
    owner = await make_client()
    login = created["owner_login"]
    assert isinstance(login, dict)
    response = await owner.post(
        "/api/v1/auth/login", json={"email": created["owner_email"], "password": login["temporary_password"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is True
    response = await owner.post(
        "/api/v1/auth/change-password",
        json={"current_password": login["temporary_password"], "new_password": "my own strong passphrase"},
    )
    assert response.status_code == 200, response.text
    return owner
