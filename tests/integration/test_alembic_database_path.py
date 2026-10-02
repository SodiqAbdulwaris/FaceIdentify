"""Which database Alembic migrates (CONTEXT open question 17, decided 2026-10-01).

The application passes the one resolved path as `config.attributes["database_path"]`; the command
line gives the library root (`FACEIDENTIFY_LIBRARY_ROOT`; the database is
`<root>/database/library.db`); the bare `FACEIDENTIFY_DATABASE_PATH` is deprecated but still
works; and nothing is guessed.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from backend.infrastructure.storage.layout import database_path_for
from backend.infrastructure.storage.library_root import LIBRARY_ROOT_ENV
from tests.fixtures.migrations import DATABASE_PATH_ENV
from tests.fixtures.persistence import alembic_config


def stamped(path: Path) -> str | None:
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else str(row[0])


@pytest.fixture(autouse=True)
def no_ambient_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_PATH_ENV, raising=False)
    monkeypatch.delenv(LIBRARY_ROOT_ENV, raising=False)


def test_the_library_root_gives_the_database_path_and_creates_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setenv(LIBRARY_ROOT_ENV, str(root))

    command.upgrade(alembic_config(), "0001")

    assert database_path_for(root) == root / "database" / "library.db"
    assert stamped(root / "database" / "library.db") == "0001"


def test_an_explicit_path_wins_over_both_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LIBRARY_ROOT_ENV, str(tmp_path / "from-root"))
    monkeypatch.setenv(DATABASE_PATH_ENV, str(tmp_path / "legacy.db"))
    explicit = tmp_path / "explicit.db"
    config = alembic_config()
    config.attributes["database_path"] = explicit

    command.upgrade(config, "0001")

    assert stamped(explicit) == "0001"
    assert not (tmp_path / "legacy.db").exists()
    assert not (tmp_path / "from-root").exists()


def test_the_library_root_wins_over_the_deprecated_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setenv(LIBRARY_ROOT_ENV, str(root))
    monkeypatch.setenv(DATABASE_PATH_ENV, str(tmp_path / "legacy.db"))

    command.upgrade(alembic_config(), "0001")

    assert stamped(root / "database" / "library.db") == "0001"
    assert not (tmp_path / "legacy.db").exists()


def test_the_deprecated_path_still_works_when_nothing_else_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy.db"
    monkeypatch.setenv(DATABASE_PATH_ENV, str(legacy))

    command.upgrade(alembic_config(), "0001")

    assert stamped(legacy) == "0001"


def test_nothing_is_guessed_when_no_library_is_given(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=LIBRARY_ROOT_ENV):
        command.upgrade(alembic_config(), "0001")
    assert list(tmp_path.iterdir()) == []
