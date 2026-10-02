"""The unit of work: write transactions that queue instead of failing, and are retried whole
(PERSISTENCE_IMPLEMENTATION.md §25; CONTEXT open question 20, direction agreed 2026-10-01 and
finalised by the owner for item 3 of the build order; issue 37).

SQLite has one writer. A deferred transaction that *reads before it writes* fails immediately with
`SQLITE_BUSY_SNAPSHOT` if another writer commits in between, and no retry of the single statement
can fix that. So:

* a **write** unit of work begins with `BEGIN IMMEDIATE`: it takes the write lock first and waits
  for it (up to `busy_timeout`, 5 s), so what it reads afterwards cannot be made stale by another
  writer;
* if the lock still cannot be had, or SQLite reports busy or locked anywhere in the transaction,
  the **whole transaction** is rolled back and run again, a bounded number of times with a
  caller-chosen back-off, and then the final failure becomes `DatabaseBusyError`, which an API layer
  maps to a retryable error. The retry is never per statement.
* a **read** unit of work is an ordinary deferred transaction: a reader does not take the lock.

Because the function is run again from the start, it must be **a function of the session only**: no
non-idempotent work outside the transaction (sending, writing a file, spawning) belongs inside it,
since a retry would repeat that as though it were part of the transaction. Do such work after the
unit of work returns, or make it idempotent. The attempts and the back-off are the caller's: neither
has a default, because choosing them would be an unmeasured threshold; `sleep` is injected so tests
do not wait.
"""

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.infrastructure.db.engine import BEGIN_IMMEDIATE, create_session_factory

T = TypeVar("T")

# Primary SQLite result codes for "someone else has the database": SQLITE_BUSY and SQLITE_LOCKED.
# The extended codes (BUSY_SNAPSHOT, BUSY_RECOVERY, BUSY_TIMEOUT, LOCKED_SHAREDCACHE...) share their
# low byte with them.
_BUSY_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


class DatabaseBusyError(RuntimeError):
    """The write lock could not be had, or the transaction kept colliding with another writer, for
    every attempt allowed. Retryable by the caller of the API, not a defect."""


@dataclass(frozen=True)
class TransactionRetry:
    """`max_attempts` runs in all (at least 1); `backoff(n)` is how many seconds to wait after the
    n-th failed attempt before the next one."""

    max_attempts: int
    backoff: Callable[[int], float]


def is_busy(error: BaseException) -> bool:
    """Whether SQLite reported that another connection holds what this one needs (busy or locked,
    including the snapshot and recovery variants). Decided by the error *code*, not its text; an
    I/O error, a full disk or a constraint is not busy and is never retried."""
    original = error.orig if isinstance(error, OperationalError) else error
    code = getattr(original, "sqlite_errorcode", None)
    return (
        isinstance(original, sqlite3.OperationalError)
        and code is not None
        and (code & 0xFF) in _BUSY_CODES
    )


class UnitOfWork:
    def __init__(
        self,
        engine: Engine,
        *,
        retry: TransactionRetry,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retry.max_attempts < 1:
            raise ValueError("a unit of work runs at least once")
        self._retry = retry
        self._sleep = sleep
        self._read = create_session_factory(engine)
        self._write: sessionmaker[Session] = create_session_factory(
            engine.execution_options(**{BEGIN_IMMEDIATE: True})
        )

    def read(self, work: Callable[[Session], T]) -> T:
        """Run `work` in a deferred read transaction (rolled back afterwards: it writes nothing)."""
        with self._read() as session:
            try:
                return work(session)
            finally:
                session.rollback()

    def write(self, work: Callable[[Session], T]) -> T:
        """Run `work` in a `BEGIN IMMEDIATE` transaction and commit it. A busy or locked database,
        on beginning, in `work` or on commit, rolls the whole transaction back and runs `work`
        again, up to the policy's attempts; any other error rolls back and propagates at once.
        `work` may therefore run several times: see the module docstring."""
        failed = 0
        while True:
            try:
                with self._write() as session:
                    result = work(session)
                    session.commit()
                    return result
            except OperationalError as error:
                if not is_busy(error):
                    raise
                failed += 1
                if failed >= self._retry.max_attempts:
                    raise DatabaseBusyError(
                        f"the database stayed busy for {failed} attempt(s): {error.orig}"
                    ) from error
                self._sleep(self._retry.backoff(failed))
