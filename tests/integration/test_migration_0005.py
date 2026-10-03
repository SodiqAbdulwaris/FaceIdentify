"""Revision 0005 on populated databases (M3: TST-032; GitHub issues 55 and 88).

Three changes in one revision: an accepted `ABSTAIN` representation may be `ACTIVE` without an
identity (the identity half of the `active_eligible` CHECK goes, the key half stays); `observations`
and `representations` gain a nullable `runtime_variant_id` foreign key, the variant that actually
executed; and a third snapshot trigger blocks `INSERT OR REPLACE`. A database that really holds rows
at revision 0004 is migrated, and each failure shape is shown to leave it exactly as it was.
"""

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.models import RuntimeVariant
from backend.app.runtime.registration import register_package
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.catalog_packages import installed, manifest_dict
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
    populate_legacy,
    record_enforcement,
    table_sql,
    trigger_names,
    version,
)
from tests.fixtures.persistence import alembic_config

OLD_TRIGGERS = {
    "trg_processing_configuration_snapshots_no_update",
    "trg_processing_configuration_snapshots_no_delete_while_used",
}
NEW_TRIGGER = "trg_processing_configuration_snapshots_no_replace"
OLD_ELIGIBLE = "state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)"
NEW_ELIGIBLE = "state != 'ACTIVE' OR ann_key IS NOT NULL"
TABLES_WITH_THE_COLUMN = ("observations", "representations")


def populated_0004(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    """A database at revision 0004: two active representations with keys, a pending one, a run and
    the snapshot it uses, a snapshot no run uses, and the index operations."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")

    def fill(session: Session) -> None:
        build = ModelFactory(session, clock, new_id)
        space = build.representation_space(dimension=4)
        identity = build.identity()
        for key in (1, 2):
            rep = build.representation(
                representation_space_id=space.id, state="ACTIVE", identity_id=identity.id,
                ann_key=key, vector=float32_vector([float(key), 0.0, 0.0, 0.0]),
            )  # fmt: skip
            build.index_operation(rep, operation="ADD")
        build.representation(representation_space_id=space.id)  # a PENDING one: no key
        build.run()
        build.snapshot()  # one that no run uses

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    return path


def execute(path: Path, statement: str, *parameters: Any) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(statement, parameters)


def snapshot_ids(path: Path) -> tuple[str, str]:
    """(a snapshot some run uses, a snapshot no run uses), as the hex the database stores."""
    with sqlite3.connect(path) as connection:
        used = connection.execute(
            "SELECT configuration_snapshot_id FROM processing_runs ORDER BY rowid LIMIT 1"
        ).fetchone()[0]
        free = connection.execute(
            "SELECT id FROM processing_configuration_snapshots WHERE id NOT IN"
            " (SELECT configuration_snapshot_id FROM processing_runs)"
        ).fetchone()[0]
    return str(used), str(free)


def columns_of(path: Path, table: str) -> list[str]:
    with sqlite3.connect(path) as connection:
        return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def a_variant(
    session: Session, tmp_path: Path, new_id: SeededUUIDs, clock: FrozenClock
) -> uuid.UUID:
    """A real runtime variant, registered from a fixture package."""
    register_package(
        session, installed(tmp_path / "package", manifest_dict("pkg")), new_id=new_id, clock=clock
    )
    return session.scalars(select(RuntimeVariant.id)).first() or uuid.uuid4()


# --- upgrading a populated database -------------------------------------------------------------


def test_a_populated_database_upgrades_with_every_row_kept_and_the_new_columns_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    assert before["representations"]
    assert before["observations"]

    migrate(monkeypatch, path, "0005")

    assert version(path) == "0005"
    after = dump(path)
    for table, rows in before.items():
        if table in TABLES_WITH_THE_COLUMN:
            assert [row[:-1] for row in after[table]] == rows  # every old value, in its place
            assert [row[-1] for row in after[table]] == [None] * len(rows)  # the new one: NULL
        else:
            assert after[table] == rows
    assert foreign_key_violations(path) == []
    for table in TABLES_WITH_THE_COLUMN:
        assert columns_of(path, table)[-1] == "runtime_variant_id"
    assert OLD_ELIGIBLE not in table_sql(path, "representations")
    assert NEW_ELIGIBLE in table_sql(path, "representations")
    assert trigger_names(path) == OLD_TRIGGERS | {NEW_TRIGGER}


# --- the CHECK: an accepted abstention has no identity, but never lacks its key -------------------


def test_an_active_representation_without_an_identity_is_accepted_only_with_its_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            space_id = session.scalars(select(RepresentationSpace.id)).first()
            assert space_id is not None
            abstained = build.representation(
                representation_space_id=space_id, state="ACTIVE", ann_key=3,
                vector=float32_vector([3.0, 0.0, 0.0, 0.0]),
            )  # fmt: skip
            assert abstained.identity_id is None
            session.commit()
            for fields in (
                {"state": "ACTIVE", "ann_key": None},  # no key, no identity
                {"state": "ACTIVE", "ann_key": None, "identity_id": build.identity().id},
            ):
                with pytest.raises(IntegrityError, match="ck_representations_active_eligible"):
                    build.representation(representation_space_id=space_id, **fields)
                session.rollback()
    finally:
        engine.dispose()


# --- the provenance columns ---------------------------------------------------------------------


def test_the_variant_columns_take_a_real_variant_refuse_an_unknown_one_and_restrict_its_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            variant = a_variant(session, tmp_path, new_id, clock)
            observation = build.observation(runtime_variant_id=variant)
            representation = build.representation(observation, runtime_variant_id=variant)
            session.commit()
            assert observation.runtime_variant_id == variant
            assert representation.runtime_variant_id == variant

            with pytest.raises(IntegrityError, match="FOREIGN KEY"):
                build.observation(runtime_variant_id=uuid.uuid4())
            session.rollback()
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):
                build.representation(runtime_variant_id=uuid.uuid4())
            session.rollback()
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):  # RESTRICT: provenance stays
                session.execute(delete(RuntimeVariant))
            session.rollback()
    finally:
        engine.dispose()


# --- snapshots: INSERT OR REPLACE is blocked ----------------------------------------------------


def test_a_snapshot_can_no_longer_be_replaced_by_insert_or_replace_or_a_duplicate_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    used, free = snapshot_ids(path)
    before = dump(path)
    insert = (
        "INSERT OR REPLACE INTO processing_configuration_snapshots"
        " (id, schema_version, canonical_json, fingerprint_sha256, created_at)"
        " VALUES (?, 99, '{}', zeroblob(32), '2026-01-01 00:00:00.000000')"
    )
    for snapshot_id in (used, free):  # one a run uses, and one that none does
        with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
            execute(path, insert, snapshot_id)
        with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
            execute(path, insert.replace("OR REPLACE ", ""), snapshot_id)  # a plain duplicate
    assert dump(path) == before

    execute(path, insert.replace("OR REPLACE ", ""), uuid.uuid4().hex)  # a new snapshot is fine
    with sqlite3.connect(path) as connection:
        count = connection.execute("SELECT count(*) FROM processing_configuration_snapshots")
        assert count.fetchone()[0] == len(before["processing_configuration_snapshots"]) + 1


def test_the_other_two_snapshot_triggers_still_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    used, free = snapshot_ids(path)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        execute(
            path,
            "UPDATE processing_configuration_snapshots SET schema_version = 2 WHERE id = ?",
            free,
        )
    with pytest.raises(sqlite3.IntegrityError, match="a run uses"):
        execute(path, "DELETE FROM processing_configuration_snapshots WHERE id = ?", used)
    execute(path, "DELETE FROM processing_configuration_snapshots WHERE id = ?", free)


# --- a failing upgrade changes nothing ----------------------------------------------------------


def assert_untouched_at_0004(path: Path, before: dict[str, list[tuple[Any, ...]]]) -> None:
    assert version(path) == "0004"
    assert dump(path) == before
    assert OLD_ELIGIBLE in table_sql(path, "representations")
    for table in TABLES_WITH_THE_COLUMN:
        assert "runtime_variant_id" not in columns_of(path, table)
    assert trigger_names(path) == OLD_TRIGGERS
    assert foreign_key_violations(path) == []


def test_a_python_error_after_the_recreations_and_the_trigger_rolls_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    patch_revision(monkeypatch, "0005", after_upgrade=fail("0005 failed at the very end"))

    with pytest.raises(RuntimeError, match="at the very end"):
        migrate(monkeypatch, path, "0005")

    assert_untouched_at_0004(path, before)


def test_a_dangling_reference_left_by_the_revision_is_caught_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    patch_revision(monkeypatch, "0005", after_upgrade=dangle(DANGLING_UPDATE))

    with pytest.raises(RuntimeError, match="index_operations with rowid 1 points at a missing row"):
        migrate(monkeypatch, path, "0005")

    assert_untouched_at_0004(path, before)


def test_foreign_key_enforcement_is_off_while_the_revision_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    seen: list[int] = []
    patch_revision(monkeypatch, "0005", after_upgrade=record_enforcement(seen))

    migrate(monkeypatch, path, "0005")

    assert seen == [0]  # recreating referenced tables needs it, with child rows present


# --- downgrading --------------------------------------------------------------------------------


def test_downgrade_restores_the_stricter_check_and_drops_the_columns_and_the_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0005")

    downgrade(monkeypatch, path, "0004", allow_destructive=True)

    assert_untouched_at_0004(path, before)


def test_downgrade_is_refused_without_the_override_for_a_populated_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    before = dump(path)

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        downgrade(monkeypatch, path, "0004", allow_destructive=False)

    assert version(path) == "0005"
    assert dump(path) == before


def test_downgrade_is_refused_atomically_while_an_identity_less_active_row_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """The older schema cannot hold an accepted abstention, so with the development override the
    database refuses and nothing changes."""
    path = populated_0004(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0005")
    execute(
        path,
        "UPDATE representations SET state = 'ACTIVE', ann_key = 99, identity_id = NULL"
        " WHERE state = 'PENDING'",
    )
    before = dump(path)

    with pytest.raises(IntegrityError, match="ck_representations_active_eligible"):
        downgrade(monkeypatch, path, "0004", allow_destructive=True)

    assert version(path) == "0005"
    assert dump(path) == before
    assert trigger_names(path) == OLD_TRIGGERS | {NEW_TRIGGER}
    assert NEW_ELIGIBLE in table_sql(path, "representations")


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0004:0005", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_representations" in sql
    assert "_alembic_tmp_observations" in sql
    assert "fk_representations_runtime_variant_id_runtime_variants" in sql
    assert "fk_observations_runtime_variant_id_runtime_variants" in sql
    assert f"CREATE TRIGGER {NEW_TRIGGER}" in sql
