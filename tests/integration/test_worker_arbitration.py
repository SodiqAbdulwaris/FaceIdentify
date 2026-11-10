"""Issue #175's remaining acceptance tests: the one worker, shared by processing and face search.

Through the real processing pipeline (a library opened by `open_library`, the real scheduler and
executor; only perception is planted, behind a real `WorkerLease`) and through the real client pool:

* a job cancelled while it waits for its turn never reaches the worker, and is settled `CANCELLED`
  with nothing private beyond what was already settled;
* no database transaction and no index lock is held while an inference runs;
* a search that arrives during a job's detection is served before the job's representation (the
  next safe boundary, not the end of the source);
* a worker that fails during a job's request hands the turn on: the waiting search runs.

Every wait is for an event or for the lease's own queue (`Watched`), never for a delay.
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable
from typing import Any, cast

import pytest
from sqlalchemy import select

from backend.api.real import ClientPool
from backend.app.jobs.models import Job
from backend.app.memory.models import Observation, Representation
from backend.app.processing.cancel import CancelOutcome, CancelProcessingUseCase
from backend.app.processing.execute_job import ProcessingCancelledError
from backend.app.processing.models import ProcessingRun
from backend.app.runtime.perception_client import Detected, Represented
from backend.app.runtime.worker_config import PerceptionPlan
from backend.ml.contracts.messages import Detection, ExecutionContext, MLRequest, MLResponse
from backend.ml.contracts.protocol import MLOperation
from backend.ml.supervisor.lease import WorkerLease, interactive
from backend.ml.supervisor.supervisor import MLSupervisor, WorkerFailedError
from tests.concurrency.test_worker_lease import DEADLINE, Watched, finish, reached, watched
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.pipeline import Pipeline, PlantedPerception
from tests.integration.test_real_profile import plan
from tests.integration.test_runtime_perception_client import Embedder, Scripted, detected
from tests.integration.test_runtime_perception_client import picture as pixels

# --- through the processing pipeline ------------------------------------------------------------


class Leased:
    """The planted perception behind a real lease: each call takes its turn, as a client does.
    `before_represent` runs just before the representation asks for its turn."""

    def __init__(self, planted: PlantedPerception, lease: WorkerLease) -> None:
        self.planted = planted
        self.lease = lease
        self.before_represent: Callable[[], None] | None = None

    def detect(self, pixels: Any) -> Detected:
        with self.lease.held():
            return self.planted.detect(pixels)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        if self.before_represent is not None:
            self.before_represent()
        with self.lease.held():
            return self.planted.represent(pixels, detections)


class Holder:
    """Another request holding the worker until the test lets it go."""

    def __init__(self, lease: WorkerLease) -> None:
        self._lease = lease
        self._inside, self._leave = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._hold)
        self._thread.start()
        reached(self._inside)  # (its turn was granted at once: the worker was free)

    def _hold(self) -> None:
        with self._lease.held():
            self._inside.set()
            reached(self._leave)

    def let_go(self) -> None:
        self._leave.set()
        finish([self._thread])


def execute_in_thread(
    pipeline: Pipeline,
) -> tuple[threading.Thread, list[BaseException], uuid.UUID]:
    """Claim the queued job and execute it on a thread: the thread, what it raised, the run."""
    started = pipeline.scheduler().claim_source_job("worker")
    assert started is not None
    run_id = started.job.processing_run_id
    assert run_id is not None
    raised: list[BaseException] = []
    executor = pipeline.executor()

    def execute() -> None:
        try:
            executor.execute(started)
        except BaseException as error:  # noqa: BLE001 - the test reads what happened
            raised.append(error)

    thread = threading.Thread(target=execute)
    thread.start()
    return thread, raised, run_id


def states(pipeline: Pipeline, run_id: uuid.UUID) -> tuple[str, str]:
    with pipeline.lib.session_factory() as session:
        run = session.get(ProcessingRun, run_id)
        job = session.scalars(select(Job).where(Job.processing_run_id == run_id)).one()
        assert run is not None
        return str(run.state), str(job.state)


@pytest.mark.parametrize("waiting_at", ["detection", "representation"])
def test_a_job_cancelled_while_it_waits_for_the_worker_never_reaches_it(
    pipeline: Pipeline, waiting_at: str
) -> None:
    lease = WorkerLease()
    condition = watched(lease)
    planted = pipeline.perception
    leased = Leased(planted, lease)
    pipeline.perception = leased  # type: ignore[assignment]
    pipeline.enqueue(pipeline.import_image())
    holders: list[Holder] = []
    if waiting_at == "detection":
        holders.append(Holder(lease))
        condition.queued_one()  # (the holder's turn)
    else:  # the detection runs; another request takes the worker before the representation
        leased.before_represent = lambda: holders.append(Holder(lease))

    thread, raised, run_id = execute_in_thread(pipeline)
    if waiting_at == "representation":
        condition.queued_one()  # (the detection's turn, granted at once)
        condition.queued_one()  # (the holder's turn, taken before the representation asks)
    condition.queued_one()  # the job's request now waits behind the holder
    calls_before = planted.calls
    cancel = CancelProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock)
    assert cancel.cancel(run_id).outcome is CancelOutcome.REQUESTED
    holders[0].let_go()
    finish([thread])

    assert len(raised) == 1
    assert isinstance(raised[0], ProcessingCancelledError)
    assert planted.calls == calls_before  # the cancelled request never reached the worker
    assert states(pipeline, run_id) == ("CANCELLED", "CANCELLED")
    assert pipeline.count(Representation) == 0
    assert pipeline.count(Observation) == (1 if waiting_at == "representation" else 0)
    assert lease.queued(False) == 0  # the turn was given up, nothing left behind
    with lease.held():  # and the worker is free
        pass


class Checking(PlantedPerception):
    """Planted perception that checks, during each inference, that nothing is held around it."""

    def __init__(self, pipeline: Pipeline) -> None:
        super().__init__(pipeline.perception.detector, pipeline.perception.embedder)
        self.pipeline = pipeline
        self.checked = 0

    def _nothing_held(self) -> None:
        database = self.pipeline.lib.engine.url.database
        assert database is not None
        other = sqlite3.connect(database, timeout=0)  # (fails at once if a writer holds the lock)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        finally:
            other.close()
        index_lock = cast(threading.Lock, self.pipeline.lib.coordinator.exclusive())
        assert index_lock.acquire(blocking=False), "the index coordinator's lock is held"
        index_lock.release()
        self.checked += 1

    def detect(self, pixels: Any) -> Detected:
        self._nothing_held()
        return super().detect(pixels)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self._nothing_held()
        return super().represent(pixels, detections)


def test_no_database_transaction_or_index_lock_is_held_across_an_inference(
    pipeline: Pipeline,
) -> None:
    checking = Checking(pipeline)
    pipeline.perception = checking
    run_id = pipeline.execute(pipeline.import_image())

    assert checking.checked == 2  # the detection and the representation
    assert states(pipeline, run_id) == ("FINALIZING", "RUNNING")  # (it ran to its FINAL)


# --- through the client pool ----------------------------------------------------------------


class Gated(Scripted):
    """A supervisor whose requests each wait for the test, noting whose request each was."""

    def __init__(self, embedder: Embedder) -> None:
        super().__init__(self._answer)
        self.embedder = embedder
        self.order: list[str] = []
        self.arrived = threading.Semaphore(0)
        self.go = threading.Semaphore(0)
        self.fail_next = False

    def _answer(self, request: MLRequest) -> MLResponse:
        who = "search" if request.execution_context.job_id is None else "job"
        self.order.append(f"{who} {request.operation.value}")
        self.arrived.release()
        assert self.go.acquire(timeout=DEADLINE), "the test never let the request go"
        if self.fail_next:
            self.fail_next = False
            raise WorkerFailedError("the worker died during a request")
        if request.operation is MLOperation.DETECT_FACES:
            return detected(request)
        return self.embedder.answer(request)

    def stop(self) -> None:
        pass

    def next_runs(self) -> None:
        """Wait for the next request to reach the worker, then let it go."""
        assert self.arrived.acquire(timeout=DEADLINE), "no request reached the worker"
        self.go.release()


def job_and_search(gated: Gated) -> tuple[ClientPool, Watched, list[threading.Thread], list[Any]]:
    """A pool over `gated`, and a job's and a search's threads on one plan (not started)."""

    def supervise(_plan: PerceptionPlan, _policy: Any) -> MLSupervisor:
        return cast(MLSupervisor, gated)

    pool = ClientPool(uuid.uuid4, supervise=supervise)
    condition = watched(pool.lease)
    which = plan(1, 1)
    raised: list[BaseException] = []

    def job() -> None:
        client = pool.client_for(which)
        context = ExecutionContext(job_id="job-1")
        try:
            found = client.detect(pixels(64, 64), context=context)
            client.represent(pixels(64, 64), found.detections, context=context)
        except BaseException as error:  # noqa: BLE001 - the test reads what happened
            raised.append(error)

    def search() -> None:
        client = pool.client_for(which)
        with interactive():
            found = client.detect(pixels(64, 64))
            client.represent(pixels(64, 64), found.detections)

    threads = [threading.Thread(target=job), threading.Thread(target=search)]
    return pool, condition, threads, raised


def test_a_search_during_a_jobs_detection_runs_at_the_next_boundary_before_its_representation(
    new_id: SeededUUIDs,
) -> None:
    """The search waits for the one inference in progress, not for the job: when the detection
    ends, the search's detection goes before the job's representation, which was already waiting."""
    gated = Gated(Embedder(new_id, dimension=4))
    pool, condition, (job, search), raised = job_and_search(gated)

    with gated.embedder.ledger:
        job.start()
        condition.queued_one()
        assert gated.arrived.acquire(timeout=DEADLINE)  # the job's detection is running
        search.start()
        condition.queued_one()  # the search waits for that one inference only
        gated.go.release()  # the detection ends: the next safe boundary
        assert gated.arrived.acquire(timeout=DEADLINE)  # the search's detection runs
        condition.queued_one()  # while the job's representation waits for its turn
        assert gated.order == ["job DETECT_FACES", "search DETECT_FACES"]
        gated.go.release()
        for _ in range(2):  # then both representations (the search's may queue first)
            gated.next_runs()
        finish([job, search])

    assert not raised
    assert sorted(gated.order[2:]) == [
        "job GENERATE_REPRESENTATIONS",
        "search GENERATE_REPRESENTATIONS",
    ]
    assert pool.lease.queued(True) == pool.lease.queued(False) == 0


def test_a_worker_that_fails_during_a_jobs_request_hands_the_turn_to_the_waiting_search(
    new_id: SeededUUIDs,
) -> None:
    gated = Gated(Embedder(new_id, dimension=4))
    gated.fail_next = True
    pool, condition, (job, search), raised = job_and_search(gated)

    with gated.embedder.ledger:
        job.start()
        condition.queued_one()
        assert gated.arrived.acquire(timeout=DEADLINE)  # the job's detection is running
        search.start()
        condition.queued_one()
        gated.go.release()  # ...and the worker dies under it
        for _ in range(2):  # the search still runs, both of its requests
            gated.next_runs()
        finish([job, search])

    assert len(raised) == 1
    assert isinstance(raised[0], WorkerFailedError)  # the job's own failure, for its job policy
    assert gated.order == [
        "job DETECT_FACES",
        "search DETECT_FACES",
        "search GENERATE_REPRESENTATIONS",
    ]
    assert pool.lease.queued(True) == pool.lease.queued(False) == 0
