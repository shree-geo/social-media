"""Health endpoints. They reveal only ok/fail per dependency — no versions or hosts."""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import runtime_engine
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

_CHECK_TIMEOUT_SECONDS = 2.0


async def _check_database() -> bool:
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS), runtime_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        log.warning("health_check_failed", dependency="database", exc_info=True)
        return False


async def _check_redis() -> bool:
    client = Redis.from_url(str(get_settings().redis_url))
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            return bool(await client.ping())
    except Exception:
        log.warning("health_check_failed", dependency="redis", exc_info=True)
        return False
    finally:
        await client.aclose()


@router.get("/health")
@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    database, redis = await asyncio.gather(_check_database(), _check_redis())
    checks = {"database": "ok" if database else "fail", "redis": "ok" if redis else "fail"}
    healthy = database and redis
    return JSONResponse(
        {"status": "ok" if healthy else "fail", "checks": checks},
        status_code=200 if healthy else 503,
    )
