"""Isolated filesystem, SQLite and USearch fixtures.

Everything lives under pytest's per-test `tmp_path`; nothing here can resolve to a real
library or %LOCALAPPDATA% directory (see `_require_inside`).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from usearch.index import Index

from backend.infrastructure.db.engine import Base, create_session_factory, create_sqlite_engine


@dataclass(frozen=True)
class AppDirs:
    """Temporary equivalents of the two roots in tech-stack.md §15.

    library_root: user-selected library (authoritative database + managed bytes).
    local_state:  machine-local derived state (%LOCALAPPDATA%/<App>: indexes, temp, logs, runtime).
    Subdirectories beyond these are Storage Manager's to define.
    """

    library_root: Path
    local_state: Path

    @property
    def database_path(self) -> Path:
        return self.library_root / "database" / "library.db"

    @property
    def indexes(self) -> Path:
        return self.local_state / "indexes"

    @property
    def temp(self) -> Path:
        return self.local_state / "temp"

    @property
    def logs(self) -> Path:
        return self.local_state / "logs"


def _require_inside(path: Path, root: Path) -> Path:
    if not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"test storage escaped its sandbox: {path} is not under {root}")
    return path


@pytest.fixture
def app_dirs(tmp_path: Path) -> AppDirs:
    dirs = AppDirs(library_root=tmp_path / "library", local_state=tmp_path / "local")
    for directory in (dirs.database_path.parent, dirs.indexes, dirs.temp, dirs.logs):
        directory.mkdir(parents=True)
    return dirs


@pytest.fixture
def sqlite_engine(app_dirs: AppDirs, tmp_path: Path) -> Iterator[Engine]:
    """Real file-backed SQLite with production pragmas and the full model registry."""
    db_path = _require_inside(app_dirs.database_path, tmp_path)
    engine = create_sqlite_engine(db_path)
    # ponytail: create_all until Alembic 0001_initial_schema exists (M2); then run migrations here.
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    # Deleting fails on Windows if any connection leaked, which surfaces the leak as a test error.
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


@pytest.fixture
def db_session(sqlite_engine: Engine) -> Iterator[Session]:
    with create_session_factory(sqlite_engine)() as session:
        yield session
        session.rollback()


@pytest.fixture
def make_usearch_index(app_dirs: AppDirs, tmp_path: Path) -> Iterator[Callable[..., Index]]:
    """Factory for real USearch indexes whose save path is inside `app_dirs.indexes`.

    Deliberately returns a raw `usearch.index.Index`, not a production RepresentationIndex.
    """
    created: list[Index] = []

    def make(
        ndim: int, *, name: str = "index.usearch", metric: str = "cos", **kwargs: Any
    ) -> Index:
        path = _require_inside(app_dirs.indexes / name, tmp_path)
        index = Index(ndim=ndim, metric=metric, path=path, **kwargs)
        created.append(index)
        return index

    yield make
    for index in created:
        index.reset()
