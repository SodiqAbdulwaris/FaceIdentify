"""Opening a library for the life of the backend (M2: TST-030; persistence sections 27 and 28;
issue 33).

`open_library` takes the library lock before it creates or changes anything, then migrates, lays out
the folders, builds the services and recovers, in the order of section 28; leaving the block, or
failing at any step, disposes the engine and then releases the lock. A database from a newer
version, and one that is not ours, is refused untouched.
"""

import hashlib
import shutil
import sqlite3
import uuid
from contextlib import AbstractContextManager, closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, select

from backend.app import lifecycle
from backend.app.jobs.models import Job
from backend.app.lifecycle import (
    DatabaseNewerThanApplicationError,
    ForeignDatabaseError,
    OpenLibrary,
    open_library,
)
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.recovery.startup import recover_on_startup
from backend.infrastructure.db.downgrade_guard import ALLOW_DESTRUCTIVE_DOWNGRADE_ENV
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.library_lock import LibraryLock, LibraryLockedError
from backend.infrastructure.storage.library_root import InvalidLibraryRootError
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.links import link_directory


class Opener:
    """`open_library` on `<tmp>/library` and `<tmp>/local` with the fixtures' clock and ids."""

    def __init__(self, tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> None:
        self.library = tmp_path / "library"
        self.local = tmp_path / "local"
        self.clock, self.new_id = clock, new_id

    def __call__(self, **overrides: Any) -> AbstractContextManager[OpenLibrary]:
        arguments: dict[str, Any] = dict(
            library_root=self.library, local_state_root=self.local, clock=self.clock,
            new_id=self.new_id, index_batch=50, max_index_passes=5,
            transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        )  # fmt: skip
        return open_library(**(arguments | overrides))

    @property
    def database(self) -> Path:
        return self.library / "database" / "library.db"


@pytest.fixture
def opener(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Opener:
    (tmp_path / "library").mkdir()
    return Opener(tmp_path, clock, new_id)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_is_free(library: Path) -> bool:
    try:
        with LibraryLock(library):
            return True
    except LibraryLockedError:
        return False


def unlink_database(opener: Opener) -> None:
    """Delete the database and its log: fails on Windows if a connection is still holding them."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(opener.database) + suffix).unlink(missing_ok=True)


def stamps(opener: Opener) -> list[tuple[str]]:
    with closing(sqlite3.connect(opener.database)) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchall()


def create_database(opener: Opener, *statements: str) -> None:
    (opener.library / "database").mkdir()
    with closing(sqlite3.connect(opener.database)) as connection:
        for statement in statements:
            connection.execute(statement)
        connection.commit()


# --- opening --------------------------------------------------------------------------------------


def test_a_new_library_is_laid_out_migrated_and_recovered_cleanly(opener: Opener) -> None:
    with opener() as library:
        assert library.roots == StorageRoots(opener.library, opener.local)
        assert opener.database.is_file()
        assert (opener.library / "staging").is_dir()
        assert (opener.local / "indexes").is_dir()
        assert stamps(opener)
        assert library.startup.clean  # nothing to repair, nothing unresolved
        index_directory = library.coordinator.index_directory(uuid.UUID(int=1))
        assert index_directory.parent == opener.local / "indexes"  # machine-local, derived data

        with library.session_factory() as session:  # the services are wired to the real database
            assert session.scalar(select(Job.id)) is None
        assert isinstance(library.unit_of_work, UnitOfWork)  # and the write path is available
        assert library.packages.installed() == []  # and so is the runtime package store
        assert library.unit_of_work.write(lambda session: session.scalar(select(Job.id))) is None


def test_a_root_given_through_a_link_is_used_as_the_real_folder(
    opener: Opener, tmp_path: Path
) -> None:
    link_directory(tmp_path / "alias", opener.library)

    with opener(library_root=tmp_path / "alias") as library:
        assert library.roots.library_root == opener.library.resolve()
        assert library.roots.database_path == opener.database.resolve()


def test_the_library_stays_locked_while_open_and_is_free_after(opener: Opener) -> None:
    with opener():
        assert not lock_is_free(opener.library)
        with pytest.raises(LibraryLockedError), opener():
            pass  # a second backend on the same library is refused
    assert lock_is_free(opener.library)


def test_opening_again_is_idempotent_and_still_clean(opener: Opener) -> None:
    with opener():
        first = stamps(opener)

    with opener() as library:
        assert library.startup.clean
    assert stamps(opener) == first


# --- the order ------------------------------------------------------------------------------------


def test_the_lock_comes_first_then_the_schema_the_layout_and_recovery(
    opener: Opener, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_acquire = LibraryLock.acquire
    real_layout = StorageRoots.ensure_layout
    real_migrate = lifecycle.migrate
    real_recover = recover_on_startup

    def acquire(self: LibraryLock) -> None:
        calls.append("lock")
        real_acquire(self)

    def layout(self: StorageRoots) -> None:
        calls.append("layout")
        real_layout(self)

    def migrate(path: Path) -> None:
        calls.append("migrate")
        real_migrate(path)

    def recover(*args: Any, **kwargs: Any) -> Any:
        calls.append("recover")
        return real_recover(*args, **kwargs)

    monkeypatch.setattr(LibraryLock, "acquire", acquire)
    monkeypatch.setattr(StorageRoots, "ensure_layout", layout)
    monkeypatch.setattr(lifecycle, "migrate", migrate)
    monkeypatch.setattr(lifecycle, "recover_on_startup", recover)

    with opener():
        pass

    assert calls == ["lock", "migrate", "layout", "recover"]


def test_a_library_held_by_someone_else_is_not_laid_out_migrated_or_recovered(
    opener: Opener,
) -> None:
    with LibraryLock(opener.library):  # another backend
        with pytest.raises(LibraryLockedError), opener():
            pass

    assert not (opener.library / "staging").exists()
    assert not opener.database.exists()
    assert not opener.local.exists()


def test_roots_that_cannot_be_used_create_nothing(
    opener: Opener, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with (
        pytest.raises(InvalidLibraryRootError, match="absolute"),
        opener(library_root=Path("relative")),
    ):
        pass
    with (
        pytest.raises(InvalidLibraryRootError, match="absolute"),
        opener(local_state_root=Path("relative-local")),
    ):
        pass
    with (
        pytest.raises(InvalidLibraryRootError, match="separate folders"),
        opener(local_state_root=opener.library / "inside"),
    ):
        pass
    with (
        pytest.raises(InvalidLibraryRootError, match="does not exist"),
        opener(library_root=tmp_path / "typo" / "library"),
    ):
        pass

    assert list(opener.library.iterdir()) == []  # not even the lock file
    assert sorted(path.name for path in tmp_path.iterdir()) == ["library"]  # nothing anywhere


# --- a database that is newer, older or not ours ------------------------------------------


def test_a_database_stamped_with_an_unknown_revision_is_refused_untouched(opener: Opener) -> None:
    create_database(
        opener,
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)",
        "INSERT INTO alembic_version VALUES ('9999')",
    )
    before = digest(opener.database)

    with pytest.raises(DatabaseNewerThanApplicationError, match="9999"), opener():
        pass

    assert digest(opener.database) == before  # neither migrated nor downgraded
    assert lock_is_free(opener.library)  # and the library is not left held
    assert not (opener.library / "staging").exists()  # nor laid out around it
    assert not opener.local.exists()


def test_one_unknown_stamp_among_several_is_enough_to_refuse(opener: Opener) -> None:
    create_database(
        opener,
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)",
        "INSERT INTO alembic_version VALUES ('0001')",
        "INSERT INTO alembic_version VALUES ('9999')",
    )

    with pytest.raises(DatabaseNewerThanApplicationError, match="9999"), opener():
        pass


def test_a_database_with_tables_but_no_stamp_is_not_ours_and_is_left_alone(opener: Opener) -> None:
    create_database(
        opener,
        "CREATE TABLE somebody_elses_data (id INTEGER)",
        "INSERT INTO somebody_elses_data VALUES (1)",
    )
    before = digest(opener.database)

    with pytest.raises(ForeignDatabaseError, match="no migration stamp"), opener():
        pass

    assert digest(opener.database) == before
    assert lock_is_free(opener.library)


def test_an_empty_database_file_is_a_first_run_that_was_interrupted_and_is_migrated(
    opener: Opener,
) -> None:
    create_database(opener)

    with opener() as library:
        assert library.startup.clean


def test_a_database_stamped_with_an_older_known_revision_is_upgraded_whatever_the_environment(
    opener: Opener, monkeypatch: pytest.MonkeyPatch
) -> None:
    (opener.library / "database").mkdir()
    command.upgrade(lifecycle._alembic_config(opener.database), "0003")
    assert stamps(opener) == [("0003",)]
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, "1")  # a downgrade switch: no effect here

    with opener() as library:
        assert library.startup.clean
    assert stamps(opener) == [("0010",)]


def test_an_install_path_with_a_percent_sign_still_migrates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alembic reads the script folder through a config parser that interpolates `%`."""
    odd = tmp_path / "100%" / "alembic"
    shutil.copytree(lifecycle.ALEMBIC_DIRECTORY, odd, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(lifecycle, "ALEMBIC_DIRECTORY", odd)
    database = tmp_path / "library.db"

    lifecycle.migrate(database)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall()


# --- failures leave nothing held -----------------------------------------------------------


@pytest.mark.parametrize("step", ["migrate", "recover_on_startup"])
def test_a_failure_while_starting_releases_the_lock_and_the_database(
    step: str, opener: Opener, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"{step} failed")

    monkeypatch.setattr(lifecycle, step, fails)

    with pytest.raises(RuntimeError, match=f"{step} failed"), opener():
        pass

    assert lock_is_free(opener.library)
    unlink_database(opener)


def test_a_failure_while_laying_out_the_folders_releases_the_lock(
    opener: Opener, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(self: StorageRoots) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(StorageRoots, "ensure_layout", fails)

    with pytest.raises(OSError, match="disk full"), opener():
        pass

    assert lock_is_free(opener.library)


def test_the_engine_is_disposed_before_the_lock_is_released(
    opener: Opener, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_dispose, real_release = Engine.dispose, LibraryLock.release

    def dispose(self: Engine, close: bool = True) -> None:
        order.append("dispose")
        real_dispose(self, close)

    def release(self: LibraryLock) -> None:
        order.append("release")
        real_release(self)

    monkeypatch.setattr(Engine, "dispose", dispose)
    monkeypatch.setattr(LibraryLock, "release", release)

    with opener():
        pass

    # (the migration's own engine is disposed too, earlier: the last dispose is the library's)
    assert order.count("release") == 1
    assert "dispose" in order
    assert order[-1] == "release"  # nothing is disposed after the lock is gone


def test_leaving_the_block_with_an_error_releases_everything_too(opener: Opener) -> None:
    with pytest.raises(RuntimeError, match="boom"), opener():
        raise RuntimeError("boom")

    assert lock_is_free(opener.library)
    unlink_database(opener)


# --- recovery runs -----------------------------------------------------------------------------


def test_what_a_crash_left_running_is_recovered_when_the_library_is_opened(
    opener: Opener, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    with opener() as library, library.session_factory() as session:
        job = ModelFactory(session, clock, new_id).job(state="RUNNING")
        job_id: uuid.UUID = job.id
        session.commit()

    with opener() as library:
        assert library.startup.interrupted.jobs == [job_id]
        with library.session_factory() as session:
            assert session.scalar(select(Job.state).where(Job.id == job_id)) == "INTERRUPTED"

    with opener() as library:  # and a second start finds nothing more to repair
        assert library.startup.repaired_nothing
