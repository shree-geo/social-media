"""Request dependencies: cookies, CSRF, tenant/platform context, permissions, subscription access.

Transactions are opened by these dependencies with ``scope="function"`` so they
commit (or roll back) *before* the response is sent.
"""

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import platform_sessionmaker, runtime_sessionmaker, set_tenant_context
from app.core.exceptions import AppError, Forbidden, Unauthorized
from app.core.security import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL, AccessClaims, InvalidAccessToken, decode_access_token
from app.models import MembershipRole, Permission, PlatformUser, Role, RolePermission, Tenant, TenantMembership, User
from app.services.audit import RequestInfo
from app.services.auth import IssuedSession
from app.services.subscriptions import Access, SubscriptionState, current_state, tenant_today

CSRF_COOKIE = "sc_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class CookieSet:
    access: str
    refresh: str
    refresh_path: str


TENANT_COOKIES = CookieSet("sc_at", "sc_rt", "/api/v1/auth")
PLATFORM_COOKIES = CookieSet("sc_pat", "sc_prt", "/api/v1/platform/auth")


class PasswordChangeRequired(AppError):
    status, code, title = 403, "password_change_required", "Please set your own password first"


class SubscriptionReadOnly(AppError):
    status, code, title = 403, "subscription_read_only", "Your subscription has expired. Renew to make changes."


class SubscriptionBlocked(AppError):
    status, code, title = 403, "subscription_blocked", "This account is suspended. Please contact us."


# --- request info, cookies, CSRF ---------------------------------------------------


def request_info(request: Request) -> RequestInfo:
    return RequestInfo(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


def set_session_cookies(response: Response, cookies: CookieSet, issued: IssuedSession) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(
        cookies.access,
        issued.access_token,
        max_age=int(ACCESS_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        cookies.refresh,
        issued.refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="strict",
        path=cookies.refresh_path,
    )


def clear_session_cookies(response: Response, cookies: CookieSet) -> None:
    response.delete_cookie(cookies.access, path="/")
    response.delete_cookie(cookies.refresh, path=cookies.refresh_path)


def issue_csrf_cookie(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, token, httponly=False, secure=get_settings().cookie_secure, samesite="strict", path="/"
    )
    return token


async def verify_csrf(request: Request) -> None:
    """Double-submit check for every state-changing request made with cookies."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise Forbidden("Missing or invalid CSRF token", code="csrf_failed")


# --- claims ------------------------------------------------------------------------


def _claims(request: Request, cookie: str, subject_type: str) -> AccessClaims:
    token = request.cookies.get(cookie)
    if not token:
        raise Unauthorized()
    try:
        claims = decode_access_token(token)
    except InvalidAccessToken as exc:
        raise Unauthorized("Session expired. Please log in again.") from exc
    if claims.subject_type != subject_type:
        raise Unauthorized()
    return claims


def tenant_claims(request: Request) -> AccessClaims:
    return _claims(request, TENANT_COOKIES.access, "user")


def platform_claims(request: Request) -> AccessClaims:
    return _claims(request, PLATFORM_COOKIES.access, "platform_user")


# --- tenant context ----------------------------------------------------------------


@dataclass
class TenantContext:
    session: AsyncSession
    user: User
    tenant: Tenant
    membership_id: uuid.UUID
    session_id: uuid.UUID
    roles: frozenset[str]
    permissions: frozenset[str]
    subscription: SubscriptionState
    request: RequestInfo

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


async def _load_tenant_context(
    session: AsyncSession, claims: AccessClaims, info: RequestInfo, *, allow_password_change: bool
) -> TenantContext:
    if claims.tenant_id is None:
        raise Unauthorized()
    await set_tenant_context(session, claims.tenant_id)

    user = await session.get(User, claims.subject_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized()
    if user.must_change_password and not allow_password_change:
        raise PasswordChangeRequired()

    membership = (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == claims.tenant_id,
                TenantMembership.user_id == user.id,
                TenantMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    tenant = await session.get(Tenant, claims.tenant_id)  # RLS: only the current tenant is visible
    if membership is None or tenant is None or tenant.status != "active":
        raise Unauthorized("Your access to this business has ended.")

    rows = await session.execute(
        select(Role.code, Permission.code)
        .select_from(MembershipRole)
        .join(Role, Role.id == MembershipRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(MembershipRole.membership_id == membership.id)
    )
    roles: set[str] = set()
    permissions: set[str] = set()
    for role_code, permission_code in rows:
        roles.add(role_code)
        if permission_code:
            permissions.add(permission_code)

    subscription = await current_state(session, tenant.id, tenant_today(tenant.timezone))
    return TenantContext(
        session=session,
        user=user,
        tenant=tenant,
        membership_id=membership.id,
        session_id=claims.session_id,
        roles=frozenset(roles),
        permissions=frozenset(permissions),
        subscription=subscription,
        request=info,
    )


async def _tenant_context(request: Request, allow_password_change: bool) -> AsyncIterator[TenantContext]:
    claims = tenant_claims(request)
    async with runtime_sessionmaker()() as session, session.begin():
        ctx = await _load_tenant_context(
            session, claims, request_info(request), allow_password_change=allow_password_change
        )
        if ctx.subscription.access is Access.BLOCKED and not allow_password_change:
            raise SubscriptionBlocked()
        yield ctx


async def tenant_context(request: Request) -> AsyncIterator[TenantContext]:
    async for ctx in _tenant_context(request, allow_password_change=False):
        yield ctx


async def tenant_context_allow_pending(request: Request) -> AsyncIterator[TenantContext]:
    """For ``me``, ``change-password`` and ``logout``: usable before the first password change."""
    async for ctx in _tenant_context(request, allow_password_change=True):
        yield ctx


TenantCtx = Annotated[TenantContext, Depends(tenant_context, scope="function")]
TenantCtxAllowPending = Annotated[TenantContext, Depends(tenant_context_allow_pending, scope="function")]


def require(*permissions: str, write: bool = False) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Permission check; ``write=True`` also requires a subscription that allows changes."""

    async def dependency(ctx: TenantCtx) -> TenantContext:
        if missing := set(permissions) - ctx.permissions:
            raise Forbidden("You don't have permission to do this.", missing=sorted(missing))
        if write and ctx.subscription.access is not Access.FULL:
            raise SubscriptionReadOnly()
        return ctx

    return dependency


# --- platform context --------------------------------------------------------------


@dataclass
class PlatformContext:
    session: AsyncSession
    user: PlatformUser
    session_id: uuid.UUID
    request: RequestInfo

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


async def _platform_context(request: Request, allow_password_change: bool) -> AsyncIterator[PlatformContext]:
    claims = platform_claims(request)
    async with platform_sessionmaker()() as session, session.begin():
        user = await session.get(PlatformUser, claims.subject_id)
        if user is None or not user.is_active:
            raise Unauthorized()
        if user.must_change_password and not allow_password_change:
            raise PasswordChangeRequired()
        yield PlatformContext(session, user, claims.session_id, request_info(request))


async def platform_context(request: Request) -> AsyncIterator[PlatformContext]:
    async for ctx in _platform_context(request, allow_password_change=False):
        yield ctx


async def platform_context_allow_pending(request: Request) -> AsyncIterator[PlatformContext]:
    async for ctx in _platform_context(request, allow_password_change=True):
        yield ctx


PlatformCtx = Annotated[PlatformContext, Depends(platform_context, scope="function")]
PlatformCtxAllowPending = Annotated[PlatformContext, Depends(platform_context_allow_pending, scope="function")]


def require_platform_role(*roles: str) -> Callable[[PlatformContext], Awaitable[PlatformContext]]:
    async def dependency(ctx: PlatformCtx) -> PlatformContext:
        if ctx.user.role not in roles:
            raise Forbidden("You don't have permission to do this.")
        return ctx

    return dependency


PLATFORM_ADMINS = ("PLATFORM_SUPER_ADMIN", "PLATFORM_ADMIN")
PLATFORM_ALL = ("PLATFORM_SUPER_ADMIN", "PLATFORM_ADMIN", "PLATFORM_SUPPORT")
