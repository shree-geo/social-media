"""Integration fixtures: a fresh ``<db>_test`` database, migrated to head.

Needs the dev PostgreSQL running (``docker compose ... up -d postgres``). Connection
details come from ``INTEGRATION_OWNER_URL`` and the role passwords in the environment;
defaults match ``.env.example`` and docker-compose.dev.yml.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
GRANTS_SQL = BACKEND_DIR.parent / "infra" / "postgres" / "init" / "02-database-grants.sql"

OWNER_URL = make_url(
    os.environ.get(
        "INTEGRATION_OWNER_URL", "postgresql+asyncpg://app_owner:change-me-owner@localhost:5442/socialcommerce"
    )
)
TEST_DB = f"{OWNER_URL.database}_test"


@dataclass(frozen=True)
class DatabaseUrls:
    owner: URL
    runtime: URL
    platform: URL


def _role_url(user: str, password_env: str, default_password: str) -> URL:
    return OWNER_URL.set(username=user, password=os.environ.get(password_env, default_password), database=TEST_DB)


async def _recreate_test_database() -> None:
    admin = create_async_engine(OWNER_URL.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": TEST_DB},
        )
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    owner = create_async_engine(OWNER_URL.set(database=TEST_DB), poolclass=NullPool)
    statements = [s.strip() for s in GRANTS_SQL.read_text().replace(':"DBNAME"', f'"{TEST_DB}"').split(";")]
    async with owner.begin() as conn:
        for statement in statements:
            lines = [line for line in statement.splitlines() if not line.strip().startswith("--")]
            if "".join(lines).strip():
                await conn.execute(text("\n".join(lines)))
    await owner.dispose()


@pytest.fixture(scope="session")
def database_urls() -> Iterator[DatabaseUrls]:
    try:
        asyncio.run(_recreate_test_database())
    except OSError as exc:  # connection refused etc.
        pytest.skip(f"PostgreSQL not reachable for integration tests: {exc}")

    owner = OWNER_URL.set(database=TEST_DB)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_MIGRATION_URL": owner.render_as_string(hide_password=False)},
        check=True,
    )
    yield DatabaseUrls(
        owner=owner,
        runtime=_role_url("app_runtime", "APP_RUNTIME_DB_PASSWORD", "change-me-runtime"),
        platform=_role_url("app_platform", "APP_PLATFORM_DB_PASSWORD", "change-me-platform"),
    )


@pytest_asyncio.fixture
async def platform_db(database_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_urls.platform, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def runtime_db(database_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    # pool_size=1 so consecutive transactions reuse one connection (proves SET LOCAL scoping).
    engine = create_async_engine(database_urls.runtime, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


# --- API fixtures -------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_env(database_urls: DatabaseUrls) -> Iterator[None]:
    """Point the application settings at the test database and seed reference data."""
    import app.core.database as database
    from app.core.config import get_settings
    from app.services.seed import seed_reference_data

    os.environ.update(
        APP_ENV="test",
        COOKIE_SECURE="false",
        DATABASE_URL=database_urls.runtime.render_as_string(hide_password=False),
        DATABASE_PLATFORM_URL=database_urls.platform.render_as_string(hide_password=False),
    )
    get_settings.cache_clear()
    database._runtime_engine = database._platform_engine = None

    async def _seed() -> None:
        async with database.platform_sessionmaker()() as session, session.begin():
            await seed_reference_data(session)
        await database.dispose_engines()

    asyncio.run(_seed())
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def make_client(api_env: None) -> AsyncIterator[Callable[[], Awaitable[httpx.AsyncClient]]]:
    """Factory for independent browser-like clients (own cookie jar + CSRF header)."""
    from app.core.database import dispose_engines
    from app.main import create_app

    app = create_app()
    clients: list[httpx.AsyncClient] = []

    async def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        token = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()
    await dispose_engines()
