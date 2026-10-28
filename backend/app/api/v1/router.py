from fastapi import APIRouter, Depends

from app.api.deps import verify_csrf
from app.api.v1 import auth, users
from app.api.v1.platform import auth as platform_auth
from app.api.v1.platform import tenants as platform_tenants

# Every cookie-authenticated route requires the CSRF header on state-changing methods.
# Webhook routers (Meta) are mounted separately, without CSRF, when they are added.
api_router = APIRouter(dependencies=[Depends(verify_csrf)])
api_router.include_router(auth.router)
api_router.include_router(users.router)

platform_router = APIRouter(prefix="/platform")
platform_router.include_router(platform_auth.router)
platform_router.include_router(platform_tenants.router)
api_router.include_router(platform_router)
