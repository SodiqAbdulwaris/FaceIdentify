"""Who uses the one perception worker next (issue #175): interactive first, first come first served
within a class, background never starved, one request at a time, and always released.

Real threads on a real lease. A test holds the worker, lines requests up (waiting until the lease
reports them queued), then lets go and reads the order in which they were served. Nothing here
depends on how long anything takes: every wait is for an event or for the lease's own queue, and
every wait is asserted to have succeeded.
"""

import logging
import threading
from collections.abc import Callable

import pytest

from backend.ml.supervisor.lease import (
    RequestCancelledError,
    TurnRecord,
    WorkerClosedError,
    WorkerLease,
    cancellable,
    interactive,
    is_interactive,
)

DEADLINE = 10.0  # seconds; a correct lease answers in milliseconds, this only ends a hang


def reached(event: threading.Event) -> None:
    assert event.wait(DEADLINE), "the event never happened"


class Watched(threading.Condition):
    """The lease's condition, reporting each request that starts to wait for its turn.

    A request's ticket is queued before it waits, and the lease's lock is held until the wait
    begins, so once `queued_one` returns the ticket is in the queue and the request is parked: the
    tests wait for that transition itself, not for a delay and not by polling. `interrupt` makes
    the next wait end in a `KeyboardInterrupt`, as a signal in the waiting thread would.
    """

    interrupt = False

    def __init__(self) -> None:
        super().__init__()
        self._arrivals = threading.Semaphore(0)

    def wait_for(  # type: ignore[override]
        self, predicate: Callable[[], bool], timeout: float | None = None
    ) -> bool:
        self._arrivals.release()
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        return super().wait_for(predicate, timeout)

    def queued_one(self) -> None:
        assert self._arrivals.acquire(timeout=DEADLINE), "no request started to wait"


def watched(lease: WorkerLease) -> Watched:
    condition = Watched()
    lease._condition = condition  # noqa: SLF001 - the seam that makes the queue observable
    return condition


def finish(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(DEADLINE)
        assert not thread.is_alive(), "a thread never ended"


class Line:
    """Requests lined up behind a held worker; `served` is the order they got it in."""

    def __init__(self, lease: WorkerLease) -> None:
        self.lease = lease
        self.condition = watched(lease)
        self.served: list[str] = []
        self.threads: list[threading.Thread] = []
        self._release = threading.Event()
        self._holding = threading.Event()
        holder = threading.Thread(target=self._hold)
        holder.start()
        self.threads.append(holder)
        reached(self._holding)
        self.condition.queued_one()  # (the holder's own turn, granted at once)

    def _hold(self) -> None:
        with self.lease.held():
            self._holding.set()
            reached(self._release)

    def join(self, name: str, *, is_interactive: bool) -> None:
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
        self.condition.queued_one()

    def let_go(self) -> list[str]:
        self._release.set()
        finish(self.threads)
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
    line = Line(WorkerLease(burst=1))
    line.join("background 1", is_interactive=False)
    line.join("background 2", is_interactive=False)
    line.join("search 1", is_interactive=True)
    line.join("search 2", is_interactive=True)

    assert line.let_go() == ["search 1", "background 1", "search 2", "background 2"]


def test_only_one_request_holds_the_worker_at_a_time() -> None:
    """Three requests queue behind a holder. Each, once inside, stays until the test lets it go,
    so a lease that admitted a second request would show it as an extra entry."""
    lease = WorkerLease()
    condition = watched(lease)
    holder_in, holder_out = threading.Event(), threading.Event()
    inside = [threading.Event() for _ in range(3)]
    leave = [threading.Event() for _ in range(3)]
    entered: list[int] = []

    def hold() -> None:
        with lease.held():
            holder_in.set()
            reached(holder_out)

    def request(n: int) -> None:
        with lease.held():
            entered.append(n)
            inside[n].set()
            reached(leave[n])

    holder = threading.Thread(target=hold)
    holder.start()
    threads = [holder]
    reached(holder_in)
    condition.queued_one()  # (the holder's own turn, granted at once)
    for n in range(3):
        thread = threading.Thread(target=request, args=(n,))
        thread.start()
        threads.append(thread)
        condition.queued_one()
        assert lease.queued(False) == n + 1
    assert entered == []  # three are waiting and none got in beside the holder

    holder_out.set()
    for n in range(3):
        reached(inside[n])
        assert entered == list(range(n + 1))  # the next waits until this one leaves
        assert lease.queued(False) == 2 - n
        leave[n].set()
    finish(threads)
    assert lease.queued(True) == lease.queued(False) == 0


def test_a_request_that_fails_releases_the_worker() -> None:
    lease = WorkerLease()

    with pytest.raises(RuntimeError), lease.held():
        raise RuntimeError("the inference failed")
    with lease.held():  # would wait for ever if the failure had kept it
        pass


def test_a_failure_right_after_the_grant_still_releases_the_worker() -> None:
    calls = 0

    def clock() -> float:
        nonlocal calls
        calls += 1
        if calls == 2:  # the reading taken for the log line, once the worker is granted
            raise RuntimeError("the clock failed after the grant")
        return 0.0

    lease = WorkerLease(clock=clock)
    with pytest.raises(RuntimeError, match="after the grant"), lease.held():
        raise AssertionError("the body must not run")
    with lease.held():  # the worker is free again
        pass


def test_an_interrupted_wait_leaves_no_ticket_behind() -> None:
    lease = WorkerLease()
    line = Line(lease)
    condition = line.condition
    outcome: list[BaseException] = []

    def interrupted() -> None:
        try:
            with lease.held():
                raise AssertionError("an interrupted request must not get the worker")
        except BaseException as error:  # noqa: BLE001 - the test reads what happened
            outcome.append(error)

    condition.interrupt = True
    thread = threading.Thread(target=interrupted)
    thread.start()
    condition.queued_one()
    finish([thread])
    assert len(outcome) == 1
    assert isinstance(outcome[0], KeyboardInterrupt)
    assert lease.queued(False) == 0  # the abandoned ticket is gone

    line.join("after", is_interactive=False)  # would never be served behind a dead head
    assert line.let_go() == ["after"]


def test_the_mark_follows_interactive_scopes_on_the_same_thread() -> None:
    assert not is_interactive()
    with interactive():
        assert is_interactive()
        with interactive():
            assert is_interactive()
        assert is_interactive()  # leaving the inner scope restores the outer one
    assert not is_interactive()

    def fails_inside() -> None:
        with interactive():
            assert is_interactive()
            raise RuntimeError("the search failed")

    with pytest.raises(RuntimeError):
        fails_inside()
    assert not is_interactive()  # an exceptional exit restores it too


def test_a_burst_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        WorkerLease(burst=0)


def test_closing_refuses_the_requests_that_wait_and_the_ones_that_come_later() -> None:
    line = Line(WorkerLease())
    outcome: list[BaseException] = []

    def waiting() -> None:
        try:
            with line.lease.held():
                raise AssertionError("a request that waited past the close must not get the worker")
        except WorkerClosedError as error:
            outcome.append(error)

    thread = threading.Thread(target=waiting)
    thread.start()
    line.condition.queued_one()
    line.lease.close()  # the holder is still inside: shutdown does not wait for the queue
    finish([thread])

    assert len(outcome) == 1
    assert line.lease.queued(False) == 0  # the refused request left no ticket
    with pytest.raises(WorkerClosedError), line.lease.held():
        raise AssertionError("a request made after the close must not get the worker")
    assert line.let_go() == []  # the holder finished normally


def test_a_request_cancelled_while_it_waits_gives_its_turn_up_and_the_next_one_runs() -> None:
    """Decision point 5: a queued request can be cancelled without entering inference. It is asked
    when its turn comes, not when it queues, so a cancellation made while it waited is seen."""
    line = Line(WorkerLease())
    cancelled = threading.Event()
    asked: list[bool] = []
    outcome: list[BaseException] = []

    def check() -> bool:
        asked.append(cancelled.is_set())
        return cancelled.is_set()

    def waiting() -> None:
        try:
            with cancellable(check), line.lease.held():
                line.served.append("cancelled")  # must never happen
        except RequestCancelledError as error:
            outcome.append(error)

    thread = threading.Thread(target=waiting)
    thread.start()
    line.threads.append(thread)
    line.condition.queued_one()
    line.join("after", is_interactive=False)
    cancelled.set()  # while it waits behind the holder

    assert line.let_go() == ["after"]  # the cancelled request never held the worker
    assert asked == [True]  # asked once, at its turn
    assert len(outcome) == 1
    assert line.lease.queued(False) == 0


def test_a_request_that_is_not_cancelled_runs_and_the_scope_ends_with_its_block() -> None:
    lease = WorkerLease()
    asked = 0

    def check() -> bool:
        nonlocal asked
        asked += 1
        return False

    with cancellable(check):
        with lease.held():
            pass
        with lease.held():
            pass
    with lease.held():  # outside the scope nothing is asked
        pass

    assert asked == 2


def test_a_turn_given_up_does_not_count_towards_the_burst() -> None:
    """With a burst of one, a cancelled search must not use the searches' one turn: the next
    search still goes before the waiting background request."""
    line = Line(WorkerLease(burst=1))

    def cancelled_search() -> None:
        with (
            pytest.raises(RequestCancelledError),
            interactive(),
            cancellable(lambda: True),
            line.lease.held(),
        ):
            line.served.append("cancelled")  # must never happen

    thread = threading.Thread(target=cancelled_search)
    thread.start()
    line.threads.append(thread)
    line.condition.queued_one()
    line.join("background", is_interactive=False)
    line.join("search", is_interactive=True)

    assert line.let_go() == ["search", "background"]


def test_a_cancellation_check_that_fails_releases_the_turn_and_raises() -> None:
    """The executor's check reads the database; if that read fails the error is the caller's (the
    runner settles an unexpected error), and the worker is not left held."""
    lease = WorkerLease()

    def broken() -> bool:
        raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError, match="locked"), cancellable(broken), lease.held():
        raise AssertionError("the body must not run")
    with lease.held():  # the worker is free again
        pass


def test_every_turn_is_measured_its_wait_its_hold_and_its_outcome() -> None:
    """Decision point 8 (D5): per class, the wait and the time holding the worker, and whether the
    request ran, failed or gave its turn up."""
    ticks = iter(range(100))
    records: list[TurnRecord] = []
    lease = WorkerLease(clock=lambda: float(next(ticks)), observe=records.append)

    with interactive(), lease.held():  # asked at 0, granted at 1, released at 2
        pass
    with pytest.raises(RuntimeError), lease.held():  # 3, 4, 5
        raise RuntimeError("the inference failed")
    with pytest.raises(RequestCancelledError), cancellable(lambda: True), lease.held():
        raise AssertionError("a cancelled request must not run")  # 6, 7, 8

    assert records == [
        TurnRecord(True, 1.0, 1.0, 0, 0, "RAN"),
        TurnRecord(False, 1.0, 1.0, 0, 0, "FAILED"),
        TurnRecord(False, 1.0, 1.0, 0, 0, "CANCELLED"),
    ]


def test_each_turn_records_how_many_of_each_class_were_still_waiting() -> None:
    records: list[TurnRecord] = []
    line = Line(WorkerLease(observe=records.append))
    line.join("background", is_interactive=False)
    line.join("search 1", is_interactive=True)
    line.join("search 2", is_interactive=True)

    assert line.let_go() == ["search 1", "search 2", "background"]
    depths = [(r.interactive, r.queued_interactive, r.queued_background) for r in records]
    assert depths == [
        (False, 0, 0),  # the holder, granted at once
        (True, 1, 1),  # search 1: search 2 and the background request still waiting
        (True, 0, 1),
        (False, 0, 0),
    ]


def test_by_default_each_turn_is_logged_at_debug_level(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="backend.ml.supervisor.lease"), WorkerLease().held():
        pass

    (record,) = caplog.records
    assert record.getMessage().startswith("worker: a background request waited ")
    assert record.getMessage().endswith(
        "(RAN); 0 interactive and 0 background waiting at its grant"
    )


def test_a_turn_whose_clock_fails_is_still_recorded_with_its_time_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The measurement never loses a turn and never fails one: a clock that fails at the release
    leaves the hold unknown; one that fails at the grant (the request then fails, as before) leaves
    both times unknown."""
    readings: list[float | Exception] = [0.0, 1.0, RuntimeError("the clock failed")]

    def clock() -> float:
        reading = readings.pop(0)
        if isinstance(reading, Exception):
            raise reading
        return reading

    records: list[TurnRecord] = []
    lease = WorkerLease(clock=clock, observe=records.append)
    with lease.held():  # asked at 0, granted at 1, the release reading fails
        pass
    readings[:] = [2.0, RuntimeError("the clock failed at the grant"), 3.0]
    with pytest.raises(RuntimeError, match="at the grant"), lease.held():
        raise AssertionError("the body must not run")

    assert records == [
        TurnRecord(False, 1.0, None, 0, 0, "RAN"),
        TurnRecord(False, None, None, 0, 0, "FAILED"),
    ]
    with caplog.at_level(logging.DEBUG, logger="backend.ml.supervisor.lease"):
        WorkerLease(clock=lambda: 0.0)._observe(records[1])  # noqa: SLF001 - the default observer
    assert "waited an unknown time and held it an unknown time (FAILED)" in caplog.text


def test_a_cancellation_check_that_fails_is_recorded_as_a_failed_turn() -> None:
    records: list[TurnRecord] = []
    lease = WorkerLease(observe=records.append)

    def broken() -> bool:
        raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError, match="locked"), cancellable(broken), lease.held():
        raise AssertionError("the body must not run")

    (record,) = records
    assert record.outcome == "FAILED"
