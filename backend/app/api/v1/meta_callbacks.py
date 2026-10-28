"""Meta app callbacks: /api/v1/webhooks/meta/* (configured in the Meta app dashboard).

* deauthorize   — a Facebook user removed our app → their connected Pages need reconnecting.
* data-deletion — required by Meta: confirm what we delete and give a status URL.
Both are signed with the app secret (``signed_request``); no CSRF (Meta has no cookies).
"""

import secrets

from fastapi import APIRouter, Form
from pydantic import BaseModel
from sqlalchemy import update

from app.core.config import get_settings
from app.core.database import platform_sessionmaker
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.integrations.meta import signed_request
from app.models import ChannelConnection
from app.services import audit, channels

router = APIRouter(prefix="/webhooks/meta", tags=["webhooks"])
log = get_logger(__name__)


class InvalidRequest(AppError):
    status, code, title = 400, "invalid_signed_request", "Invalid signed request"


class DeletionReceipt(BaseModel):
    url: str
    confirmation_code: str


def _user_id(raw: str) -> str:
    try:
        data = signed_request.parse(raw)
    except signed_request.InvalidSignedRequest as exc:
        log.warning("meta_signed_request_rejected", reason=str(exc))
        raise InvalidRequest() from exc
    user_id = str(data.get("user_id") or "")
    if not user_id:
        raise InvalidRequest()
    return user_id


@router.post("/deauthorize")
async def deauthorize(signed_request_value: str = Form(alias="signed_request")) -> dict[str, int]:
    affected = await channels.mark_deauthorized(_user_id(signed_request_value))
    return {"affected": affected}


@router.post("/data-deletion")
async def data_deletion(signed_request_value: str = Form(alias="signed_request")) -> DeletionReceipt:
    """We store only the Facebook user id on the connections they made; Pages stop working and are flagged."""
    user_id = _user_id(signed_request_value)
    affected = await channels.mark_deauthorized(user_id)
    code = secrets.token_hex(8)
    async with platform_sessionmaker()() as session, session.begin():
        await session.execute(
            update(ChannelConnection).where(ChannelConnection.external_user_id == user_id).values(external_user_id=None)
        )
        await audit.record(
            session,
            action="META_DATA_DELETION",
            actor_type="system",
            actor_id=None,
            tenant_id=None,
            after={"confirmation_code": code, "connections_affected": affected},
        )
    return DeletionReceipt(url=f"{get_settings().app_base_url}/data-deletion?code={code}", confirmation_code=code)
