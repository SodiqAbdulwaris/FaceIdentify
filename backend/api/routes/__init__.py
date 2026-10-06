"""The versioned application API: every router under `/api/v1` (API and Contracts section 3)."""

from fastapi import APIRouter

from backend.api.routes import sources

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(sources.router)
