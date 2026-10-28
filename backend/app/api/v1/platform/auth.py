"""Platform staff authentication: /api/v1/platform/auth/*"""

from fastapi import APIRouter, Request, Response

from app.api.deps import (
    PLATFORM_COOKIES,
    PlatformCtxAllowPending,
    clear_session_cookies,
    request_info,
    set_session_cookies,
)
from app.core.database import platform_sessionmaker
from app.core.exceptions import Unauthorized
from app.core.security import InvalidAccessToken, decode_access_token
from app.models import PlatformUser
from app.schemas.auth import ChangePasswordRequest, LoginRequest, PlatformMeResponse, SessionResponse
from app.services import auth
from app.services.auth import LoginFailure

router = APIRouter(prefix="/auth", tags=["platform-auth"])


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> SessionResponse:
    async with platform_sessionmaker()() as session, session.begin():
        result = await auth.login(
            session,
            model=PlatformUser,
            email=body.email,
            password=body.password,
            tenant_id=None,
            request=request_info(request),
        )
    if isinstance(result, LoginFailure):
        raise result.error
    set_session_cookies(response, PLATFORM_COOKIES, result)
    return SessionResponse(must_change_password=result.must_change_password)


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> SessionResponse:
    token = request.cookies.get(PLATFORM_COOKIES.refresh)
    if not token:
        raise Unauthorized()
    async with platform_sessionmaker()() as session, session.begin():
        issued = await auth.refresh(
            session, refresh_token=token, expected_subject="platform_user", request=request_info(request)
        )
    if isinstance(issued, LoginFailure):
        clear_session_cookies(response, PLATFORM_COOKIES)
        raise issued.error
    set_session_cookies(response, PLATFORM_COOKIES, issued)
    return SessionResponse(must_change_password=issued.must_change_password)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(PLATFORM_COOKIES.access)
    if token:
        try:
            claims = decode_access_token(token)
        except InvalidAccessToken:
            claims = None
        if claims is not None and claims.subject_type == "platform_user":
            async with platform_sessionmaker()() as session, session.begin():
                await auth.logout(session, session_id=claims.session_id)
    clear_session_cookies(response, PLATFORM_COOKIES)
    response.status_code = 204
    return response


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest, ctx: PlatformCtxAllowPending, response: Response
) -> SessionResponse:
    issued = await auth.change_password(
        ctx.session,
        subject_type="platform_user",
        subject_id=ctx.user_id,
        tenant_id=None,
        current_password=body.current_password,
        new_password=body.new_password,
        request=ctx.request,
    )
    set_session_cookies(response, PLATFORM_COOKIES, issued)
    return SessionResponse(must_change_password=False)


@router.get("/me")
async def me(ctx: PlatformCtxAllowPending) -> PlatformMeResponse:
    return PlatformMeResponse(
        user_id=ctx.user_id,
        email=ctx.user.email,
        full_name=ctx.user.full_name,
        role=ctx.user.role,
        must_change_password=ctx.user.must_change_password,
    )
