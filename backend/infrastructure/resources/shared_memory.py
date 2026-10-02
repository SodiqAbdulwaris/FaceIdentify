"""Shared-memory segments for the ML worker: who creates, who reads, who releases
(API and Contracts.md sections 44 to 46).

The rule is that the creator owns the lifetime. FastAPI creates the segments that carry an image
into the worker and releases them after the terminal response; the worker creates the segments
that carry an embedding out and unlinks them when told (RELEASE_OUTPUT). The receiver of a
segment attaches, copies what it needs and closes its own handle; it never releases a segment it
did not create. Shared memory is never authoritative: if everything is lost, nothing is.

On Windows a segment lives until the last handle to it is closed and `unlink` does nothing, so a
process that dies releases everything it held without anyone's help, and there are no stale
segments to clean up after a crash of the whole application. On POSIX a segment is a file that
outlives its creator, which is what `unlink` and `cleanup_stale` are for.

Memory safety: closing a segment while a numpy array over it still exists is not an error that
NumPy or Python reports, and touching that array afterwards crashes the process. So no segment
hands out a long-lived array. Access is through `view()`, a context manager that counts live
views (a segment with one cannot be released or closed), `copy()` and `write()`. A view must not
be kept past its `with` block.

A descriptor is self-consistent but does not say where the real segment ends, so `attach` checks
the size of the segment it actually opened before anyone reads through the descriptor.
"""

import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from multiprocessing import shared_memory
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor, describe

NAME_PREFIX = "faceidentify-"


class SegmentInUseError(RuntimeError):
    """A segment cannot be released or closed while a view of it is open."""


class _Segment:
    """What owned and attached segments share: a handle, a descriptor, a count of open views."""

    def __init__(
        self,
        segment: shared_memory.SharedMemory,
        descriptor: SharedMemoryDescriptor,
        *,
        writable: bool,
    ) -> None:
        self._segment: shared_memory.SharedMemory | None = segment
        self.descriptor = descriptor
        self._writable = writable
        self._views = 0

    @property
    def closed(self) -> bool:
        return self._segment is None

    @contextmanager
    def view(self) -> Iterator[np.ndarray[Any, Any]]:
        """The segment's memory as an array, valid only inside the `with` block."""
        if self._segment is None:
            raise ValueError("the segment has been closed")
        array: np.ndarray[Any, Any] = np.ndarray(
            self.descriptor.shape, dtype=self.descriptor.dtype, buffer=self._segment.buf
        )
        array.flags.writeable = self._writable
        self._views += 1
        try:
            yield array
        finally:
            self._views -= 1

    def copy(self) -> np.ndarray[Any, Any]:
        """The data, detached from the segment, so the handle can be closed."""
        with self.view() as array:
            return array.copy()

    def _close(self) -> shared_memory.SharedMemory | None:
        """Close this process's handle (idempotent); returns the handle it closed, if any."""
        if self._segment is None:
            return None
        if self._views:
            raise SegmentInUseError("a view of the segment is still open")
        segment, self._segment = self._segment, None
        segment.close()
        return segment


class OwnedSegment(_Segment):
    """A segment this process created and must release. The owner may always write."""

    def __init__(
        self,
        dtype: str,
        shape: tuple[int, ...],
        *,
        new_id: Callable[[], uuid.UUID],
        readonly: bool = True,
    ) -> None:
        # Describe first: it validates the shape, so nothing is allocated for a bad request.
        probe = describe("probe", dtype, shape, readonly=readonly)
        segment = shared_memory.SharedMemory(
            name=f"{NAME_PREFIX}{new_id().hex}", create=True, size=probe.size_bytes
        )
        super().__init__(
            segment,
            describe(segment.name, dtype, shape, readonly=readonly, size_bytes=segment.size),
            writable=True,
        )
        self.name = segment.name

    def write(self, values: Any) -> None:
        with self.view() as array:
            array[...] = values

    def release(self) -> None:
        """Close and unlink. Idempotent. Raises `SegmentInUseError`, leaving the segment as it
        was, while a view is open."""
        segment = self._close()
        if segment is not None:
            try:
                segment.unlink()
            except FileNotFoundError:
                pass


class AttachedSegment(_Segment):
    """A segment someone else created, opened to read (or, if the descriptor says so, write)."""

    def __init__(self, descriptor: SharedMemoryDescriptor) -> None:
        try:
            segment = shared_memory.SharedMemory(name=descriptor.name)
        except FileNotFoundError:
            raise ContractError(
                MLErrorCode.SHARED_MEMORY_UNAVAILABLE, f"no segment named {descriptor.name!r}"
            ) from None
        if segment.size < descriptor.size_bytes:
            actual = segment.size
            segment.close()
            raise ContractError(
                MLErrorCode.SHARED_MEMORY_INVALID,
                f"segment {descriptor.name!r} holds {actual} bytes, the descriptor claims "
                f"{descriptor.size_bytes}",
            )
        super().__init__(segment, descriptor, writable=not descriptor.readonly)

    def close(self) -> None:
        """Close this process's handle. Idempotent. The receiver never unlinks."""
        self._close()

    def __enter__(self) -> "AttachedSegment":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class SegmentLedger:
    """The segments one process has created and not yet released, so it can release them all
    when its peer dies or it shuts down (the creator owns the lifetime)."""

    def __init__(self, *, new_id: Callable[[], uuid.UUID]) -> None:
        self._new_id = new_id
        self._owned: dict[str, OwnedSegment] = {}

    @property
    def names(self) -> list[str]:
        return sorted(self._owned)

    def create(self, dtype: str, shape: tuple[int, ...], *, readonly: bool = True) -> OwnedSegment:
        segment = OwnedSegment(dtype, shape, new_id=self._new_id, readonly=readonly)
        self._owned[segment.name] = segment
        return segment

    def release(self, name: str) -> bool:
        """Release one segment; False if this ledger does not own it (so a stray release request
        for someone else's segment does nothing)."""
        segment = self._owned.get(name)
        if segment is None:
            return False
        segment.release()
        del self._owned[name]
        return True

    def release_all(self) -> list[str]:
        """Release everything owned, returning the names. A segment with an open view stays
        owned and the first such error is raised after the others have been released."""
        released: list[str] = []
        failure: SegmentInUseError | None = None
        for name in list(self._owned):
            try:
                self.release(name)
            except SegmentInUseError as error:
                failure = failure or error
            else:
                released.append(name)
        if failure is not None:
            raise failure
        return released

    def __enter__(self) -> "SegmentLedger":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release_all()


def cleanup_stale() -> list[str]:
    """Remove segments left by an application that crashed, by name prefix. On Windows there is
    nothing to do: the operating system frees a segment when its last handle goes. On POSIX the
    segments are files in `/dev/shm`. Best effort, and only ever our own prefix."""
    removed: list[str] = []
    if sys.platform != "win32":  # pragma: no cover - the suite runs on Windows
        for entry in Path("/dev/shm").glob(f"{NAME_PREFIX}*"):
            try:
                entry.unlink()
            except OSError:
                continue
            removed.append(entry.name)
    return removed
