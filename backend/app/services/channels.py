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


async def access_token(session: AsyncSession, account: ChannelAccount) -> str | None:
    credential = (
        await session.execute(
            select(ChannelCredential)
            .where(
                ChannelCredential.tenant_id == account.tenant_id,
                ChannelCredential.connection_id == account.connection_id,
                ChannelCredential.revoked_at.is_(None),
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


async def messenger_capacity(session: AsyncSession, tenant_id: uuid.UUID, plan_id: uuid.UUID | None) -> PlanCapacity:
    used = (
        await session.execute(
            select(func.count())
            .select_from(ChannelAccount)
            .where(
                ChannelAccount.tenant_id == tenant_id,
                ChannelAccount.provider == "messenger",
                ChannelAccount.status == "connected",
            )
        )
    ).scalar_one()
    return PlanCapacity(await entitlements.limit(session, plan_id, "max_messenger_pages"), used)


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


async def _page_owner(session: AsyncSession, page_id: str) -> uuid.UUID | None:
    row = (
        await session.execute(text("SELECT tenant_id FROM route_channel_account('messenger', :p)"), {"p": page_id})
    ).first()
    return row.tenant_id if row else None


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


# --- disconnect --------------------------------------------------------------------------


async def disconnect(
    session: AsyncSession, *, tenant_id: uuid.UUID, account_id: uuid.UUID, actor_id: uuid.UUID, request: RequestInfo
) -> ChannelAccount:
    account = await session.get(ChannelAccount, account_id)
    if account is None or account.tenant_id != tenant_id:
        raise NotFound()
    token = await access_token(session, account)
    if token and account.provider == "messenger" and get_settings().meta_configured:
        try:
            await graph.delete(f"/{account.external_account_id}/subscribed_apps", token=token)
        except graph.GraphError:
            log.warning("unsubscribe_failed", provider=account.provider)  # best effort; we stop processing anyway
    await revoke_credentials(session, account)
    account.status = "disconnected"
    account.health_status, account.health_reason = "disconnected", "Disconnected by your team"
    remaining = (
        await session.execute(
            select(func.count())
            .select_from(ChannelAccount)
            .where(ChannelAccount.connection_id == account.connection_id, ChannelAccount.status == "connected")
        )
    ).scalar_one()
    if remaining == 0:
        await session.execute(
            update(ChannelConnection)
            .where(ChannelConnection.id == account.connection_id)
            .values(status="disconnected", disconnected_at=datetime.now(UTC))
        )
    await audit.record(
        session,
        action="CHANNEL_DISCONNECTED",
        actor_type="user",
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="channel_account",
        resource_id=account.id,
        after={"provider": account.provider, "name": account.display_name},
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


async def check_health() -> dict[str, int]:
    """Daily system job: is each connected Page's token valid and our subscription still there?"""
    counts = {"healthy": 0, "action_needed": 0}
    if not get_settings().meta_configured:
        return counts
    async with platform_sessionmaker()() as session, session.begin():
        accounts = (
            (
                await session.execute(
                    select(ChannelAccount).where(
                        ChannelAccount.provider == "messenger", ChannelAccount.status == "connected"
                    )
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            reason: str | None = None
            token = await access_token(session, account)
            try:
                if token is None:
                    reason = "We no longer have access to this Page. Reconnect it."
                else:
                    info = await graph.debug_token(token)
                    if not info.get("is_valid"):
                        reason = "Facebook access expired — you may have changed your password or removed our app. Reconnect it."
                    else:
                        subscribed = await graph.get(f"/{account.external_account_id}/subscribed_apps", token=token)
                        app_id = str(get_settings().meta_app_id)
                        if not any(str(a.get("id")) == app_id for a in subscribed.get("data") or []):
                            reason = "Messages from this Page aren't reaching us. Reconnect it."
            except graph.GraphError as exc:
                if exc.transient:
                    continue  # try again tomorrow; don't alarm the business over a Meta hiccup
                reason = "Facebook access expired. Reconnect this Page."
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
