"""Who uses the one perception worker next (issue #175).

Owner decision 2026-10-14 (locked): one persistent worker, shared by interactive face searches and
background processing through cooperative priority scheduling with starvation protection. An
inference already running is never interrupted; the next one is chosen at that safe boundary:

* an interactive request goes before a background one, so a face search waits for at most the
  inference in progress (one detect or one represent), not for a whole source;
* within a class, requests are served first come, first served;
* after `burst` interactive grants in a row, a waiting background request goes first, so a stream
  of face searches cannot stop processing (and a backlog of processing never blocks a search
  beyond one inference).

A request is interactive when it is made inside `interactive()` (face search wraps its perception
in it); everything else is background. The lease is held only for the inference itself: nothing
here touches the database or the filesystem.
"""

import contextvars
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

LOG = logging.getLogger(__name__)

# Interactive grants in a row before a waiting background request goes first. ponytail: a fixed
# value until a benchmark of real searches against long runs picks one (the decision's point 4).
BURST = 3

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


class WorkerLease:
    def __init__(self, *, burst: int = BURST, clock: Callable[[], float] = time.monotonic) -> None:
        if burst < 1:
            raise ValueError("the burst must be at least one")
        self._burst = burst
        self._clock = clock
        self._condition = threading.Condition()
        self._held = False
        self._waiting: dict[bool, deque[object]] = {True: deque(), False: deque()}
        self._streak = 0  # interactive grants since the last background one

    def queued(self, interactive_class: bool) -> int:
        """How many requests of a class are waiting (for readiness and tests)."""
        with self._condition:
            return len(self._waiting[interactive_class])

    def _next(self) -> object | None:
        interactive_queue, background = self._waiting[True], self._waiting[False]
        if interactive_queue and (not background or self._streak < self._burst):
            return interactive_queue[0]
        if background:
            return background[0]
        return None

    @contextmanager
    def held(self) -> Iterator[None]:
        """Wait for the worker, in this request's class and turn, and hold it for the body."""
        cls = is_interactive()
        ticket = object()
        queued_at = self._clock()
        with self._condition:
            self._waiting[cls].append(ticket)
            try:
                self._condition.wait_for(lambda: not self._held and self._next() is ticket)
            except BaseException:  # (an interrupted wait must not leave its ticket at the head)
                self._waiting[cls].remove(ticket)
                self._condition.notify_all()
                raise
            self._waiting[cls].popleft()
            self._held = True
            self._streak = self._streak + 1 if cls else 0
        try:
            LOG.debug(
                "worker granted to a %s request after %.3fs",
                "interactive" if cls else "background",
                self._clock() - queued_at,
            )
            yield
        finally:
            with self._condition:
                self._held = False
                self._condition.notify_all()
