"""End-to-end API flow from ONBOARDING_AND_CHANNEL_SETUP.md §3 and §13 (acceptance 1-2, 12).

Platform admin creates a package and a tenant → Owner logs in with the temporary
password → must change it → can then use the app and add staff.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.integration.helpers import (
    ClientFactory,
    _admin_client,
    _create_tenant,
    _owner_session,
    _super_admin_plan,
)

pytestmark = pytest.mark.integration


async def test_admin_creates_tenant_with_subscription_and_owner_login(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    plan_id = await _super_admin_plan(platform_db)
    created = await _create_tenant(admin, plan_id)

    sub = created["subscription"]
    assert isinstance(sub, dict)
    assert sub["status"] == "ACTIVE"
    assert sub["expiry_date"] == (date.today().replace(year=date.today().year + 1) - timedelta(days=1)).isoformat()
    assert str(created["receipt_number"]).startswith(f"SUB-{date.today().year}-")

    login = created["owner_login"]
    assert isinstance(login, dict)
    assert len(login["temporary_password"]) == 14
    assert login["temporary_password"] in login["share_message"]
    assert "अस्थायी पासवर्ड" in login["share_message"]

    # The temporary password is stored only as a hash.
    async with platform_db.connect() as conn:
        stored = (
            await conn.execute(text("SELECT password_hash FROM users WHERE email = :e"), {"e": created["owner_email"]})
        ).scalar_one()
    assert stored.startswith("$argon2id$") and login["temporary_password"] not in stored


async def test_owner_must_change_temporary_password_before_anything_else(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    login = created["owner_login"]
    assert isinstance(login, dict)

    owner = await make_client()
    response = await owner.post(
        "/api/v1/auth/login", json={"email": created["owner_email"], "password": login["temporary_password"]}
    )
    assert response.json()["must_change_password"] is True

    # Allowed: me. Blocked: everything else.
    assert (await owner.get("/api/v1/auth/me")).status_code == 200
    blocked = await owner.get("/api/v1/users")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "password_change_required"

    weak = await owner.post(
        "/api/v1/auth/change-password",
        json={"current_password": login["temporary_password"], "new_password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["code"] == "password_rejected"

    changed = await owner.post(
        "/api/v1/auth/change-password",
        json={"current_password": login["temporary_password"], "new_password": "my own strong passphrase"},
    )
    assert changed.status_code == 200

    me = (await owner.get("/api/v1/auth/me")).json()
    assert me["must_change_password"] is False
    assert me["roles"] == ["OWNER"]
    assert "user.manage" in me["permissions"]
    assert me["subscription"]["status"] == "ACTIVE"
    assert (await owner.get("/api/v1/users")).status_code == 200

    # The temporary password no longer works.
    other = await make_client()
    old = await other.post(
        "/api/v1/auth/login", json={"email": created["owner_email"], "password": login["temporary_password"]}
    )
    assert old.status_code == 401


async def test_owner_adds_staff_with_temporary_password_and_plan_limit(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db, max_users=2))
    owner = await _owner_session(make_client, created)

    staff = await owner.post(
        "/api/v1/users",
        json={"full_name": "Sita", "email": f"sita-{new_id().hex[-12:]}@example.com", "role": "SALES"},
    )
    assert staff.status_code == 201, staff.text
    assert staff.json()["temporary_password"]

    over_limit = await owner.post(
        "/api/v1/users",
        json={"full_name": "Hari", "email": f"hari-{new_id().hex[-12:]}@example.com", "role": "SALES"},
    )
    assert over_limit.status_code == 403
    assert over_limit.json()["code"] == "plan_limit_exceeded"

    # SALES staff cannot manage users.
    sales = await make_client()
    await sales.post(
        "/api/v1/auth/login",
        json={"email": staff.json()["email"], "password": staff.json()["temporary_password"]},
    )
    await sales.post(
        "/api/v1/auth/change-password",
        json={"current_password": staff.json()["temporary_password"], "new_password": "sales person passphrase"},
    )
    me = (await sales.get("/api/v1/auth/me")).json()
    assert me["roles"] == ["SALES"]
    assert (await sales.get("/api/v1/users")).status_code == 403


async def test_users_list_is_isolated_between_tenants(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    admin = await _admin_client(make_client, platform_db)
    plan_id = await _super_admin_plan(platform_db)
    owner_a = await _owner_session(make_client, await _create_tenant(admin, plan_id))
    created_b = await _create_tenant(admin, plan_id)

    emails = {u["email"] for u in (await owner_a.get("/api/v1/users")).json()}
    assert created_b["owner_email"] not in emails
    assert len(emails) == 1


async def test_reset_login_invalidates_old_password_and_sessions(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    owner = await _owner_session(make_client, created)
    assert (await owner.get("/api/v1/users")).status_code == 200

    reset = await admin.post(f"/api/v1/platform/tenants/{created['tenant_id']}/owner/reset-login")
    assert reset.status_code == 200
    new_temp = reset.json()["temporary_password"]

    # Refresh of the old session fails; the old password fails; the new temp password works.
    assert (await owner.post("/api/v1/auth/refresh")).status_code == 401
    fresh = await make_client()
    old = await fresh.post(
        "/api/v1/auth/login", json={"email": created["owner_email"], "password": "my own strong passphrase"}
    )
    assert old.status_code == 401
    new = await fresh.post("/api/v1/auth/login", json={"email": created["owner_email"], "password": new_temp})
    assert new.status_code == 200 and new.json()["must_change_password"] is True


async def test_refresh_rotation_and_reuse_detection(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    admin = await _admin_client(make_client, platform_db)
    owner = await _owner_session(make_client, await _create_tenant(admin, await _super_admin_plan(platform_db)))

    stolen = owner.cookies.get("sc_rt", path="/api/v1/auth")
    assert (await owner.post("/api/v1/auth/refresh")).status_code == 200  # rotates

    attacker = await make_client()
    attacker.cookies.set("sc_rt", stolen, domain="testserver.local", path="/api/v1/auth")
    replay = await attacker.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    # Reuse revoked the whole session: the legitimate client's new token is dead too.
    assert (await owner.post("/api/v1/auth/refresh")).status_code == 401


async def test_lockout_after_repeated_failures(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    client = await make_client()
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": created["owner_email"], "password": "wrong"})).json()[
            "code"
        ]
        for _ in range(5)
    ]
    assert codes[:4] == ["invalid_credentials"] * 4
    assert codes[4] == "account_locked"
    login = created["owner_login"]
    assert isinstance(login, dict)
    still_locked = await client.post(
        "/api/v1/auth/login", json={"email": created["owner_email"], "password": login["temporary_password"]}
    )
    assert still_locked.json()["code"] == "account_locked"


async def test_expired_subscription_is_read_only_and_renewal_restores(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    # Started 2 years ago, 1-year cycle, 7-day grace → expired now.
    created = await _create_tenant(
        admin, await _super_admin_plan(platform_db), start=date.today() - timedelta(days=730), payment=False
    )
    owner = await _owner_session(make_client, created)

    me = (await owner.get("/api/v1/auth/me")).json()
    assert me["subscription"]["status"] == "EXPIRED"
    assert me["subscription"]["access"] == "read_only"
    assert (await owner.get("/api/v1/users")).status_code == 200  # reading still works
    blocked = await owner.post(
        "/api/v1/users", json={"full_name": "X", "email": f"x-{new_id().hex[-12:]}@example.com", "role": "VIEWER"}
    )
    assert blocked.json()["code"] == "subscription_read_only"

    sub = created["subscription"]
    assert isinstance(sub, dict)
    renewal = await admin.post(
        f"/api/v1/platform/subscriptions/{sub['id']}/payments",
        json={"amount": "24000", "payment_method": "bank_transfer", "paid_at": datetime.now(UTC).isoformat()},
    )
    assert renewal.status_code == 201, renewal.text
    assert renewal.json()["subscription"]["status"] == "ACTIVE"
    assert renewal.json()["subscription"]["start_date"] == sub["start_date"]
    assert (await owner.get("/api/v1/auth/me")).json()["subscription"]["status"] == "ACTIVE"


async def test_csrf_required_for_state_changes(make_client: ClientFactory) -> None:
    client = await make_client()
    del client.headers["X-CSRF-Token"]
    response = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


async def test_tenant_session_cannot_use_platform_api(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    admin = await _admin_client(make_client, platform_db)
    owner = await _owner_session(make_client, await _create_tenant(admin, await _super_admin_plan(platform_db)))
    assert (await owner.get("/api/v1/platform/tenants")).status_code == 401


async def test_actions_are_audited(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    await _owner_session(make_client, created)
    async with platform_db.connect() as conn:
        actions = set(
            (
                await conn.execute(
                    text("SELECT action FROM audit_logs WHERE tenant_id = :t"), {"t": created["tenant_id"]}
                )
            )
            .scalars()
            .all()
        )
    assert {
        "TENANT_CREATED",
        "USER_CREATED",
        "MEMBERSHIP_CREATED",
        "SUBSCRIPTION_PAYMENT_RECORDED",
        "LOGIN",
        "PASSWORD_CHANGED",
    } <= actions


async def test_suspend_blocks_tenant_and_reactivate_restores(
    make_client: ClientFactory, platform_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(admin, await _super_admin_plan(platform_db))
    owner = await _owner_session(make_client, created)
    sub = created["subscription"]
    assert isinstance(sub, dict)

    suspended = await admin.post(
        f"/api/v1/platform/subscriptions/{sub['id']}/status", json={"action": "suspend", "reason": "non-payment"}
    )
    assert suspended.json()["status"] == "SUSPENDED"
    blocked = await owner.get("/api/v1/users")
    assert blocked.status_code == 403 and blocked.json()["code"] == "subscription_blocked"
    # The Owner can still see why (me works) to show the "contact us" page.
    assert (await owner.get("/api/v1/auth/me")).json()["subscription"]["access"] == "blocked"

    again = await admin.post(f"/api/v1/platform/subscriptions/{sub['id']}/status", json={"action": "suspend"})
    assert again.status_code == 409

    reactivated = await admin.post(f"/api/v1/platform/subscriptions/{sub['id']}/status", json={"action": "reactivate"})
    assert reactivated.json()["status"] == "ACTIVE"
    assert (await owner.get("/api/v1/users")).status_code == 200


async def test_daily_job_persists_time_based_transitions(make_client: ClientFactory, platform_db: AsyncEngine) -> None:
    from app.core.database import platform_sessionmaker
    from app.services.onboarding import recompute_statuses

    admin = await _admin_client(make_client, platform_db)
    created = await _create_tenant(
        admin, await _super_admin_plan(platform_db), start=date.today() - timedelta(days=370), payment=False
    )
    sub = created["subscription"]
    assert isinstance(sub, dict)
    # Created already past expiry but inside grace; force the stored status back to ACTIVE.
    async with platform_db.begin() as conn:
        await conn.execute(text("UPDATE subscriptions SET status = 'ACTIVE' WHERE id = :s"), {"s": sub["id"]})

    async with platform_sessionmaker()() as session, session.begin():
        changed = await recompute_statuses(session, now=datetime.now(UTC) + timedelta(days=30))
    assert changed >= 1
    async with platform_db.connect() as conn:
        status = (await conn.execute(text("SELECT status FROM subscriptions WHERE id = :s"), {"s": sub["id"]})).scalar()
        events = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM subscription_history WHERE subscription_id = :s AND event_type = 'status_changed'"
                ),
                {"s": sub["id"]},
            )
        ).scalar()
    assert status == "EXPIRED"
    assert events == 1
