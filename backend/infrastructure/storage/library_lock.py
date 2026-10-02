"""An exclusive, library-lifetime lock (CONTEXT open question 23, decided 2026-10-01 by the owner).

A library on a shared or removable drive could be opened by two backends at once, and recovery of
the second would then mark the first one's live `PENDING` artifact `MISSING`. So the backend takes
an exclusive lock on `<library>/database/.lock` for its whole life, after the library root is
resolved and validated and before migrations, recovery, workers or any other mutation; if another
live process holds it, startup for that library fails (`LibraryLockedError`) and never falls back to
another library.

It is an *operating-system* lock on an open file (`msvcrt.locking` on Windows, `flock` elsewhere),
not the existence of a file, so it is released when the process ends however it ends: a crash or a
kill never leaves the library locked. `release` unlocks explicitly and then closes the file (relying
on the close alone would leave the moment of release to the operating system, and a prompt restart
could be refused); the file itself is left in place (deleting it would race a second opener).

The root is validated here too (`validate_library_root`): a lock on a typo'd path would otherwise
create a library skeleton there. Only the root's last level and its `database` folder are created.

Scope: the lock protects against a second *backend* opening the library. It does not stop a person
or another program from editing the files, and a network share whose server does not honour
byte-range locks gives no protection (a limit of the platform, not of this module). The Alembic
command line does not take it: a migration started by hand while a backend is running is not
refused (the lifecycle, issue 33, migrates under the lock).
"""

import contextlib
import errno
import sys
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from backend.infrastructure.storage.library_root import validate_library_root

LOCK_FILE_NAME = ".lock"

# What a failed non-blocking lock reports: "someone else holds it". Anything else (an invalid
# handle, an I/O error, a file system without locking) is a different problem and is not hidden
# behind this message.
_HELD_BY_SOMEONE_ELSE = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK}


class LibraryLockedError(RuntimeError):
    """Another live process holds this library."""


class LibraryLock:
    """Hold the lock with `with LibraryLock(root):` or `acquire()` / `release()`. Not reentrant: a
    second lock on the same library, even in this process, fails."""

    def __init__(self, library_root: Path) -> None:
        self.root = validate_library_root(library_root)
        self.path = self.root / "database" / LOCK_FILE_NAME
        self._file: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._file is not None

    def acquire(self) -> None:
        """Take the lock or raise `LibraryLockedError`. The root's `database` folder is created if
        it is missing: the lock file must live somewhere before the layout exists."""
        if self._file is not None:
            raise LibraryLockedError(f"this process already holds the library {self.root}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            _lock(handle)
        except OSError as error:
            handle.close()
            if error.errno not in _HELD_BY_SOMEONE_ELSE:
                raise
            raise LibraryLockedError(
                f"the library {self.root} is open in another FaceIdentify process"
                " (or on another computer); close it first"
            ) from error
        except BaseException:
            # Any other failure (an interrupt just after the lock was taken, say): do not leave the
            # lock to the garbage collector or to the operating system's own timing.
            with contextlib.suppress(OSError):
                _unlock(handle)
            handle.close()
            raise
        self._file = handle

    def release(self) -> None:
        """Release the lock. Safe to call twice."""
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _lock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # one byte, may be past the end

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - the suite runs on Windows; this keeps the module importable elsewhere
    import fcntl

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
