"""The API process's startup coordinator and lifespan (Architecture section 22; M4 W1).

FastAPI starts serving at once; the library is opened afterwards, in a worker thread, so the shell
can poll `/readiness` and see `INITIALIZING` instead of a refused connection while migrations and
recovery run. Opening the library (`open_library`) is the staged startup: lock, migrations, layout,
recovery, indexes. Nothing may claim work before it finishes; the scheduler (W2) is created only
after this reports the library open, so recovery and normal scheduling never race over a job.

`/readiness` says only what is true: the library capabilities come from the recovery report, and
the ML worker and the scheduler are `NOT_STARTED` until W2 builds them. A failure to open the
library is `FAILED` with the exception's class name (never a path, never the launch capability) and
the process keeps answering, so the shell can show why. Leaving the application releases the
library lock.
"""

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

import anyio.to_thread
from fastapi import FastAPI

from backend.api.app import BackendReadiness, create_app
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.recovery.startup import StartupReport
from backend.infrastructure.db.unit_of_work import TransactionRetry

NOT_STARTED: Final = "NOT_STARTED"


class LifecycleState(StrEnum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    SHUTTING_DOWN = "SHUTTING_DOWN"


@dataclass(frozen=True)
class LibrarySettings:
    """Everything `open_library` needs. There are no defaults: the retry policies and the index
    catch-up limits are unmeasured thresholds, so the caller (the sidecar host) chooses them."""

    library_root: Path
    local_state_root: Path
    clock: Callable[[], datetime]
    new_id: Callable[[], uuid.UUID]
    retry: RetryPolicy
    transaction_retry: TransactionRetry
    index_batch: int
    max_index_passes: int


def capabilities_from(report: StartupReport) -> dict[str, str]:
    """Readiness capabilities from what recovery found. `DEGRADED` means something recoverable is
    outstanding (a reconstructible index, a locked file); the library itself is usable."""
    artifacts, operations = report.artifacts, report.index_operations
    degraded = "DEGRADED"
    return {
        "database": "READY",  # migrations ran, or the library would not have opened
        "storage": degraded
        if artifacts.skipped
        or artifacts.staging_left
        or artifacts.delete_failed
        or report.workspaces.failed
        else "READY",
        "index": degraded
        if operations.unindexable
        or operations.leftover_files
        or operations.retrying
        or operations.failed
        else "READY",
        "recovery": degraded
        if report.erasure.outstanding_cleanup or report.packages.left or report.packages.invalid
        else "READY",
        "ml_worker": NOT_STARTED,
        "scheduler": NOT_STARTED,
    }


@dataclass
class Backend:
    """What the API process owns: the library once opened, and the lifecycle around it."""

    settings: LibrarySettings
    state: LifecycleState = LifecycleState.INITIALIZING
    library: OpenLibrary | None = None
    failure: str | None = None
    capabilities: dict[str, str] = field(default_factory=dict)
    # Set once startup has finished, whether it opened the library or failed. Thread-safe, so a
    # test can wait for it instead of sleeping.
    settled: threading.Event = field(default_factory=threading.Event)
    _opened: AbstractContextManager[OpenLibrary] | None = None

    def readiness(self) -> BackendReadiness:
        return BackendReadiness(self.state.value, dict(self.capabilities))

    def _open(self) -> None:
        """Open the library (blocking: migrations and recovery). Runs in a worker thread."""
        settings = self.settings
        try:
            opened = open_library(
                library_root=settings.library_root,
                local_state_root=settings.local_state_root,
                clock=settings.clock,
                new_id=settings.new_id,
                retry=settings.retry,
                transaction_retry=settings.transaction_retry,
                index_batch=settings.index_batch,
                max_index_passes=settings.max_index_passes,
            )
            library = opened.__enter__()
        except Exception as error:  # noqa: BLE001 - any failure is FAILED, reported by class name
            self.failure = type(error).__name__
            self.state = LifecycleState.FAILED
        else:
            self._opened = opened
            self.library = library
            self.capabilities = capabilities_from(library.startup)
            degraded = any(value == "DEGRADED" for value in self.capabilities.values())
            self.state = LifecycleState.DEGRADED if degraded else LifecycleState.READY
        finally:
            self.settled.set()

    def _close(self) -> None:
        opened, self._opened, self.library = self._opened, None, None
        if opened is not None:
            opened.__exit__(None, None, None)  # disposes the engine, then releases the lock


def backend_lifespan(backend: Backend) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.backend = backend
        starting = asyncio.create_task(anyio.to_thread.run_sync(backend._open))
        try:
            yield
        finally:
            await starting  # a blocking open cannot be interrupted: let it finish, then undo it
            backend.state = LifecycleState.SHUTTING_DOWN
            await anyio.to_thread.run_sync(backend._close)

    return lifespan


def create_backend_app(launch_token: str, settings: LibrarySettings) -> FastAPI:
    """The authenticated application whose lifespan opens the library and whose `/readiness`
    reports the real lifecycle."""
    backend = Backend(settings)
    return create_app(launch_token, readiness=backend.readiness, lifespan=backend_lifespan(backend))
