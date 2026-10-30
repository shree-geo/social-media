"""Operational commands: ``python -m app.cli seed``, ``demo-inbox``, ``connect-whatsapp``."""

import argparse
import asyncio
import getpass
import os
import sys

from app.core.config import get_settings
from app.core.database import dispose_engines, platform_sessionmaker
from app.services.seed import run_seed


async def _seed() -> int:
    settings = get_settings()
    async with platform_sessionmaker()() as session, session.begin():
        result = await run_seed(session, settings.bootstrap_admin_email)
    await dispose_engines()
    print(f"Seeded {result.permissions} permissions and {result.roles} system roles.")
    if result.bootstrap_admin_temp_password:
        # Printed exactly once; the stored value is only a hash.
        print("Bootstrap platform admin created:")
        print(f"  email:              {result.bootstrap_admin_email}")
        print(f"  temporary password: {result.bootstrap_admin_temp_password}")
        print("  It expires in 7 days and must be changed at first login.")
    return 0


_DEMO_MESSAGES = (
    ("9779812345678", "Ram Sharma", "Namaste! Office chair ko price kati ho?", 50),
    ("9779812345678", "Ram Sharma", "20 ota chahiyo, Itahari ma delivery hunchha?", 48),
    ("9779801111111", "Sita Rai", "Do you have 4 feet tables in black?", 30),
    ("9779846666666", "Hari Thapa", "Payment eSewa bata garna milchha?", 5),
)


async def _demo_inbox(owner_email: str) -> int:
    """Development only: feed sample customer messages through the real ingestion pipeline."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.ids import new_id
    from app.integrations.base import InboundMessage
    from app.models import ChannelAccount, ChannelConnection, TenantMembership, User
    from app.services import ingestion

    settings = get_settings()
    if settings.app_env != "development":
        print("demo-inbox only runs with APP_ENV=development.", file=sys.stderr)
        return 2

    async with platform_sessionmaker()() as session, session.begin():
        tenant_id = (
            await session.execute(
                select(TenantMembership.tenant_id)
                .join(User, User.id == TenantMembership.user_id)
                .where(User.email == owner_email)
                .limit(1)
            )
        ).scalar_one_or_none()
        if tenant_id is None:
            print(f"No tenant found for {owner_email}.", file=sys.stderr)
            return 1
        external_id = f"demo-{tenant_id.hex[:12]}"
        exists = (
            await session.execute(select(ChannelAccount.id).where(ChannelAccount.external_account_id == external_id))
        ).first()
        if not exists:
            connection = ChannelConnection(tenant_id=tenant_id, provider="whatsapp", status="connected")
            session.add(connection)
            await session.flush()
            session.add(
                ChannelAccount(
                    tenant_id=tenant_id,
                    connection_id=connection.id,
                    provider="whatsapp",
                    external_account_id=external_id,
                    display_name="Demo WhatsApp (no real number)",
                    display_phone="+977 98XXXXXXXX",
                )
            )

    now = datetime.now(UTC)
    for user_id, name, body, minutes_ago in _DEMO_MESSAGES:
        await ingestion._process_one(
            "whatsapp",
            InboundMessage(
                channel_external_id=external_id,
                provider_user_id=user_id,
                provider_message_id=f"demo.{new_id().hex}",
                timestamp=now - timedelta(minutes=minutes_ago),
                message_type="text",
                text=body,
                profile_name=name,
                phone=user_id,
            ),
        )
    await dispose_engines()
    print(f"Added {len(_DEMO_MESSAGES)} demo messages to the inbox of {owner_email}'s business.")
    print("Replies will show 'Not sent': the demo channel has no real WhatsApp connection (Phase 3).")
    return 0


async def _connect_whatsapp(owner_email: str, waba_id: str, phone_number_id: str, token: str) -> int:
    """Connect a number that is already on the Cloud API (e.g. Meta's test number) to the owner's business."""
    from datetime import date

    from sqlalchemy import select

    from app.core.database import runtime_sessionmaker, set_tenant_context
    from app.models import TenantMembership, User
    from app.services import channels, subscriptions

    if not get_settings().meta_configured:
        print("Set the META_* values in .env first (see docs/DEVELOPMENT.md).", file=sys.stderr)
        return 2
    async with platform_sessionmaker()() as session:
        row = (
            await session.execute(
                select(TenantMembership.tenant_id, User.id)
                .join(User, User.id == TenantMembership.user_id)
                .where(User.email == owner_email)
                .limit(1)
            )
        ).first()
    if row is None:
        print(f"No business found for {owner_email}.", file=sys.stderr)
        await dispose_engines()
        return 1
    tenant_id, user_id = row
    try:
        async with runtime_sessionmaker()() as session, session.begin():
            await set_tenant_context(session, tenant_id)
            state = await subscriptions.current_state(session, tenant_id, date.today())
            connected = await channels.connect_whatsapp_with_token(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                token=token,
                plan_id=state.plan_id,
            )
    except channels.ChannelSetupError as exc:
        print(f"Not connected ({exc.code}): {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await dispose_engines()
    print(f"Connected WhatsApp {connected.display_phone} ({connected.display_name}) to {owner_email}'s business.")
    print("Messages to this number now arrive in its inbox; replies go out through the Cloud API.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Seed permissions, system roles and the bootstrap platform admin")
    demo = sub.add_parser("demo-inbox", help="(development) add sample conversations for a tenant owner")
    demo.add_argument("owner_email")
    wa = sub.add_parser(
        "connect-whatsapp",
        help="connect a number already on the Cloud API (e.g. Meta's test number) with a system-user token",
        description="The token is read from WHATSAPP_ACCESS_TOKEN, or asked for, so it stays out of shell history.",
    )
    wa.add_argument("owner_email")
    wa.add_argument("--waba-id", required=True, help="WhatsApp Business Account ID (WhatsApp → API Setup)")
    wa.add_argument("--phone-number-id", required=True, help="Phone number ID (WhatsApp → API Setup)")
    args = parser.parse_args(argv)
    if args.command == "seed":
        return asyncio.run(_seed())
    if args.command == "demo-inbox":
        return asyncio.run(_demo_inbox(args.owner_email))
    if args.command == "connect-whatsapp":
        token = os.environ.get("WHATSAPP_ACCESS_TOKEN") or getpass.getpass("System user access token: ")
        if not token.strip():
            print("An access token is required.", file=sys.stderr)
            return 2
        return asyncio.run(_connect_whatsapp(args.owner_email, args.waba_id, args.phone_number_id, token.strip()))
    return 1


if __name__ == "__main__":
    sys.exit(main())
