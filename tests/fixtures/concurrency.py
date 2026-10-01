"""Make concurrent writers genuinely overlap, without sleeping.

A threaded test that only starts its threads together can pass by luck: each unit of work is so
short that the threads run one after another. `rendezvous_before_write` holds every thread at its
first matching statement until all of them have arrived, so an implementation that reads and then
writes (a lost update waiting to happen) has every thread read before any thread writes. A correct
single-statement write is unaffected: the hold is *before* the statement runs, so no lock is held
while waiting.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event


@contextmanager
def rendezvous_before_write(engine: Engine, statement_prefix: str, parties: int) -> Iterator[None]:
    """For the duration, each thread's first statement beginning with `statement_prefix` waits
    until `parties` threads have reached one. A thread's later statements are not held, so the
    rest of its work runs freely. Waiting is bounded; a thread that never arrives breaks the
    barrier and the test fails rather than hangs."""
    barrier = threading.Barrier(parties)
    arrived = threading.local()

    def hold(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if statement.lstrip().startswith(statement_prefix) and not getattr(arrived, "done", False):
            arrived.done = True
            barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", hold)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", hold)
