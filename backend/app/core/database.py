"""Database engines and sessions.

Two engines, matching the PostgreSQL roles in ARCHITECTURE.md §6:

* runtime  (``app_runtime``)  — RLS enforced. Every tenant transaction must call
  :func:`set_tenant_context` first; without it RLS policies match no rows.
* platform (``app_platform``) — bypasses RLS. Only for platform admin routes and
  system jobs; never reachable from tenant routes.
"""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_runtime_engine: AsyncEngine | None = None
_platform_engine: AsyncEngine | None = None


def _make_engine(url: str) -> AsyncEngine:
    settings = get_settings()
    if settings.app_env == "test":
        # Tests run each case on its own event loop; pooled asyncpg connections can't cross loops.
        return create_async_engine(url, poolclass=NullPool)
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


def runtime_engine() -> AsyncEngine:
    global _runtime_engine
    if _runtime_engine is None:
        _runtime_engine = _make_engine(str(get_settings().database_url))
    return _runtime_engine


def platform_engine() -> AsyncEngine:
    global _platform_engine
    if _platform_engine is None:
        _platform_engine = _make_engine(str(get_settings().database_platform_url))
    return _platform_engine


async def dispose_engines() -> None:
    global _runtime_engine, _platform_engine
    for engine in (_runtime_engine, _platform_engine):
        if engine is not None:
            await engine.dispose()
    _runtime_engine = _platform_engine = None


def runtime_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(runtime_engine(), expire_on_commit=False)


def platform_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(platform_engine(), expire_on_commit=False)


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope the current transaction to one tenant for RLS.

    ``set_config(..., is_local => true)`` is the function form of ``SET LOCAL``: it
    lasts until the transaction ends, so a pooled connection never carries one
    tenant's context into another request.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """One transaction for one tenant: commit on success, roll back on error."""
    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        yield session


async def platform_session() -> AsyncIterator[AsyncSession]:
    async with platform_sessionmaker()() as session, session.begin():
        yield session
