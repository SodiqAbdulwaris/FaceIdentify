"""The exclusive, library-lifetime lock (M2: TST-030; CONTEXT open question 23).

An operating-system lock on `<library>/database/.lock`: a second holder fails clearly, in this
process and in another one, and it is released when the holder ends however it ends. The cross-
process cases use real subprocesses, because a lock that only conflicts inside one process proves
nothing about two backends.
"""

import errno
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.infrastructure.storage import library_lock
from backend.infrastructure.storage.library_lock import (
    LOCK_FILE_NAME,
    LibraryLock,
    LibraryLockedError,
)
from backend.infrastructure.storage.library_root import InvalidLibraryRootError

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


def kill_tree(process: subprocess.Popen[str]) -> None:
    """Kill the holder and everything it started. On Windows the venv's `python.exe` is a launcher
    that starts the real interpreter as a child, and that child is the one holding the lock."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:  # pragma: no cover - the suite runs on Windows
        process.kill()
    process.wait(timeout=30)


def close_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def start_holder(root: Path) -> subprocess.Popen[str]:
    """A second process that holds the library until it is told to stop, or killed. Whatever goes
    wrong while starting it, the process does not outlive the test."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=Path(__file__).parents[2],
    )  # fmt: skip
    assert process.stdout is not None
    try:
        with ThreadPoolExecutor(
            max_workers=1
        ) as pool:  # a hung start must fail, not hang the suite
            line = pool.submit(process.stdout.readline).result(timeout=60)
        assert line.strip() == "HELD"
    except BaseException:
        kill_tree(process)
        close_streams(process)
        raise
    return process


def acquire_soon(root: Path, seconds: float = 10) -> None:
    """The lock of a process that has just ended is released by the operating system, which is not
    instantaneous after `TerminateProcess`: allow it a moment, and no more."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with LibraryLock(root):
                return
        except LibraryLockedError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


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


def test_an_interruption_while_locking_leaves_the_file_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_lock = library_lock._lock

    def locks_then_is_interrupted(handle: object) -> None:
        real_lock(handle)  # type: ignore[arg-type]
        raise KeyboardInterrupt

    monkeypatch.setattr(library_lock, "_lock", locks_then_is_interrupted)
    with pytest.raises(KeyboardInterrupt):
        LibraryLock(tmp_path).acquire()

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
