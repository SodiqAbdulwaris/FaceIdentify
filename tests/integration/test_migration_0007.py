"""Revision 0007 gives jobs an integer priority rank (CONTEXT question 14; decided 2026-10-06).

`jobs.priority` is a string, so ordering by it is alphabetical; the scheduler claims by the integer
rank, which the database keeps in agreement with the string.
"""

import io
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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

PRIORITIES = ("INTERACTIVE", "HIGH", "NORMAL", "LOW", "MAINTENANCE")


def populated_0006(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0006")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        first = build.job(priority="NORMAL", state="QUEUED")
        for priority in PRIORITIES:
            build.job(priority=priority, state="QUEUED")
        build.job(priority="HIGH", state="INTERRUPTED", previous_job_id=first.id)

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    assert len(dump(path)["jobs"]) == 7
    return path


def index_names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'jobs'"
            )
        }


def ranks(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as connection:
        return dict(connection.execute("SELECT DISTINCT priority, priority_rank FROM jobs"))


def test_a_populated_database_keeps_its_jobs_and_ranks_them_from_the_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0006(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)["jobs"]

    migrate(monkeypatch, path, "0007")

    assert version(path) == "0007"
    assert ranks(path) == {name: rank for rank, name in enumerate(PRIORITIES)}
    assert foreign_key_violations(path) == []
    with closing(sqlite3.connect(path)) as connection:
        after = connection.execute(
            "SELECT id, type, processing_run_id, previous_job_id, state, priority,"
            " payload_schema_version, attempt_number, created_at FROM jobs ORDER BY rowid"
        ).fetchall()
        # every old column of every old row is unchanged (the new column sits beside them)
        names = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
    assert len(after) == len(before) == 7
    assert [row[0] for row in after] == [row[0] for row in before]
    assert "priority_rank" in names
    assert "DEFAULT" not in table_sql(path, "jobs").split("priority_rank")[1].split(",")[0]


def test_the_claim_index_follows_the_rank_and_the_old_one_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0006(tmp_path, monkeypatch, clock, new_id)
    assert "ix_jobs_state_priority_created_at" in index_names(path)

    migrate(monkeypatch, path, "0007")

    names = index_names(path)
    assert "ix_jobs_state_priority_rank_created_at" in names
    assert "ix_jobs_state_priority_created_at" not in names
    assert {"ix_jobs_lease_expires_at", "ix_jobs_processing_run_id"} <= names  # the others stay


def test_the_database_refuses_a_rank_that_disagrees_with_the_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0006(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0007")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            ok = build.job(priority="LOW")  # the model derives the rank
            session.commit()
            assert ok.priority_rank == 3
            with pytest.raises(IntegrityError, match="ck_jobs_priority_rank_matches_priority"):
                build.job(priority="LOW", priority_rank=0)
            session.rollback()
            with pytest.raises(IntegrityError, match="ck_jobs_priority"):
                build.job(priority="URGENT")
            session.rollback()
    finally:
        engine.dispose()
    with (
        closing(sqlite3.connect(path)) as connection,
        pytest.raises(sqlite3.IntegrityError, match="NOT NULL"),
    ):
        connection.execute(  # a row written without the rank is refused, never defaulted
            "INSERT INTO jobs (id, type, state, priority, payload_schema_version, progress_mode,"
            " created_at, updated_at) VALUES (x'00000000000000000000000000000001',"
            " 'PROCESS_SOURCE',"
            " 'QUEUED', 'HIGH', 1, 'DETERMINATE', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )


def test_downgrade_drops_the_rank_and_restores_the_old_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0006(tmp_path, monkeypatch, clock, new_id)
    original = dump(path)["jobs"]
    migrate(monkeypatch, path, "0007")

    downgrade(monkeypatch, path, "0006", allow_destructive=True)

    assert version(path) == "0006"
    assert dump(path)["jobs"] == original  # the old columns and rows, exactly
    names = index_names(path)
    assert "ix_jobs_state_priority_created_at" in names
    assert "ix_jobs_state_priority_rank_created_at" not in names
    assert "priority_rank" not in table_sql(path, "jobs")


def test_downgrading_a_populated_library_is_refused_without_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0006(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0007")
    before = dump(path)

    with pytest.raises(Exception, match="(?i)destructive|populated"):
        downgrade(monkeypatch, path, "0006")

    assert version(path) == "0007"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0006:0007", sql=True)

    sql = config.output_buffer.getvalue()
    assert "priority_rank" in sql
    assert "_alembic_tmp_jobs" in sql
    assert "ck_jobs_priority_rank_matches_priority" in sql
