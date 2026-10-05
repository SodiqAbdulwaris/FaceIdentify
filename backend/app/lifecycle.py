"""Opening a library for the lifetime of the backend process
(PERSISTENCE_IMPLEMENTATION.md §27, §28; CONTEXT open questions 17, 20, 23, 26; issue 33).

`open_library` is the one place the startup order lives, as a context manager a FastAPI lifespan
wraps (no web framework is needed to build or test it):

1. the roots are validated (`validate_library_root`, `resolve_local_state_root`,
   `validate_distinct_roots`): nothing is created for a typo or for nested roots;
2. **the library lock is taken** (`LibraryLock`): before the schema, the layout, recovery or any
   other mutation, and a second backend on the same library fails here, clearly. (Taking it creates
   only the library's `database` folder and the lock file.)
3. the schema is migrated to `head` (Alembic; a database *newer* than this application, or one this
   application did not create, is refused untouched);
4. the folder layout is created (idempotent; nothing is removed);
5. the engine, the Storage Manager, the IndexCoordinator and the eraser are built, and
   `recover_on_startup` reconciles what a crash left half done (artifacts, in-flight work, indexes,
   erasures), in the order of §28;
6. the caller gets an `OpenLibrary` and runs; leaving the block disposes the engine and releases the
   lock, and so does a failure at any earlier step, so a failed start never leaves the library held.

Nothing here has a default for a threshold that has not been measured: the index operation retry
policy, the transaction retry policy (`UnitOfWork`: `BEGIN IMMEDIATE` and whole-transaction retry,
CONTEXT open question 20) and the two index catch-up limits are the caller's. The clock and the id
source are injected, as everywhere, so tests are deterministic.

What it does not do: start the ML worker or the scheduler (later milestones), or read the shell's
persisted library setting (the shell passes the resolved root in).
"""

import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing, contextmanager
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
from backend.app.runtime.package_store import RuntimePackageStore
from backend.infrastructure.db.engine import create_session_factory, create_sqlite_engine
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.library_lock import LibraryLock
from backend.infrastructure.storage.library_root import (
    resolve_local_state_root,
    validate_distinct_roots,
    validate_library_root,
)
from backend.infrastructure.storage.workspaces import WorkspaceManager

ALEMBIC_DIRECTORY = Path(__file__).resolve().parents[1] / "alembic"


class DatabaseNewerThanApplicationError(RuntimeError):
    """The library's database is stamped with a revision this application does not know
    (`DATABASE_SCHEMA_NEWER_THAN_APPLICATION`, persistence §27): it was written by a newer version
    (or is not ours), and is neither migrated nor downgraded."""


class ForeignDatabaseError(RuntimeError):
    """The database file holds tables but no migration stamp: it is not a FaceIdentify library
    this application created, and migrating it would add our tables to somebody else's data."""


@dataclass(frozen=True)
class OpenLibrary:
    """Everything the backend needs from an opened library. Valid only inside the `with` block:
    leaving it disposes the engine, so a session the caller still holds then keeps the database
    file open after the lock is released; close them first."""

    roots: StorageRoots
    engine: Engine
    session_factory: sessionmaker[Session]
    store: ManagedFileStore
    workspaces: WorkspaceManager
    coordinator: IndexCoordinator
    eraser: RepresentationEraser
    unit_of_work: UnitOfWork
    packages: RuntimePackageStore
    startup: StartupReport


def _alembic_config(database_path: Path) -> Config:
    config = Config()
    # (ConfigParser interpolation: a literal percent sign in an install path must be doubled)
    config.set_main_option("script_location", str(ALEMBIC_DIRECTORY).replace("%", "%%"))
    config.attributes["database_path"] = database_path
    config.attributes["configure_logger"] = False  # this is a host process: keep its logging
    return config


def _inspect(database_path: Path) -> tuple[set[str], bool]:
    """(the revisions the database is stamped with, whether it holds any table other than the stamp
    itself). Read-only, so a database that is refused is not even checkpointed. A new or empty
    database is `(set(), False)`."""
    if not database_path.exists():
        return set(), False
    with closing(sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)) as connection:
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        stamps: set[str] = set()
        if "alembic_version" in tables:
            stamps = {
                str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")
            }
    return stamps, bool(tables - {"alembic_version"})


def migrate(database_path: Path) -> None:
    """Bring the database to `head`. A database stamped with a revision this application does not
    have (newer, or foreign) and one that holds tables but no stamp are refused untouched; a
    database stamped with an older known revision is upgraded."""
    config = _alembic_config(database_path)
    stamps, has_tables = _inspect(database_path)
    known = {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}
    if stamps - known:
        raise DatabaseNewerThanApplicationError(
            f"the library database is at revision {sorted(stamps - known)}, which this version of "
            "the application does not know: it was written by a newer version"
        )
    if not stamps and has_tables:
        raise ForeignDatabaseError(
            "the library database holds tables but no migration stamp: it is not a library this "
            "application created, so it is left as it is"
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
    transaction_retry: TransactionRetry,
    index_batch: int,
    max_index_passes: int,
) -> Iterator[OpenLibrary]:
    """Open the library for the life of the `with` block (see the module docstring)."""
    library_root = validate_library_root(library_root)
    local_state_root = resolve_local_state_root(explicit=local_state_root)
    validate_distinct_roots(library_root, local_state_root)
    with ExitStack() as cleanup:
        cleanup.enter_context(LibraryLock(library_root))  # before anything else is changed
        roots = StorageRoots(library_root=library_root, local_state_root=local_state_root)
        migrate(roots.database_path)
        roots.ensure_layout()
        engine = create_sqlite_engine(roots.database_path)
        cleanup.callback(engine.dispose)  # the file and its log are released before the lock is
        session_factory = create_session_factory(engine)
        unit_of_work = UnitOfWork(engine, retry=transaction_retry)
        store = ManagedFileStore(roots)
        workspaces = WorkspaceManager(roots)
        coordinator = IndexCoordinator(
            session_factory, unit_of_work, roots.indexes, clock=clock, new_id=new_id, retry=retry
        )
        eraser = RepresentationEraser(
            session_factory, engine, coordinator, clock=clock, new_id=new_id
        )
        packages = RuntimePackageStore(roots, new_id=new_id)
        startup = recover_on_startup(
            session_factory, store, workspaces, coordinator, eraser, packages,
            clock=clock, index_batch=index_batch, max_index_passes=max_index_passes,
        )  # fmt: skip
        yield OpenLibrary(
            roots, engine, session_factory, store, workspaces, coordinator, eraser,
            unit_of_work, packages, startup,
        )  # fmt: skip
