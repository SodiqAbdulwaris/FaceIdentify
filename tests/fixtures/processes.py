"""Real subprocesses for the tests that must kill something (architecture 25.13).

A process that is killed gets no chance to tidy up, which is the point. On Windows the virtual
environment's `python.exe` is a launcher that starts the real interpreter as a child, so killing
only the process we started would leave the one that does the work (and holds any lock) running:
the whole tree is killed.
"""

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.infrastructure.storage.library_lock import LibraryLock, LibraryLockedError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def kill_tree(process: subprocess.Popen[str]) -> None:
    """Kill the process and everything it started; a process that is already gone is fine."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:  # pragma: no cover - the suite runs on Windows
        process.kill()
    process.wait(timeout=30)


def close_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def start_until(script: str, *arguments: str, ready: str) -> subprocess.Popen[str]:
    """Run `python -c script arguments` from the repository root and wait until it prints `ready`.
    Whatever goes wrong while starting it (a crash, a hang past 60 seconds, another first line), the
    process does not outlive the test and the failure says what it printed."""
    process = subprocess.Popen(
        [sys.executable, "-c", script, *arguments],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=REPOSITORY_ROOT,
    )  # fmt: skip
    assert process.stdout is not None
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        line = pool.submit(process.stdout.readline).result(timeout=60)
        if line.strip() != ready:
            kill_tree(process)  # (so reading what it said cannot block)
            said = process.stdout.read()  # (error output is merged into it, so nothing blocks)
            raise AssertionError(f"expected {ready!r}, got {line!r}; then: {said}")
    except BaseException:
        kill_tree(process)  # first: the reader thread is waiting on this process's output
        pool.shutdown(wait=False)
        close_streams(process)
        raise
    pool.shutdown(wait=False)
    return process


def acquire_soon(root: Path, seconds: float = 10) -> None:
    """Take and release the library lock, allowing a just-killed holder's lock a moment to go: the
    operating system releases it after `TerminateProcess`, which is not instantaneous."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with LibraryLock(root):
                return
        except LibraryLockedError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
