"""Revision 0011 adds reprocessing generations: the supersession link, the superseded timestamps and
two Evidence kinds (owner decision 2026-11-09, D1; persistence 12.1 item 1)."""

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.infrastructure.db.downgrade_guard import DestructiveDowngradeRefused
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import (
    downgrade,
    dump,
    foreign_key_violations,
    migrate,
    populate_legacy,
    table_sql,
    version,
)
from tests.fixtures.persistence import alembic_config

NEW_KINDS = ("REPROCESS_DECISION_CARRIED_OVER", "REPROCESS_REVIEW_REQUIRED")
TABLES = ("processing_runs", "observations", "representations", "occurrences", "evidence")


def populated_0010(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0010")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        run = build.run(state="COMPLETED")
        observation = build.observation(run, state="ACTIVE")
        identity = build.identity()
        build.representation(observation, identity_id=identity.id, state="ACTIVE", ann_key=1)
        build.occurrence(observation, identity_id=identity.id, state="ACTIVE")
        build.evidence(kind="IDENTITY_MATCHED", processing_run_id=run.id, source_id=run.source_id)

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    rows = dump(path)
    assert all(rows[table] for table in TABLES)
    return path


def test_a_populated_database_keeps_its_rows_and_accepts_the_new_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0010(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    migrate(monkeypatch, path, "0011")

    assert version(path) == "0011"
    after = dump(path)
    for table in TABLES:  # every row kept; the added column (last) is NULL
        if table == "evidence":
            assert after[table] == before[table]
        else:
            assert [row[:-1] for row in after[table]] == before[table], table
            assert all(row[-1] is None for row in after[table]), table
    assert foreign_key_violations(path) == []
    assert all(kind in table_sql(path, "evidence") for kind in NEW_KINDS)
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            first = build.run(state="COMPLETED")
            second = build.run(source_id=first.source_id, state="COMPLETED")
            second.supersedes_run_id = first.id
            for kind in NEW_KINDS:
                build.evidence(kind=kind)
            observation = build.observation(
                first, state="SUPERSEDED", superseded_at=clock(), superseded_by_run_id=second.id
            )
            build.representation(observation, state="SUPERSEDED", superseded_at=clock(), ann_key=7)
            build.occurrence(observation, state="SUPERSEDED", superseded_at=clock())
            session.commit()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("violation", "constraint"),
    [
        ("self", "ck_processing_runs_supersedes_not_self"),
        ("second_completed_superseder", "UNIQUE constraint failed: processing_runs.supersedes"),
        ("dangling", "FOREIGN KEY"),
        ("observation_without_time", "ck_observations_superseded_has_time"),
        ("observation_without_run", "ck_observations_superseded_has_time"),
        ("representation_without_time", "ck_representations_superseded_has_time"),
        ("occurrence_without_time", "ck_occurrences_superseded_has_time"),
        ("unknown_kind", "ck_evidence_kind"),
    ],
)
def test_each_new_rule_refuses_a_violating_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    violation: str,
    constraint: str,
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0011")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            first = build.run(state="COMPLETED")
            other = build.run(source_id=first.source_id, state="FAILED")
            session.commit()

            def two_completed_superseders() -> None:
                for _ in range(2):
                    build.run(
                        source_id=first.source_id, state="COMPLETED", supersedes_run_id=first.id
                    )

            def supersede_itself() -> None:
                first.supersedes_run_id = first.id
                session.flush()

            violate: dict[str, Callable[[], object]] = {
                "self": supersede_itself,
                "second_completed_superseder": two_completed_superseders,
                "dangling": lambda: build.run(
                    source_id=first.source_id, supersedes_run_id=new_id()
                ),
                "observation_without_time": lambda: build.observation(
                    first, state="SUPERSEDED", superseded_by_run_id=other.id, superseded_at=None
                ),
                "observation_without_run": lambda: build.observation(
                    first, state="SUPERSEDED", superseded_at=clock(), superseded_by_run_id=None
                ),
                "representation_without_time": lambda: build.representation(
                    build.observation(first), state="SUPERSEDED", superseded_at=None
                ),
                "occurrence_without_time": lambda: build.occurrence(
                    build.observation(first), state="SUPERSEDED", superseded_at=None
                ),
                "unknown_kind": lambda: build.evidence(kind="REPROCESS_INVENTED"),
            }
            with pytest.raises(IntegrityError, match=constraint):
                violate[violation]()
            session.rollback()
    finally:
        engine.dispose()


def test_a_superseded_run_may_have_many_unfinished_successors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """The unique index is partial: only a second *completed* superseder is refused, so a failed
    reprocess run and its retry may both name the same predecessor."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0011")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            first = build.run(state="COMPLETED")
            for state in ("FAILED", "INTERRUPTED", "COMPLETED"):
                build.run(source_id=first.source_id, state=state, supersedes_run_id=first.id)
            session.commit()
            assert (
                session.scalar(
                    text("SELECT count(*) FROM processing_runs WHERE supersedes_run_id = :id"),
                    {"id": first.id.hex},
                )
                == 3
            )
    finally:
        engine.dispose()


def test_downgrade_restores_the_earlier_schema_on_an_empty_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0011")

    downgrade(monkeypatch, path, "0010")

    assert version(path) == "0010"
    assert "supersedes_run_id" not in table_sql(path, "processing_runs")
    for table in ("observations", "representations", "occurrences"):
        assert "superseded_at" not in table_sql(path, table)
    assert not any(kind in table_sql(path, "evidence") for kind in NEW_KINDS)


def test_downgrade_refuses_a_populated_library_unless_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0010(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0011")
    migrated = dump(path)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade(monkeypatch, path, "0010")
    assert version(path) == "0011"
    assert dump(path) == migrated

    downgrade(monkeypatch, path, "0010", allow_destructive=True)
    assert version(path) == "0010"
    assert dump(path) == before


def test_a_forced_downgrade_is_stopped_by_a_reprocessing_evidence_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0010(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0011")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            ModelFactory(session, clock, new_id).evidence(kind="REPROCESS_REVIEW_REQUIRED")
            session.commit()
    finally:
        engine.dispose()
    before = dump(path)

    with pytest.raises(IntegrityError, match="ck_evidence_kind"):
        downgrade(monkeypatch, path, "0010", allow_destructive=True)

    assert version(path) == "0011"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0010:0011", sql=True)

    sql = config.output_buffer.getvalue()
    for table in TABLES:
        assert f"_alembic_tmp_{table}" in sql
    assert "uq_processing_runs_one_completed_superseder" in sql
    assert all(kind in sql for kind in NEW_KINDS)
