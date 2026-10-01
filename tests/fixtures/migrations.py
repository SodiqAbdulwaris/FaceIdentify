"""Helpers for tests that migrate real databases through Alembic revisions (TST-032).

Alembic loads a fresh copy of each revision module for every command, so a test that wants a
revision to fail or to report something part-way through patches the loader (`patch_revision`),
not the module.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from alembic import command, util

from backend.infrastructure.db.downgrade_guard import ALLOW_DESTRUCTIVE_DOWNGRADE_ENV
from tests.fixtures.persistence import alembic_config

DATABASE_PATH_ENV = "FACEIDENTIFY_DATABASE_PATH"

DANGLING_UPDATE = (
    "UPDATE index_operations SET representation_id = X'00000000000000000000000000000001'"
    " WHERE rowid = (SELECT min(rowid) FROM index_operations)"
)


def migrate(monkeypatch: pytest.MonkeyPatch, path: Path, revision: str) -> None:
    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    command.upgrade(alembic_config(), revision)


def downgrade(
    monkeypatch: pytest.MonkeyPatch, path: Path, revision: str, *, allow_destructive: bool = True
) -> None:
    """Downgrade `path`. A downgrade of a populated library is refused unless the development
    override is set, so the tests of a revision's downgrade opt in; the tests of the guard itself
    pass `allow_destructive=False`."""
    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    if allow_destructive:
        monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, "1")
    else:
        monkeypatch.delenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, raising=False)
    command.downgrade(alembic_config(), revision)


def dump(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table except the version stamp, by rowid."""
    with sqlite3.connect(path) as connection:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                " AND name != 'alembic_version' ORDER BY name"
            )
        ]
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()  # noqa: S608
            for table in tables
        }


def version(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def table_sql(path: Path, table: str) -> str:
    with sqlite3.connect(path) as connection:
        return str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()[0]
        )


def trigger_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }


def foreign_key_violations(path: Path) -> list[Any]:
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA foreign_key_check").fetchall()


def patch_revision(
    monkeypatch: pytest.MonkeyPatch,
    revision_id: str,
    *,
    after_upgrade: Callable[[], None] | None = None,
    after_downgrade: Callable[[], None] | None = None,
) -> None:
    """Make the revision run its real upgrade and downgrade and then the given hook."""
    real_load = util.load_python_file

    def wrap(real: Callable[[], None], after: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            real()
            after()

        return run

    def load(directory: str, filename: str) -> Any:
        module = real_load(directory, filename)
        if getattr(module, "revision", None) == revision_id:
            if after_upgrade is not None:
                vars(module)["upgrade"] = wrap(module.upgrade, after_upgrade)
            if after_downgrade is not None:
                vars(module)["downgrade"] = wrap(module.downgrade, after_downgrade)
        return module

    monkeypatch.setattr(util, "load_python_file", load)


def record_enforcement(seen: list[int]) -> Callable[[], None]:
    def record() -> None:
        from alembic import op

        seen.append(op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar_one())

    return record


def fail(message: str) -> Callable[[], None]:
    def raise_it() -> None:
        raise RuntimeError(message)

    return raise_it


def dangle(table_update: str) -> Callable[[], None]:
    def run() -> None:
        from alembic import op

        op.execute(table_update)

    return run
