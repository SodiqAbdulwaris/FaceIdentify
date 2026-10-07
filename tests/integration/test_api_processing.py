"""The API process runs queued jobs: the scheduler loop starts only after the library opened, picks
up work, and reports itself in `/readiness` (M4 W2.3; TST-048, TST-060).

Perception is planted (no weights); the library, scheduler, executor, acceptance and index are
real. The library is prepared by a first open (catalog, an image, queued jobs, even a run a crash
left `FINALIZING`) and then closed, so the application under test starts on it as after a restart.
"""

import asyncio
import base64
import secrets
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from backend.api.app import create_app
from backend.api.scheduler import SchedulerService
from backend.api.startup import (
    Backend,
    LibrarySettings,
    ProcessingSettings,
    backend_lifespan,
)
from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import Occurrence
from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.processing.models import ProcessingRun
from backend.app.processing.runner import RunOutcomeKind
from backend.app.runtime.worker_config import PerceptionPlan
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import (
    NDIM,
    Pipeline,
    PlantedPerception,
    prepare_catalog,
    variant_from_json,
)

LONG = 60.0


def token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


class World:
    """A prepared library on disk and the settings an application would start it with."""

    def __init__(
        self,
        tmp_path: Path,
        clock: FrozenClock,
        new_id: SeededUUIDs,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "library").mkdir()
        self.settings = LibrarySettings(
            library_root=tmp_path / "library",
            local_state_root=tmp_path / "local",
            clock=clock,
            new_id=new_id,
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
            transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
            index_batch=50,
            max_index_passes=5,
        )
        self.clock, self.new_id = clock, new_id
        self.catalog: dict[str, Any] = {}
        self.sources: list[Any] = []
        self.perception: PlantedPerception | None = None
        self.plan: PerceptionPlan | None = None
        self.monkeypatch = monkeypatch

    def prepare(self, *, queued: int = 1, crashed_after_execution: int = 0) -> None:
        """Queue `queued` jobs, and leave `crashed_after_execution` runs FINALIZING (as a crash
        after the FINAL checkpoint would), in a library that is then closed."""
        settings = self.settings
        with open_library(
            library_root=settings.library_root, local_state_root=settings.local_state_root,
            clock=self.clock, new_id=self.new_id, retry=settings.retry,
            transaction_retry=settings.transaction_retry, index_batch=50, max_index_passes=5,
        ) as lib:  # fmt: skip
            self.catalog = prepare_catalog(lib, self.clock, self.new_id)
            pipeline = Pipeline(lib, self.clock, self.new_id, self.catalog)
            for _ in range(crashed_after_execution):
                pipeline.execute(pipeline.import_image())
            for _ in range(queued):
                pipeline.enqueue(pipeline.import_image())
        detector = variant_from_json(self.catalog["detector"])
        embedder = variant_from_json(self.catalog["embedder"])
        self.perception = PlantedPerception(detector, embedder)
        self.plan = PerceptionPlan(_uuid(self.catalog["space_id"]), NDIM, (detector,), (embedder,))
        plan = self.plan
        self.monkeypatch.setattr(
            ExecuteProcessingJob, "_plan", lambda _self, _session, _frozen: plan
        )

    def processing(self, idle_seconds: float = LONG) -> ProcessingSettings:
        perception = self.perception
        assert perception is not None
        return ProcessingSettings(
            client_for=lambda _plan: perception,
            request_for=lambda _session: self.catalog["request"],
            max_pixels=100,
            recognition_k=2,
            lease_for=timedelta(minutes=5),
            idle_seconds=idle_seconds,
            owner="api-test",
        )

    def app(self, secret: str, idle_seconds: float = LONG) -> tuple[Any, Backend]:
        backend = Backend(self.settings, self.processing(idle_seconds))
        app = create_app(secret, readiness=backend.readiness, lifespan=backend_lifespan(backend))
        return app, backend


def _uuid(text: str) -> Any:
    import uuid

    return uuid.UUID(text)


@pytest.fixture
def world(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> World:
    return World(tmp_path, clock, new_id, monkeypatch)


async def until(condition: Callable[[], bool], seconds: float = 30) -> None:
    """Poll a condition on the running application (it works in worker threads), with a bound."""
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.02)


def states(backend: Backend, model: Any) -> list[str]:
    """The states of every row, or none while the library is still opening (it is polled)."""
    if backend.library is None:
        return []
    with backend.library.session_factory() as session:
        return sorted(session.scalars(select(model.state)))


def count(backend: Backend, model: Any) -> int:
    if backend.library is None:
        return 0
    with backend.library.session_factory() as session:
        return len(list(session.scalars(select(model.id))))


async def test_a_queued_job_is_processed_once_the_library_is_open(world: World) -> None:
    world.prepare(queued=1)
    secret = token()
    app, backend = world.app(secret)

    async with app.router.lifespan_context(app):
        await until(lambda: backend.scheduler is not None and states(backend, Job) == ["COMPLETED"])

        assert states(backend, ProcessingRun) == ["COMPLETED"]
        assert count(backend, Identity) == 1
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (
                await client.get("/readiness", headers={"Authorization": f"Bearer {secret}"})
            ).json()
        assert body["capabilities"]["scheduler"] == "READY"

    assert backend.readiness().capabilities["scheduler"] == "STOPPED"


async def test_the_scheduler_does_not_exist_until_recovery_has_finished(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.prepare(queued=1)
    app, backend = world.app(token())
    release = threading.Event()

    def slow_open(**kwargs: Any) -> Any:
        assert release.wait(30)  # startup recovery "still running"
        return open_library(**kwargs)

    monkeypatch.setattr("backend.api.startup.open_library", slow_open)

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.2)  # long enough for a premature scheduler to have claimed the job
        assert backend.scheduler is None
        assert backend.library is None
        release.set()
        await until(lambda: backend.scheduler is not None)
        await until(lambda: states(backend, Job) == ["COMPLETED"])


async def test_recovery_finishes_a_crashed_run_before_the_scheduler_claims_new_work(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.prepare(queued=1, crashed_after_execution=1)
    app, backend = world.app(token())
    seen_at_start: list[list[Any]] = []
    real_start = SchedulerService.start

    def start(service: SchedulerService) -> None:
        assert backend.library is not None  # the scheduler is created after the library opened
        seen_at_start.append(list(backend.library.startup.finalizing.accepted))
        real_start(service)

    monkeypatch.setattr(SchedulerService, "start", start)

    async with app.router.lifespan_context(app):
        await until(lambda: states(backend, Job) == ["COMPLETED", "COMPLETED"])

        assert len(seen_at_start) == 1
        assert len(seen_at_start[0]) == 1  # the crashed run was accepted by recovery first
        assert states(backend, ProcessingRun) == ["COMPLETED", "COMPLETED"]
        # Both faces are the same planted vector: the new job could only match the identity the
        # crashed run created if recovery had already accepted that run before it was claimed.
        assert count(backend, Identity) == 1
        assert count(backend, Occurrence) == 2


def is_idle(backend: Backend) -> Callable[[], bool]:
    def idle() -> bool:
        scheduler = backend.scheduler
        outcome = None if scheduler is None else scheduler.last_outcome
        return outcome is not None and outcome.kind is RunOutcomeKind.IDLE

    return idle


async def test_a_wake_picks_up_a_job_queued_while_running(world: World) -> None:
    world.prepare(queued=1)
    app, backend = world.app(token(), idle_seconds=LONG)

    async with app.router.lifespan_context(app):
        await until(lambda: states(backend, Job) == ["COMPLETED"])
        await until(is_idle(backend))  # the loop looked again, found nothing, and now waits LONG
        assert backend.library is not None
        pipeline = Pipeline(backend.library, world.clock, world.new_id, world.catalog)
        pipeline.enqueue(pipeline.import_image())
        assert states(backend, Job) == ["COMPLETED", "QUEUED"]  # nothing claims it by itself

        backend.wake_scheduler()

        await until(lambda: states(backend, Job) == ["COMPLETED", "COMPLETED"])


async def test_a_failing_look_degrades_the_scheduler_capability_until_a_success(
    world: World,
) -> None:
    world.prepare(queued=1)
    assert world.perception is not None
    perception = world.perception
    failures = {"left": 1}

    def defect() -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise ValueError("a bug")

    perception.on_represent = defect
    # A long idle wait: the loop looks again only when woken, so the failed look's `last_error`
    # stays observable until the explicit wake below. A short interval lets the loop's own next
    # (idle, successful) look clear it within milliseconds, before a slow poller can see it.
    app, backend = world.app(token())

    async with app.router.lifespan_context(app):
        await until(
            lambda: backend.scheduler is not None and backend.scheduler.last_error is not None
        )
        assert backend.readiness().capabilities["scheduler"] == "DEGRADED"
        assert states(backend, Job) == ["FAILED"]  # the defect settled its claim, then was raised

        assert backend.library is not None
        pipeline = Pipeline(backend.library, world.clock, world.new_id, world.catalog)
        pipeline.enqueue(pipeline.import_image())
        backend.wake_scheduler()

        await until(lambda: states(backend, Job) == ["COMPLETED", "FAILED"])
        await until(lambda: backend.scheduler is not None and backend.scheduler.last_error is None)
        assert backend.readiness().capabilities["scheduler"] == "READY"


async def test_no_scheduler_is_created_when_the_library_cannot_open(world: World) -> None:
    world.prepare(queued=1)
    unopenable = replace(
        world.settings, library_root=world.settings.library_root.parent / "no" / "such"
    )
    backend = Backend(unopenable, world.processing())
    app = create_app(token(), readiness=backend.readiness, lifespan=backend_lifespan(backend))

    async with app.router.lifespan_context(app):
        await asyncio.to_thread(backend.settled.wait, 30)
        await asyncio.sleep(0.1)

        assert backend.state.value == "FAILED"
        assert backend.scheduler is None  # nothing claims work in a library that did not open


async def test_no_scheduler_starts_when_the_open_library_was_reported_failed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The library opened but its recovery report was unreadable: FAILED, so nothing claims work."""
    world.prepare(queued=1)
    app, backend = world.app(token())

    def broken(_report: object) -> dict[str, str]:
        raise KeyError("report")

    monkeypatch.setattr("backend.api.startup.capabilities_from", broken)

    async with app.router.lifespan_context(app):
        await asyncio.to_thread(backend.settled.wait, 30)
        await asyncio.sleep(0.1)

        assert backend.state.value == "FAILED"
        assert backend.library is not None  # it did open ...
        assert backend.scheduler is None  # ... but nothing is allowed to claim work in it
        assert states(backend, Job) == ["QUEUED"]


async def test_without_processing_settings_the_scheduler_is_not_configured(world: World) -> None:
    world.prepare(queued=1)
    backend = Backend(world.settings)  # no ProcessingSettings
    app = create_app(token(), readiness=backend.readiness, lifespan=backend_lifespan(backend))

    async with app.router.lifespan_context(app):
        await asyncio.to_thread(backend.settled.wait, 30)
        await asyncio.sleep(0.1)

        assert backend.scheduler is None
        assert backend.readiness().capabilities["scheduler"] == "NOT_CONFIGURED"
        assert states(backend, Job) == ["QUEUED"]  # nobody claimed it
        backend.wake_scheduler()  # harmless without a scheduler
