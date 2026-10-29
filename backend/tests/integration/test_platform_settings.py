"""Super admin edits the support contact; the public website reads it without logging in."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import ClientFactory, _admin_client

pytestmark = pytest.mark.integration


async def test_super_admin_sets_support_contact_shown_publicly(
    make_client: ClientFactory, platform_db: AsyncEngine, runtime_db: AsyncEngine
) -> None:
    admin = await _admin_client(make_client, platform_db)
    body = {"support_phone": "+977 9851234567", "support_email": "help@myleadtoday.cloud"}

    # A plain platform admin can read but not change it.
    assert (await admin.get("/api/v1/platform/settings")).status_code == 200
    assert (await admin.patch("/api/v1/platform/settings", json=body)).status_code == 403

    async with platform_db.begin() as conn:
        await conn.execute(
            text("UPDATE platform_users SET role = 'PLATFORM_SUPER_ADMIN' WHERE role = 'PLATFORM_ADMIN'")
        )
    response = await admin.patch("/api/v1/platform/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == body

    bad = await admin.patch("/api/v1/platform/settings", json={"support_phone": "call me", "support_email": None})
    assert bad.status_code == 422

    public = await (await make_client()).get("/api/v1/public/site")
    assert public.status_code == 200
    assert public.json() == body
    assert public.headers["cache-control"] == "no-cache"

    async with platform_db.connect() as conn:
        action = (
            await conn.execute(
                text(
                    "SELECT action FROM audit_logs WHERE resource_type = 'platform_settings' ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).scalar_one()
    assert action == "PLATFORM_SETTINGS_UPDATED"

    # Business (tenant) sessions can read the row but never change it.
    async with runtime_db.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("UPDATE platform_settings SET support_phone = NULL"))
