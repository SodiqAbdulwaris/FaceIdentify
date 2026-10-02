"""The exclusive, library-lifetime lock (M2: TST-030; CONTEXT open question 23).

An operating-system lock on `<library>/database/.lock`: a second holder fails clearly, in this
process and in another one, and it is released when the holder ends however it ends. The cross-
process cases use real subprocesses, because a lock that only conflicts inside one process proves
nothing about two backends.
"""

import errno
import subprocess
import time
from pathlib import Path

import pytest

from backend.infrastructure.storage import library_lock
from backend.infrastructure.storage.library_lock import (
    LOCK_FILE_NAME,
    LibraryLock,
    LibraryLockedError,
)
from backend.infrastructure.storage.library_root import InvalidLibraryRootError
from tests.fixtures.processes import acquire_soon, close_streams, kill_tree, start_until

HOLDER = """
import sys
from pathlib import Path
from backend.infrastructure.storage.library_lock import LibraryLock
lock = LibraryLock(Path(sys.argv[1]))
lock.acquire()
print("HELD", flush=True)
sys.stdin.read()  # hold until the parent closes stdin or kills us
"""


def is_held(lock: LibraryLock) -> bool:
    return lock.held  # (a function, so a type checker does not carry an earlier answer over)


def start_holder(root: Path) -> subprocess.Popen[str]:
    """A second process that holds the library until it is told to stop, or killed."""
    return start_until(HOLDER, str(root), ready="HELD")


def test_the_lock_is_a_file_under_the_database_folder_created_on_demand(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    with LibraryLock(root) as lock:
        assert is_held(lock)
        assert (root / "database" / LOCK_FILE_NAME).is_file()
    assert (root / "database" / LOCK_FILE_NAME).is_file()  # left in place: deleting it would race


def test_a_root_that_would_not_be_accepted_is_not_locked_or_created(tmp_path: Path) -> None:
    with pytest.raises(InvalidLibraryRootError, match="absolute"):
        LibraryLock(Path("relative"))
    with pytest.raises(InvalidLibraryRootError, match="does not exist"):
        LibraryLock(tmp_path / "typo" / "library")
    assert list(tmp_path.iterdir()) == []  # no skeleton was created for a typo


def test_a_second_holder_in_the_same_process_is_refused_and_can_try_again_after_the_release(
    tmp_path: Path,
) -> None:
    first, second = LibraryLock(tmp_path), LibraryLock(tmp_path)
    first.acquire()

    started = time.monotonic()
    with pytest.raises(LibraryLockedError, match="another FaceIdentify process"):
        second.acquire()
    assert time.monotonic() - started < 5  # refused at once, not after a blocking lock retries
    assert not is_held(second)

    first.release()
    second.acquire()  # the refusal left nothing behind, and the release was immediate
    assert is_held(second)
    second.release()


def test_one_lock_object_cannot_be_acquired_twice(tmp_path: Path) -> None:
    with LibraryLock(tmp_path) as lock, pytest.raises(LibraryLockedError, match="already holds"):
        lock.acquire()


def test_releasing_twice_and_without_acquiring_is_harmless(tmp_path: Path) -> None:
    lock = LibraryLock(tmp_path)
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()
    assert not is_held(lock)


def test_the_lock_is_released_when_the_with_block_ends_even_by_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"), LibraryLock(tmp_path):
        raise RuntimeError("boom")

    with LibraryLock(tmp_path):  # free again
        pass


def test_release_unlocks_explicitly_before_it_closes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real_unlock = library_lock._unlock

    def spy(handle: object) -> None:
        seen.append(getattr(handle, "closed", True))  # still open when the unlock is requested
        real_unlock(handle)  # type: ignore[arg-type]

    monkeypatch.setattr(library_lock, "_unlock", spy)

    with LibraryLock(tmp_path):
        pass

    assert seen == [False]


def test_a_failure_that_is_not_a_held_lock_is_not_reported_as_one_and_leaves_nothing_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(handle: object) -> None:
        raise OSError(errno.EIO, "disk error")

    monkeypatch.setattr(library_lock, "_lock", broken)
    with pytest.raises(OSError, match="disk error") as raised:
        LibraryLock(tmp_path).acquire()
    assert not isinstance(raised.value, LibraryLockedError)

    monkeypatch.undo()
    with LibraryLock(tmp_path):  # the file was closed: nothing is left holding it
        pass


def test_an_interruption_while_locking_unlocks_and_closes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_lock, real_unlock = library_lock._lock, library_lock._unlock
    unlocked: list[bool] = []

    def locks_then_is_interrupted(handle: object) -> None:
        real_lock(handle)  # type: ignore[arg-type]
        raise KeyboardInterrupt

    def spy(handle: object) -> None:
        unlocked.append(not getattr(handle, "closed", True))  # unlocked while still open
        real_unlock(handle)  # type: ignore[arg-type]

    monkeypatch.setattr(library_lock, "_lock", locks_then_is_interrupted)
    monkeypatch.setattr(library_lock, "_unlock", spy)
    with pytest.raises(KeyboardInterrupt):
        LibraryLock(tmp_path).acquire()

    assert unlocked == [True]
    monkeypatch.undo()
    with LibraryLock(tmp_path):  # the lock it had just taken was not leaked
        pass


def test_another_process_holding_the_library_blocks_startup_and_its_orderly_exit_frees_it(
    tmp_path: Path,
) -> None:
    holder = start_holder(tmp_path)
    try:
        with pytest.raises(LibraryLockedError):
            LibraryLock(tmp_path).acquire()
    finally:
        assert holder.stdin is not None
        holder.stdin.close()  # the holder reads EOF and exits normally
        holder.wait(timeout=30)
        close_streams(holder)

    acquire_soon(tmp_path)  # free after an orderly exit


def test_a_killed_holder_never_leaves_the_library_locked(tmp_path: Path) -> None:
    holder = start_holder(tmp_path)
    try:
        with pytest.raises(LibraryLockedError):
            LibraryLock(tmp_path).acquire()
    finally:
        kill_tree(holder)  # no chance to release anything
        close_streams(holder)

    acquire_soon(tmp_path)  # the operating system freed it


def test_two_libraries_do_not_lock_each_other(tmp_path: Path) -> None:
    with LibraryLock(tmp_path / "one"), LibraryLock(tmp_path / "two"):
        pass
