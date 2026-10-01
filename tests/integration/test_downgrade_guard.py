"""A downgrade must not silently destroy a populated library (M2: TST-032; persistence section 27,
decision 2026-10-01, CONTEXT open question 19, issue 35).

Proved here: a library with no user or domain data downgrades freely, internal bookkeeping and
re-creatable metadata do not count as data, a library with data is refused at every revision
*before* anything changes, only the exact override lets it through, an unknown table counts as
data, and a revision that forgets the guard fails the build.
"""

import ast
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.app.settings.app_state import AppStateRepository
from backend.app.settings.repository import SettingsRepository
from backend.infrastructure.db.downgrade_guard import (
    ALLOW_DESTRUCTIVE_DOWNGRADE_ENV,
    DestructiveDowngradeRefused,
)
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import downgrade, dump, migrate, version

VERSIONS = Path(__file__).parents[2] / "backend" / "alembic" / "versions"
REVISIONS = ["0001", "0002", "0003", "0004"]


def insert_identity(path: Path) -> None:
    """A row of user/domain data that every schema from `0001` can hold."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO identities (id, state, revision, created_at, updated_at)"
            " VALUES (X'00000000000000000000000000000001', 'ACTIVE', 1,"
            " '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')"
        )


# --- a library without data -----------------------------------------------------------------------


def test_a_library_without_data_downgrades_all_the_way_without_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")

    downgrade(monkeypatch, path, "base", allow_destructive=False)

    assert sqlite_tables(path) <= {"alembic_version"}  # everything was dropped


def sqlite_tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_bookkeeping_and_re_creatable_metadata_do_not_count_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            build.component_version()  # a catalog row
            build.representation_space()  # a space (and the component it needs)
            SettingsRepository(session).bootstrap(now=clock())
            AppStateRepository(session).set("wal_truncation_owed", "token", now=clock())
            session.commit()
    finally:
        engine.dispose()

    downgrade(monkeypatch, path, "base", allow_destructive=False)  # no refusal


# --- a library with data --------------------------------------------------------------------------


@pytest.mark.parametrize("revision", REVISIONS)
def test_a_populated_library_is_refused_at_every_revision_before_anything_changes(
    revision: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, revision)
    insert_identity(path)
    before = dump(path)
    previous = f"{int(revision) - 1:04d}" if revision != "0001" else "base"

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(identities\)"):
        downgrade(monkeypatch, path, previous, allow_destructive=False)

    assert version(path) == revision  # the revision was not undone
    assert dump(path) == before  # and no row, table or constraint changed


def test_the_refusal_names_the_override_and_says_it_is_for_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)

    with pytest.raises(DestructiveDowngradeRefused) as refused:
        downgrade(monkeypatch, path, "0003", allow_destructive=False)

    assert ALLOW_DESTRUCTIVE_DOWNGRADE_ENV in str(refused.value)
    assert "development" in str(refused.value)
    assert "forward" in str(refused.value)  # recovery moves forward, it does not roll back


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "11", " 1"])
def test_only_the_exact_override_lets_a_populated_library_through(
    value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, value)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade_with_current_environment(monkeypatch, path, "0003")

    assert version(path) == "0004"


def downgrade_with_current_environment(
    monkeypatch: pytest.MonkeyPatch, path: Path, revision: str
) -> None:
    """The helper would overwrite the variable under test, so call Alembic directly."""
    from alembic import command

    from tests.fixtures.migrations import DATABASE_PATH_ENV
    from tests.fixtures.persistence import alembic_config

    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    command.downgrade(alembic_config(), revision)


def test_the_override_set_to_one_lets_it_through_and_the_rows_survive_a_safe_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, "1")

    downgrade_with_current_environment(monkeypatch, path, "0003")

    assert version(path) == "0003"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM identities").fetchone() == (1,)


def test_a_table_the_guard_does_not_know_counts_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE mystery (id INTEGER)")
        connection.execute("INSERT INTO mystery VALUES (1)")

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(mystery\)"):
        downgrade(monkeypatch, path, "0003", allow_destructive=False)


# --- no revision can forget the guard ------------------------------------------------------


@pytest.mark.parametrize("revision_file", sorted(VERSIONS.glob("0*.py")), ids=lambda p: p.stem[:4])
def test_every_revision_starts_its_downgrade_with_the_guard(revision_file: Path) -> None:
    module = ast.parse(revision_file.read_text(encoding="utf-8"))
    (downgrade_function,) = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    ]
    statements = [
        statement
        for statement in downgrade_function.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]  # the docstring is not a statement that runs

    first = statements[0]
    assert isinstance(first, ast.Expr)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "require_destructive_downgrade_allowed"
