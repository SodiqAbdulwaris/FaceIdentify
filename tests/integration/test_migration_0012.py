"""Revision 0012 adds camera sources: the `CAMERA` kind without an original, the device row and the
camera session job type (delegated decision 2026-11-11, M7 step 1; persistence 4.2, 4.3 and 15)."""

import io
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.cameras.models import CameraSourceMetadata
from backend.app.sources.models import Source
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


def populated_0011(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0011")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        run = build.run(state="COMPLETED")
        build.source(kind="VIDEO", display_name="clip.mp4")
        build.job(processing_run_id=run.id, state="COMPLETED")
        build.job(type="CLEAN_STORAGE", priority="MAINTENANCE")

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    rows = dump(path)
    assert len(rows["sources"]) == 2
    assert len(rows["jobs"]) == 2
    return path


def test_a_populated_database_keeps_its_rows_and_takes_a_camera(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0011(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    migrate(monkeypatch, path, "0012")

    assert version(path) == "0012"
    after = dump(path)
    assert after["sources"] == before["sources"]
    assert after["jobs"] == before["jobs"]
    assert after["camera_source_metadata"] == []
    assert foreign_key_violations(path) == []
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            camera = build.camera(device_path="@device_pnp_one")
            build.job(type="PROCESS_CAMERA_SESSION", processing_run_id=None)
            session.commit()
            source = session.get(Source, camera.source_id)
            assert source is not None
            assert (source.kind, source.original_artifact_id) == ("CAMERA", None)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("violation", "constraint"),
    [
        ("image_without_original", "ck_sources_original_unless_camera"),
        ("camera_with_original", "ck_sources_original_unless_camera"),
        ("blank_device_name", "ck_camera_source_metadata_device_name_not_empty"),
        ("blank_device_path", "ck_camera_source_metadata_device_path_not_empty"),
        ("no_source", "FOREIGN KEY"),
        ("second_device_row", "UNIQUE constraint failed: camera_source_metadata.source_id"),
        ("unknown_job_type", "ck_jobs_type"),
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
    migrate(monkeypatch, path, "0012")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            camera = build.camera()
            session.commit()

            def second_device_row() -> None:  # (in SQL: the session knows the first one)
                session.execute(
                    text(
                        "INSERT INTO camera_source_metadata (source_id, device_name)"
                        " VALUES (:id, 'Other')"
                    ),
                    {"id": camera.source_id.hex},
                )

            violate: dict[str, Callable[[], object]] = {
                "image_without_original": lambda: build.source(original_artifact_id=None),
                "camera_with_original": lambda: build.source(kind="CAMERA"),
                "blank_device_name": lambda: build.camera(device_name="  "),
                "blank_device_path": lambda: build.camera(device_path=" "),
                "no_source": lambda: build.camera(source_id=new_id()),
                "second_device_row": second_device_row,
                "unknown_job_type": lambda: build.job(type="PROCESS_CAMERA_STREAM"),
            }
            with pytest.raises(IntegrityError, match=constraint):
                violate[violation]()
            session.rollback()
    finally:
        engine.dispose()


def test_a_camera_device_row_goes_with_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0012")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            camera = ModelFactory(session, clock, new_id).camera()
            session.commit()
            session.delete(session.get(Source, camera.source_id))
            session.commit()
            assert session.scalars(select(CameraSourceMetadata)).all() == []
    finally:
        engine.dispose()


def test_downgrade_restores_the_earlier_schema_on_an_empty_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0012")

    downgrade(monkeypatch, path, "0011")

    assert version(path) == "0011"
    assert "CAMERA" not in table_sql(path, "sources")
    assert "original_artifact_id CHAR(32) NOT NULL" in table_sql(path, "sources")
    assert "PROCESS_CAMERA_SESSION" not in table_sql(path, "jobs")
    with closing(sqlite3.connect(path)) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE name = 'camera_source_metadata'"
            ).fetchone()[0]
            == 0
        )


def test_downgrade_refuses_a_populated_library_unless_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0011(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0012")
    migrated = dump(path)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade(monkeypatch, path, "0011")
    assert version(path) == "0012"
    assert dump(path) == migrated

    downgrade(monkeypatch, path, "0011", allow_destructive=True)
    assert version(path) == "0011"
    assert dump(path) == before


@pytest.mark.parametrize("row", ["camera", "camera_job"])
def test_a_forced_downgrade_is_stopped_by_a_camera_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    row: str,
) -> None:
    path = populated_0011(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0012")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            if row == "camera":
                # (without its device row, which the downgrade drops before it reaches `sources`)
                build.source(kind="CAMERA", original_artifact_id=None)
            else:
                build.job(type="PROCESS_CAMERA_SESSION")
            session.commit()
    finally:
        engine.dispose()
    before = dump(path)

    with pytest.raises(IntegrityError, match="ck_jobs_type|ck_sources_kind|NOT NULL"):
        downgrade(monkeypatch, path, "0011", allow_destructive=True)

    assert version(path) == "0012"
    assert dump(path) == before


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0011:0012", sql=True)

    sql = config.output_buffer.getvalue()
    for table in ("sources", "jobs"):
        assert f"_alembic_tmp_{table}" in sql
    assert "CREATE TABLE camera_source_metadata" in sql
    assert "ck_sources_original_unless_camera" in sql
    assert "PROCESS_CAMERA_SESSION" in sql
