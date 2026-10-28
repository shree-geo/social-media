from fastapi import APIRouter, Depends

from app.api.deps import verify_csrf
from app.api.v1 import auth, conversations, customers, events, users, webhooks
from app.api.v1.platform import auth as platform_auth
from app.api.v1.platform import tenants as platform_tenants

# Every cookie-authenticated route requires the CSRF header on state-changing methods.
# Webhooks are called by providers (no cookies), so they are mounted without CSRF.
api_router = APIRouter(dependencies=[Depends(verify_csrf)])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(customers.router)
api_router.include_router(conversations.router)
api_router.include_router(events.router)

platform_router = APIRouter(prefix="/platform")
platform_router.include_router(platform_auth.router)
platform_router.include_router(platform_tenants.router)
api_router.include_router(platform_router)

webhook_router = APIRouter()
webhook_router.include_router(webhooks.router)
