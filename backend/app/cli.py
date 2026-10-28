"""Operational commands: ``python -m app.cli seed``."""

import argparse
import asyncio
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Seed permissions, system roles and the bootstrap platform admin")
    args = parser.parse_args(argv)
    if args.command == "seed":
        return asyncio.run(_seed())
    return 1


if __name__ == "__main__":
    sys.exit(main())
