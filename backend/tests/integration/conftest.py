"""Integration fixtures: a fresh ``<db>_test`` database, migrated to head.

Needs the dev PostgreSQL running (``docker compose ... up -d postgres``). Connection
details come from ``INTEGRATION_OWNER_URL`` and the role passwords in the environment;
defaults match ``.env.example`` and docker-compose.dev.yml.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from tests.fakes import FakeAdapter

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
        # This project's dev Redis (docker-compose.dev.yml), not whatever runs on 6379.
        REDIS_URL=os.environ.get("INTEGRATION_REDIS_URL", "redis://localhost:6381/15"),
        # This project's dev S3 (SeaweedFS), separate bucket for tests.
        S3_ENDPOINT=os.environ.get("INTEGRATION_S3_ENDPOINT", "http://localhost:8343"),
        S3_ACCESS_KEY=os.environ.get("INTEGRATION_S3_ACCESS_KEY", "local-access-key"),
        S3_SECRET_KEY=os.environ.get("INTEGRATION_S3_SECRET_KEY", "local-secret-key-change-me"),
        S3_BUCKET="socialcommerce-test",
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


# --- inbox fixtures -----------------------------------------------------------------


@dataclass
class Jobs:
    """Captures enqueued background jobs so tests run them explicitly and deterministically."""

    queued: list[tuple[str, dict[str, object], float | None]]

    async def run_all(self) -> list[str]:
        from app.services import channels, ingestion, messaging

        results: list[str] = []
        while self.queued:
            name, kwargs, _ = self.queued.pop(0)
            if name == "webhooks.process_event":
                results.append(await ingestion.process(uuid.UUID(str(kwargs["event_id"]))))
            elif name == "messages.send":
                results.append(
                    await messaging.send(uuid.UUID(str(kwargs["tenant_id"])), uuid.UUID(str(kwargs["message_id"])))
                )
            elif name == "customers.fetch_profile":
                found = await channels.fetch_profile(
                    uuid.UUID(str(kwargs["tenant_id"])),
                    uuid.UUID(str(kwargs["channel_account_id"])),
                    str(kwargs["provider_user_id"]),
                )
                results.append("profile" if found else "no_profile")
            else:
                raise AssertionError(f"test harness does not know how to run job {name!r}")
        return results


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> Jobs:
    from app.workers import queue

    captured = Jobs(queued=[])

    async def capture(name: str, kwargs: dict[str, object], countdown: float | None) -> None:
        captured.queued.append((name, kwargs, countdown))

    monkeypatch.setattr(queue, "dispatcher", capture)
    return captured


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> Iterator["FakeAdapter"]:
    from app.integrations import registry
    from app.services import realtime
    from tests.fakes import FakeAdapter

    async def no_publish(*_: object, **__: object) -> None:
        return None

    # Real-time fan-out is covered separately; keep inbox tests independent of Redis.
    monkeypatch.setattr(realtime, "publish", no_publish)
    adapter = FakeAdapter()
    registry.register(adapter)
    yield adapter
    registry.unregister(adapter.provider)


@dataclass(frozen=True)
class ConnectedChannel:
    tenant_id: uuid.UUID
    account_id: uuid.UUID
    external_id: str


async def connect_channel(
    platform_db: AsyncEngine, tenant_id: uuid.UUID, token: str = "test-access-token"
) -> ConnectedChannel:
    """Insert a connected WhatsApp-like account with an encrypted token (what Phase 3's wizard will do)."""
    from app.core.crypto import encrypt
    from app.core.ids import new_id
    from app.services.messaging import credential_aad

    connection_id, account_id, credential_id = new_id(), new_id(), new_id()
    external_id = f"pn-{account_id.hex[-12:]}"
    blob = encrypt(token.encode(), credential_aad(tenant_id, credential_id))
    async with platform_db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO channel_connections (id, tenant_id, provider, status) "
                "VALUES (:id, :t, 'whatsapp', 'connected')"
            ),
            {"id": connection_id, "t": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO channel_accounts (id, tenant_id, connection_id, provider, external_account_id, display_name) "
                "VALUES (:id, :t, :c, 'whatsapp', :e, 'Sharma Furniture')"
            ),
            {"id": account_id, "t": tenant_id, "c": connection_id, "e": external_id},
        )
        await conn.execute(
            text(
                "INSERT INTO channel_credentials (id, tenant_id, connection_id, credential_type, ciphertext, nonce, key_version) "
                "VALUES (:id, :t, :c, 'system_user_token', :ct, :n, :v)"
            ),
            {
                "id": credential_id,
                "t": tenant_id,
                "c": connection_id,
                "ct": blob.ciphertext,
                "n": blob.nonce,
                "v": blob.key_version,
            },
        )
    return ConnectedChannel(tenant_id, account_id, external_id)
