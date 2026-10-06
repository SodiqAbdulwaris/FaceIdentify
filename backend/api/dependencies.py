"""What a route may depend on: the backend, and an open library (API section 25: 503).

A route that uses the library takes `Library`. Until the backend reports the library open
(`READY`, or `DEGRADED`, which still serves) the request is answered `503 LIBRARY_UNAVAILABLE`:
retryable while the backend is still starting, not once startup failed or shutdown began. The
body carries the lifecycle state (and, for a failed start, the exception class name) and nothing
else.
"""

from typing import Annotated

from fastapi import Depends, Request

from backend.api.errors import ApiError
from backend.api.startup import Backend, LifecycleState
from backend.app.lifecycle import OpenLibrary

SERVING = (LifecycleState.READY, LifecycleState.DEGRADED)


def get_backend(request: Request) -> Backend:
    backend: Backend = request.app.state.backend
    return backend


def require_library(backend: Annotated[Backend, Depends(get_backend)]) -> OpenLibrary:
    library = backend.library
    if library is None or backend.state not in SERVING:
        details: dict[str, str] = {"state": backend.state.value}
        if backend.failure is not None:
            details["failure"] = backend.failure
        raise ApiError(
            503,
            "LIBRARY_UNAVAILABLE",
            "The library is not available.",
            details=details,
            retryable=backend.state is LifecycleState.INITIALIZING,
        )
    return library


Library = Annotated[OpenLibrary, Depends(require_library)]
