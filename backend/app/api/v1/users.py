"""Tenant staff logins: /api/v1/users"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import TenantContext, require
from app.core.config import get_settings
from app.core.exceptions import Forbidden
from app.models import MembershipRole, Role, TenantMembership, User
from app.schemas.auth import StrictModel
from app.schemas.platform import LoginDetailsOut
from app.services import entitlements, users
from app.services.login_messages import share_message

router = APIRouter(prefix="/users", tags=["users"])

StaffRole = Literal["ADMIN", "MANAGER", "SALES", "DELIVERY", "ACCOUNTANT", "VIEWER", "OWNER"]


class UserCreate(StrictModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    role: StaffRole


class UserOut(BaseModel):
    user_id: str
    full_name: str
    email: str
    roles: list[str]
    status: str
    must_change_password: bool


@router.get("")
async def list_users(ctx: Annotated[TenantContext, Depends(require("user.manage"))]) -> list[UserOut]:
    rows = await ctx.session.execute(
        select(TenantMembership, User, Role.code)
        .join(User, User.id == TenantMembership.user_id)
        .outerjoin(MembershipRole, MembershipRole.membership_id == TenantMembership.id)
        .outerjoin(Role, Role.id == MembershipRole.role_id)
        .where(TenantMembership.tenant_id == ctx.tenant_id)
        .order_by(User.full_name)
    )
    by_user: dict[str, UserOut] = {}
    for membership, user, role_code in rows:
        item = by_user.setdefault(
            str(user.id),
            UserOut(
                user_id=str(user.id),
                full_name=user.full_name,
                email=user.email,
                roles=[],
                status=membership.status,
                must_change_password=user.must_change_password,
            ),
        )
        if role_code:
            item.roles.append(role_code)
    return list(by_user.values())


@router.post("", status_code=201)
async def create_user(
    body: UserCreate, ctx: Annotated[TenantContext, Depends(require("user.manage", write=True))]
) -> LoginDetailsOut:
    if body.role == "OWNER" and "OWNER" not in ctx.roles:
        raise Forbidden("Only an Owner can add another Owner.")
    await entitlements.require_capacity(
        ctx.session, tenant_id=ctx.tenant_id, plan_id=ctx.subscription.plan_id, key="max_users"
    )
    details = await users.add_tenant_user(
        ctx.session,
        tenant_id=ctx.tenant_id,
        email=body.email,
        full_name=body.full_name,
        phone=body.phone,
        role_code=body.role,
        actor_type="user",
        actor_id=ctx.user_id,
        request=ctx.request,
    )
    settings = get_settings()
    login_url = f"{settings.app_base_url}/login"
    message = None
    if details.temporary_password and details.expires_at:
        message = share_message(
            app_name=settings.app_name,
            login_url=login_url,
            full_name=body.full_name,
            email=details.email,
            temporary_password=details.temporary_password,
            expires_at=details.expires_at,
        )
    return LoginDetailsOut(
        login_url=login_url,
        email=details.email,
        temporary_password=details.temporary_password,
        expires_at=details.expires_at,
        share_message=message,
    )
