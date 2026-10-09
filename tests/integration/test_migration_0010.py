"""Revision 0010 lets a deleted artifact have no location and adds the source-deleted Evidence kind
(owner decision 2026-10-09, M5 step 4c; identity model section 41)."""

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

NEW_KIND = "SOURCE_PERMANENTLY_DELETED"


def populated_0009(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0009")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        run = build.run()
        build.evidence(kind="IDENTITY_MATCHED", processing_run_id=run.id, source_id=run.source_id)
        build.artifact(kind="FACE_CROP")

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    assert len(dump(path)["evidence"]) == 1
    assert dump(path)["artifacts"]
    return path


def test_a_populated_database_keeps_its_rows_and_accepts_the_new_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0009(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    migrate(monkeypatch, path, "0010")

    assert version(path) == "0010"
    assert dump(path) == before
    assert NEW_KIND in table_sql(path, "evidence")
    assert "state = 'DELETED'" in table_sql(path, "artifacts")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            build.evidence(kind=NEW_KIND)
            # a deleted referenced artifact may carry no path; any other without a location may not
            build.artifact(
                storage_mode="REFERENCED", storage_key=None, external_path=None, state="DELETED"
            )
            session.commit()
            with pytest.raises(IntegrityError, match="ck_artifacts_location"):
                build.artifact(
                    storage_mode="REFERENCED", storage_key=None, external_path=None, state="MISSING"
                )
            session.rollback()
            with pytest.raises(IntegrityError, match="ck_evidence_kind"):
                build.evidence(kind="INVENTED")
            session.rollback()
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):  # enforcement is back on
                build.evidence(kind="IDENTITY_MERGED", subject_identity_id=new_id())
            session.rollback()
    finally:
        engine.dispose()


def test_downgrade_restores_the_stricter_rules_on_an_empty_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0010")

    downgrade(monkeypatch, path, "0009")

    assert version(path) == "0009"
    assert NEW_KIND not in table_sql(path, "evidence")
    assert "state = 'DELETED'" not in table_sql(path, "artifacts")


def test_downgrade_refuses_a_populated_library_unless_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0009(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0010")
    before = dump(path)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade(monkeypatch, path, "0009")
    assert version(path) == "0010"
    assert dump(path) == before

    downgrade(monkeypatch, path, "0009", allow_destructive=True)
    assert version(path) == "0009"
    assert dump(path) == before


@pytest.mark.parametrize("what", ["kind", "artifact"])
def test_a_forced_downgrade_is_stopped_by_data_the_old_rules_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    what: str,
) -> None:
    path = populated_0009(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0010")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            if what == "kind":
                build.evidence(kind=NEW_KIND)
            else:
                build.artifact(
                    storage_mode="REFERENCED", storage_key=None, external_path=None, state="DELETED"
                )
            session.commit()
    finally:
        engine.dispose()
    before = dump(path)
    expected = "ck_evidence_kind" if what == "kind" else "ck_artifacts_location"

    with pytest.raises(IntegrityError, match=expected):
        downgrade(monkeypatch, path, "0009", allow_destructive=True)

    assert version(path) == "0010"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0009:0010", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_evidence" in sql
    assert "_alembic_tmp_artifacts" in sql
    assert NEW_KIND in sql
    assert "state = 'DELETED'" in sql
    assert "UPDATE artifacts SET external_path = NULL" in sql  # the legacy rows, cleared too


def legacy_referenced_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    """A 0009 library whose referenced original was already deleted (or being deleted) and so still
    carries the user's path: the revision exists to remove it."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0009")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        build.artifact(
            storage_mode="REFERENCED",
            storage_key=None,
            external_path="C:/private/Ada-holiday.jpg",
            original_filename="Ada-holiday.jpg",
            mime_type="image/jpeg",
            sha256=b"\x01" * 32,
            size_bytes=7,
            state="DELETED",
        )
        build.artifact(  # a live referenced file is the user's and is left exactly as it is
            storage_mode="REFERENCED",
            storage_key=None,
            external_path="C:/private/live.jpg",
            original_filename="live.jpg",
        )

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    return path


def test_upgrading_clears_the_path_of_an_original_deleted_before_it_and_owes_a_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = legacy_referenced_original(tmp_path, monkeypatch, clock, new_id)

    migrate(monkeypatch, path, "0010")

    with sqlite3.connect(path) as connection:
        columns = "external_path, original_filename, sha256, size_bytes, mime_type"
        deleted = connection.execute(
            f"SELECT {columns} FROM artifacts WHERE state = 'DELETED'"  # noqa: S608
        ).fetchall()
        live = connection.execute(
            "SELECT external_path, original_filename FROM artifacts"
            " WHERE storage_mode = 'REFERENCED' AND state = 'AVAILABLE'"
        ).fetchall()
        owed = connection.execute("SELECT key FROM app_state").fetchall()
    assert deleted == [(None, None, None, None, None)]
    assert live == [("C:/private/live.jpg", "live.jpg")]
    assert owed == [("wal_truncation_owed",)]


def test_upgrading_a_library_with_nothing_to_clear_owes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0009(tmp_path, monkeypatch, clock, new_id)

    migrate(monkeypatch, path, "0010")

    assert dump(path)["app_state"] == []
