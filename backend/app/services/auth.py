"""Authentication for tenant users and platform users (ARCHITECTURE.md §7).

* Login: email + password, lockout after repeated failures, expired temporary
  passwords rejected (admin must reset), tenant chosen from active memberships.
* Sessions: short-lived access JWT + opaque refresh token rotated on every use.
  Presenting an already-rotated refresh token revokes the whole session family.
* Password change: required while ``must_change_password`` is set; revokes every
  session and starts a new one.

Tenant users are handled on the runtime role (``users`` and ``refresh_tokens`` have
no RLS; memberships come from ``auth_user_memberships``). Platform users are handled
on the platform role, because the runtime role cannot read ``platform_users``.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.core.exceptions import AppError, Unauthorized
from app.core.ids import new_id
from app.core.security import (
    REFRESH_TOKEN_TTL,
    SubjectType,
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    needs_rehash,
    password_problems,
    verify_password,
)
from app.models import PlatformUser, RefreshToken, User
from app.services import audit
from app.services.audit import RequestInfo

MAX_FAILED_LOGINS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# Verified against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("dummy-password-for-timing")

Account = User | PlatformUser


class InvalidCredentials(AppError):
    status, code, title = 401, "invalid_credentials", "Email or password is incorrect"


class AccountLocked(AppError):
    status, code, title = 423, "account_locked", "Too many failed attempts. Try again in 15 minutes."


class TemporaryPasswordExpired(AppError):
    status, code, title = 401, "temporary_password_expired", "Your temporary password has expired. Ask us to reset it."


class NoActiveMembership(AppError):
    status, code, title = 403, "no_active_membership", "Your account is not linked to an active business."


class PasswordRejected(AppError):
    status, code, title = 422, "password_rejected", "Choose a different password"


@dataclass(frozen=True)
class Membership:
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    business_name: str
    is_owner: bool


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    subject_id: uuid.UUID
    tenant_id: uuid.UUID | None
    must_change_password: bool


@dataclass(frozen=True)
class LoginFailure:
    """Returned (not raised) so the caller commits failure counters before raising."""

    error: AppError


def _now() -> datetime:
    return datetime.now(UTC)


def _subject_type(account: Account) -> SubjectType:
    return "platform_user" if isinstance(account, PlatformUser) else "user"


async def memberships_for(session: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    rows = await session.execute(text("SELECT * FROM auth_user_memberships(:uid)"), {"uid": user_id})
    return [Membership(r.tenant_id, r.membership_id, r.business_name, r.is_owner) for r in rows]


async def _issue(
    session: AsyncSession,
    account: Account,
    *,
    tenant_id: uuid.UUID | None,
    family_id: uuid.UUID | None = None,
    request: RequestInfo,
) -> tuple[IssuedSession, RefreshToken]:
    family = family_id or new_id()
    refresh = generate_opaque_token()
    row = RefreshToken(
        subject_type=_subject_type(account),
        subject_id=account.id,
        family_id=family,
        token_hash=hash_token(refresh),
        active_tenant_id=tenant_id,
        expires_at=_now() + REFRESH_TOKEN_TTL,
        ip=request.ip,
        user_agent=(request.user_agent or "")[:512] or None,
    )
    session.add(row)
    await session.flush()
    access = create_access_token(
        subject_id=account.id, subject_type=_subject_type(account), session_id=family, tenant_id=tenant_id
    )
    return (
        IssuedSession(access, refresh, family, account.id, tenant_id, account.must_change_password),
        row,
    )


async def _audit(
    session: AsyncSession,
    action: str,
    account: Account | None,
    tenant_id: uuid.UUID | None,
    request: RequestInfo,
    **after: object,
) -> None:
    if tenant_id is not None:
        await set_tenant_context(session, tenant_id)
    await audit.record(
        session,
        action=action,
        actor_type=_subject_type(account) if account else "system",
        actor_id=account.id if account else None,
        tenant_id=tenant_id,
        resource_type=_subject_type(account) if account else None,
        resource_id=account.id if account else None,
        after=dict(after) or None,
        request=request,
    )


async def _find_account(session: AsyncSession, model: type[Account], email: str) -> Account | None:
    normalized = email.strip().lower()
    if model is User:
        user_query = select(User).where(func.lower(User.email) == normalized, User.deleted_at.is_(None))
        return (await session.execute(user_query.with_for_update())).scalar_one_or_none()
    staff_query = select(PlatformUser).where(func.lower(PlatformUser.email) == normalized)
    return (await session.execute(staff_query.with_for_update())).scalar_one_or_none()


async def login(
    session: AsyncSession,
    *,
    model: type[Account],
    email: str,
    password: str,
    tenant_id: uuid.UUID | None,
    request: RequestInfo,
) -> IssuedSession | LoginFailure:
    account = await _find_account(session, model, email)
    now = _now()

    if account is None or not account.is_active:
        verify_password(_DUMMY_HASH, password)
        await _audit(session, "LOGIN_FAILED", account, None, request, reason="unknown_or_inactive")
        return LoginFailure(InvalidCredentials())

    if account.locked_until and account.locked_until > now:
        await _audit(session, "LOGIN_FAILED", account, None, request, reason="locked")
        return LoginFailure(AccountLocked())

    if not verify_password(account.password_hash, password):
        account.failed_login_count += 1
        if account.failed_login_count >= MAX_FAILED_LOGINS:
            account.locked_until = now + LOCKOUT_DURATION
            account.failed_login_count = 0
            await _audit(session, "ACCOUNT_LOCKED", account, None, request)
        await _audit(session, "LOGIN_FAILED", account, None, request, reason="bad_password")
        return LoginFailure(
            AccountLocked() if account.locked_until and account.locked_until > now else InvalidCredentials()
        )

    if account.must_change_password and account.temp_password_expires_at and account.temp_password_expires_at < now:
        await _audit(session, "LOGIN_FAILED", account, None, request, reason="temporary_password_expired")
        return LoginFailure(TemporaryPasswordExpired())

    chosen_tenant: uuid.UUID | None = None
    if isinstance(account, User):
        memberships = await memberships_for(session, account.id)
        if not memberships:
            await _audit(session, "LOGIN_FAILED", account, None, request, reason="no_active_membership")
            return LoginFailure(NoActiveMembership())
        by_tenant = {m.tenant_id: m for m in memberships}
        chosen_tenant = tenant_id if tenant_id in by_tenant else memberships[0].tenant_id

    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = now
    if needs_rehash(account.password_hash):
        account.password_hash = hash_password(password)

    issued, _ = await _issue(session, account, tenant_id=chosen_tenant, request=request)
    await _audit(session, "LOGIN", account, chosen_tenant, request, session_id=str(issued.session_id))
    return issued


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def _revoke_all(session: AsyncSession, subject_type: SubjectType, subject_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.subject_type == subject_type,
            RefreshToken.subject_id == subject_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )


async def _load_account(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> Account | None:
    account: Account | None = (
        await session.get(PlatformUser, subject_id)
        if subject_type == "platform_user"
        else await session.get(User, subject_id)
    )
    if account is None or not account.is_active or (isinstance(account, User) and account.deleted_at):
        return None
    return account


async def refresh(
    session: AsyncSession, *, refresh_token: str, expected_subject: SubjectType, request: RequestInfo
) -> IssuedSession | LoginFailure:
    """Rotate a refresh token. Failures are returned so revocations still commit."""
    row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)).with_for_update()
        )
    ).scalar_one_or_none()
    expired = LoginFailure(Unauthorized("Session expired. Please log in again."))
    if row is None or row.subject_type != expected_subject:
        return expired

    if row.revoked_at is not None:
        # A rotated token was replayed: assume theft and end the whole session.
        await _revoke_family(session, row.family_id)
        account = await _load_account(session, row.subject_type, row.subject_id)
        await _audit(session, "REFRESH_TOKEN_REUSE", account, None, request, session_id=str(row.family_id))
        return expired

    if row.expires_at <= _now():
        return expired

    account = await _load_account(session, row.subject_type, row.subject_id)
    if account is None:
        await _revoke_family(session, row.family_id)
        return expired

    tenant_id = row.active_tenant_id
    if isinstance(account, User):
        active = {m.tenant_id for m in await memberships_for(session, account.id)}
        if tenant_id not in active:
            await _revoke_family(session, row.family_id)
            return LoginFailure(Unauthorized("Your access to this business has ended."))

    issued, new_row = await _issue(session, account, tenant_id=tenant_id, family_id=row.family_id, request=request)
    row.revoked_at = _now()
    row.replaced_by_id = new_row.id
    return issued


async def logout(session: AsyncSession, *, session_id: uuid.UUID) -> None:
    await _revoke_family(session, session_id)


async def change_password(
    session: AsyncSession,
    *,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    current_password: str,
    new_password: str,
    request: RequestInfo,
) -> IssuedSession:
    account = await _load_account(session, subject_type, subject_id)
    if account is None:
        raise Unauthorized()
    if not verify_password(account.password_hash, current_password):
        raise InvalidCredentials("Current password is incorrect")
    if problems := password_problems(new_password, email=account.email):
        raise PasswordRejected(" ".join(problems), problems=problems)
    if verify_password(account.password_hash, new_password):
        raise PasswordRejected("The new password must be different from the current one.")

    account.password_hash = hash_password(new_password)
    account.must_change_password = False
    account.temp_password_expires_at = None
    account.password_changed_at = _now()
    await _revoke_all(session, subject_type, account.id)
    issued, _ = await _issue(session, account, tenant_id=tenant_id, request=request)
    await _audit(session, "PASSWORD_CHANGED", account, tenant_id, request)
    return issued


async def switch_tenant(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, tenant_id: uuid.UUID, request: RequestInfo
) -> IssuedSession:
    account = await _load_account(session, "user", user_id)
    if account is None:
        raise Unauthorized()
    if tenant_id not in {m.tenant_id for m in await memberships_for(session, user_id)}:
        raise NoActiveMembership("You are not a member of that business.")
    await _revoke_family(session, session_id)
    issued, _ = await _issue(session, account, tenant_id=tenant_id, request=request)
    await _audit(session, "TENANT_SWITCHED", account, tenant_id, request)
    return issued
