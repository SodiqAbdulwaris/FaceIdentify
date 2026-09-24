"""What WAL mode and SQLite's single writer actually do (M2: TST-021; PERSISTENCE_IMPLEMENTATION.md
§25: "WAL permits readers during normal writes; it does not permit multiple writers to hold long
transactions... The application must tolerate SQLITE_BUSY").

The pragma values themselves are asserted in `test_persistence_fixtures.py`, and the required
constraints in `test_schema_contract.py`. These tests pin the *behaviour* the rest of the backend
relies on: earlier code comments assume "SQLite's single-writer model", and use cases assume a
long-lived reader does not stop a writer.
"""

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.processing.models import ProcessingConfigurationSnapshot
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory


def database_path(engine: Engine) -> Path:
    assert engine.url.database is not None
    return Path(engine.url.database)


def snapshot_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ProcessingConfigurationSnapshot)) or 0


def test_the_database_file_is_persistently_in_wal_mode(sqlite_engine: Engine) -> None:
    """WAL is recorded in the file itself, so it survives without our per-connection pragma: a
    tool or a future code path that opens the library plainly still gets WAL, not a rollback
    journal."""
    with closing(sqlite3.connect(database_path(sqlite_engine))) as plain:
        assert plain.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_a_reader_is_not_blocked_by_an_open_write_transaction(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    build.snapshot()  # flushed, uncommitted: this session now holds the write lock

    with create_session_factory(sqlite_engine)() as reader:
        reader.connection().exec_driver_sql("PRAGMA busy_timeout = 0")  # blocked would fail at once
        assert snapshot_count(reader) == 0  # committed state only: the write is invisible
        reader.rollback()

        db_session.commit()
        assert snapshot_count(reader) == 1


def test_a_second_writer_is_refused_while_the_first_holds_the_write_lock(
    sqlite_engine: Engine, db_session: Session, build: ModelFactory
) -> None:
    build.snapshot()  # holds the write lock until commit or rollback

    with create_session_factory(sqlite_engine)() as second:
        second.connection().exec_driver_sql("PRAGMA busy_timeout = 50")  # keep the test fast
        second.add(
            ProcessingConfigurationSnapshot(
                id=build.new_id(),
                schema_version=1,
                canonical_json={},
                fingerprint_sha256=b"\x00" * 32,
                created_at=build.clock(),
            )
        )
        with pytest.raises(OperationalError, match="database is locked"):
            second.flush()
        second.rollback()

    db_session.commit()
    with create_session_factory(sqlite_engine)() as check:
        assert snapshot_count(check) == 1  # only the first writer's row


def test_a_reader_turned_writer_fails_at_once_if_another_writer_committed_in_between(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    """SQLite's BUSY_SNAPSHOT: a transaction that has already read cannot upgrade to a write once
    another connection has committed. Waiting does not help: it fails at once instead of waiting
    out the busy timeout. Every use case that reads before it writes (merge, split, assignment) is
    exposed to this, and a retry has to redo the whole transaction, not the failed statement."""
    factory = create_session_factory(sqlite_engine)
    with factory() as stale:
        stale.connection().exec_driver_sql("PRAGMA busy_timeout = 5000")  # generous: not waited
        assert snapshot_count(stale) == 0  # takes the read snapshot

        with factory() as other:
            other.add(
                ProcessingConfigurationSnapshot(
                    id=build.new_id(),
                    schema_version=1,
                    canonical_json={},
                    fingerprint_sha256=b"" * 32,
                    created_at=build.clock(),
                )
            )
            other.commit()

        stale.add(
            ProcessingConfigurationSnapshot(
                id=build.new_id(),
                schema_version=1,
                canonical_json={},
                fingerprint_sha256=b"" * 32,
                created_at=build.clock(),
            )
        )
        started = time.monotonic()
        with pytest.raises(OperationalError, match="database is locked"):
            stale.flush()
        assert time.monotonic() - started < 2  # far below the 5 s timeout: it did not wait
        stale.rollback()

        assert snapshot_count(stale) == 1  # a fresh transaction sees the other writer's row
