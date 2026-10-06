"""The API process's startup coordinator and lifespan (Architecture section 22; M4 W1).

FastAPI starts serving at once; the library is opened afterwards, in a worker thread, so the shell
can poll `/readiness` and see `INITIALIZING` instead of a refused connection while migrations and
recovery run. Opening the library (`open_library`) is the staged startup: lock, migrations, layout,
recovery, indexes. Nothing may claim work before it finishes; the scheduler (W2) is created only
after this reports the library open, so recovery and normal scheduling never race over a job.

`/readiness` says only what is true: the library capabilities come from the recovery report; the
scheduler is `NOT_CONFIGURED` unless processing was configured, then `READY` while its loop runs
(`DEGRADED` while its last look failed); the ML worker is `NOT_CONFIGURED` until it is wired. A
failure to open the library is `FAILED` with the exception's class name (never a path, never the
launch capability) and the process keeps answering, so the shell can show why. Leaving the
application stops the scheduler first (the call in flight finishes, nothing more is claimed), then
releases the library lock.
"""

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from fastapi import FastAPI

from backend.api.app import BackendReadiness, create_app
from backend.api.scheduler import SchedulerService
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.processing.runner import ProcessingRunner, RunOutcome
from backend.app.processing.scheduler import ProcessingScheduler
from backend.app.recovery.startup import StartupReport
from backend.app.runtime.worker_config import PerceptionPlan
from backend.infrastructure.db.unit_of_work import TransactionRetry

NOT_CONFIGURED: Final = "NOT_CONFIGURED"


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


@dataclass(frozen=True)
class ProcessingSettings:
    """Turns on the scheduler loop. No defaults: the limits are unmeasured, so the host chooses
    them. `client_for` is the perception boundary (a fake until real weights are cleared, #69)."""

    client_for: Callable[[PerceptionPlan], Any]
    max_pixels: int
    recognition_k: int
    lease_for: timedelta
    idle_seconds: float
    owner: str


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
        "ml_worker": NOT_CONFIGURED,
        "scheduler": NOT_CONFIGURED,
    }


@dataclass
class Backend:
    """What the API process owns: the library once opened, and the lifecycle around it."""

    settings: LibrarySettings
    processing: ProcessingSettings | None = None
    state: LifecycleState = LifecycleState.INITIALIZING
    scheduler: SchedulerService | None = None
    library: OpenLibrary | None = None
    failure: str | None = None
    capabilities: dict[str, str] = field(default_factory=dict)
    # Set once startup has finished, whether it opened the library or failed. Thread-safe, so a
    # test can wait for it instead of sleeping.
    settled: threading.Event = field(default_factory=threading.Event)
    _opened: AbstractContextManager[OpenLibrary] | None = None

    def readiness(self) -> BackendReadiness:
        capabilities = dict(self.capabilities)
        scheduler = self.scheduler
        if scheduler is not None:
            if not scheduler.running:
                capabilities["scheduler"] = "STOPPED"
            else:
                capabilities["scheduler"] = "DEGRADED" if scheduler.last_error else "READY"
        return BackendReadiness(self.state.value, capabilities, self.failure)

    def wake_scheduler(self) -> None:
        """Ask the scheduler to look at the queue now (a job was queued). Safe from any thread."""
        if self.scheduler is not None:
            self.scheduler.wake()

    async def _boot(self) -> None:
        """Open the library, and only then start the scheduler: recovery has finished, so the loop
        and recovery can never race over the same job or run."""
        await anyio.to_thread.run_sync(self._open)
        library, processing = self.library, self.processing
        if library is not None and processing is not None and self.state != LifecycleState.FAILED:
            self.scheduler = SchedulerService(
                self._run_once_for(library, processing), idle_seconds=processing.idle_seconds
            )
            self.scheduler.start()

    def _run_once_for(
        self, library: OpenLibrary, processing: ProcessingSettings
    ) -> Callable[[], RunOutcome]:
        settings, uow = self.settings, library.unit_of_work

        def wake_index() -> None:
            library.coordinator.apply_pending(limit=settings.index_batch)

        runner = ProcessingRunner(
            uow,
            ProcessingScheduler(
                uow, new_id=settings.new_id, clock=settings.clock, lease_for=processing.lease_for
            ),
            ExecuteProcessingJob(
                uow,
                packages=library.packages,
                files=library.store,
                client_for=processing.client_for,
                global_index_for=library.coordinator.open_for_recognition,
                new_id=settings.new_id,
                clock=settings.clock,
                max_pixels=processing.max_pixels,
                recognition_k=processing.recognition_k,
            ),
            AcceptProcessingRunUseCase(
                uow, new_id=settings.new_id, clock=settings.clock, wake_index=wake_index
            ),
            owner=processing.owner,
            clock=settings.clock,
        )
        return runner.run_once

    async def _shutdown(self) -> None:
        if self.scheduler is not None:
            await self.scheduler.stop()
        self.state = LifecycleState.SHUTTING_DOWN
        await anyio.to_thread.run_sync(self._close)

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
            self._opened = opened  # recorded first: shutdown closes it whatever happens next
            self.library = library
            try:
                self.capabilities = capabilities_from(library.startup)
            except Exception as error:  # noqa: BLE001 - an unreadable report is FAILED, not a crash
                self.failure = type(error).__name__
                self.state = LifecycleState.FAILED
            else:
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
        starting = asyncio.create_task(backend._boot())
        try:
            yield
        finally:
            await starting  # a blocking open cannot be interrupted: let it finish, then undo it
            await backend._shutdown()

    return lifespan


def create_backend_app(
    launch_token: str, settings: LibrarySettings, processing: ProcessingSettings | None = None
) -> FastAPI:
    """The authenticated application whose lifespan opens the library (and, when `processing` is
    given, then starts the scheduler) and whose `/readiness` reports the real lifecycle."""
    backend = Backend(settings, processing)
    return create_app(launch_token, readiness=backend.readiness, lifespan=backend_lifespan(backend))
