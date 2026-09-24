"""Alembic migration tests (M2: TST-032; PERSISTENCE_IMPLEMENTATION.md §27).

Revision `0001_initial_schema` is the only revision so far, so there is no earlier populated
schema to migrate *from*: these tests pin what a fresh database gets (it must be exactly what the
models describe), that an empty database round-trips through downgrade, and that a failed
migration never damages an existing database ("Existing databases are never automatically
deleted because migration failed", Roadmap-Plan §37). Every other persistence test also runs on
the migrated schema, via the `sqlite_engine` fixture.
"""

import io
import logging.config
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from backend.app.models import Base
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.fixtures.persistence import alembic_config

DATABASE_PATH_ENV = "FACEIDENTIFY_DATABASE_PATH"
TABLE_LEVEL_KEYWORDS = ("CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN")


def migrate(monkeypatch: pytest.MonkeyPatch, path: Path, revision: str = "head") -> None:
    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    command.upgrade(alembic_config(), revision)


def downgrade(monkeypatch: pytest.MonkeyPatch, path: Path, revision: str = "base") -> None:
    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    command.downgrade(alembic_config(), revision)


def create_all_database(path: Path) -> Path:
    engine = create_sqlite_engine(path)
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def schema_objects(path: Path) -> dict[tuple[str, str], str]:
    """Every user table and index in the database, keyed by (type, name), with its DDL."""
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master"
            " WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        ).fetchall()
    return {(kind, name): sql for kind, name, sql in rows}


def table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {name for (name,) in rows}


def split_members(create_table_sql: str) -> list[str]:
    """The top-level comma-separated members of a CREATE TABLE body: columns then constraints."""
    body = create_table_sql[create_table_sql.index("(") + 1 : create_table_sql.rindex(")")]
    members: list[str] = []
    depth = 0
    in_string = False
    start = 0
    for position, character in enumerate(body):
        if character == "'":
            in_string = not in_string
        elif not in_string:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character == "," and depth == 0:
                members.append(body[start:position].strip())
                start = position + 1
    members.append(body[start:].strip())
    return members


def columns_and_constraints(create_table_sql: str) -> tuple[list[str], list[str]]:
    members = split_members(create_table_sql)
    columns = [m for m in members if not m.startswith(TABLE_LEVEL_KEYWORDS)]
    constraints = sorted(m for m in members if m.startswith(TABLE_LEVEL_KEYWORDS))
    return columns, constraints


# --- the migrated schema is exactly the models' schema ---------------------------------------


def test_upgrade_creates_exactly_the_objects_create_all_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate(monkeypatch, tmp_path / "migrated.db")
    created = create_all_database(tmp_path / "created.db")

    assert set(schema_objects(tmp_path / "migrated.db")) == set(schema_objects(created))
    assert table_names(tmp_path / "migrated.db") == {*Base.metadata.tables, "alembic_version"}


def test_migrated_indexes_match_create_all_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each index is one statement, so its DDL compares exactly — including the partial
    indexes' WHERE clauses (§27 rule 7: "verify required partial indexes after upgrade")."""
    migrate(monkeypatch, tmp_path / "migrated.db")
    migrated = schema_objects(tmp_path / "migrated.db")
    created = schema_objects(create_all_database(tmp_path / "created.db"))

    indexes = {key for key in created if key[0] == "index"}
    assert indexes  # the comparison below would pass vacuously on an empty set
    assert {key: migrated[key] for key in indexes} == {key: created[key] for key in indexes}
    assert any("WHERE" in created[key] for key in indexes)  # partial indexes are in the set


def test_migrated_tables_match_create_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same columns in the same order, and the same named constraints (CHECK, FOREIGN KEY with
    its ON DELETE rule, UNIQUE, PRIMARY KEY). The constraints are compared as sorted lists (so
    a duplicate would still show) because Alembic and create_all list them in different
    orders inside the same CREATE TABLE."""
    migrate(monkeypatch, tmp_path / "migrated.db")
    migrated = schema_objects(tmp_path / "migrated.db")
    created = schema_objects(create_all_database(tmp_path / "created.db"))

    tables = {key for key in created if key[0] == "table"}
    assert len(tables) == len(Base.metadata.tables)
    for key in sorted(tables):
        assert columns_and_constraints(migrated[key]) == columns_and_constraints(created[key]), key


def test_models_and_migration_have_no_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate(monkeypatch, tmp_path / "migrated.db")
    command.check(alembic_config())  # raises AutogenerateDiffsDetected on any model/schema drift


# --- revision history ------------------------------------------------------------------------


def test_the_revision_history_is_one_linear_chain_starting_at_0001() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == ["0001"]
    assert script.get_revision("0001").down_revision is None


def test_upgrade_stamps_the_head_revision_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path)
    migrate(monkeypatch, path)  # already at head: must be a no-op, not a duplicate-table error

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("0001",)
        ]
    assert len(schema_objects(path)) == len(schema_objects(create_all_database(tmp_path / "c.db")))


def test_downgrade_removes_every_table_and_the_revision_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path)
    downgrade(monkeypatch, path)

    assert schema_objects(path) == {}
    assert table_names(path) == {"alembic_version"}

    migrate(monkeypatch, path)
    assert set(schema_objects(path)) == set(schema_objects(create_all_database(tmp_path / "c.db")))


# --- failure safety --------------------------------------------------------------------------


def test_a_failed_migration_leaves_an_existing_database_exactly_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roadmap-Plan §37: existing databases are never destroyed because a migration failed. A
    conflicting table that the revision only reaches late makes it fail midway; SQLite could
    otherwise be left with a half-applied schema and no version stamp."""
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE occurrence_observations (x INTEGER)")
        connection.execute("INSERT INTO occurrence_observations VALUES (7)")

    with pytest.raises(OperationalError, match="already exists"):
        migrate(monkeypatch, path)

    assert path.exists()
    assert table_names(path) == {"occurrence_observations"}  # nothing partial, no version table
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT x FROM occurrence_observations").fetchall() == [(7,)]


# --- environment ------------------------------------------------------------------------------


def test_running_migrations_requires_the_database_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_PATH_ENV, raising=False)
    with pytest.raises(RuntimeError, match=DATABASE_PATH_ENV):
        command.upgrade(alembic_config(), "head")


def test_offline_mode_emits_the_schema_as_reviewable_sql() -> None:
    config = alembic_config()
    config.output_buffer = io.StringIO()
    command.upgrade(config, "head", sql=True)

    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE artifacts" in sql
    assert "CREATE TABLE identities" in sql
    assert "INSERT INTO alembic_version" in sql


def test_logging_is_only_reconfigured_when_asked_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host process (tests, the application) must keep its own logging; the CLI opts in."""
    calls: list[str] = []
    monkeypatch.setattr(logging.config, "fileConfig", lambda name, **_: calls.append(str(name)))

    quiet = alembic_config()
    quiet.output_buffer = io.StringIO()
    command.upgrade(quiet, "head", sql=True)
    assert calls == []

    cli_like = alembic_config()
    cli_like.attributes["configure_logger"] = True
    cli_like.output_buffer = io.StringIO()
    command.upgrade(cli_like, "head", sql=True)
    assert len(calls) == 1
    assert calls[0].endswith("alembic.ini")
