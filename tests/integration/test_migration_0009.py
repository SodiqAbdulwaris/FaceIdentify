"""Revision 0009 removes the never-assigned SPLIT identity state (CONTEXT question 15)."""

import io
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.infrastructure.db.downgrade_guard import DestructiveDowngradeRefused
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import downgrade, dump, migrate, populate_legacy, table_sql, version
from tests.fixtures.persistence import alembic_config


def populated_0008(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: FrozenClock,
    new_id: SeededUUIDs,
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0008")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        survivor = build.identity()
        loser = build.identity(state="MERGED", merged_into_identity_id=survivor.id)
        build.identity()
        # rows in other tables that point at identities must survive the recreation
        build.evidence(kind="IDENTITY_MERGED", subject_identity_id=survivor.id)
        build.lineage(loser.id, survivor.id, "MERGED_INTO")
        build.occurrence(identity_id=survivor.id)

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    assert len(dump(path)["identities"]) == 3
    return path


def test_a_populated_database_keeps_its_identities_and_refuses_the_removed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0008(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    migrate(monkeypatch, path, "0009")

    assert version(path) == "0009"
    assert dump(path) == before
    assert "'SPLIT'" not in table_sql(path, "identities")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            with pytest.raises(IntegrityError, match="ck_identities_state"):
                build.identity(state="SPLIT")
            session.rollback()
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):  # enforcement is back on
                build.evidence(kind="IDENTITY_MERGED", subject_identity_id=new_id())
            session.rollback()
    finally:
        engine.dispose()


def test_an_identity_left_in_the_removed_state_stops_the_upgrade_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0008(tmp_path, monkeypatch, clock, new_id)
    with sqlite3.connect(path) as connection:  # head's own check refuses the state, so write raw
        connection.execute(
            "INSERT INTO identities (id, state, created_at, updated_at)"
            " VALUES ('00000000000000000000000000000009', 'SPLIT', '2026-01-01 00:00:00.000000',"
            " '2026-01-01 00:00:00.000000')"
        )
    before = dump(path)

    with pytest.raises(IntegrityError, match="ck_identities_state"):
        migrate(monkeypatch, path, "0009")

    assert version(path) == "0008"
    assert dump(path) == before


def test_downgrade_restores_the_state_on_an_empty_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0009")

    downgrade(monkeypatch, path, "0008")

    assert version(path) == "0008"
    assert "'SPLIT'" in table_sql(path, "identities")


def test_downgrade_refuses_a_populated_library_unless_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0008(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0009")
    before = dump(path)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade(monkeypatch, path, "0008")
    assert version(path) == "0009"
    assert dump(path) == before

    downgrade(monkeypatch, path, "0008", allow_destructive=True)
    assert version(path) == "0008"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0008:0009", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_identities" in sql
    assert "ck_identities_state" in sql
    assert "'SPLIT'" not in sql
