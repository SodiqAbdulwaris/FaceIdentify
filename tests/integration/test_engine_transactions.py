"""SQLite transaction semantics of the production engine.

Python's sqlite3 driver defers BEGIN until the first DML statement. Without the engine's
explicit BEGIN, a SAVEPOINT issued first would open the outer transaction itself, and its
RELEASE would commit, so a later rollback could not undo it.
"""

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from backend.app.processing.models import ProcessingConfigurationSnapshot
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import SHA
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs


def _snapshot(clock: FrozenClock, new_id: SeededUUIDs) -> ProcessingConfigurationSnapshot:
    return ProcessingConfigurationSnapshot(
        id=new_id(), schema_version=1, canonical_json={}, fingerprint_sha256=SHA, created_at=clock()
    )


def _count(engine: Engine) -> int | None:
    with engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(ProcessingConfigurationSnapshot))


def test_released_savepoint_is_undone_by_outer_rollback(
    sqlite_engine: Engine, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    with create_session_factory(sqlite_engine)() as session:
        with session.begin_nested():  # the very first statement of the transaction
            session.add(_snapshot(clock, new_id))
        session.rollback()
    assert _count(sqlite_engine) == 0


def test_rolled_back_savepoint_keeps_earlier_writes(
    sqlite_engine: Engine, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    with create_session_factory(sqlite_engine)() as session:
        session.add(_snapshot(clock, new_id))
        session.flush()
        savepoint = session.begin_nested()
        session.add(_snapshot(clock, new_id))
        session.flush()
        savepoint.rollback()
        session.commit()
    assert _count(sqlite_engine) == 1


def test_commit_is_durable(sqlite_engine: Engine, clock: FrozenClock, new_id: SeededUUIDs) -> None:
    with Session(sqlite_engine) as session:
        session.add(_snapshot(clock, new_id))
        session.commit()
    assert _count(sqlite_engine) == 1
