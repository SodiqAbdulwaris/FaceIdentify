"""One line for the one worker, whatever the plan (issues #175 and #221).

The pool keeps a supervisor per plan, and a job's plan is frozen when the job is queued, so a
CPU-only job and a DirectML search arrive on different supervisors. They must still take turns on
one lease: the pool owns it and every client it hands out uses it. And only one of the supervisors
may have a worker at a time: a turn on another plan stops the running worker before its own starts
(the real-process proof is in test_runtime_perception_client).
"""

import threading
import uuid
from typing import Any, cast

import pytest

from backend.api.real import ClientPool
from backend.app.runtime.perception_client import PerceptionClient
from backend.app.runtime.worker_config import PerceptionPlan
from backend.ml.contracts.messages import MLRequest, MLResponse
from backend.ml.supervisor.lease import ServiceClass, WorkerClosedError, interactive
from backend.ml.supervisor.supervisor import MLSupervisor, MLUnavailableError
from tests.concurrency.test_worker_lease import Watched, finish, reached, watched
from tests.integration.test_real_profile import plan
from tests.integration.test_runtime_perception_client import Scripted, detected
from tests.integration.test_runtime_perception_client import picture as pixels


class Gate:
    """Answers like a worker that stays busy until the test lets the request go."""

    def __init__(self) -> None:
        self.entered: list[str] = []
        self.arrived = {name: threading.Event() for name in ("first", "second", "third")}
        self.leave = {name: threading.Event() for name in self.arrived}
        self._count = 0
        self._lock = threading.Lock()

    def answer(self, request: MLRequest) -> MLResponse:
        with self._lock:
            name = list(self.arrived)[self._count]
            self._count += 1
            self.entered.append(name)
        self.arrived[name].set()
        reached(self.leave[name])
        return detected(request)


class Stoppable(Scripted):
    stopped = 0
    refuses = False

    def stop(self) -> None:
        if self.refuses:
            raise OSError("the worker process could not be ended")
        self.stopped += 1


def pool_of(gate: Gate) -> tuple[ClientPool, Watched, list[Stoppable]]:
    made: list[Stoppable] = []

    def supervise(_plan: PerceptionPlan, _policy: Any) -> MLSupervisor:
        made.append(Stoppable(gate.answer))  # one supervisor per plan, as in life
        return cast(MLSupervisor, made[-1])

    pool = ClientPool(uuid.uuid4, supervise=supervise)
    condition = watched(pool.lease)
    return pool, condition, made


def start(
    pool: ClientPool,
    which: PerceptionPlan,
    condition: Watched,
    *,
    search: bool,
    threads: list[threading.Thread],
    outcomes: list[BaseException] | None = None,
) -> None:
    client: PerceptionClient = pool.client_for(which)

    def run() -> None:
        try:
            if search:
                with interactive():
                    client.detect(pixels(64, 64))
            else:
                client.detect(pixels(64, 64))
        except WorkerClosedError as error:
            assert outcomes is not None
            outcomes.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    threads.append(thread)
    condition.queued_one()  # its turn was asked for (granted at once if the worker was free)


def test_requests_on_two_plans_never_run_on_the_worker_together() -> None:
    gate = Gate()
    threads: list[threading.Thread] = []
    pool, condition, made = pool_of(gate)
    cpu_only, directml = plan(1, 1), plan(2, 3)

    start(pool, cpu_only, condition, search=False, threads=threads)
    reached(gate.arrived["first"])
    start(pool, directml, condition, search=False, threads=threads)
    assert pool.lease.queued(ServiceClass.BACKGROUND) == 1
    assert gate.entered == ["first"]  # the second plan's request waits for the first's

    gate.leave["first"].set()
    reached(gate.arrived["second"])
    gate.leave["second"].set()
    finish(threads)
    assert gate.entered == ["first", "second"]
    assert [s.stopped for s in made] == [1, 0]  # the second plan's turn stopped the first's worker


def test_a_search_on_one_plan_goes_before_background_work_on_another() -> None:
    gate = Gate()
    threads: list[threading.Thread] = []
    pool, condition, _ = pool_of(gate)
    cpu_only, directml = plan(1, 1), plan(2, 3)

    start(pool, cpu_only, condition, search=False, threads=threads)  # a job holds the worker
    reached(gate.arrived["first"])
    start(pool, cpu_only, condition, search=False, threads=threads)  # another job queues first
    start(pool, directml, condition, search=True, threads=threads)  # a search, later, other plan
    assert (
        pool.lease.queued(ServiceClass.INTERACTIVE),
        pool.lease.queued(ServiceClass.BACKGROUND),
    ) == (1, 1)

    gate.leave["first"].set()
    reached(gate.arrived["second"])
    assert (
        pool.lease.queued(ServiceClass.INTERACTIVE),
        pool.lease.queued(ServiceClass.BACKGROUND),
    ) == (0, 1)  # the search went first
    gate.leave["second"].set()
    reached(gate.arrived["third"])
    gate.leave["third"].set()
    finish(threads)


def test_closing_the_pool_refuses_a_queued_request_instead_of_restarting_a_worker() -> None:
    gate = Gate()
    threads: list[threading.Thread] = []
    outcomes: list[BaseException] = []
    pool, condition, made = pool_of(gate)
    cpu_only, directml = plan(1, 1), plan(2, 3)

    start(pool, cpu_only, condition, search=False, threads=threads)
    reached(gate.arrived["first"])
    start(pool, directml, condition, search=False, threads=threads, outcomes=outcomes)
    assert pool.lease.queued(ServiceClass.BACKGROUND) == 1

    closing = threading.Thread(target=pool.close)
    closing.start()
    finish(threads[1:])
    assert len(outcomes) == 1
    assert closing.is_alive()  # shutdown drains the active worker protocol before stopping workers
    assert [s.stopped for s in made] == [0, 0]
    gate.leave["first"].set()
    finish([*threads, closing])
    assert [s.stopped for s in made] == [1, 1]  # every worker was stopped, once
    assert gate.entered == ["first"]  # the refused request never reached a worker


def stops_seen_by_each_request() -> tuple[ClientPool, list[Stoppable], list[tuple[int, ...]]]:
    """A pool whose workers note, at every request they run, how often each one had been stopped."""
    made: list[Stoppable] = []
    seen: list[tuple[int, ...]] = []

    def answer(request: MLRequest) -> MLResponse:
        seen.append(tuple(s.stopped for s in made))
        return detected(request)

    def supervise(_plan: PerceptionPlan, _policy: Any) -> MLSupervisor:
        made.append(Stoppable(answer))
        return cast(MLSupervisor, made[-1])

    return ClientPool(uuid.uuid4, supervise=supervise), made, seen


def test_a_turn_on_another_plan_stops_the_running_worker_first_and_the_same_plan_keeps_it() -> None:
    pool, made, seen = stops_seen_by_each_request()
    job = pool.client_for(plan(1, 1))
    search = pool.client_for(plan(2, 3))

    job.detect(pixels(64, 64))
    job.detect(pixels(64, 64))  # the same plan again: its worker is kept, nothing is stopped
    search.detect(pixels(64, 64))
    job.detect(pixels(64, 64))

    # (stop is idempotent: the search's supervisor, never started, was told once at the job's turn)
    assert seen == [(0, 1), (0, 1), (1, 1), (1, 2)]


def test_a_worker_that_will_not_stop_refuses_the_other_plans_request_and_frees_the_turn() -> None:
    pool, made, seen = stops_seen_by_each_request()
    job = pool.client_for(plan(1, 1))
    search = pool.client_for(plan(2, 3))
    job.detect(pixels(64, 64))
    made[0].refuses = True

    with pytest.raises(MLUnavailableError, match="could not be stopped"):
        search.detect(pixels(64, 64))
    assert made[1].requests == []  # no second worker was asked to run beside the first
    job.detect(pixels(64, 64))  # the turn was given back, and the job's worker is still the one
    made[0].refuses = False
    search.detect(pixels(64, 64))  # stopping is tried again at the next turn
    assert len(made[1].requests) == 1
    assert seen[-1] == (1, 1)
