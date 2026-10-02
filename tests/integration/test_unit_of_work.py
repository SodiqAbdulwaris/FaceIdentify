"""The unit of work: BEGIN IMMEDIATE and whole-transaction retry (M2: TST-024; persistence
section 25; CONTEXT open question 20; issue 37).

A write begins by taking SQLite's write lock, so a transaction that reads first cannot be made stale
by another writer; a busy or locked database rolls the whole transaction back and runs it again, a
bounded number of times, and the final failure is a retryable error. What counts as busy is decided
by SQLite's error code, never by message text.
"""

import sqlite3
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.infrastructure.db.unit_of_work import (
    DatabaseBusyError,
    TransactionRetry,
    UnitOfWork,
    is_busy,
)


def error_with(code: int | None, message: str = "database is locked") -> OperationalError:
    inner = sqlite3.OperationalError(message)
    if code is not None:
        inner.sqlite_errorcode = code
    return OperationalError("UPDATE counter", {}, inner)


def busy() -> OperationalError:
    return error_with(sqlite3.SQLITE_BUSY)


@pytest.fixture
def counter(sqlite_engine: Engine) -> Engine:
    """The test database with one table to write to."""
    with sqlite_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER)")
        connection.exec_driver_sql("INSERT INTO counter VALUES (1, 0)")
    return sqlite_engine


class Sleeps:
    """An injected `sleep` that records instead of waiting."""

    def __init__(self) -> None:
        self.waited: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


RETRY = TransactionRetry(max_attempts=3, backoff=lambda n: 0.5 * n)


def value(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql("SELECT n FROM counter WHERE id = 1").scalar_one())


def rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql("SELECT count(*) FROM counter").scalar_one())


@pytest.fixture
def statements(counter: Engine) -> Iterator[list[str]]:
    seen: list[str] = []

    def spy(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(counter, "before_cursor_execute", spy)
    yield seen
    event.remove(counter, "before_cursor_execute", spy)


# --- how a transaction begins -------------------------------------------------------------------


def test_a_write_begins_immediately_and_a_read_does_not(
    counter: Engine, statements: list[str]
) -> None:
    uow = UnitOfWork(counter, retry=RETRY, sleep=Sleeps())

    uow.write(lambda session: session.execute(text("UPDATE counter SET n = n + 1")))
    written = [s for s in statements if s.startswith("BEGIN")]
    statements.clear()
    uow.read(lambda session: session.execute(text("SELECT n FROM counter")).all())
    read = [s for s in statements if s.startswith("BEGIN")]

    assert written == ["BEGIN IMMEDIATE"]
    assert read == ["BEGIN"]


def test_a_write_commits_what_it_did_and_returns_its_result(counter: Engine) -> None:
    uow = UnitOfWork(counter, retry=RETRY, sleep=Sleeps())

    def work(session: Session) -> int:
        session.execute(text("UPDATE counter SET n = 41"))
        return int(session.execute(text("SELECT n + 1 FROM counter")).scalar_one())

    assert uow.write(work) == 42
    assert value(counter) == 41


def test_a_read_commits_nothing(counter: Engine) -> None:
    uow = UnitOfWork(counter, retry=RETRY, sleep=Sleeps())

    assert (
        uow.read(lambda session: session.execute(text("SELECT n FROM counter")).scalar_one()) == 0
    )
    uow.read(lambda session: session.execute(text("UPDATE counter SET n = 99")))

    assert value(counter) == 0


def test_an_error_in_the_work_rolls_the_write_back_and_propagates_without_a_retry(
    counter: Engine,
) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)
    calls = 0

    def work(session: Session) -> None:
        nonlocal calls
        calls += 1
        session.execute(text("UPDATE counter SET n = 7"))
        raise ValueError("not a database problem")

    with pytest.raises(ValueError, match="not a database"):
        uow.write(work)

    assert (calls, value(counter), sleeps.waited) == (1, 0, [])


def test_a_constraint_error_is_not_busy_and_is_not_retried(counter: Engine) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)

    with pytest.raises(IntegrityError):
        uow.write(lambda session: session.execute(text("INSERT INTO counter VALUES (1, 5)")))

    assert sleeps.waited == []


# --- two writers that read before they write -------------------------------------------


def test_two_writers_that_read_before_they_write_queue_instead_of_colliding(
    counter: Engine,
) -> None:
    """A reads the counter, B arrives while A is still in its transaction, A writes and commits, B
    then reads *its* value. With a deferred begin B would read the old value, A's commit would make
    B's snapshot stale and B's write would fail with BUSY_SNAPSHOT (then be retried): so there must
    be no retry at all, and both increments must be applied to the latest value."""
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)
    a_read, b_arrived = threading.Event(), threading.Event()

    def spy(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if threading.current_thread().name == "B" and statement.startswith("BEGIN"):
            b_arrived.set()

    event.listen(counter, "before_cursor_execute", spy)

    def a(session: Session) -> None:
        current = session.execute(text("SELECT n FROM counter")).scalar_one()
        a_read.set()
        assert b_arrived.wait(timeout=10)
        time.sleep(0.2)  # let B reach (and wait at) its BEGIN IMMEDIATE
        session.execute(text("UPDATE counter SET n = :n"), {"n": current + 1})

    def b(session: Session) -> None:
        current = session.execute(text("SELECT n FROM counter")).scalar_one()
        session.execute(text("UPDATE counter SET n = :n"), {"n": current + 1})

    failures: list[BaseException] = []

    def run(name: str, work: Any) -> threading.Thread:
        def target() -> None:
            try:
                uow.write(work)
            except BaseException as error:  # noqa: BLE001 - reported to the test below
                failures.append(error)

        thread = threading.Thread(target=target, name=name)
        thread.start()
        return thread

    try:
        thread_a = run("A", a)
        assert a_read.wait(timeout=10)
        thread_b = run("B", b)
        thread_a.join(timeout=30)
        thread_b.join(timeout=30)
    finally:
        event.remove(counter, "before_cursor_execute", spy)

    assert failures == []
    assert value(counter) == 2  # B saw A's committed value
    assert sleeps.waited == []  # and nothing collided, so nothing was retried


# --- retry ---------------------------------------------------------------------------------------


def test_a_busy_transaction_is_rolled_back_and_run_again_from_the_start(counter: Engine) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)
    calls = 0

    def work(session: Session) -> str:
        nonlocal calls
        calls += 1
        session.execute(text("INSERT INTO counter VALUES (:id, 0)"), {"id": 100 + calls})
        if calls < 3:
            raise busy()  # (after writing: the write must not survive the rollback)
        return "done"

    assert uow.write(work) == "done"

    assert calls == 3
    assert sleeps.waited == [0.5, 1.0]  # the back-off after the first and the second failure
    assert rows(counter) == 2  # the original row and only the successful attempt's insert


def test_every_busy_variant_is_retried(counter: Engine) -> None:
    uow = UnitOfWork(counter, retry=TransactionRetry(2, lambda n: 0.0), sleep=Sleeps())
    for code in (
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_BUSY | (1 << 8),  # BUSY_RECOVERY
        sqlite3.SQLITE_BUSY | (2 << 8),  # BUSY_SNAPSHOT
        sqlite3.SQLITE_LOCKED | (1 << 8),  # LOCKED_SHAREDCACHE
    ):
        attempts = 0

        def work(session: Session, code: int = code) -> int:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise error_with(code)
            return attempts

        assert uow.write(work) == 2, code


def test_the_last_failure_becomes_a_retryable_error_after_the_attempts_allowed(
    counter: Engine,
) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)
    calls = 0

    def work(session: Session) -> None:
        nonlocal calls
        calls += 1
        session.execute(text("UPDATE counter SET n = 9"))
        raise busy()

    with pytest.raises(DatabaseBusyError, match="3 attempt") as raised:
        uow.write(work)

    assert calls == 3
    assert sleeps.waited == [0.5, 1.0]  # no wait after the last attempt
    assert isinstance(raised.value.__cause__, OperationalError)
    assert value(counter) == 0  # nothing of any attempt was kept


def test_one_attempt_means_no_retry(counter: Engine) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=TransactionRetry(1, lambda n: 1.0), sleep=sleeps)

    def work(session: Session) -> None:
        raise busy()

    with pytest.raises(DatabaseBusyError):
        uow.write(work)

    assert sleeps.waited == []


def test_an_io_error_is_not_busy_and_is_not_retried(counter: Engine) -> None:
    sleeps = Sleeps()
    uow = UnitOfWork(counter, retry=RETRY, sleep=sleeps)
    calls = 0

    def work(session: Session) -> None:
        nonlocal calls
        calls += 1
        raise error_with(sqlite3.SQLITE_IOERR, "disk I/O error")

    with pytest.raises(OperationalError, match="disk I/O error"):
        uow.write(work)

    assert (calls, sleeps.waited) == (1, [])


def test_a_real_locked_database_is_waited_out_and_the_transaction_then_succeeds(
    counter: Engine,
) -> None:
    """Another connection holds the write lock and the engine does not wait for it: BEGIN IMMEDIATE
    fails with SQLite's own busy error, which is retried after the back-off (here: the holder lets
    go during the wait)."""
    counter.dispose()
    event.listen(
        counter, "connect", lambda connection, _: connection.execute("PRAGMA busy_timeout = 0")
    )
    holder = sqlite3.connect(str(counter.url.database), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    waits: list[float] = []

    def release_the_lock(seconds: float) -> None:
        waits.append(seconds)
        holder.execute("COMMIT")

    uow = UnitOfWork(counter, retry=RETRY, sleep=release_the_lock)
    try:
        uow.write(lambda session: session.execute(text("UPDATE counter SET n = 5")))
    finally:
        holder.close()

    assert waits == [0.5]  # one failed attempt, one wait
    assert value(counter) == 5


def test_a_unit_of_work_runs_at_least_once() -> None:
    with pytest.raises(ValueError, match="at least once"):
        UnitOfWork(None, retry=TransactionRetry(0, lambda n: 0.0))  # type: ignore[arg-type]


# --- what is busy --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_BUSY | (1 << 8),
        sqlite3.SQLITE_BUSY | (2 << 8),
        sqlite3.SQLITE_BUSY | (3 << 8),
        sqlite3.SQLITE_LOCKED | (1 << 8),
    ],
)
def test_busy_and_locked_in_all_their_variants_are_busy(code: int) -> None:
    assert is_busy(error_with(code))
    inner = sqlite3.OperationalError("x")
    inner.sqlite_errorcode = code
    assert is_busy(inner)  # the driver's own error, before SQLAlchemy wraps it


@pytest.mark.parametrize(
    "code",
    [sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL, sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_READONLY],
)
def test_other_errors_are_not_busy_whatever_their_message_says(code: int) -> None:
    assert not is_busy(error_with(code, "database is locked"))  # the text is not consulted


def test_an_error_without_a_code_or_of_another_kind_is_not_busy() -> None:
    assert not is_busy(error_with(None))
    assert not is_busy(ValueError("database is locked"))
    assert not is_busy(IntegrityError("INSERT", {}, sqlite3.IntegrityError("UNIQUE")))


def test_only_a_sqlite_operational_error_can_be_busy_whatever_attribute_it_carries() -> None:
    impostor = RuntimeError("database is locked")
    impostor.sqlite_errorcode = sqlite3.SQLITE_BUSY  # type: ignore[attr-defined]

    assert not is_busy(impostor)
    assert not is_busy(sqlite3.IntegrityError("x"))
