"""Unauthenticated data for the public website: /api/v1/public/*."""

from fastapi import APIRouter, Response

from app.core.database import platform_sessionmaker
from app.models import PlatformSetting
from app.schemas.platform import SiteContact

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/site")
async def site(response: Response) -> SiteContact:
    async with platform_sessionmaker()() as session:
        row = await session.get(PlatformSetting, 1)
    response.headers["Cache-Control"] = "no-cache"  # tiny lookup; edits show at once
    return SiteContact(
        support_phone=row.support_phone if row else None, support_email=row.support_email if row else None
    )
