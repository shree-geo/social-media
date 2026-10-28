"""Idempotent reference data: permissions, system roles, bootstrap platform admin (DATABASE.md §15)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import PERMISSIONS, ROLE_NAMES, ROLE_PERMISSIONS
from app.core.security import TEMP_PASSWORD_TTL, generate_temporary_password, hash_password
from app.models import Permission, PlatformUser, Role, RolePermission
from app.services import audit


@dataclass(frozen=True)
class SeedResult:
    permissions: int
    roles: int
    bootstrap_admin_email: str | None = None
    bootstrap_admin_temp_password: str | None = None  # shown once by the CLI


async def seed_reference_data(session: AsyncSession) -> tuple[int, int]:
    await session.execute(
        insert(Permission)
        .values([{"code": code, "description": text} for code, text in PERMISSIONS.items()])
        .on_conflict_do_update(index_elements=["code"], set_={"description": insert(Permission).excluded.description})
    )
    permission_ids = dict((await session.execute(select(Permission.code, Permission.id))).tuples().all())

    for code, name in ROLE_NAMES.items():
        role = (
            await session.execute(select(Role).where(Role.tenant_id.is_(None), Role.code == code))
        ).scalar_one_or_none()
        if role is None:
            role = Role(code=code, name=name, is_system=True)
            session.add(role)
            await session.flush()
        wanted = {permission_ids[p] for p in ROLE_PERMISSIONS[code]}
        current = set(
            (await session.execute(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)))
            .scalars()
            .all()
        )
        if missing := wanted - current:
            session.add_all(RolePermission(role_id=role.id, permission_id=pid) for pid in missing)
        if extra := current - wanted:
            await session.execute(
                delete(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_id.in_(extra))
            )
    return len(PERMISSIONS), len(ROLE_NAMES)


async def ensure_bootstrap_admin(session: AsyncSession, email: str) -> str | None:
    """Create the first PLATFORM_SUPER_ADMIN if no platform user exists. Returns the temp password once."""
    if not email:
        return None
    exists = (await session.execute(select(PlatformUser.id).limit(1))).first()
    if exists:
        return None
    temp_password = generate_temporary_password()
    admin = PlatformUser(
        email=email,
        password_hash=hash_password(temp_password),
        full_name="Platform Administrator",
        role="PLATFORM_SUPER_ADMIN",
        must_change_password=True,
        temp_password_expires_at=datetime.now(UTC) + TEMP_PASSWORD_TTL,
    )
    session.add(admin)
    await session.flush()
    await audit.record(
        session,
        action="PLATFORM_USER_CREATED",
        actor_type="system",
        actor_id=None,
        tenant_id=None,
        resource_type="platform_user",
        resource_id=admin.id,
        after={"email": email, "role": admin.role},
    )
    return temp_password


async def run_seed(session: AsyncSession, bootstrap_admin_email: str) -> SeedResult:
    permissions, roles = await seed_reference_data(session)
    temp_password = await ensure_bootstrap_admin(session, bootstrap_admin_email)
    return SeedResult(
        permissions=permissions,
        roles=roles,
        bootstrap_admin_email=bootstrap_admin_email if temp_password else None,
        bootstrap_admin_temp_password=temp_password,
    )
