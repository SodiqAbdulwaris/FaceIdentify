"""Isolated filesystem, SQLite and USearch fixtures.

Everything lives under pytest's per-test `tmp_path`; nothing here can resolve to a real
library or %LOCALAPPDATA% directory (see `_require_inside`).
"""

import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from usearch.index import Index

from backend.infrastructure.db.engine import create_session_factory, create_sqlite_engine
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config() -> Config:
    """The project's real Alembic config, safe to run inside a host process (no logging reset)."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    return config


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
def storage_roots(app_dirs: AppDirs) -> StorageRoots:
    """The real storage layout on the sandboxed roots (TESTING_STRATEGY.md §7.2)."""
    roots = StorageRoots(library_root=app_dirs.library_root, local_state_root=app_dirs.local_state)
    roots.ensure_layout()
    return roots


@pytest.fixture
def file_store(storage_roots: StorageRoots) -> ManagedFileStore:
    return ManagedFileStore(storage_roots)


@pytest.fixture(scope="session")
def migrated_template_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database migrated to Alembic `head` once per session; each test copies it.

    Every persistence test therefore runs against the real migration's schema, not
    `Base.metadata.create_all()`'s (PERSISTENCE_IMPLEMENTATION.md §27: "Fresh databases also run
    Alembic"), without paying for a migration per test.
    """
    path = tmp_path_factory.mktemp("migrated-template") / "library.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FACEIDENTIFY_DATABASE_PATH", str(path))
        command.upgrade(alembic_config(), "head")
    # Tests copy only the main file. That is complete only if nothing still holds the template
    # open, so a leaked connection (a leftover WAL) must fail loudly rather than truncate copies.
    assert not path.with_name(path.name + "-wal").exists()
    return path


@pytest.fixture
def sqlite_engine(
    app_dirs: AppDirs, tmp_path: Path, migrated_template_db: Path
) -> Iterator[Engine]:
    """Real file-backed SQLite with production pragmas and the migrated schema."""
    db_path = _require_inside(app_dirs.database_path, tmp_path)
    shutil.copyfile(migrated_template_db, db_path)
    engine = create_sqlite_engine(db_path)
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
