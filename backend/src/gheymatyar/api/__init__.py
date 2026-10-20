"""API route package."""

from fastapi import APIRouter

from gheymatyar.api.health import router as health_router
from gheymatyar.api.mappings import router as mappings_router
from gheymatyar.api.sessions import router as sessions_router
from gheymatyar.api.settings import router as settings_router
from gheymatyar.api.suppliers import router as suppliers_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(suppliers_router)
api_router.include_router(mappings_router)
api_router.include_router(sessions_router)
api_router.include_router(settings_router)
