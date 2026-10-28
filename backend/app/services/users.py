"""Creating tenant users with admin-issued temporary passwords (ONBOARDING_AND_CHANNEL_SETUP.md §3).

Used by the platform console (tenant Owner) and by tenant Owners/Admins (staff).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound
from app.core.security import TEMP_PASSWORD_TTL, generate_temporary_password, hash_password
from app.models import MembershipRole, RefreshToken, Role, TenantMembership, User
from app.services import audit
from app.services.audit import ActorType, RequestInfo


class InvalidRole(AppError):
    status, code, title = 422, "invalid_role", "Unknown role"


@dataclass(frozen=True)
class LoginDetails:
    """Shown once to whoever created the login; only the hash is stored."""

    user_id: uuid.UUID
    email: str
    temporary_password: str | None  # None when an existing account was linked
    expires_at: datetime | None


async def _system_role(session: AsyncSession, code: str) -> Role:
    role = (await session.execute(select(Role).where(Role.tenant_id.is_(None), Role.code == code))).scalar_one_or_none()
    if role is None:
        raise InvalidRole(f"Unknown role {code}")
    return role


def _new_temporary_password() -> tuple[str, str, datetime]:
    password = generate_temporary_password()
    return password, hash_password(password), datetime.now(UTC) + TEMP_PASSWORD_TTL


async def add_tenant_user(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    full_name: str,
    phone: str | None,
    role_code: str,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    request: RequestInfo,
) -> LoginDetails:
    role = await _system_role(session, role_code)
    user = (
        await session.execute(
            select(User).where(func.lower(User.email) == email.strip().lower(), User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    temporary_password: str | None = None
    expires_at: datetime | None = None
    if user is None:
        temporary_password, password_hash, expires_at = _new_temporary_password()
        user = User(
            email=email.strip(),
            full_name=full_name,
            phone=phone,
            password_hash=password_hash,
            must_change_password=True,
            temp_password_expires_at=expires_at,
        )
        session.add(user)
        await session.flush()
        await audit.record(
            session,
            action="USER_CREATED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            resource_type="user",
            resource_id=user.id,
            after={"email": user.email, "full_name": full_name},
            request=request,
        )
    else:
        existing = (
            await session.execute(
                select(TenantMembership.id).where(
                    TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise Conflict("This person already has a login for this business.")

    membership = TenantMembership(tenant_id=tenant_id, user_id=user.id, status="active", joined_at=datetime.now(UTC))
    session.add(membership)
    await session.flush()
    session.add(MembershipRole(membership_id=membership.id, role_id=role.id, tenant_id=tenant_id, granted_by=actor_id))
    await audit.record(
        session,
        action="MEMBERSHIP_CREATED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="membership",
        resource_id=membership.id,
        after={"user_id": user.id, "role": role_code},
        request=request,
    )
    return LoginDetails(user.id, user.email, temporary_password, expires_at)


async def reset_login(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    request: RequestInfo,
) -> LoginDetails:
    """New temporary password; the old password and all sessions stop working immediately."""
    member = (
        await session.execute(
            select(TenantMembership.id).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    user = await session.get(User, user_id)
    if member is None or user is None or user.deleted_at is not None:
        raise NotFound()

    temporary_password, password_hash, expires_at = _new_temporary_password()
    user.password_hash = password_hash
    user.must_change_password = True
    user.temp_password_expires_at = expires_at
    user.failed_login_count = 0
    user.locked_until = None
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.subject_type == "user", RefreshToken.subject_id == user.id, RefreshToken.revoked_at.is_(None)
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(
        session,
        action="LOGIN_RESET",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    return LoginDetails(user.id, user.email, temporary_password, expires_at)
