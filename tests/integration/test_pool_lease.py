"""One line for the one worker, whatever the plan (issue #175).

The pool keeps a supervisor per plan, and a job's plan is frozen when the job is queued, so a
CPU-only job and a DirectML search arrive on different supervisors. They must still take turns on
one lease: the pool owns it and every client it hands out uses it.
"""

import threading
import uuid
from typing import Any, cast

from backend.api.real import ClientPool
from backend.app.runtime.perception_client import PerceptionClient
from backend.app.runtime.worker_config import PerceptionPlan
from backend.ml.contracts.messages import MLRequest, MLResponse
from backend.ml.supervisor.lease import interactive
from backend.ml.supervisor.supervisor import MLSupervisor
from tests.concurrency.test_worker_lease import eventually, finish, reached
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


def pool_of(gate: Gate) -> ClientPool:
    def supervise(_plan: PerceptionPlan, _policy: Any) -> MLSupervisor:
        return cast(MLSupervisor, Scripted(gate.answer))  # one supervisor per plan, as in life

    return ClientPool(uuid.uuid4, supervise=supervise)


def start(
    pool: ClientPool, which: PerceptionPlan, *, search: bool, threads: list[threading.Thread]
) -> None:
    client: PerceptionClient = pool.client_for(which)

    def run() -> None:
        if search:
            with interactive():
                client.detect(pixels(64, 64))
        else:
            client.detect(pixels(64, 64))

    thread = threading.Thread(target=run)
    thread.start()
    threads.append(thread)


def test_requests_on_two_plans_never_run_on_the_worker_together() -> None:
    gate = Gate()
    threads: list[threading.Thread] = []
    pool = pool_of(gate)
    cpu_only, directml = plan(1, 1), plan(2, 3)

    start(pool, cpu_only, search=False, threads=threads)
    reached(gate.arrived["first"])
    start(pool, directml, search=False, threads=threads)
    eventually(lambda: pool.lease.queued(False) == 1)
    assert gate.entered == ["first"]  # the second plan's request waits for the first's

    gate.leave["first"].set()
    reached(gate.arrived["second"])
    gate.leave["second"].set()
    finish(threads)
    assert gate.entered == ["first", "second"]


def test_a_search_on_one_plan_goes_before_background_work_on_another() -> None:
    gate = Gate()
    threads: list[threading.Thread] = []
    pool = pool_of(gate)
    cpu_only, directml = plan(1, 1), plan(2, 3)

    start(pool, cpu_only, search=False, threads=threads)  # a job holds the worker
    reached(gate.arrived["first"])
    start(pool, cpu_only, search=False, threads=threads)  # another job queues first
    eventually(lambda: pool.lease.queued(False) == 1)
    start(pool, directml, search=True, threads=threads)  # a search on the other plan, later
    eventually(lambda: pool.lease.queued(True) == 1)

    gate.leave["first"].set()
    reached(gate.arrived["second"])
    assert pool.lease.queued(True) == 0  # the search was served; the job is still waiting
    assert pool.lease.queued(False) == 1
    gate.leave["second"].set()
    reached(gate.arrived["third"])
    gate.leave["third"].set()
    finish(threads)
