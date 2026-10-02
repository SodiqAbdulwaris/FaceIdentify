"""Opening a library for the lifetime of the backend process
(PERSISTENCE_IMPLEMENTATION.md §27, §28; CONTEXT open questions 17, 20, 23, 26; issue 33).

`open_library` is the one place the startup order lives, as a context manager a FastAPI lifespan
wraps (no web framework is needed to build or test it):

1. the roots are validated (`validate_library_root`, `validate_distinct_roots`): nothing is created
   for a typo or for nested roots;
2. **the library lock is taken** (`LibraryLock`): before the layout, the migrations, recovery or any
   other mutation, and a second backend on the same library fails here, clearly;
3. the layout is created (idempotent; nothing is removed);
4. the schema is migrated to `head` (Alembic; a database *newer* than this application fails safely
   with `DatabaseNewerThanApplicationError` instead of being touched);
5. the engine, the Storage Manager, the IndexCoordinator and the eraser are built, and
   `recover_on_startup` reconciles what a crash left half done (artifacts, in-flight work, indexes,
   erasures), exactly in the order of §28;
6. the caller gets an `OpenLibrary` and runs; leaving the block disposes the engine and releases the
   lock, and so does a failure at any earlier step, so a failed start never leaves the library held.

Nothing here has a default for a threshold that has not been measured: the retry policy and the two
index catch-up limits are the caller's, as for `recover_on_startup`. The clock and the id source are
injected, as everywhere, so tests are deterministic.

What it does not do: start the ML worker or the scheduler (later milestones), or read the shell's
persisted library setting (the shell passes the resolved root in).
"""

import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.erasure import RepresentationEraser
from backend.app.memory.index_coordinator import IndexCoordinator, RetryPolicy
from backend.app.recovery.startup import StartupReport, recover_on_startup
from backend.infrastructure.db.engine import create_session_factory, create_sqlite_engine
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.library_lock import LibraryLock
from backend.infrastructure.storage.library_root import (
    validate_distinct_roots,
    validate_library_root,
)
from backend.infrastructure.storage.workspaces import WorkspaceManager

ALEMBIC_DIRECTORY = Path(__file__).resolve().parents[1] / "alembic"


class DatabaseNewerThanApplicationError(RuntimeError):
    """The library's database is at a revision this application does not know
    (`DATABASE_SCHEMA_NEWER_THAN_APPLICATION`, persistence §27): it was written by a newer version,
    and is neither migrated nor downgraded."""


@dataclass(frozen=True)
class OpenLibrary:
    """Everything the backend needs from an opened library. Valid only inside the `with` block."""

    roots: StorageRoots
    engine: Engine
    session_factory: sessionmaker[Session]
    store: ManagedFileStore
    workspaces: WorkspaceManager
    coordinator: IndexCoordinator
    eraser: RepresentationEraser
    startup: StartupReport


def _alembic_config(database_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIRECTORY))
    config.attributes["database_path"] = database_path
    config.attributes["configure_logger"] = False  # this is a host process: keep its logging
    return config


def _stamped_revision(database_path: Path) -> str | None:
    """The revision the database is stamped with, or None for a new database."""
    with sqlite3.connect(database_path) as connection:
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:  # no such table: not migrated yet
            return None
    return None if row is None else str(row[0])


def migrate(database_path: Path) -> None:
    """Bring the database to `head`. A database stamped with a revision this application does not
    have is refused untouched (it is newer, or foreign)."""
    config = _alembic_config(database_path)
    stamped = _stamped_revision(database_path)
    known = {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}
    if stamped is not None and stamped not in known:
        raise DatabaseNewerThanApplicationError(
            f"the library database is at revision {stamped!r}, which this version of the "
            "application does not know: it was written by a newer version"
        )
    command.upgrade(config, "head")


@contextmanager
def open_library(
    *,
    library_root: Path,
    local_state_root: Path,
    clock: Callable[[], datetime],
    new_id: Callable[[], uuid.UUID],
    retry: RetryPolicy,
    index_batch: int,
    max_index_passes: int,
) -> Iterator[OpenLibrary]:
    """Open the library for the life of the `with` block (see the module docstring)."""
    library_root = validate_library_root(library_root)
    validate_distinct_roots(library_root, local_state_root)
    with ExitStack() as cleanup:
        cleanup.enter_context(LibraryLock(library_root))  # before anything is created or changed
        roots = StorageRoots(library_root=library_root, local_state_root=local_state_root)
        roots.ensure_layout()
        migrate(roots.database_path)
        engine = create_sqlite_engine(roots.database_path)
        cleanup.callback(engine.dispose)  # the file and its log are released before the lock is
        session_factory = create_session_factory(engine)
        store = ManagedFileStore(roots)
        workspaces = WorkspaceManager(roots)
        coordinator = IndexCoordinator(
            session_factory, roots.local_state_root / "indexes",
            clock=clock, new_id=new_id, retry=retry,
        )  # fmt: skip
        eraser = RepresentationEraser(
            session_factory, engine, coordinator, clock=clock, new_id=new_id
        )
        startup = recover_on_startup(
            session_factory, store, workspaces, coordinator, eraser,
            clock=clock, index_batch=index_batch, max_index_passes=max_index_passes,
        )  # fmt: skip
        yield OpenLibrary(
            roots, engine, session_factory, store, workspaces, coordinator, eraser, startup
        )
