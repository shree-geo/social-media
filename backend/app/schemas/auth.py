import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    tenant_id: uuid.UUID | None = None


class ChangePasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SwitchTenantRequest(StrictModel):
    tenant_id: uuid.UUID


class CsrfResponse(BaseModel):
    csrf_token: str


class SessionResponse(BaseModel):
    must_change_password: bool
    tenant_id: uuid.UUID | None = None


class MembershipOut(BaseModel):
    tenant_id: uuid.UUID
    business_name: str


class SubscriptionOut(BaseModel):
    status: str | None
    access: str
    expiry_date: date | None
    days_remaining: int | None


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    must_change_password: bool
    email_verified: bool
    tenant_id: uuid.UUID
    business_name: str
    roles: list[str]
    permissions: list[str]
    subscription: SubscriptionOut
    memberships: list[MembershipOut]


class PlatformMeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    must_change_password: bool
