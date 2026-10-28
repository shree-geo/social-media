"""Database-level tenant isolation (ARCHITECTURE.md §6 layer 3, DATABASE.md §3).

Two tenants are created through the platform role; every test then acts as the
runtime role and proves it cannot see or touch the other tenant's rows.
"""

import uuid
from dataclasses import dataclass
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.ids import new_id

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SeededTenant:
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    subscription_id: uuid.UUID


async def _seed_tenant(conn: AsyncConnection, name: str, plan_id: uuid.UUID, price_id: uuid.UUID) -> SeededTenant:
    tenant_id, user_id, membership_id, subscription_id = new_id(), new_id(), new_id(), new_id()
    await conn.execute(
        text("INSERT INTO tenants (id, business_name, slug) VALUES (:id, :name, :slug)"),
        {"id": tenant_id, "name": name, "slug": f"{name.lower()}-{tenant_id.hex[-12:]}"},
    )
    await conn.execute(
        text("INSERT INTO users (id, email, password_hash, full_name) VALUES (:id, :email, 'x', :name)"),
        {"id": user_id, "email": f"{tenant_id.hex}@example.com", "name": f"{name} owner"},
    )
    await conn.execute(
        text("INSERT INTO tenant_memberships (id, tenant_id, user_id) VALUES (:id, :tenant, :user)"),
        {"id": membership_id, "tenant": tenant_id, "user": user_id},
    )
    await conn.execute(
        text(
            "INSERT INTO notifications (id, tenant_id, user_id, type, title) "
            "VALUES (:id, :tenant, :user, 'test', :title)"
        ),
        {"id": new_id(), "tenant": tenant_id, "user": user_id, "title": f"hello {name}"},
    )
    await conn.execute(
        text(
            "INSERT INTO subscriptions (id, tenant_id, plan_id, plan_price_id, price_amount, currency, "
            "billing_cycle, status, start_date, expiry_date) VALUES "
            "(:id, :tenant, :plan, :price, 1000, 'NPR', 'yearly', 'ACTIVE', :start, :expiry)"
        ),
        {
            "id": subscription_id,
            "tenant": tenant_id,
            "plan": plan_id,
            "price": price_id,
            "start": date(2026, 1, 1),
            "expiry": date(2026, 12, 31),
        },
    )
    await conn.execute(
        text("INSERT INTO audit_logs (id, tenant_id, actor_type, action) VALUES (:id, :tenant, 'system', 'TEST')"),
        {"id": new_id(), "tenant": tenant_id},
    )
    return SeededTenant(tenant_id, membership_id, subscription_id)


@pytest_asyncio.fixture
async def tenants(platform_db: AsyncEngine) -> tuple[SeededTenant, SeededTenant]:
    plan_id, price_id = new_id(), new_id()
    async with platform_db.begin() as conn:
        await conn.execute(
            text("INSERT INTO plans (id, code, name) VALUES (:id, :code, 'Test')"),
            {"id": plan_id, "code": f"PLAN_{plan_id.hex[-12:]}"},
        )
        await conn.execute(
            text("INSERT INTO plan_prices (id, plan_id, billing_cycle, amount) VALUES (:id, :plan, 'yearly', 1000)"),
            {"id": price_id, "plan": plan_id},
        )
        a = await _seed_tenant(conn, "Alpha", plan_id, price_id)
        b = await _seed_tenant(conn, "Beta", plan_id, price_id)
    return a, b


async def _as_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(text(sql), params)).scalar_one()


TENANT_TABLES = ("tenant_memberships", "notifications", "subscriptions", "audit_logs")


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_no_tenant_context_sees_nothing(runtime_db: AsyncEngine, tenants: object, table: str) -> None:
    async with runtime_db.begin() as conn:
        assert await _scalar(conn, f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_tenant_sees_only_own_rows(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant], table: str
) -> None:
    a, b = tenants
    async with runtime_db.begin() as conn:
        await _as_tenant(conn, a.tenant_id)
        assert await _scalar(conn, f"SELECT count(*) FROM {table} WHERE tenant_id = :b", b=b.tenant_id) == 0
        assert await _scalar(conn, f"SELECT count(*) FROM {table} WHERE tenant_id = :a", a=a.tenant_id) >= 1


async def test_tenants_table_shows_only_own_tenant(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, _ = tenants
    async with runtime_db.begin() as conn:
        await _as_tenant(conn, a.tenant_id)
        ids = (await conn.execute(text("SELECT id FROM tenants"))).scalars().all()
    assert ids == [a.tenant_id]


async def test_cannot_insert_row_for_other_tenant(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = tenants
    with pytest.raises(DBAPIError, match="row-level security"):
        async with runtime_db.begin() as conn:
            await _as_tenant(conn, a.tenant_id)
            await conn.execute(
                text(
                    "INSERT INTO usage_records (id, tenant_id, metric, period_start, period_end) "
                    "VALUES (:id, :b, 'orders', '2026-01-01', '2026-01-31')"
                ),
                {"id": new_id(), "b": b.tenant_id},
            )


async def test_cannot_update_or_delete_other_tenant_rows(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = tenants
    async with runtime_db.begin() as conn:
        await _as_tenant(conn, a.tenant_id)
        updated = await conn.execute(
            text("UPDATE notifications SET title = 'hacked' WHERE tenant_id = :b"), {"b": b.tenant_id}
        )
        deleted = await conn.execute(text("DELETE FROM tenant_memberships WHERE id = :m"), {"m": b.membership_id})
    assert updated.rowcount == 0
    assert deleted.rowcount == 0


async def test_tenant_context_does_not_leak_between_transactions(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, _ = tenants
    async with runtime_db.connect() as conn:
        async with conn.begin():
            await _as_tenant(conn, a.tenant_id)
            assert await _scalar(conn, "SELECT count(*) FROM notifications") >= 1
        async with conn.begin():  # same connection, new transaction
            assert await _scalar(conn, "SELECT app_current_tenant()") is None
            assert await _scalar(conn, "SELECT count(*) FROM notifications") == 0


async def test_subscriptions_are_read_only_for_tenants(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, _ = tenants
    with pytest.raises(DBAPIError, match="permission denied"):
        async with runtime_db.begin() as conn:
            await _as_tenant(conn, a.tenant_id)
            await conn.execute(
                text("UPDATE subscriptions SET expiry_date = '2099-12-31' WHERE id = :s"), {"s": a.subscription_id}
            )


async def test_tenant_can_edit_business_details_but_not_status(
    runtime_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    a, _ = tenants
    async with runtime_db.begin() as conn:
        await _as_tenant(conn, a.tenant_id)
        result = await conn.execute(
            text("UPDATE tenants SET business_name = 'Alpha Traders' WHERE id = :a"), {"a": a.tenant_id}
        )
        assert result.rowcount == 1
    with pytest.raises(DBAPIError, match="permission denied"):
        async with runtime_db.begin() as conn:
            await _as_tenant(conn, a.tenant_id)
            await conn.execute(text("UPDATE tenants SET status = 'closed' WHERE id = :a"), {"a": a.tenant_id})


@pytest.mark.parametrize("statement", ["UPDATE audit_logs SET action = 'X'", "DELETE FROM audit_logs"])
@pytest.mark.parametrize("role", ["runtime", "platform"])
async def test_audit_log_is_append_only(
    runtime_db: AsyncEngine,
    platform_db: AsyncEngine,
    tenants: tuple[SeededTenant, SeededTenant],
    statement: str,
    role: str,
) -> None:
    engine = runtime_db if role == "runtime" else platform_db
    a, _ = tenants
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine.begin() as conn:
            await _as_tenant(conn, a.tenant_id)
            await conn.execute(text(statement))


async def test_runtime_role_cannot_read_platform_users(runtime_db: AsyncEngine) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with runtime_db.begin() as conn:
            await conn.execute(text("SELECT count(*) FROM platform_users"))


async def test_composite_fk_blocks_cross_tenant_reference(
    platform_db: AsyncEngine, tenants: tuple[SeededTenant, SeededTenant]
) -> None:
    """Even the RLS-bypassing role cannot link tenant B's row to tenant A's membership."""
    a, b = tenants
    with pytest.raises(IntegrityError, match="foreign key"):
        async with platform_db.begin() as conn:
            role_id = await _scalar(
                conn,
                "INSERT INTO roles (id, code, name, is_system) VALUES (:id, :code, 'Test', true) RETURNING id",
                id=new_id(),
                code=f"TEST_{new_id().hex[-12:]}",
            )
            await conn.execute(
                text("INSERT INTO membership_roles (membership_id, role_id, tenant_id) VALUES (:m, :r, :b)"),
                {"m": a.membership_id, "r": role_id, "b": b.tenant_id},
            )
