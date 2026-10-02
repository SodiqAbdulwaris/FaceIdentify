"""The exclusive, library-lifetime lock (M2: TST-030; CONTEXT open question 23).

An operating-system lock on `<library>/database/.lock`: a second holder fails clearly, in this
process and in another one, and it is released when the holder ends however it ends. The cross-
process cases use real subprocesses, because a lock that only conflicts inside one process proves
nothing about two backends.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.infrastructure.storage.library_lock import (
    LOCK_FILE_NAME,
    LibraryLock,
    LibraryLockedError,
)

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
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)], check=True, capture_output=True
        )
    else:  # pragma: no cover - the suite runs on Windows
        process.kill()
    process.wait(timeout=30)


def start_holder(root: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=Path(__file__).parents[2],
    )  # fmt: skip
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line.strip() == "HELD", process.stderr.read() if process.stderr else line
    return process


def test_the_lock_is_a_file_under_the_database_folder_created_on_demand(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    with LibraryLock(root) as lock:
        assert lock.held
        assert (root / "database" / LOCK_FILE_NAME).is_file()
    assert (root / "database" / LOCK_FILE_NAME).is_file()  # left in place: deleting it would race


def test_a_second_holder_in_the_same_process_is_refused_and_can_try_again_after_the_release(
    tmp_path: Path,
) -> None:
    first, second = LibraryLock(tmp_path), LibraryLock(tmp_path)
    first.acquire()

    started = time.monotonic()
    with pytest.raises(LibraryLockedError, match="another FaceIdentify process"):
        second.acquire()
    assert (
        time.monotonic() - started < 5
    )  # refused at once, not after the retries of a blocking lock
    assert not is_held(second)

    first.release()
    second.acquire()  # the refusal left nothing behind
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
    assert not lock.held


def test_the_lock_is_released_when_the_with_block_ends_even_by_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"), LibraryLock(tmp_path):
        raise RuntimeError("boom")

    with LibraryLock(tmp_path):  # free again
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
        for stream in (holder.stdout, holder.stderr):
            if stream is not None:
                stream.close()

    with LibraryLock(tmp_path):  # free after an orderly exit
        pass


def test_a_killed_holder_never_leaves_the_library_locked(tmp_path: Path) -> None:
    holder = start_holder(tmp_path)
    try:
        with pytest.raises(LibraryLockedError):
            LibraryLock(tmp_path).acquire()
    finally:
        kill_tree(holder)  # no chance to release anything
        for stream in (holder.stdin, holder.stdout, holder.stderr):
            if stream is not None:
                stream.close()

    with LibraryLock(tmp_path):  # the operating system freed it
        pass


def test_two_libraries_do_not_lock_each_other(tmp_path: Path) -> None:
    with LibraryLock(tmp_path / "one"), LibraryLock(tmp_path / "two"):
        pass
