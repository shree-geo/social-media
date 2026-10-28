"""All models are imported here so Alembic sees the full metadata."""

from app.models.base import Base
from app.models.identity import (
    AuthToken,
    MembershipRole,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    TenantMembership,
    TenantOnboarding,
    User,
)
from app.models.platform import (
    Plan,
    PlanFeature,
    PlanPrice,
    PlatformUser,
    Subscription,
    SubscriptionHistory,
    SubscriptionPayment,
    Tenant,
    TenantSettings,
    UsageRecord,
)
from app.models.system import AuditLog, DocumentSequence, IdempotencyKey, Notification, StoredObject

__all__ = [
    "AuditLog",
    "AuthToken",
    "Base",
    "DocumentSequence",
    "IdempotencyKey",
    "MembershipRole",
    "Notification",
    "Permission",
    "Plan",
    "PlanFeature",
    "PlanPrice",
    "PlatformUser",
    "RefreshToken",
    "Role",
    "RolePermission",
    "StoredObject",
    "Subscription",
    "SubscriptionHistory",
    "SubscriptionPayment",
    "Tenant",
    "TenantMembership",
    "TenantOnboarding",
    "TenantSettings",
    "UsageRecord",
    "User",
]
