"""Revision 0004 (the `app_state` key/value table) and its repository (M2: TST-032, TST-031;
GitHub issue 52).

The table holds the durable "WAL truncation owed" marker. A database that really holds rows at
revision 0003 is migrated, a failing revision is shown to leave it as it was, and the repository's
one-statement operations are checked on the migrated schema.
"""

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import (
    downgrade,
    dump,
    fail,
    foreign_key_violations,
    migrate,
    patch_revision,
    populate_legacy,
    version,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def populated_0003(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0003")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        build.representation()
        build.identity()

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    return path


def tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


# --- the migration ------------------------------------------------------------------------------


def test_a_populated_database_upgrades_with_every_row_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0003(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    assert "app_state" not in tables(path)

    migrate(monkeypatch, path, "0004")

    assert version(path) == "0004"
    assert dump(path) == {**before, "app_state": []}  # nothing else changed; the table is empty
    assert foreign_key_violations(path) == []


def test_a_failing_revision_leaves_the_database_at_0003_without_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0003(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    patch_revision(monkeypatch, "0004", after_upgrade=fail("0004 failed at the very end"))

    with pytest.raises(RuntimeError, match="at the very end"):
        migrate(monkeypatch, path, "0004")

    assert version(path) == "0003"
    assert dump(path) == before
    assert "app_state" not in tables(path)  # the table was created in the rolled-back transaction


def test_downgrade_drops_the_table_and_leaves_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0003(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0004")

    downgrade(monkeypatch, path, "0003", allow_destructive=True)

    assert version(path) == "0003"
    assert dump(path) == before
    assert "app_state" not in tables(path)


# --- the repository -----------------------------------------------------------------------------


def test_the_key_must_not_be_empty(sqlite_engine: Engine) -> None:
    with sqlite_engine.begin() as connection, pytest.raises(IntegrityError, match="key_not_empty"):
        connection.execute(
            text("INSERT INTO app_state (key, value, updated_at) VALUES ('', 'x', :now)"),
            {"now": "2026-10-01 12:00:00.000000"},
        )


def test_set_creates_a_value_and_overwrites_it_in_one_row(sqlite_engine: Engine) -> None:
    with Session(sqlite_engine) as session:
        repository = AppStateRepository(session)
        repository.set(WAL_TRUNCATION_OWED, "one", now=NOW)
        repository.set(WAL_TRUNCATION_OWED, "two", now=NOW)
        session.commit()

        assert repository.get(WAL_TRUNCATION_OWED) == "two"
        assert repository.get("unknown") is None
        count = session.execute(text("SELECT count(*) FROM app_state")).scalar_one()
        assert count == 1


def test_clear_deletes_the_marker_and_reports_whether_it_did(sqlite_engine: Engine) -> None:
    with Session(sqlite_engine) as session:
        repository = AppStateRepository(session)
        assert repository.clear(WAL_TRUNCATION_OWED) is False  # nothing to clear
        repository.set(WAL_TRUNCATION_OWED, "one", now=NOW)

        assert repository.clear(WAL_TRUNCATION_OWED) is True
        assert repository.get(WAL_TRUNCATION_OWED) is None


def test_clearing_with_a_value_leaves_a_marker_that_was_set_again_meanwhile(
    sqlite_engine: Engine,
) -> None:
    """A checkpoint that finishes after a later erasure re-set the marker must not clear it: that
    erasure's own checkpoint has not run yet."""
    with Session(sqlite_engine) as session:
        repository = AppStateRepository(session)
        repository.set(WAL_TRUNCATION_OWED, uuid.UUID(int=1).hex, now=NOW)
        repository.set(WAL_TRUNCATION_OWED, uuid.UUID(int=2).hex, now=NOW)

        assert repository.clear(WAL_TRUNCATION_OWED, value=uuid.UUID(int=1).hex) is False
        assert repository.get(WAL_TRUNCATION_OWED) == uuid.UUID(int=2).hex
        assert repository.clear(WAL_TRUNCATION_OWED, value=uuid.UUID(int=2).hex) is True
