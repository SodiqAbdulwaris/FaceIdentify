"""An exclusive, library-lifetime lock (CONTEXT open question 23, decided 2026-10-01 by the owner).

A library on a shared or removable drive could be opened by two backends at once, and recovery of
the second would then mark the first one's live `PENDING` artifact `MISSING`. So the backend takes
an exclusive lock on `<library>/database/.lock` for its whole life, after the library root is
resolved and before migrations, recovery, workers or any other mutation; if another live process
holds it, startup for that library fails (`LibraryLockedError`) and never falls back to another
library.

It is an *operating-system* lock on an open file (`msvcrt.locking` on Windows, `flock` elsewhere),
not the existence of a file, so it is released when the process ends however it ends: a crash or a
kill never leaves the library locked. The file itself is left in place (deleting it would race a
second opener). Orderly shutdown calls `release`.

Scope: the lock protects against a second *backend* opening the library. It does not stop a person
or another program from editing the files, and a network share whose server does not honour
byte-range locks gives no protection (a limit of the platform, not of this module).
"""

import sys
from pathlib import Path
from types import TracebackType
from typing import IO, Self

LOCK_FILE_NAME = ".lock"


class LibraryLockedError(RuntimeError):
    """Another live process holds this library."""


class LibraryLock:
    """Hold the lock with `with LibraryLock(root):` or `acquire()` / `release()`. Not reentrant: a
    second lock on the same library, even in this process, fails."""

    def __init__(self, library_root: Path) -> None:
        self.path = library_root / "database" / LOCK_FILE_NAME
        self._file: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._file is not None

    def acquire(self) -> None:
        """Take the lock or raise `LibraryLockedError`. The `database` folder is created if it is
        missing: the lock file must live somewhere before the layout exists."""
        if self._file is not None:
            raise LibraryLockedError(
                f"this process already holds the library {self.path.parent.parent}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            _lock(handle)
        except OSError as error:
            handle.close()
            raise LibraryLockedError(
                f"the library {self.path.parent.parent} is open in another FaceIdentify process"
                " (or on another computer); close it first"
            ) from error
        self._file = handle

    def release(self) -> None:
        """Release the lock. Safe to call twice."""
        handle, self._file = self._file, None
        if handle is not None:
            handle.close()  # closing the file releases the operating-system lock

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

else:  # pragma: no cover - the suite runs on Windows; this keeps the module importable elsewhere
    import fcntl

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
