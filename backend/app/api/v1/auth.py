"""Tenant user authentication: /api/v1/auth/*"""

from fastapi import APIRouter, Request, Response

from app.api.deps import (
    TENANT_COOKIES,
    TenantCtxAllowPending,
    clear_session_cookies,
    issue_csrf_cookie,
    request_info,
    set_session_cookies,
)
from app.core.database import runtime_sessionmaker
from app.core.exceptions import Unauthorized
from app.core.security import InvalidAccessToken, decode_access_token
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    CsrfResponse,
    LoginRequest,
    MembershipOut,
    MeResponse,
    SessionResponse,
    SubscriptionOut,
    SwitchTenantRequest,
)
from app.services import auth
from app.services.auth import LoginFailure

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/csrf")
async def csrf(response: Response) -> CsrfResponse:
    return CsrfResponse(csrf_token=issue_csrf_cookie(response))


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> SessionResponse:
    async with runtime_sessionmaker()() as session, session.begin():
        result = await auth.login(
            session,
            model=User,
            email=body.email,
            password=body.password,
            tenant_id=body.tenant_id,
            request=request_info(request),
        )
    # Failure counters and audit rows are committed above before the error is raised.
    if isinstance(result, LoginFailure):
        raise result.error
    set_session_cookies(response, TENANT_COOKIES, result)
    return SessionResponse(must_change_password=result.must_change_password, tenant_id=result.tenant_id)


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> SessionResponse:
    token = request.cookies.get(TENANT_COOKIES.refresh)
    if not token:
        raise Unauthorized()
    async with runtime_sessionmaker()() as session, session.begin():
        issued = await auth.refresh(
            session, refresh_token=token, expected_subject="user", request=request_info(request)
        )
    if isinstance(issued, LoginFailure):
        clear_session_cookies(response, TENANT_COOKIES)
        raise issued.error
    set_session_cookies(response, TENANT_COOKIES, issued)
    return SessionResponse(must_change_password=issued.must_change_password, tenant_id=issued.tenant_id)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(TENANT_COOKIES.access)
    if token:
        try:
            claims = decode_access_token(token)
        except InvalidAccessToken:
            claims = None
        if claims is not None:
            async with runtime_sessionmaker()() as session, session.begin():
                await auth.logout(session, session_id=claims.session_id)
    clear_session_cookies(response, TENANT_COOKIES)
    response.status_code = 204
    return response


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest, ctx: TenantCtxAllowPending, response: Response
) -> SessionResponse:
    issued = await auth.change_password(
        ctx.session,
        subject_type="user",
        subject_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        current_password=body.current_password,
        new_password=body.new_password,
        request=ctx.request,
    )
    set_session_cookies(response, TENANT_COOKIES, issued)
    return SessionResponse(must_change_password=False, tenant_id=ctx.tenant_id)


@router.post("/switch-tenant")
async def switch_tenant(body: SwitchTenantRequest, ctx: TenantCtxAllowPending, response: Response) -> SessionResponse:
    issued = await auth.switch_tenant(
        ctx.session, user_id=ctx.user_id, session_id=ctx.session_id, tenant_id=body.tenant_id, request=ctx.request
    )
    set_session_cookies(response, TENANT_COOKIES, issued)
    return SessionResponse(must_change_password=issued.must_change_password, tenant_id=issued.tenant_id)


@router.get("/me")
async def me(ctx: TenantCtxAllowPending) -> MeResponse:
    memberships = await auth.memberships_for(ctx.session, ctx.user_id)
    sub = ctx.subscription
    return MeResponse(
        user_id=ctx.user_id,
        email=ctx.user.email,
        full_name=ctx.user.full_name,
        must_change_password=ctx.user.must_change_password,
        email_verified=ctx.user.email_verified_at is not None,
        tenant_id=ctx.tenant_id,
        business_name=ctx.tenant.business_name,
        roles=sorted(ctx.roles),
        permissions=sorted(ctx.permissions),
        subscription=SubscriptionOut(
            status=sub.status, access=sub.access.value, expiry_date=sub.expiry_date, days_remaining=sub.days_remaining
        ),
        memberships=[MembershipOut(tenant_id=m.tenant_id, business_name=m.business_name) for m in memberships],
    )
