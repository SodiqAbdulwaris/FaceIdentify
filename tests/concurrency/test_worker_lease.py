"""Who uses the one perception worker next (issue #175): interactive first, first come first served
within a class, background never starved, one request at a time, and always released.

Real threads on a real lease. A test holds the worker, lines requests up (waiting until the lease
reports them queued), then lets go and reads the order in which they were served.
"""

import threading
import time
from collections.abc import Callable

import pytest

from backend.ml.supervisor.lease import WorkerLease, interactive
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy, WorkerFailedError

DEADLINE = 10.0  # seconds; a correct lease answers in milliseconds


def eventually(condition: Callable[[], bool]) -> None:
    """Wait for something the lease reports (not for an assumed amount of time)."""
    give_up = time.monotonic() + DEADLINE
    while not condition():
        if time.monotonic() > give_up:
            raise AssertionError("the lease never reached the expected state")
        time.sleep(0.001)


class Line:
    """Requests lined up behind a held worker; `served` is the order they got it in."""

    def __init__(self, lease: WorkerLease) -> None:
        self.lease = lease
        self.served: list[str] = []
        self.threads: list[threading.Thread] = []
        self._release = threading.Event()
        self._holding = threading.Event()
        holder = threading.Thread(target=self._hold)
        holder.start()
        self._holding.wait(DEADLINE)
        self.threads.append(holder)

    def _hold(self) -> None:
        with self.lease.held():
            self._holding.set()
            self._release.wait(DEADLINE)

    def join(self, name: str, *, is_interactive: bool) -> None:
        before = self.lease.queued(is_interactive)

        def request() -> None:
            if is_interactive:
                with interactive(), self.lease.held():
                    self.served.append(name)
            else:
                with self.lease.held():
                    self.served.append(name)

        thread = threading.Thread(target=request)
        thread.start()
        self.threads.append(thread)
        eventually(lambda: self.lease.queued(is_interactive) == before + 1)

    def let_go(self) -> list[str]:
        self._release.set()
        for thread in self.threads:
            thread.join(DEADLINE)
        return self.served


def test_an_interactive_request_goes_before_waiting_background_work() -> None:
    line = Line(WorkerLease())
    line.join("background 1", is_interactive=False)
    line.join("background 2", is_interactive=False)
    line.join("search 1", is_interactive=True)
    line.join("search 2", is_interactive=True)

    assert line.let_go() == ["search 1", "search 2", "background 1", "background 2"]


def test_a_stream_of_searches_lets_waiting_background_work_through() -> None:
    line = Line(WorkerLease(burst=2))
    line.join("background", is_interactive=False)
    for n in range(1, 5):
        line.join(f"search {n}", is_interactive=True)

    assert line.let_go() == ["search 1", "search 2", "background", "search 3", "search 4"]


def test_the_streak_counts_from_the_last_background_grant() -> None:
    lease = WorkerLease(burst=1)
    line = Line(lease)
    line.join("background 1", is_interactive=False)
    line.join("background 2", is_interactive=False)
    line.join("search 1", is_interactive=True)
    line.join("search 2", is_interactive=True)

    assert line.let_go() == ["search 1", "background 1", "search 2", "background 2"]


def test_only_one_request_holds_the_worker_at_a_time() -> None:
    lease = WorkerLease()
    inside, most = 0, 0
    count = threading.Lock()

    def request(is_interactive: bool) -> None:
        nonlocal inside, most

        def body() -> None:
            nonlocal inside, most
            with count:
                inside += 1
                most = max(most, inside)
            time.sleep(0.002)  # (a request that takes a moment, so overlaps would show)
            with count:
                inside -= 1

        if is_interactive:
            with interactive(), lease.held():
                body()
        else:
            with lease.held():
                body()

    threads = [threading.Thread(target=request, args=(n % 3 == 0,)) for n in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(DEADLINE)

    assert most == 1
    assert lease.queued(True) == lease.queued(False) == 0


def test_a_request_that_fails_releases_the_worker() -> None:
    lease = WorkerLease()

    with pytest.raises(RuntimeError), lease.held():
        raise RuntimeError("the inference failed")
    with lease.held():  # would wait for ever if the failure had kept it
        pass


def test_the_mark_is_only_inside_interactive() -> None:
    line = Line(WorkerLease())
    line.join("search", is_interactive=True)
    line.join("after", is_interactive=False)  # same thread as the test: not marked any more

    assert line.lease.queued(True) == 1
    assert line.lease.queued(False) == 1
    assert line.let_go() == ["search", "after"]


def test_a_burst_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        WorkerLease(burst=0)


def test_the_supervisor_takes_its_turn_on_the_lease_for_every_request() -> None:
    lease = WorkerLease()
    policy = SupervisorPolicy(1, 1, 1, 0, 0, 60)

    def cannot_start() -> object:
        raise OSError("no worker in this test")

    supervisor = MLSupervisor(cannot_start, policy, lease=lease)  # type: ignore[arg-type]
    outcome: list[BaseException] = []
    line = Line(lease)

    def request() -> None:
        try:
            supervisor.execute(None)  # type: ignore[arg-type]
        except BaseException as error:  # noqa: BLE001 - the test reads what happened
            outcome.append(error)

    thread = threading.Thread(target=request)
    thread.start()
    eventually(lambda: lease.queued(False) == 1)  # waiting for the worker, not running
    assert outcome == []
    line.let_go()
    thread.join(DEADLINE)

    assert len(outcome) == 1
    assert isinstance(outcome[0], WorkerFailedError)
