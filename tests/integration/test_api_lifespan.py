"""The API lifespan opens the library and `/readiness` reports the real lifecycle (M4 W1; TST-048).

Uses the real `open_library` on a temporary library through Starlette's test client, which runs the
application's lifespan. Waiting is on `Backend.settled`, a thread event, never on sleeping.
"""

import base64
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx
import pytest
from fastapi import FastAPI

from backend.api.app import create_app
from backend.api.startup import (
    NOT_STARTED,
    Backend,
    LibrarySettings,
    LifecycleState,
    backend_lifespan,
    capabilities_from,
    create_backend_app,
)
from backend.app.lifecycle import open_library
from backend.app.memory.erasure import ErasureReport
from backend.app.memory.index_coordinator import CoordinatorReport, RetryPolicy
from backend.app.recovery.startup import InterruptedWork, StartupReport
from backend.app.runtime.package_store import InstallRecoveryReport
from backend.app.sources.artifact_storage import RecoveryReport
from backend.infrastructure.db.unit_of_work import TransactionRetry
from backend.infrastructure.storage.library_lock import LibraryLock, LibraryLockedError
from backend.infrastructure.storage.workspaces import WorkspaceCleanup
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs


def token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def settings_for(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> LibrarySettings:
    (tmp_path / "library").mkdir()
    return LibrarySettings(
        library_root=tmp_path / "library",
        local_state_root=tmp_path / "local",
        clock=clock,
        new_id=new_id,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
        index_batch=50,
        max_index_passes=5,
    )


def app_and_backend(settings: LibrarySettings, launch_token: str) -> tuple[FastAPI, Backend]:
    backend = Backend(settings)
    app = create_app(launch_token, readiness=backend.readiness, lifespan=backend_lifespan(backend))
    return app, backend


def open_library_of(backend: Backend) -> object:
    return backend.library


def lock_is_free(root: Path) -> bool:
    try:
        with LibraryLock(root):
            return True
    except LibraryLockedError:
        return False


async def settled(backend: Backend) -> bool:
    """Wait for startup to finish without blocking the event loop that is running it."""
    return await anyio.to_thread.run_sync(backend.settled.wait, 30)


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_the_library_opens_after_serving_starts_and_readiness_says_ready(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = token()
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, secret)
    auth = {"Authorization": f"Bearer {secret}"}

    async with app.router.lifespan_context(app), client_for(app) as client:
        assert await settled(backend)
        body = (await client.get("/readiness", headers=auth)).json()

        assert body["state"] == "READY"
        assert body["capabilities"] == {
            "database": "READY",
            "storage": "READY",
            "index": "READY",
            "recovery": "READY",
            "ml_worker": NOT_STARTED,
            "scheduler": NOT_STARTED,
        }
        assert (await client.get("/readiness")).status_code == 401  # still authenticated
        assert backend.library is not None
        assert not lock_is_free(settings.library_root)  # the application holds the library

    assert backend.state is LifecycleState.SHUTTING_DOWN
    assert open_library_of(backend) is None  # the library was closed on the way out
    assert lock_is_free(settings.library_root)  # leaving the application released it


async def test_readiness_answers_initializing_while_the_library_is_still_opening(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = token()
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, secret)
    auth = {"Authorization": f"Bearer {secret}"}
    release = threading.Event()

    def slow_open(**kwargs: Any) -> Any:
        assert release.wait(30)  # recovery "still running" until the test lets it finish
        return open_library(**kwargs)

    monkeypatch.setattr("backend.api.startup.open_library", slow_open)

    async with app.router.lifespan_context(app), client_for(app) as client:
        assert (await client.get("/readiness", headers=auth)).json() == {"state": "INITIALIZING"}
        assert not backend.settled.is_set()
        release.set()
        assert await settled(backend)
        assert (await client.get("/readiness", headers=auth)).json()["state"] == "READY"


async def test_a_library_that_cannot_open_is_failed_by_class_name_and_still_answers(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = token()
    settings = settings_for(tmp_path, clock, new_id)
    missing = replace(settings, library_root=tmp_path / "no" / "such")
    app, backend = app_and_backend(missing, secret)
    auth = {"Authorization": f"Bearer {secret}"}

    async with app.router.lifespan_context(app), client_for(app) as client:
        assert await settled(backend)
        response = await client.get("/readiness", headers=auth)

        assert response.status_code == 200
        assert response.json() == {"state": "FAILED", "failure": backend.failure}
        assert backend.failure is not None
        assert str(tmp_path) not in response.text  # never a path
        assert (await client.get("/health", headers=auth)).json() == {"status": "ok"}

    assert backend.library is None


async def test_an_unreadable_recovery_report_is_failed_and_the_library_is_still_closed(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, token())

    def broken(report: StartupReport) -> dict[str, str]:
        raise KeyError("report")

    monkeypatch.setattr("backend.api.startup.capabilities_from", broken)

    async with app.router.lifespan_context(app):
        assert await settled(backend)
        assert backend.state is LifecycleState.FAILED
        assert backend.failure == "KeyError"
        assert not lock_is_free(settings.library_root)  # it did open ...
    assert lock_is_free(settings.library_root)  # ... and shutdown still released it


async def test_a_library_held_by_another_backend_fails_without_taking_it(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = token()
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, secret)

    with LibraryLock(settings.library_root):
        async with app.router.lifespan_context(app):
            assert await settled(backend)
            assert backend.state is LifecycleState.FAILED
            assert backend.failure == "LibraryLockedError"
        assert not lock_is_free(settings.library_root)  # still the other holder's
    assert lock_is_free(settings.library_root)


async def test_recovery_runs_before_the_application_reports_ready(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Whatever a crash left is reconciled by the time `READY` is reported (never after)."""
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, token())

    async with app.router.lifespan_context(app):
        assert await settled(backend)
        assert backend.library is not None
        assert backend.library.startup.clean  # recovery completed, and found nothing outstanding
        assert backend.state is LifecycleState.READY


async def test_a_degraded_capability_makes_the_application_degraded_but_usable(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = token()
    app, backend = app_and_backend(settings_for(tmp_path, clock, new_id), secret)
    real = capabilities_from

    def index_degraded(report: StartupReport) -> dict[str, str]:
        return real(report) | {"index": "DEGRADED"}

    monkeypatch.setattr("backend.api.startup.capabilities_from", index_degraded)

    async with app.router.lifespan_context(app), client_for(app) as client:
        assert await settled(backend)
        response = await client.get("/readiness", headers={"Authorization": f"Bearer {secret}"})

        assert response.json()["state"] == "DEGRADED"
        assert response.json()["capabilities"]["database"] == "READY"
        assert backend.state is LifecycleState.DEGRADED
        assert backend.library is not None  # degraded, not failed: the library is open


async def test_shutting_down_while_the_library_is_opening_still_releases_it(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocking open cannot be interrupted, so shutdown waits for it and then closes what it
    opened; otherwise the library lock would outlive the application."""
    settings = settings_for(tmp_path, clock, new_id)
    app, backend = app_and_backend(settings, token())
    entered, release = threading.Event(), threading.Event()

    def slow_open(**kwargs: Any) -> Any:
        entered.set()
        assert release.wait(30)
        return open_library(**kwargs)

    monkeypatch.setattr("backend.api.startup.open_library", slow_open)

    async with app.router.lifespan_context(app):
        assert await anyio.to_thread.run_sync(entered.wait, 30)  # the open is in flight
        threading.Timer(0.2, release.set).start()  # let it finish while shutdown is waiting

    assert backend.settled.is_set()  # shutdown waited for the open ...
    assert lock_is_free(settings.library_root)  # ... and then released what it had opened


async def test_create_backend_app_wires_the_lifespan_and_readiness(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = token()
    app = create_backend_app(secret, settings_for(tmp_path, clock, new_id))

    async with app.router.lifespan_context(app), client_for(app) as client:
        assert await settled(app.state.backend)
        response = await client.get("/readiness", headers={"Authorization": f"Bearer {secret}"})
        assert response.json()["state"] == "READY"


def clean_report() -> StartupReport:
    return StartupReport(
        artifacts=RecoveryReport(),
        missing_references=[],
        missing_managed=[],
        interrupted=InterruptedWork(),
        workspaces=WorkspaceCleanup(),
        indexes_rebuilt=[],
        requeued_operations=[],
        index_operations=CoordinatorReport(),
        index_passes=0,
        erasure=ErasureReport(),
        packages=InstallRecoveryReport(),
    )


def _storage(report: StartupReport) -> None:
    report.artifacts.staging_left.append("staging/orphan")


def _workspace(report: StartupReport) -> None:
    report.workspaces.failed.append((uuid.uuid4(), "locked"))


def _index(report: StartupReport) -> None:
    report.index_operations.failed.append((uuid.uuid4(), "out of attempts"))


def _unindexable(report: StartupReport) -> None:
    report.index_operations.unindexable.append(uuid.uuid4())


def _erasure(report: StartupReport) -> None:
    report.erasure.errors.append("truncate_wal: busy")


def _packages(report: StartupReport) -> None:
    report.packages.invalid.append("fixture-package")


@pytest.mark.parametrize(
    ("damage", "capability"),
    [
        (_storage, "storage"),
        (_workspace, "storage"),
        (_index, "index"),
        (_unindexable, "index"),
        (_erasure, "recovery"),
        (_packages, "recovery"),
    ],
)
def test_outstanding_recoverable_work_degrades_only_the_matching_capability(
    damage: Callable[[StartupReport], None], capability: str
) -> None:
    clean = capabilities_from(clean_report())
    assert {value for key, value in clean.items() if key not in ("ml_worker", "scheduler")} == {
        "READY"
    }
    report = clean_report()
    damage(report)

    degraded = capabilities_from(report)

    assert degraded[capability] == "DEGRADED"
    assert {key for key, value in degraded.items() if value == "DEGRADED"} == {capability}
