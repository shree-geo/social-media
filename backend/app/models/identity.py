"""Tenant users, memberships, roles/permissions and auth tokens (DATABASE.md §5)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantOwned, Timestamps, UUIDPrimaryKey, check_in

TENANT_ROLES = ("OWNER", "ADMIN", "MANAGER", "SALES", "DELIVERY", "ACCOUNTANT", "VIEWER")
SUBJECT_TYPES = ("user", "platform_user")


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (Index("users_email_key", "email", unique=True, postgresql_where=text("deleted_at IS NULL")),)

    email: Mapped[str] = mapped_column(CITEXT)
    password_hash: Mapped[str]
    full_name: Mapped[str]
    phone: Mapped[str | None]
    email_verified_at: Mapped[datetime | None]
    must_change_password: Mapped[bool] = mapped_column(server_default=text("true"))
    temp_password_expires_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    mfa_secret_enc: Mapped[bytes | None]
    mfa_enabled_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class TenantOnboarding(Timestamps, Base):
    __tablename__ = "tenant_onboarding"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    dismissed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class TenantMembership(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "tenant_memberships"
    __extra_table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(check_in("status", ("active", "disabled")), name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    joined_at: Mapped[datetime | None]
    disabled_at: Mapped[datetime | None]


class Role(UUIDPrimaryKey, Timestamps, Base):
    """System roles have ``tenant_id IS NULL``; custom tenant roles are post-MVP."""

    __tablename__ = "roles"
    __table_args__ = (
        Index(
            "roles_tenant_code_key",
            text("coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "code",
            unique=True,
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    code: Mapped[str]
    name: Mapped[str]
    is_system: Mapped[bool] = mapped_column(server_default=text("false"))


class Permission(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class MembershipRole(CreatedAt, Base):
    __tablename__ = "membership_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.id"],
            ondelete="CASCADE",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    granted_by: Mapped[uuid.UUID | None]


class AuthToken(UUIDPrimaryKey, CreatedAt, Base):
    """Single-use email verification and password reset tokens (hash only)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(check_in("subject_type", SUBJECT_TYPES), name="subject_type"),
        CheckConstraint(check_in("purpose", ("verify_email", "password_reset")), name="purpose"),
    )

    subject_type: Mapped[str]
    subject_id: Mapped[uuid.UUID]
    purpose: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class RefreshToken(UUIDPrimaryKey, CreatedAt, Base):
    """Rotating refresh tokens. Reuse of a rotated token revokes the whole family."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(check_in("subject_type", SUBJECT_TYPES), name="subject_type"),
        Index(
            "ix_refresh_tokens_active_subject",
            "subject_type",
            "subject_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    subject_type: Mapped[str]
    subject_id: Mapped[uuid.UUID]
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    active_tenant_id: Mapped[uuid.UUID | None]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by_id: Mapped[uuid.UUID | None]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
