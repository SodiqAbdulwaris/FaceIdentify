"""Revision 0003 on populated databases (M2: TST-032; PER-09, PER-10; GitHub issues 48 and 51).

`ann_key` becomes unique within a representation space instead of across the table, which recreates
`representations`; and two triggers make a committed processing configuration snapshot immutable. A
database that really holds rows at revision 0002 is migrated, and each failure shape is shown to
leave it exactly as it was.
"""

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace
from backend.app.processing.models import ProcessingConfigurationSnapshot
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import (
    DANGLING_UPDATE,
    dangle,
    downgrade,
    dump,
    fail,
    foreign_key_violations,
    migrate,
    patch_revision,
    record_enforcement,
    table_sql,
    trigger_names,
    version,
)
from tests.fixtures.persistence import alembic_config

TRIGGERS = {
    "trg_processing_configuration_snapshots_no_update",
    "trg_processing_configuration_snapshots_no_delete_while_used",
}


def populated_0002(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    """A database at revision 0002: two spaces with keys 1 and 2 in the first and 3 in the second
    (the table-wide constraint forbids a key twice), a snapshot that a run uses and one that none
    does."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0002")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            first = build.representation_space(dimension=4)
            second = build.representation_space(dimension=4)
            identity = build.identity()
            for space, key in ((first, 1), (first, 2), (second, 3)):
                rep = build.representation(
                    representation_space_id=space.id, state="ACTIVE", identity_id=identity.id,
                    ann_key=key, vector=float32_vector([float(key), 0.0, 0.0, 0.0]),
                )  # fmt: skip
                build.index_operation(rep, operation="ADD")
            build.representation(representation_space_id=first.id)  # a PENDING one: no key
            build.run()  # a snapshot and a run that uses it
            build.snapshot()  # and one that no run uses
            session.commit()
    finally:
        engine.dispose()
    return path


def spaces(path: Path) -> list[Any]:
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            return list(
                session.scalars(select(RepresentationSpace.id).order_by(RepresentationSpace.id))
            )
    finally:
        engine.dispose()


def execute(path: Path, statement: str, *parameters: Any) -> None:
    """A plain sqlite3 statement, committed (so triggers and constraints answer, not the ORM)."""
    with sqlite3.connect(path) as connection:
        connection.execute(statement, parameters)


def snapshot_ids(path: Path) -> tuple[uuid.UUID, uuid.UUID]:
    """(a snapshot some run uses, a snapshot no run uses). The factories give every run its own
    snapshot, so there are several of the first kind."""
    with sqlite3.connect(path) as connection:
        used = connection.execute(
            "SELECT configuration_snapshot_id FROM processing_runs ORDER BY rowid LIMIT 1"
        ).fetchone()[0]
        free = connection.execute(
            "SELECT id FROM processing_configuration_snapshots WHERE id NOT IN"
            " (SELECT configuration_snapshot_id FROM processing_runs)"
        ).fetchone()[0]
    return uuid.UUID(used), uuid.UUID(free)


# --- upgrading a populated database -------------------------------------------------------------


def test_a_populated_database_upgrades_with_every_row_and_key_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    assert {row[7] for row in before["representations"] if row[7] is not None} == {1, 2, 3}

    migrate(monkeypatch, path, "0003")

    assert version(path) == "0003"
    assert dump(path) == before  # nothing lost, changed or reordered, in any table; keys included
    assert foreign_key_violations(path) == []
    sql = table_sql(path, "representations")
    assert "UNIQUE (representation_space_id, ann_key)" in sql
    assert "UNIQUE (ann_key)" not in sql  # the table-wide constraint is gone
    assert trigger_names(path) == TRIGGERS


def test_the_same_key_may_be_used_in_two_spaces_but_not_twice_in_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    first, second = spaces(path)[:2]
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            # key 1 is held in one space; the other space may hold key 1 as well
            build.representation(
                representation_space_id=second, state="ACTIVE", identity_id=build.identity().id,
                ann_key=1, vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
            )  # fmt: skip
            session.commit()

            # but a key twice in one space is refused
            with pytest.raises(IntegrityError, match="representation_space_id, .*ann_key"):
                build.representation(
                    representation_space_id=second, state="ACTIVE",
                    identity_id=build.identity().id, ann_key=1,
                    vector=float32_vector([0.0, 1.0, 0.0, 0.0]),
                )  # fmt: skip
            session.rollback()

            # and representations without a key (pending, erased) may repeat the absence
            for _ in range(2):
                build.representation(representation_space_id=second)
            session.commit()
    finally:
        engine.dispose()


# --- snapshots are immutable --------------------------------------------------------------------


def test_a_committed_snapshot_cannot_be_updated_by_sql_or_by_the_orm_even_to_the_same_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    used, free = snapshot_ids(path)
    before = dump(path)

    for snapshot_id in (used, free):  # a snapshot a run uses and one that none does
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            execute(
                path,
                "UPDATE processing_configuration_snapshots SET canonical_json = '{}' WHERE id = ?",
                snapshot_id.hex,
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            execute(  # a no-op update is an update too
                path,
                "UPDATE processing_configuration_snapshots SET schema_version = schema_version"
                " WHERE id = ?",
                snapshot_id.hex,
            )

    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            row = session.get(ProcessingConfigurationSnapshot, used)
            assert row is not None
            row.canonical_json = {"changed": True}
            with pytest.raises(IntegrityError, match="immutable"):
                session.commit()
    finally:
        engine.dispose()

    assert dump(path) == before


def test_a_snapshot_a_run_uses_cannot_be_deleted_and_one_no_run_uses_can(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    used, free = snapshot_ids(path)

    with pytest.raises(sqlite3.IntegrityError, match="a run uses"):
        execute(path, "DELETE FROM processing_configuration_snapshots WHERE id = ?", used.hex)

    execute(path, "DELETE FROM processing_configuration_snapshots WHERE id = ?", free.hex)
    with sqlite3.connect(path) as connection:
        remaining = {
            row[0]
            for row in connection.execute("SELECT id FROM processing_configuration_snapshots")
        }
    assert free.hex not in remaining
    assert used.hex in remaining


def test_known_limit_insert_or_replace_rewrites_a_snapshot_no_run_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """SQLite fires no delete trigger for the deletion REPLACE performs, so the triggers do not
    stop it on a snapshot no run references; one a run uses is still protected by the foreign
    key (GitHub issue 55). Pinned so that closing the gap shows up as a deliberate change."""
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    used, free = snapshot_ids(path)
    replace = (
        "INSERT OR REPLACE INTO processing_configuration_snapshots"
        " (id, schema_version, canonical_json, fingerprint_sha256, created_at)"
        " VALUES (?, 99, '{}', zeroblob(32), '2026-01-01 00:00:00.000000')"
    )

    execute(path, replace, free.hex)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT schema_version FROM processing_configuration_snapshots WHERE id = ?",
            (free.hex,),
        ).fetchone() == (99,)  # rewritten: the known limit

    with sqlite3.connect(path) as connection:
        # the application's connections enforce foreign keys; a plain one does not
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(replace, (used.hex,))


def test_a_new_snapshot_can_still_be_created_and_a_second_run_cannot_reuse_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    used, _ = snapshot_ids(path)
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            build.snapshot()  # creation is an ordinary INSERT
            session.commit()
            with pytest.raises(IntegrityError, match="configuration_snapshot_id"):
                build.run(
                    configuration_snapshot_id=used
                )  # one snapshot per run, from revision 0001
            session.rollback()
    finally:
        engine.dispose()


# --- a failing upgrade changes nothing ----------------------------------------------------------


def assert_untouched_at_0002(path: Path, before: dict[str, list[tuple[Any, ...]]]) -> None:
    assert version(path) == "0002"
    assert dump(path) == before
    sql = table_sql(path, "representations")
    assert "UNIQUE (ann_key)" in sql
    assert "UNIQUE (representation_space_id, ann_key)" not in sql  # the new one is gone
    assert trigger_names(path) == set()
    assert foreign_key_violations(path) == []


def test_a_python_error_after_the_recreation_and_the_triggers_rolls_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    patch_revision(monkeypatch, "0003", after_upgrade=fail("0003 failed at the very end"))

    with pytest.raises(RuntimeError, match="at the very end"):
        migrate(monkeypatch, path, "0003")

    assert_untouched_at_0002(path, before)  # the recreated table and both triggers are gone


def test_a_dangling_reference_left_by_the_revision_is_caught_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    patch_revision(monkeypatch, "0003", after_upgrade=dangle(DANGLING_UPDATE))

    with pytest.raises(RuntimeError, match="index_operations with rowid 1 points at a missing row"):
        migrate(monkeypatch, path, "0003")

    assert_untouched_at_0002(path, before)


def test_foreign_key_enforcement_is_off_while_the_revision_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    seen: list[int] = []
    patch_revision(monkeypatch, "0003", after_upgrade=record_enforcement(seen))

    migrate(monkeypatch, path, "0003")

    assert seen == [0]  # recreating a referenced table needs it, with child rows present


def test_in_one_upgrade_a_failing_third_revision_leaves_the_first_two_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    patch_revision(monkeypatch, "0003", after_upgrade=fail("0003 failed"))

    with pytest.raises(RuntimeError, match="0003 failed"):
        migrate(monkeypatch, path, "0003")

    assert version(path) == "0002"  # each revision commits on its own
    assert trigger_names(path) == set()


# --- downgrading --------------------------------------------------------------------------------


def test_downgrade_restores_the_table_wide_constraint_and_drops_the_triggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0003")

    downgrade(monkeypatch, path, "0002")

    assert_untouched_at_0002(path, before)
    used, _ = snapshot_ids(path)
    execute(  # the trigger is gone, so a snapshot can be changed again
        path,
        "UPDATE processing_configuration_snapshots SET schema_version = schema_version"
        " WHERE id = ?",
        used.hex,
    )


def test_downgrade_is_refused_atomically_while_two_spaces_hold_the_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Q19 (what downgrade does to a populated library) stays open; this pins what happens: the
    older schema cannot hold the same key in two spaces, so the database refuses and nothing
    changes."""
    path = populated_0002(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0003")
    first, second = spaces(path)[:2]
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            build.representation(
                representation_space_id=second, state="ACTIVE", identity_id=build.identity().id,
                ann_key=1, vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
            )  # fmt: skip
            session.commit()
    finally:
        engine.dispose()
    before = dump(path)

    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        downgrade(monkeypatch, path, "0002")

    assert version(path) == "0003"
    assert dump(path) == before
    assert trigger_names(path) == TRIGGERS
    assert "UNIQUE (representation_space_id, ann_key)" in table_sql(path, "representations")


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0002:0003", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_representations" in sql  # the table is recreated
    assert "uq_representations_representation_space_id_ann_key" in sql
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in sql
