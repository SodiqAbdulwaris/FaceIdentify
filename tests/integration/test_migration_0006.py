"""Revision 0006 preserves evidence while adding accepted-abstention history (M3: #104).

The new kind is deliberately an immutable event: later resolution may add evidence, but it must
not need to rewrite the decision that originally declined identity assignment.
"""

import io
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import downgrade, dump, migrate, populate_legacy, table_sql, version
from tests.fixtures.persistence import alembic_config

OLD_KINDS = (
    "IDENTITY_CREATED",
    "IDENTITY_MATCHED",
    "IDENTITY_ASSIGNED_TO_PERSON",
    "IDENTITY_REMOVED_FROM_PERSON",
    "IDENTITY_MERGED",
    "IDENTITY_SPLIT",
    "IDENTITY_FORGOTTEN",
    "USER_CORRECTION",
)
NEW_KIND = "RECOGNITION_ABSTAINED"


def populated_0005(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0005")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        run = build.run()
        build.evidence(kind="IDENTITY_MATCHED", processing_run_id=run.id, source_id=run.source_id)

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    assert len(dump(path)["evidence"]) == 1
    return path


def test_a_populated_database_keeps_evidence_and_accepts_the_new_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0005(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    migrate(monkeypatch, path, "0006")

    assert version(path) == "0006"
    assert dump(path) == before
    assert NEW_KIND in table_sql(path, "evidence")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            abstention = build.evidence(kind=NEW_KIND)
            session.commit()
            assert abstention.kind == NEW_KIND
            with pytest.raises(IntegrityError, match="ck_evidence_kind"):
                build.evidence(kind="INVENTED")
            session.rollback()
    finally:
        engine.dispose()


def test_downgrade_refuses_the_new_historical_kind_without_changing_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0005(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0006")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            ModelFactory(session, clock, new_id).evidence(kind=NEW_KIND)
            session.commit()
    finally:
        engine.dispose()
    before = dump(path)

    with pytest.raises(IntegrityError, match="ck_evidence_kind"):
        downgrade(monkeypatch, path, "0005", allow_destructive=True)

    assert version(path) == "0006"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0005:0006", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_evidence" in sql
    assert NEW_KIND in sql
    assert "fk_evidence_processing_run_id_processing_runs" in sql
