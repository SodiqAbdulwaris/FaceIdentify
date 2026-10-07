"""The versioned application API: every router under `/api/v1` (API and Contracts section 3)."""

from fastapi import APIRouter

from backend.api.errors import ErrorEnvelope
from backend.api.routes import corrections, jobs, memory, people, processing, sources

api_router = APIRouter(
    prefix="/api/v1",
    responses={"default": {"model": ErrorEnvelope, "description": "The one error shape."}},
)
api_router.include_router(sources.router)
api_router.include_router(processing.router)
api_router.include_router(jobs.router)
api_router.include_router(memory.router)
api_router.include_router(people.router)
api_router.include_router(corrections.router)
