"""Channel lifecycle: encrypted credentials, the connect wizard, disconnect, health (ONBOARDING_AND_CHANNEL_SETUP.md §6, §8).

Facebook Messenger connect flow (wizard A):
  start      → setup session + OAuth ``state`` (only its hash is stored); plan limit checked
  authorize  → verify the user token with Meta (our app, valid, required scopes) → long-lived
               token kept encrypted in the session → list Pages and mark which can be connected
  complete   → per Page: subscribe our app → verify the subscription → store encrypted Page token,
               channel connection and account → wipe the user token
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import EncryptedBlob, decrypt, encrypt
from app.core.database import platform_sessionmaker, runtime_sessionmaker, set_tenant_context
from app.core.exceptions import AppError, NotFound
from app.core.logging import get_logger
from app.integrations import registry
from app.integrations.base import ChannelAccountRef
from app.integrations.messenger.adapter import PAGE_SUBSCRIBED_FIELDS
from app.integrations.meta import graph
from app.models import (
    ChannelAccount,
    ChannelConnection,
    ChannelCredential,
    ChannelSetupSession,
    Customer,
    CustomerIdentity,
)
from app.services import audit, entitlements
from app.services.audit import RequestInfo

log = get_logger(__name__)

SESSION_TTL = timedelta(minutes=30)
MESSENGER_SCOPES = frozenset({"pages_show_list", "pages_messaging", "pages_manage_metadata"})
PLACEHOLDER_NAME = "Unknown customer"


class ChannelSetupError(AppError):
    status, code, title = 422, "channel_setup_failed", "The channel could not be connected"


class ChannelsNotConfigured(AppError):
    status, code, title = 503, "channels_not_configured", "Facebook connection is not available yet"


# --- credentials ------------------------------------------------------------------------


def credential_aad(tenant_id: uuid.UUID, credential_id: uuid.UUID) -> bytes:
    """Binds a ciphertext to its row: a blob copied elsewhere fails to decrypt."""
    return f"{tenant_id}|{credential_id}".encode()


async def store_credential(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    channel_account_id: uuid.UUID | None,
    credential_type: str,
    token: str,
    expires_at: datetime | None = None,
) -> None:
    """Encrypt and store a token, revoking the previous one of the same kind."""
    now = datetime.now(UTC)
    await session.execute(
        update(ChannelCredential)
        .where(
            ChannelCredential.connection_id == connection_id,
            ChannelCredential.credential_type == credential_type,
            ChannelCredential.revoked_at.is_(None),
            ChannelCredential.channel_account_id == channel_account_id
            if channel_account_id
            else ChannelCredential.channel_account_id.is_(None),
        )
        .values(revoked_at=now, token_status="revoked")
    )
    await session.flush()
    credential_id = uuid.uuid4()
    blob = encrypt(token.encode(), credential_aad(tenant_id, credential_id))
    session.add(
        ChannelCredential(
            id=credential_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel_account_id=channel_account_id,
            credential_type=credential_type,
            ciphertext=blob.ciphertext,
            nonce=blob.nonce,
            key_version=blob.key_version,
            token_status="valid",
            expires_at=expires_at,
            last_checked_at=now,
        )
    )


# Credentials that authenticate API calls. Others (e.g. the WhatsApp two-step PIN) never do.
ACCESS_TOKEN_TYPES = ("page_token", "business_token", "system_user_token")


async def access_token(session: AsyncSession, account: ChannelAccount) -> str | None:
    credential = (
        await session.execute(
            select(ChannelCredential)
            .where(
                ChannelCredential.tenant_id == account.tenant_id,
                ChannelCredential.connection_id == account.connection_id,
                ChannelCredential.revoked_at.is_(None),
                ChannelCredential.credential_type.in_(ACCESS_TOKEN_TYPES),
                (ChannelCredential.channel_account_id == account.id) | ChannelCredential.channel_account_id.is_(None),
            )
            # Account-level token (Page token) wins over the connection-level one.
            .order_by(ChannelCredential.channel_account_id.is_(None))
            .limit(1)
        )
    ).scalar_one_or_none()
    if credential is None:
        return None
    blob = EncryptedBlob(credential.key_version, credential.nonce, credential.ciphertext)
    return decrypt(blob, credential_aad(account.tenant_id, credential.id)).decode()


async def revoke_credentials(session: AsyncSession, account: ChannelAccount) -> None:
    await session.execute(
        update(ChannelCredential)
        .where(
            ChannelCredential.connection_id == account.connection_id,
            ChannelCredential.revoked_at.is_(None),
            (ChannelCredential.channel_account_id == account.id) | ChannelCredential.channel_account_id.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), token_status="revoked")
    )


# --- setup sessions ------------------------------------------------------------------------


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _session_token_aad(setup: ChannelSetupSession) -> bytes:
    return f"{setup.tenant_id}|setup|{setup.id}".encode()


def _set_temp_token(setup: ChannelSetupSession, token: str | None) -> None:
    if token is None:
        setup.temp_token_ciphertext = setup.temp_token_nonce = None
        setup.temp_token_key_version = None
        return
    blob = encrypt(token.encode(), _session_token_aad(setup))
    setup.temp_token_ciphertext, setup.temp_token_nonce, setup.temp_token_key_version = (
        blob.ciphertext,
        blob.nonce,
        blob.key_version,
    )


def _temp_token(setup: ChannelSetupSession) -> str:
    if not setup.temp_token_ciphertext or not setup.temp_token_nonce or setup.temp_token_key_version is None:
        raise ChannelSetupError("Please log in to Facebook again.", code="setup_expired")
    blob = EncryptedBlob(setup.temp_token_key_version, setup.temp_token_nonce, setup.temp_token_ciphertext)
    return decrypt(blob, _session_token_aad(setup)).decode()


def _fail(setup: ChannelSetupSession, code: str, message: str) -> ChannelSetupError:
    setup.last_error_code, setup.last_error_message = code, message[:500]
    return ChannelSetupError(message, code=code)


@dataclass(frozen=True)
class PlanCapacity:
    maximum: int | None  # None = unlimited
    used: int


_LIMIT_KEYS = {"messenger": "max_messenger_pages", "whatsapp": "max_whatsapp_numbers"}


async def capacity(
    session: AsyncSession, tenant_id: uuid.UUID, plan_id: uuid.UUID | None, provider: str
) -> PlanCapacity:
    used = (
        await session.execute(
            select(func.count())
            .select_from(ChannelAccount)
            .where(
                ChannelAccount.tenant_id == tenant_id,
                ChannelAccount.provider == provider,
                ChannelAccount.status == "connected",
            )
        )
    ).scalar_one()
    return PlanCapacity(await entitlements.limit(session, plan_id, _LIMIT_KEYS[provider]), used)


async def messenger_capacity(session: AsyncSession, tenant_id: uuid.UUID, plan_id: uuid.UUID | None) -> PlanCapacity:
    return await capacity(session, tenant_id, plan_id, "messenger")


async def start_setup(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, provider: str, mode: str
) -> tuple[ChannelSetupSession, str]:
    if not get_settings().meta_configured:
        raise ChannelsNotConfigured()
    state = secrets.token_urlsafe(32)
    setup = ChannelSetupSession(
        tenant_id=tenant_id,
        provider=provider,
        mode=mode,
        state_hash=_hash_state(state),
        started_by=user_id,
        expires_at=datetime.now(UTC) + SESSION_TTL,
    )
    session.add(setup)
    await session.flush()
    return setup, state


async def _open_setup(
    session: AsyncSession, tenant_id: uuid.UUID, setup_id: uuid.UUID, *, allowed: tuple[str, ...]
) -> ChannelSetupSession:
    setup = (
        await session.execute(select(ChannelSetupSession).where(ChannelSetupSession.id == setup_id).with_for_update())
    ).scalar_one_or_none()
    if setup is None or setup.tenant_id != tenant_id:
        raise NotFound()
    if setup.expires_at < datetime.now(UTC):
        setup.status = "expired"
        _set_temp_token(setup, None)
        raise ChannelSetupError("This connection attempt timed out. Please start again.", code="setup_expired")
    if setup.status not in allowed:
        raise ChannelSetupError(
            "This connection attempt has already finished. Please start again.", code="setup_closed"
        )
    return setup


async def _owner(session: AsyncSession, provider: str, external_id: str) -> uuid.UUID | None:
    """Which business (if any) has this Page / number connected right now."""
    row = (
        await session.execute(
            text("SELECT tenant_id FROM route_channel_account(:provider, :e)"), {"provider": provider, "e": external_id}
        )
    ).first()
    return row.tenant_id if row else None


async def _page_owner(session: AsyncSession, page_id: str) -> uuid.UUID | None:
    return await _owner(session, "messenger", page_id)


async def _list_pages(user_token: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    data = await graph.get(
        "/me/accounts", token=user_token, fields="id,name,tasks,access_token,picture{url}", limit=100
    )
    pages.extend(data.get("data") or [])
    return pages


async def authorize_messenger(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    setup_id: uuid.UUID,
    state: str,
    user_token: str,
    plan_id: uuid.UUID | None,
) -> tuple[ChannelSetupSession, list[dict[str, Any]], PlanCapacity]:
    setup = await _open_setup(session, tenant_id, setup_id, allowed=("started", "authorized"))
    if not secrets.compare_digest(setup.state_hash, _hash_state(state)):
        raise _fail(setup, "invalid_state", "This connection attempt doesn't match. Please start again.")

    settings = get_settings()
    try:
        info = await graph.debug_token(user_token)
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "Facebook didn't confirm your login. Please try again.") from None
    if not info.get("is_valid") or str(info.get("app_id")) != str(settings.meta_app_id):
        # A token for another app must never be accepted (token substitution).
        raise _fail(setup, "invalid_token", "Facebook didn't confirm your login. Please try again.")
    missing = MESSENGER_SCOPES - set(info.get("scopes") or [])
    if missing:
        raise _fail(
            setup,
            "permissions_missing",
            "We need permission to manage messages for your Page. Try again and allow all requested permissions.",
        )

    try:
        long_lived = await graph.exchange_for_long_lived(user_token)
        pages = await _list_pages(long_lived)
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "Facebook didn't respond. Nothing was changed. Please try again.") from None

    listed: list[dict[str, Any]] = []
    for page in pages:
        page_id = str(page.get("id"))
        tasks = set(page.get("tasks") or [])
        owner = await _page_owner(session, page_id)
        if owner is not None and owner != tenant_id:
            status = "connected_elsewhere"
        elif not {"MANAGE", "MESSAGING"} <= tasks:
            status = "needs_full_control"
        elif owner == tenant_id:
            status = "connected_here"
        else:
            status = "connectable"
        listed.append(
            {
                "id": page_id,
                "name": page.get("name") or page_id,
                "picture": ((page.get("picture") or {}).get("data") or {}).get("url"),
                "status": status,
            }
        )

    _set_temp_token(setup, long_lived)
    setup.external_user_id = str(info.get("user_id") or "") or None
    setup.meta_session_info = {"pages": listed}  # no tokens here
    setup.status = "authorized"
    setup.steps_completed = ["authorized"]
    setup.last_error_code = setup.last_error_message = None
    capacity = await messenger_capacity(session, tenant_id, plan_id)
    return setup, listed, capacity


@dataclass(frozen=True)
class PageResult:
    page_id: str
    name: str
    ok: bool
    channel_account_id: uuid.UUID | None = None
    error_code: str | None = None
    message: str | None = None


async def _subscribe_page(page_id: str, page_token: str) -> None:
    await graph.post(
        f"/{page_id}/subscribed_apps", token=page_token, subscribed_fields=",".join(PAGE_SUBSCRIBED_FIELDS)
    )
    subscribed = await graph.get(f"/{page_id}/subscribed_apps", token=page_token)
    app_id = str(get_settings().meta_app_id)
    if not any(str(app.get("id")) == app_id for app in subscribed.get("data") or []):
        raise graph.GraphError("Subscription could not be verified")


async def _upsert_page(
    session: AsyncSession,
    *,
    setup: ChannelSetupSession,
    user_id: uuid.UUID,
    page: dict[str, Any],
    page_token: str,
) -> ChannelAccount:
    now = datetime.now(UTC)
    account = (
        (
            await session.execute(
                select(ChannelAccount).where(
                    ChannelAccount.tenant_id == setup.tenant_id,
                    ChannelAccount.provider == "messenger",
                    ChannelAccount.external_account_id == page["id"],
                )
            )
        )
        .scalars()
        .first()
    )
    if account is None:
        connection = ChannelConnection(
            tenant_id=setup.tenant_id,
            provider="messenger",
            status="connected",
            external_business_id=page["id"],
            external_user_id=setup.external_user_id,
            connected_by=user_id,
            connected_at=now,
        )
        session.add(connection)
        await session.flush()
        account = ChannelAccount(
            tenant_id=setup.tenant_id,
            connection_id=connection.id,
            provider="messenger",
            external_account_id=page["id"],
        )
        session.add(account)
    else:
        existing = await session.get(ChannelConnection, account.connection_id)
        assert existing is not None
        existing.status, existing.connected_at, existing.disconnected_at = "connected", now, None
        existing.external_user_id, existing.connected_by, existing.last_error = (
            setup.external_user_id,
            user_id,
            None,
        )
    account.display_name = page["name"]
    account.status = "connected"
    account.health_status, account.health_reason, account.last_health_check_at = "healthy", None, now
    account.provider_metadata = {"picture": page.get("picture")}
    await session.flush()
    await store_credential(
        session,
        tenant_id=setup.tenant_id,
        connection_id=account.connection_id,
        channel_account_id=account.id,
        credential_type="page_token",
        token=page_token,
    )
    return account


async def complete_messenger(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    setup_id: uuid.UUID,
    page_ids: list[str],
    plan_id: uuid.UUID | None,
    request: RequestInfo,
) -> list[PageResult]:
    setup = await _open_setup(session, tenant_id, setup_id, allowed=("authorized", "failed"))
    known = {p["id"]: p for p in setup.meta_session_info.get("pages", [])}
    chosen = [known[p] for p in dict.fromkeys(page_ids) if p in known]
    if not chosen:
        raise _fail(setup, "no_pages", "Choose at least one Page to connect.")
    blocked = [p for p in chosen if p["status"] in ("connected_elsewhere", "needs_full_control")]
    if blocked:
        raise _fail(setup, "page_not_connectable", f"{blocked[0]['name']} can't be connected from this account.")

    capacity = await messenger_capacity(session, tenant_id, plan_id)
    new_pages = sum(1 for p in chosen if p["status"] != "connected_here")
    if capacity.maximum is not None and capacity.used + new_pages > capacity.maximum:
        raise _fail(setup, "plan_limit_exceeded", f"Your package allows {capacity.maximum} Facebook Page(s).")

    setup.status = "completing"
    try:
        fresh = {str(p.get("id")): p for p in await _list_pages(_temp_token(setup))}
    except graph.GraphError as exc:
        setup.status = "failed"
        raise _fail(setup, exc.short_code, "Facebook didn't respond. Nothing was changed. Please try again.") from None

    results: list[PageResult] = []
    for page in chosen:
        token = (fresh.get(page["id"]) or {}).get("access_token")
        if not token:
            results.append(
                PageResult(
                    page["id"],
                    page["name"],
                    False,
                    error_code="page_access_lost",
                    message="We no longer have access to this Page. Log in to Facebook again.",
                )
            )
            continue
        try:
            await _subscribe_page(page["id"], token)  # before any DB write: a failure changes nothing
        except graph.GraphError as exc:
            results.append(
                PageResult(
                    page["id"],
                    page["name"],
                    False,
                    error_code=exc.short_code,
                    message="Facebook didn't accept the connection. Nothing was changed for this Page.",
                )
            )
            continue
        account = await _upsert_page(session, setup=setup, user_id=user_id, page=page, page_token=token)
        await audit.record(
            session,
            action="CHANNEL_CONNECTED",
            actor_type="user",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type="channel_account",
            resource_id=account.id,
            after={"provider": "messenger", "page_id": page["id"], "name": page["name"]},
            request=request,
        )
        results.append(PageResult(page["id"], page["name"], True, channel_account_id=account.id))

    succeeded = [r for r in results if r.ok]
    setup.steps_completed = [*setup.steps_completed, "completed"] if succeeded else setup.steps_completed
    setup.channel_account_id = succeeded[0].channel_account_id if succeeded else None
    if succeeded:
        setup.status = "completed"
        _set_temp_token(setup, None)  # the user token is not needed any more
        setup.last_error_code = setup.last_error_message = None
    else:
        setup.status = "failed"
        setup.last_error_code, setup.last_error_message = results[-1].error_code, results[-1].message
    return results


async def cancel_setup(session: AsyncSession, *, tenant_id: uuid.UUID, setup_id: uuid.UUID) -> None:
    setup = await session.get(ChannelSetupSession, setup_id)
    if setup is None or setup.tenant_id != tenant_id:
        raise NotFound()
    if setup.status not in ("completed", "cancelled"):
        setup.status = "cancelled"
    _set_temp_token(setup, None)


# --- WhatsApp Embedded Signup (wizard B) ------------------------------------------------------

WHATSAPP_SCOPES = frozenset({"whatsapp_business_management", "whatsapp_business_messaging"})
# Cloud API registration errors meaning "a two-step verification PIN from a previous setup is set".
_PIN_ERRORS = frozenset({133005, 133006})


@dataclass(frozen=True)
class WhatsAppConnected:
    channel_account_id: uuid.UUID
    display_phone: str | None
    display_name: str | None
    name_status: str | None
    coexistence: bool


def _granted_for(info: dict[str, Any], scope: str, target: str) -> bool:
    """With granular scopes, the user picks which WABAs they share; make sure it includes this one."""
    granular = info.get("granular_scopes")
    if not granular:
        return True  # older tokens without granular scopes: the WABA ownership check below still applies
    for item in granular:
        if item.get("scope") == scope:
            targets = item.get("target_ids")
            return targets is None or target in {str(t) for t in targets}
    return False


async def _whatsapp_token(setup: ChannelSetupSession, code: str | None) -> str:
    if "token" in setup.steps_completed:
        return _temp_token(setup)
    if not code:
        raise _fail(setup, "code_missing", "Facebook didn't finish the sign-up. Please try again.")
    try:
        token = await graph.exchange_code(code)  # the code works once; keep the result for retries
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "Facebook didn't confirm the sign-up. Please start again.") from None
    _set_temp_token(setup, token)
    setup.steps_completed = [*setup.steps_completed, "token"]
    return token


async def _verify_whatsapp(
    session: AsyncSession,
    setup: ChannelSetupSession,
    token: str,
    waba_id: str,
    phone_number_id: str,
    plan_id: uuid.UUID | None,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        info = await graph.debug_token(token)
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "Facebook didn't confirm the sign-up. Please try again.") from None
    if not info.get("is_valid") or str(info.get("app_id")) != str(settings.meta_app_id):
        raise _fail(setup, "invalid_token", "Facebook didn't confirm the sign-up. Please start again.")
    if WHATSAPP_SCOPES - set(info.get("scopes") or []):
        raise _fail(
            setup, "permissions_missing", "We need permission to manage and send messages for your WhatsApp account."
        )
    if not _granted_for(info, "whatsapp_business_management", waba_id):
        raise _fail(
            setup, "waba_not_shared", "This WhatsApp account wasn't shared with us during sign-up. Please start again."
        )

    try:
        numbers = await graph.get(
            f"/{waba_id}/phone_numbers",
            token=token,
            fields="id,display_phone_number,verified_name,name_status,quality_rating,code_verification_status,platform_type",
        )
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "We couldn't read your WhatsApp account. Please try again.") from None
    phone = next((n for n in numbers.get("data") or [] if str(n.get("id")) == phone_number_id), None)
    if phone is None:
        raise _fail(
            setup, "number_not_in_account", "That number isn't in the WhatsApp account you chose. Please start again."
        )

    owner = await _owner(session, "whatsapp", phone_number_id)
    if owner is not None and owner != setup.tenant_id:
        raise _fail(setup, "number_connected_elsewhere", "This number is connected to another business. Contact us.")
    if owner is None:
        cap = await capacity(session, setup.tenant_id, plan_id, "whatsapp")
        if cap.maximum is not None and cap.used >= cap.maximum:
            raise _fail(setup, "plan_limit_exceeded", f"Your package allows {cap.maximum} WhatsApp number(s).")
    setup.external_user_id = str(info.get("user_id") or "") or setup.external_user_id
    return dict(phone)


async def _subscribe_waba(setup: ChannelSetupSession, token: str, waba_id: str) -> None:
    try:
        await graph.post(f"/{waba_id}/subscribed_apps", token=token)
        subscribed = await graph.get(f"/{waba_id}/subscribed_apps", token=token)
    except graph.GraphError as exc:
        raise _fail(setup, exc.short_code, "WhatsApp didn't accept the connection. Please try again.") from None
    app_id = str(get_settings().meta_app_id)
    ids = {
        str((app.get("whatsapp_business_api_data") or {}).get("id") or app.get("id"))
        for app in subscribed.get("data") or []
    }
    if app_id not in ids:
        raise _fail(setup, "subscription_unverified", "WhatsApp didn't confirm the connection. Please try again.")


async def _save_whatsapp(
    session: AsyncSession,
    *,
    setup: ChannelSetupSession,
    user_id: uuid.UUID,
    waba_id: str,
    phone: dict[str, Any],
    token: str,
    coexistence: bool,
    needs_registration: bool,
) -> ChannelAccount:
    now = datetime.now(UTC)
    connection = (
        (
            await session.execute(
                select(ChannelConnection).where(
                    ChannelConnection.tenant_id == setup.tenant_id,
                    ChannelConnection.provider == "whatsapp",
                    ChannelConnection.external_business_id == waba_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if connection is None:
        connection = ChannelConnection(tenant_id=setup.tenant_id, provider="whatsapp", external_business_id=waba_id)
        session.add(connection)
    connection.status, connection.connected_at, connection.disconnected_at, connection.last_error = (
        "connected",
        now,
        None,
        None,
    )
    connection.external_user_id, connection.connected_by = setup.external_user_id, user_id
    await session.flush()

    account = (
        (
            await session.execute(
                select(ChannelAccount).where(
                    ChannelAccount.tenant_id == setup.tenant_id,
                    ChannelAccount.provider == "whatsapp",
                    ChannelAccount.external_account_id == str(phone["id"]),
                )
            )
        )
        .scalars()
        .first()
    )
    if account is None:
        account = ChannelAccount(
            tenant_id=setup.tenant_id,
            connection_id=connection.id,
            provider="whatsapp",
            external_account_id=str(phone["id"]),
        )
        session.add(account)
    account.connection_id = connection.id
    account.display_phone = phone.get("display_phone_number")
    account.display_name = phone.get("verified_name") or phone.get("display_phone_number")
    account.name_status = phone.get("name_status")
    account.quality_rating = phone.get("quality_rating")
    account.coexistence = coexistence
    account.status = "connected"
    # A new number is "pending" until it is registered for the Cloud API.
    account.health_status = "pending" if needs_registration else "healthy"
    account.health_reason = "Activating the number for messages." if needs_registration else None
    account.last_health_check_at = now
    account.provider_metadata = {"waba_id": waba_id, "platform_type": phone.get("platform_type")}
    await session.flush()
    # One business token per WhatsApp Business Account, stored at connection level.
    await store_credential(
        session,
        tenant_id=setup.tenant_id,
        connection_id=connection.id,
        channel_account_id=None,
        credential_type="business_token",
        token=token,
    )
    return account


async def _register_number(
    session: AsyncSession, setup: ChannelSetupSession, account: ChannelAccount, token: str
) -> None:
    """New-number mode: activate the number on the Cloud API with a two-step verification PIN we keep (encrypted)."""
    pin = f"{secrets.randbelow(10**6):06d}"
    try:
        await graph.post(
            f"/{account.external_account_id}/register", token=token, json={"messaging_product": "whatsapp", "pin": pin}
        )
    except graph.GraphError as exc:
        account.health_status = "action_needed"
        if exc.code in _PIN_ERRORS:
            account.health_reason = "This number is protected by a PIN from an earlier setup. Remove two-step verification in WhatsApp Manager, then try again."
            raise _fail(setup, "pin_protected", account.health_reason) from None
        account.health_reason = "The number isn't active for messages yet. Try connecting again."
        raise _fail(setup, exc.short_code, "WhatsApp couldn't activate this number. Please try again.") from None
    await store_credential(
        session,
        tenant_id=setup.tenant_id,
        connection_id=account.connection_id,
        channel_account_id=account.id,
        credential_type="two_step_pin",
        token=pin,
    )
    account.health_status, account.health_reason = "healthy", None


async def complete_whatsapp(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    setup_id: uuid.UUID,
    state: str,
    code: str | None,
    waba_id: str,
    phone_number_id: str,
    plan_id: uuid.UUID | None,
    request: RequestInfo,
) -> WhatsAppConnected:
    """Finish Embedded Signup. Every step is recorded, so a retry continues from the failed step."""
    setup = await _open_setup(session, tenant_id, setup_id, allowed=("started", "failed", "completing"))
    if not secrets.compare_digest(setup.state_hash, _hash_state(state)):
        raise _fail(setup, "invalid_state", "This connection attempt doesn't match. Please start again.")
    info = setup.meta_session_info or {}
    if info.get("waba_id") and (info.get("waba_id"), info.get("phone_number_id")) != (waba_id, phone_number_id):
        raise _fail(setup, "invalid_state", "This connection attempt doesn't match. Please start again.")
    setup.meta_session_info = {**info, "waba_id": waba_id, "phone_number_id": phone_number_id}
    setup.status = "completing"
    coexistence = setup.mode == "coexistence"
    done = setup.steps_completed
    # Coexistence numbers stay on the Business app; numbers already on the Cloud API (reconnects) are registered.

    token = await _whatsapp_token(setup, code)
    done = setup.steps_completed  # re-read: the token step may just have been recorded
    phone = await _verify_whatsapp(session, setup, token, waba_id, phone_number_id, plan_id)
    if "subscribed" not in done:
        await _subscribe_waba(setup, token, waba_id)
        setup.steps_completed = done = [*done, "subscribed"]
    needs_registration = (
        not coexistence and "registered" not in done and str(phone.get("platform_type") or "").upper() != "CLOUD_API"
    )
    account = await _save_whatsapp(
        session,
        setup=setup,
        user_id=user_id,
        waba_id=waba_id,
        phone=phone,
        token=token,
        coexistence=coexistence,
        needs_registration=needs_registration,
    )
    if "saved" not in done:
        setup.steps_completed = done = [*done, "saved"]
        await audit.record(
            session,
            action="CHANNEL_CONNECTED",
            actor_type="user",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type="channel_account",
            resource_id=account.id,
            after={"provider": "whatsapp", "phone": account.display_phone, "coexistence": coexistence},
            request=request,
        )
    if needs_registration:
        try:
            await _register_number(session, setup, account, token)
        except ChannelSetupError:
            setup.status = "failed"  # resumable: the next attempt starts at registration
            raise
        setup.steps_completed = done = [*done, "registered"]

    setup.status = "completed"
    setup.channel_account_id = account.id
    setup.last_error_code = setup.last_error_message = None
    _set_temp_token(setup, None)
    return WhatsAppConnected(account.id, account.display_phone, account.display_name, account.name_status, coexistence)


async def record_cancel(
    session: AsyncSession, *, tenant_id: uuid.UUID, setup_id: uuid.UUID, step: str | None, error: str | None
) -> None:
    """The person closed Meta's window or it reported an error: keep where it stopped for support."""
    setup = await session.get(ChannelSetupSession, setup_id)
    if setup is None or setup.tenant_id != tenant_id:
        raise NotFound()
    setup.meta_session_info = {**(setup.meta_session_info or {}), "stopped_at_step": step, "meta_error": error}
    if setup.status in ("started", "authorized"):
        setup.status = "cancelled"
        _set_temp_token(setup, None)


# --- disconnect --------------------------------------------------------------------------


async def disconnect(
    session: AsyncSession, *, tenant_id: uuid.UUID, account_id: uuid.UUID, actor_id: uuid.UUID, request: RequestInfo
) -> ChannelAccount:
    account = await session.get(ChannelAccount, account_id)
    if account is None or account.tenant_id != tenant_id:
        raise NotFound()
    token = await access_token(session, account)
    others = (
        await session.execute(
            select(func.count())
            .select_from(ChannelAccount)
            .where(
                ChannelAccount.connection_id == account.connection_id,
                ChannelAccount.status == "connected",
                ChannelAccount.id != account.id,
            )
        )
    ).scalar_one()
    last_on_connection = others == 0

    if token and get_settings().meta_configured:
        # Messenger subscribes per Page; WhatsApp per business account (shared by its numbers).
        target = (
            account.external_account_id
            if account.provider == "messenger"
            else (account.provider_metadata or {}).get("waba_id")
            if last_on_connection
            else None
        )
        if target:
            try:
                await graph.delete(f"/{target}/subscribed_apps", token=token)
            except graph.GraphError:
                log.warning("unsubscribe_failed", provider=account.provider)  # best effort; we stop processing anyway

    now = datetime.now(UTC)
    # This account's own credentials (Page token, WhatsApp PIN) always go; the shared
    # connection-level token (WhatsApp business token) only with the last account on it.
    await session.execute(
        update(ChannelCredential)
        .where(
            ChannelCredential.connection_id == account.connection_id,
            ChannelCredential.revoked_at.is_(None),
            (ChannelCredential.channel_account_id == account.id)
            | (ChannelCredential.channel_account_id.is_(None) if last_on_connection else False),
        )
        .values(revoked_at=now, token_status="revoked")
    )
    account.status = "disconnected"
    account.health_status, account.health_reason = "disconnected", "Disconnected by your team"
    if last_on_connection:
        await session.execute(
            update(ChannelConnection)
            .where(ChannelConnection.id == account.connection_id)
            .values(status="disconnected", disconnected_at=now)
        )
    await audit.record(
        session,
        action="CHANNEL_DISCONNECTED",
        actor_type="user",
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="channel_account",
        resource_id=account.id,
        after={"provider": account.provider, "name": account.display_name or account.display_phone},
        request=request,
    )
    return account


# --- customer profiles ---------------------------------------------------------------------


async def fetch_profile(tenant_id: uuid.UUID, channel_account_id: uuid.UUID, provider_user_id: str) -> bool:
    """Worker: fill in the name of a customer whose first message arrived without one."""
    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        account = await session.get(ChannelAccount, channel_account_id)
        adapter = registry.get(account.provider) if account else None
        token = await access_token(session, account) if account else None
        if account is None or adapter is None or token is None:
            return False
        ref = ChannelAccountRef(str(account.id), account.external_account_id, token)

    profile = await adapter.get_customer_profile(ref, provider_user_id)
    if profile is None or not profile.name:
        return False

    async with runtime_sessionmaker()() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        identity = (
            await session.execute(
                select(CustomerIdentity).where(
                    CustomerIdentity.channel_account_id == channel_account_id,
                    CustomerIdentity.provider_user_id == provider_user_id,
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            return False
        identity.profile_name = profile.name
        customer = await session.get(Customer, identity.customer_id)
        if customer is not None and customer.display_name == PLACEHOLDER_NAME:
            customer.display_name = profile.name  # never overwrite a name the team typed
    return True


# --- health ----------------------------------------------------------------------------------


def _app_subscribed(data: dict[str, Any]) -> bool:
    app_id = str(get_settings().meta_app_id)
    return any(
        str((a.get("whatsapp_business_api_data") or {}).get("id") or a.get("id")) == app_id
        for a in data.get("data") or []
    )


async def _messenger_health(account: ChannelAccount, token: str) -> str | None:
    info = await graph.debug_token(token)
    if not info.get("is_valid"):
        return "Facebook access expired — you may have changed your password or removed our app. Reconnect it."
    if not _app_subscribed(await graph.get(f"/{account.external_account_id}/subscribed_apps", token=token)):
        return "Messages from this Page aren't reaching us. Reconnect it."
    return None


async def _whatsapp_health(account: ChannelAccount, token: str) -> str | None:
    info = await graph.debug_token(token)
    if not info.get("is_valid"):
        return "Our access to this WhatsApp account has ended. Reconnect it."
    phone = await graph.get(
        f"/{account.external_account_id}", token=token, fields="quality_rating,name_status,verified_name"
    )
    account.quality_rating = phone.get("quality_rating") or account.quality_rating
    account.name_status = phone.get("name_status") or account.name_status
    if str(account.name_status or "").upper() == "APPROVED" and phone.get("verified_name"):
        account.display_name = phone["verified_name"]
    waba_id = (account.provider_metadata or {}).get("waba_id")
    if waba_id and not _app_subscribed(await graph.get(f"/{waba_id}/subscribed_apps", token=token)):
        return "Messages to this number aren't reaching us. Reconnect it."
    if str(account.name_status or "").upper() in ("DECLINED", "REJECTED"):
        return "Meta didn't approve your display name. Use a name that matches your business, then submit it again."
    if str(account.quality_rating or "").upper() == "RED":
        return "WhatsApp rated this number's quality low. Only message people who contacted you, and reply promptly."
    return None


_HEALTH_CHECKS = {"messenger": _messenger_health, "whatsapp": _whatsapp_health}


async def check_health() -> dict[str, int]:
    """Daily system job: tokens still valid, webhooks still subscribed, WhatsApp quality and name status."""
    counts = {"healthy": 0, "action_needed": 0}
    if not get_settings().meta_configured:
        return counts
    async with platform_sessionmaker()() as session, session.begin():
        accounts = (
            (
                await session.execute(
                    select(ChannelAccount).where(
                        ChannelAccount.provider.in_(tuple(_HEALTH_CHECKS)),
                        ChannelAccount.status == "connected",
                        ChannelAccount.health_status != "pending",  # still being activated
                    )
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            token = await access_token(session, account)
            try:
                reason = (
                    "We no longer have access to this channel. Reconnect it."
                    if token is None
                    else await _HEALTH_CHECKS[account.provider](account, token)
                )
            except graph.GraphError as exc:
                if exc.transient:
                    continue  # try again tomorrow; don't alarm the business over a Meta hiccup
                reason = "Our access to this channel has ended. Reconnect it."
            before = account.health_status
            account.health_status = "action_needed" if reason else "healthy"
            account.health_reason = reason
            account.last_health_check_at = datetime.now(UTC)
            counts[account.health_status] += 1
            if before != account.health_status:
                await audit.record(
                    session,
                    action="CHANNEL_HEALTH_CHANGED",
                    actor_type="system",
                    actor_id=None,
                    tenant_id=account.tenant_id,
                    resource_type="channel_account",
                    resource_id=account.id,
                    before={"health": before},
                    after={"health": account.health_status, "reason": reason},
                )
    return counts


async def mark_deauthorized(external_user_id: str) -> int:
    """Meta says this Facebook user removed our app: every Page they connected needs reconnecting."""
    async with platform_sessionmaker()() as session, session.begin():
        accounts = (
            (
                await session.execute(
                    select(ChannelAccount)
                    .join(ChannelConnection, ChannelConnection.id == ChannelAccount.connection_id)
                    .where(ChannelConnection.external_user_id == external_user_id, ChannelAccount.status == "connected")
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            account.health_status = "action_needed"
            account.health_reason = "Our app was removed from Facebook's Business Integrations. Reconnect this Page."
            await audit.record(
                session,
                action="CHANNEL_DEAUTHORIZED",
                actor_type="system",
                actor_id=None,
                tenant_id=account.tenant_id,
                resource_type="channel_account",
                resource_id=account.id,
            )
        return len(accounts)
