"""Revision 0002 (the `ERASING` representation state) on populated databases (M2: TST-032;
PERSISTENCE_IMPLEMENTATION.md §27 rule 7: "Test migration from the previous released revision...
Verify foreign keys... after upgrade"; CONTEXT open question 18).

`representations` is recreated, because SQLite cannot alter a CHECK in place, and other tables
reference it. These tests use a database that really holds rows at revision 0001: recreating a
referenced table with foreign key enforcement on fails the moment a child row exists, which an empty
database never shows. They also pin how a failing upgrade behaves: a failure after the recreation, a
foreign key left dangling, and a database that was already inconsistent each leave the database
exactly as it was.
"""

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.memory.models import Representation
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
    populate_legacy,
    record_enforcement,
    table_sql,
    version,
)
from tests.fixtures.persistence import alembic_config


def populated_0001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> Path:
    """A database at revision 0001 holding rows that reference `representations`."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0001")

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
        build.representation(representation_space_id=space.id)  # a PENDING one as well

    populate_legacy(tmp_path / "scratch.db", monkeypatch, path, fill)
    return path


def refuse(session: Session, representation_id: Any, state: str) -> None:
    session.execute(
        update(Representation).where(Representation.id == representation_id).values(state=state)
    )
    session.commit()


def representations_sql(path: Path) -> str:
    return table_sql(path, "representations")


# --- upgrading a populated database -----------------------------------------------------------


def test_a_populated_database_upgrades_with_every_row_kept_and_no_dangling_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    assert before["representations"]  # the rows that matter exist
    assert before["index_operations"]

    migrate(monkeypatch, path, "0002")

    assert version(path) == "0002"
    assert dump(path) == before  # nothing lost, changed or reordered, in any table
    assert foreign_key_violations(path) == []
    assert "'ERASING'" in representations_sql(path)


def test_the_recreated_table_accepts_erasing_and_still_enforces_the_other_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0002")

    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            with sqlite3.connect(
                path
            ) as connection:  # (the ORM selects columns this revision lacks)
                (active_id,) = connection.execute(
                    "SELECT id FROM representations WHERE state = 'ACTIVE' LIMIT 1"
                ).fetchone()
            active = uuid.UUID(active_id)
            session.execute(
                update(Representation).where(Representation.id == active).values(state="ERASING")
            )
            session.commit()  # ERASING keeps its vector and key: the other CHECKs are unchanged
            with sqlite3.connect(path) as connection:
                assert connection.execute(
                    "SELECT state, vector IS NOT NULL, ann_key IS NOT NULL FROM representations"
                    " WHERE state = 'ERASING'"
                ).fetchall() == [("ERASING", 1, 1)]
            # a state that is not listed, and ERASED with a vector, are still refused
            for state in ("BOGUS", "ERASED"):
                with pytest.raises(Exception, match="CHECK constraint failed"):
                    refuse(session, active, state)
                session.rollback()
    finally:
        engine.dispose()


def test_foreign_key_enforcement_is_off_while_the_revision_runs_and_the_data_is_checked_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    seen: list[int] = []
    patch_revision(monkeypatch, "0002", after_upgrade=record_enforcement(seen))

    migrate(monkeypatch, path, "0002")

    assert seen == [0]  # a plain recreation would fail with enforcement on and child rows present
    engine = create_sqlite_engine(path)
    try:
        with engine.connect() as connection:  # the application's own connections enforce again
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose()


# --- a failing upgrade changes nothing --------------------------------------------------------


def assert_untouched_at_0001(path: Path, before: dict[str, list[tuple[Any, ...]]]) -> None:
    assert version(path) == "0001"
    assert dump(path) == before
    assert "'ERASING'" not in representations_sql(path)
    assert foreign_key_violations(path) == []


def test_a_python_error_after_the_recreation_rolls_the_whole_upgrade_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    patch_revision(
        monkeypatch, "0002", after_upgrade=fail("the revision failed after recreating the table")
    )
    with pytest.raises(RuntimeError, match="after recreating"):
        migrate(monkeypatch, path, "0002")

    assert_untouched_at_0001(path, before)  # 0001 stays applied, as it was


def test_a_reference_the_revision_leaves_dangling_is_caught_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """With enforcement off nothing stops a revision pointing a row at nothing; the check does."""
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)

    patch_revision(monkeypatch, "0002", after_upgrade=dangle(DANGLING_UPDATE))
    with pytest.raises(
        RuntimeError,
        match=r"index_operations with rowid 1 points at a missing row of representations",
    ):
        migrate(monkeypatch, path, "0002")

    assert_untouched_at_0001(path, before)


def test_a_database_that_was_already_inconsistent_is_not_upgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    with sqlite3.connect(path) as connection:  # enforcement is off on a plain sqlite3 connection
        connection.execute(
            "UPDATE index_operations SET representation_id = X'00000000000000000000000000000002'"
            " WHERE rowid = (SELECT min(rowid) FROM index_operations)"
        )
    before = dump(path)

    with pytest.raises(RuntimeError, match="may have been inconsistent before this migration"):
        migrate(monkeypatch, path, "0002")

    assert version(path) == "0001"
    assert dump(path) == before


def test_in_one_upgrade_a_failing_second_revision_leaves_the_first_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLite gives Alembic no transactional DDL, so each revision commits on its own: from an empty
    database, `upgrade head` applies 0001, then 0002 fails and rolls back only itself. (If the whole
    run were one transaction, 0001 would be gone too; every other test here starts at 0001 and
    cannot tell the two apart.)"""
    path = tmp_path / "library.db"
    patch_revision(monkeypatch, "0002", after_upgrade=fail("0002 failed"))

    with pytest.raises(RuntimeError, match="0002 failed"):
        migrate(monkeypatch, path, "0002")

    assert version(path) == "0001"
    assert "'ERASING'" not in representations_sql(path)
    assert "representations" in dump(path)  # 0001's tables are there


# --- downgrading ------------------------------------------------------------------------------


def test_downgrade_restores_the_old_check_and_keeps_the_rows_when_nothing_is_erasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    before = dump(path)
    migrate(monkeypatch, path, "0002")
    seen: list[int] = []
    patch_revision(monkeypatch, "0002", after_downgrade=record_enforcement(seen))

    downgrade(monkeypatch, path, "0001", allow_destructive=True)

    assert_untouched_at_0001(path, before)
    assert seen == [
        0
    ]  # a downgrade recreates the table too, so it runs with enforcement off as well


def test_a_downgrade_that_leaves_a_dangling_reference_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0002")
    before = dump(path)
    patch_revision(monkeypatch, "0002", after_downgrade=dangle(DANGLING_UPDATE))

    with pytest.raises(RuntimeError, match="foreign key violation"):
        downgrade(monkeypatch, path, "0001", allow_destructive=True)

    assert version(path) == "0002"
    assert dump(path) == before
    assert "'ERASING'" in representations_sql(path)


def test_downgrade_is_refused_atomically_while_a_representation_is_erasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Q19 (what downgrade should do to a populated library) stays open; this pins what happens: the
    older schema cannot hold `ERASING`, so the database refuses and nothing changes."""
    path = populated_0001(tmp_path, monkeypatch, clock, new_id)
    migrate(monkeypatch, path, "0002")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE representations SET state = 'ERASING' WHERE state = 'ACTIVE' AND ann_key = 1"
        )
    before = dump(path)

    with pytest.raises(Exception, match="CHECK constraint failed"):
        downgrade(monkeypatch, path, "0001", allow_destructive=True)

    assert version(path) == "0002"
    assert dump(path) == before
    assert "'ERASING'" in representations_sql(path)


def test_the_revision_can_be_printed_as_sql_without_a_database() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "0001:0002", sql=True)

    sql = config.output_buffer.getvalue()
    assert "_alembic_tmp_representations" in sql  # the table is recreated
    assert "'ERASING'" in sql
