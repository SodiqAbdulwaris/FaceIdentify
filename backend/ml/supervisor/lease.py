"""Who uses the one perception worker next (issue #175).

Owner decision 2026-10-14 (locked): one persistent worker, shared by interactive face searches and
background processing through cooperative priority scheduling with starvation protection. An
inference already running is never interrupted; the next one is chosen at that safe boundary:

* an interactive request goes before a waiting background one, so a face search waits for the
  inference in progress and the interactive requests ahead of it (one detect or one represent
  each), not for a whole source;
* within a class, requests are served first come, first served;
* after `burst` interactive grants in a row, a waiting background request goes first, so a stream
  of face searches cannot stop processing (and a backlog of processing delays a search by at most
  the inference in progress, and one background inference after a burst).

A request is interactive when it is made inside `interactive()` (face search wraps its perception
in it); everything else is background. The lease is held through a worker request and its output
attachment/release: nothing here touches the database or the filesystem.

A request made inside `cancellable(cancelled)` is asked `cancelled()` when its turn comes, before it
reaches the worker: one that answers true gives its turn up and raises `RequestCancelledError`, so
a request cancelled while it waited never enters inference (decision point 5). An inference already
running is never interrupted; its cancellation is the caller's to observe after it, at the boundary.

Every turn is measured (decision point 8, M6 D5): its class, how long it waited, how long it held
the worker, how many of each class were still waiting when it was granted, and whether it ran,
failed or was cancelled. A `TurnRecord` goes to `observe`, which logs it at debug level unless told
otherwise (the stress benchmark collects them).
"""

import contextvars
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from backend.ml.supervisor.supervisor import MLUnavailableError

LOG = logging.getLogger(__name__)

# Interactive grants in a row before a waiting background request goes first. ponytail: a fixed
# value until a benchmark of real searches against long runs picks one (the decision's point 4).
BURST = 3


class WorkerClosedError(MLUnavailableError):
    """The worker is shutting down: no request gets a turn any more."""


class RequestCancelledError(MLUnavailableError):
    """The request was cancelled while it waited: it gave its turn up and never ran."""


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One request's turn on the worker."""

    interactive: bool
    waited: float | None  # seconds from asking for the turn to getting it (None: the clock failed)
    held: float | None  # seconds holding the worker: inference and output protocol (None: idem)
    queued_interactive: int  # requests of each class still waiting when this one was granted
    queued_background: int
    outcome: str  # RAN, FAILED (the body raised) or CANCELLED (given up at its turn)


def _seconds(value: float | None) -> str:
    return "an unknown time" if value is None else f"{value:.3f}s"


def log_turn(record: TurnRecord) -> None:
    """The default observer: one debug line per turn."""
    LOG.debug(
        "worker: a %s request waited %s and held it %s (%s); %d interactive and %d "
        "background waiting at its grant",
        "interactive" if record.interactive else "background",
        _seconds(record.waited),
        _seconds(record.held),
        record.outcome,
        record.queued_interactive,
        record.queued_background,
    )


_interactive: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "faceidentify_interactive", default=False
)


@contextmanager
def interactive() -> Iterator[None]:
    """Mark the worker requests made inside as interactive (a person is waiting for them)."""
    token = _interactive.set(True)
    try:
        yield
    finally:
        _interactive.reset(token)


def is_interactive() -> bool:
    """Whether the current request is made inside `interactive()`."""
    return _interactive.get()


_cancelled: contextvars.ContextVar[Callable[[], bool] | None] = contextvars.ContextVar(
    "faceidentify_cancelled", default=None
)


@contextmanager
def cancellable(cancelled: Callable[[], bool]) -> Iterator[None]:
    """Ask `cancelled()` at the turn of each worker request made inside, before it runs."""
    token = _cancelled.set(cancelled)
    try:
        yield
    finally:
        _cancelled.reset(token)


class WorkerLease:
    def __init__(
        self,
        *,
        burst: int = BURST,
        clock: Callable[[], float] = time.perf_counter,  # (monotonic, and finer than
        # time.monotonic on Windows, whose 15.6 ms tick hid short waits)
        observe: Callable[[TurnRecord], None] = log_turn,
    ) -> None:
        if burst < 1:
            raise ValueError("the burst must be at least one")
        self._burst = burst
        self._clock = clock
        self._observe = observe  # (must not raise: it runs as the turn is released)
        self._condition = threading.Condition()
        self._held = False
        self._closed = False
        self._waiting: dict[bool, deque[object]] = {True: deque(), False: deque()}
        self._streak = 0  # interactive grants since the last background one

    def queued(self, interactive_class: bool) -> int:
        """How many requests of a class are waiting (for readiness and tests)."""
        with self._condition:
            return len(self._waiting[interactive_class])

    def close(self) -> None:
        """Refuse every request that waits and every later one (shutdown), so a queued request is
        never granted a worker that has been stopped. One already holding the worker finishes."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def wait_until_idle(self) -> None:
        """Wait for the granted request to leave its worker protocol boundary."""
        with self._condition:
            self._condition.wait_for(lambda: not self._held)

    def _next(self) -> object:
        """The ticket to serve next. Only a waiter calls it, so one queue is never empty."""
        interactive_queue, background = self._waiting[True], self._waiting[False]
        if interactive_queue and (not background or self._streak < self._burst):
            return interactive_queue[0]
        return background[0]

    @contextmanager
    def held(self) -> Iterator[None]:
        """Wait for the worker, in this request's class and turn, and hold it for the body."""
        cls = is_interactive()
        ticket = object()
        queued_at = self._clock()
        with self._condition:
            if self._closed:
                raise WorkerClosedError("the worker is shutting down")
            self._waiting[cls].append(ticket)
            try:
                self._condition.wait_for(
                    lambda: self._closed or (not self._held and self._next() is ticket)
                )
                if self._closed:
                    raise WorkerClosedError("the worker is shutting down")
            except BaseException:  # (a wait that ends without a turn must not leave its ticket)
                self._waiting[cls].remove(ticket)
                self._condition.notify_all()
                raise
            self._waiting[cls].popleft()
            self._held = True
            behind = (len(self._waiting[True]), len(self._waiting[False]))
        granted_at: float | None = None
        outcome = "FAILED"
        try:
            granted_at = self._clock()
            cancelled = _cancelled.get()
            if cancelled is not None and cancelled():  # (asked holding the turn, never the lock)
                outcome = "CANCELLED"
                raise RequestCancelledError(
                    "the request was cancelled before it reached the worker"
                )
            with self._condition:  # (a turn given up does not count towards the burst)
                self._streak = self._streak + 1 if cls else 0
            yield
            outcome = "RAN"
        finally:
            with self._condition:
                self._held = False
                self._condition.notify_all()
            released_at = self._reading()  # (a failing clock must not lose the turn's record)
            self._observe(
                TurnRecord(
                    cls,
                    _span(queued_at, granted_at),
                    _span(granted_at, released_at),
                    *behind,
                    outcome,
                )
            )

    def _reading(self) -> float | None:
        """The clock, or None if it fails: timing is diagnosis, never a reason to fail a turn."""
        try:
            return self._clock()
        except Exception:  # noqa: BLE001 - recorded as an unknown time, see `TurnRecord`
            return None


def _span(start: float | None, end: float | None) -> float | None:
    return None if start is None or end is None else end - start
