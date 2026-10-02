"""TST-034: shared-memory ownership and cleanup (API and Contracts.md sections 44 to 46).

The creator owns the lifetime, the receiver only attaches and closes its own handle, a descriptor
is checked against the real segment, nothing is closed under an open view, and a process that dies
frees what it held.
"""

import gc
import json
import subprocess
import sys
from multiprocessing import shared_memory
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from backend.infrastructure.resources import shared_memory as shm_module
from backend.infrastructure.resources.shared_memory import (
    NAME_PREFIX,
    AttachedSegment,
    OwnedSegment,
    SegmentInUseError,
    SegmentLedger,
)
from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor, describe
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.processes import close_streams, kill_tree, start_until


def gone(descriptor: SharedMemoryDescriptor) -> bool:
    try:
        AttachedSegment(descriptor).close()
    except ContractError as error:
        return error.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE
    return False


@pytest.fixture
def owned(new_id: SeededUUIDs) -> OwnedSegment:
    segment = OwnedSegment("float32", (4,), new_id=new_id)
    segment.write([1, 2, 3, 4])
    return segment


def leave_a_stray_handle_to_be_collected(owned: OwnedSegment) -> None:
    """What an earlier test leaves behind: another handle to a segment of the same (seeded) name,
    finalised by the collector at some later moment. `SharedMemory.__del__` calls `close()`, so a
    test that patches `close` for the whole class sees that call too; this makes it happen now."""
    stray = shared_memory.SharedMemory(name=owned.name)
    del stray
    gc.collect()


# --- one process ---------------------------------------------------------------------------------


def test_what_the_owner_writes_the_receiver_reads(owned: OwnedSegment) -> None:
    with AttachedSegment(owned.descriptor) as attached:
        assert attached.copy().tolist() == [1, 2, 3, 4]
        with attached.view() as array:
            assert array.tolist() == [1, 2, 3, 4]
    owned.release()


def test_the_bytes_in_the_segment_are_the_arrays_in_the_declared_dtype(owned: OwnedSegment) -> None:
    raw = shared_memory.SharedMemory(name=owned.name)
    try:
        assert raw.buf is not None
        assert bytes(raw.buf[:16]) == np.array([1, 2, 3, 4], dtype="float32").tobytes()
    finally:
        raw.close()
    owned.release()


def test_releasing_and_closing_close_the_handle_explicitly_not_by_garbage_collection(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[str] = []
    watched: set[int] = set()  # ids, not the handles: see below
    real = shared_memory.SharedMemory.close

    def spy(self: shared_memory.SharedMemory) -> None:
        # Only these two handles, not every handle: one left behind by an earlier test has the same
        # (seeded) name and is closed through here when the collector finalises it. They are matched
        # by id, and held by this test's own frame, never by this function's closure: a patched
        # function that is the last owner of the objects whose finaliser calls it is freed, on
        # undo, with those objects still to be finalised, and the finaliser calls a dead function.
        if id(self) in watched:
            closed.append(self.name)
        real(self)

    monkeypatch.setattr(shared_memory.SharedMemory, "close", spy)
    leave_a_stray_handle_to_be_collected(owned)  # (it closes through `spy` too)
    attached = AttachedSegment(owned.descriptor)
    handles = (attached._segment, owned._segment)  # (held by this frame: only an explicit close)
    watched.update(id(handle) for handle in handles)

    attached.close()
    owned.release()

    assert closed == [owned.name, owned.name]


def test_the_descriptor_names_a_segment_big_enough_for_the_array(owned: OwnedSegment) -> None:
    descriptor = owned.descriptor

    assert descriptor.name == owned.name
    assert descriptor.name.startswith(NAME_PREFIX)
    assert descriptor.dtype == "float32"
    assert descriptor.shape == (4,)
    assert descriptor.size_bytes >= 16
    assert descriptor.readonly is True
    owned.release()


def test_a_readonly_descriptor_gives_the_receiver_an_array_it_cannot_write(
    owned: OwnedSegment,
) -> None:
    with AttachedSegment(owned.descriptor) as attached, attached.view() as array:
        with pytest.raises(ValueError, match="read-only"):
            array[0] = 9
    assert owned.copy()[0] == 1
    owned.release()


def test_the_owner_can_write_whatever_the_descriptor_tells_the_receiver(
    owned: OwnedSegment,
) -> None:
    assert owned.descriptor.readonly is True

    owned.write([5, 6, 7, 8])

    assert owned.copy().tolist() == [5, 6, 7, 8]
    owned.release()


def test_a_writable_descriptor_lets_the_receiver_write_back(new_id: SeededUUIDs) -> None:
    segment = OwnedSegment("uint8", (2, 2, 3), new_id=new_id, readonly=False)
    segment.write(0)

    with AttachedSegment(segment.descriptor) as attached, attached.view() as array:
        array[0, 0, 0] = 7

    assert segment.copy()[0, 0, 0] == 7
    segment.release()


def test_two_segments_have_two_names(new_id: SeededUUIDs) -> None:
    first = OwnedSegment("uint8", (3,), new_id=new_id)
    second = OwnedSegment("uint8", (3,), new_id=new_id)

    assert first.name != second.name
    first.release()
    second.release()


def test_a_segment_that_does_not_exist_is_unavailable_not_invalid() -> None:
    missing = describe(f"{NAME_PREFIX}nothing-here", "uint8", (4,), readonly=True)

    with pytest.raises(ContractError) as raised:
        AttachedSegment(missing)

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE


def test_a_descriptor_that_claims_more_than_the_segment_holds_is_refused_and_closed(
    owned: OwnedSegment,
) -> None:
    claims_too_much = describe(
        owned.name, "float32", (4,), readonly=True, size_bytes=owned.descriptor.size_bytes + 10**6
    )

    with pytest.raises(ContractError) as raised:
        AttachedSegment(claims_too_much)

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID
    assert "claims" in raised.value.message
    owned.release()
    assert gone(owned.descriptor)  # the refused attach did not keep the segment alive


def test_a_released_segment_can_no_longer_be_attached_or_used(owned: OwnedSegment) -> None:
    descriptor = owned.descriptor

    owned.release()

    assert owned.closed
    assert gone(descriptor)
    with pytest.raises(ValueError, match="closed"):
        owned.copy()
    with pytest.raises(ValueError, match="closed"), owned.view():
        pass


def test_a_segment_someone_else_already_unlinked_is_still_released(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    def already_gone(self: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(shared_memory.SharedMemory, "unlink", already_gone)

    owned.release()

    assert owned.closed


def test_a_receiver_never_unlinks_what_it_closes(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    unlinked: list[str] = []
    monkeypatch.setattr(
        shared_memory.SharedMemory, "unlink", lambda self: unlinked.append(self.name)
    )

    with AttachedSegment(owned.descriptor):
        pass
    assert unlinked == []

    owned.release()
    assert unlinked == [owned.name]  # only the creator unlinks


def test_a_name_that_is_not_one_of_ours_is_refused_before_it_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        shared_memory,
        "SharedMemory",
        lambda name, **kw: opened.append(name),
    )

    with pytest.raises(ContractError) as raised:
        AttachedSegment(describe("Global\\someone-elses", "uint8", (4,), readonly=True))

    assert raised.value.code is MLErrorCode.SHARED_MEMORY_INVALID
    assert opened == []


def test_a_close_that_fails_leaves_the_segment_open_to_be_tried_again(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = shared_memory.SharedMemory.close
    attempts: list[int] = []
    handle = owned._segment  # (held by this frame until the test ends; the closure sees its id)
    handle_id = id(handle)

    def flaky(self: shared_memory.SharedMemory) -> None:
        # This handle only, not every handle: one left behind by an earlier test has the same
        # (seeded) name, and the collector closes it through here, even if closed already.
        if id(self) != handle_id:
            real(self)
            return
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("handle busy")
        real(self)

    monkeypatch.setattr(shared_memory.SharedMemory, "close", flaky)
    leave_a_stray_handle_to_be_collected(owned)  # (it closes through `flaky` too)

    with pytest.raises(OSError, match="busy"):
        owned.release()
    assert not owned.closed  # not reported released while the handle is still open

    owned.release()
    assert owned.closed


def test_a_release_cannot_slip_in_while_a_view_is_being_built(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused: list[bool] = []
    real: Any = np.ndarray

    def build_then_race(*args: object, **kwargs: object) -> object:
        try:
            owned.release()  # another thread, at the one moment between the check and the array
        except SegmentInUseError:
            refused.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(shm_module, "np", SimpleNamespace(ndarray=build_then_race))

    with owned.view():
        pass

    assert refused == [True]
    assert not owned.closed
    owned.release()


def test_a_view_that_cannot_be_built_does_not_stay_counted(
    owned: OwnedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise TypeError("cannot build")

    monkeypatch.setattr(shm_module, "np", SimpleNamespace(ndarray=fail))
    with pytest.raises(TypeError), owned.view():
        pass
    monkeypatch.undo()

    owned.release()  # nothing is left counted
    assert owned.closed


def test_a_context_manager_leaves_the_error_that_is_already_failing_to_propagate(
    new_id: SeededUUIDs, owned: OwnedSegment
) -> None:
    failure = RuntimeError("inference failed")
    attached = AttachedSegment(owned.descriptor)
    view = attached.view()
    view.__enter__()
    ledger = SegmentLedger(new_id=new_id)
    other = ledger.create("uint8", (4,))
    other_view = other.view()
    other_view.__enter__()

    # With a view still open and an error in flight, exiting says nothing (the error is the news)...
    attached.__exit__(RuntimeError, failure, None)
    ledger.__exit__(RuntimeError, failure, None)
    assert not attached.closed
    assert ledger.names == [other.name]  # ...and nothing was released from under the view

    view.__exit__(None, None, None)
    other_view.__exit__(None, None, None)
    attached.close()
    ledger.release_all()
    owned.release()


def test_a_ledger_that_ends_cleanly_over_an_open_view_says_so(new_id: SeededUUIDs) -> None:
    ledger = SegmentLedger(new_id=new_id)
    view = ledger.create("uint8", (4,)).view()
    view.__enter__()

    with pytest.raises(SegmentInUseError):
        ledger.__exit__(None, None, None)

    view.__exit__(None, None, None)
    ledger.release_all()


def test_a_context_manager_that_ends_cleanly_over_an_open_view_says_so(
    owned: OwnedSegment,
) -> None:
    attached = AttachedSegment(owned.descriptor)
    view = attached.view()
    view.__enter__()

    with pytest.raises(SegmentInUseError):
        attached.__exit__(None, None, None)

    view.__exit__(None, None, None)
    attached.close()
    owned.release()


def test_releasing_twice_is_harmless(owned: OwnedSegment) -> None:
    owned.release()
    owned.release()

    assert owned.closed


def test_a_segment_with_an_open_view_is_not_released_and_stays_usable(owned: OwnedSegment) -> None:
    with owned.view():
        with pytest.raises(SegmentInUseError):
            owned.release()
        assert not owned.closed

    assert owned.copy().tolist() == [1, 2, 3, 4]  # still usable after the refused release
    owned.release()
    assert owned.closed


def test_a_view_that_ends_by_an_error_is_still_counted_out(owned: OwnedSegment) -> None:
    with pytest.raises(RuntimeError), owned.view():
        raise RuntimeError("inference failed")

    owned.release()  # the view is over, so nothing blocks the release
    assert owned.closed


def test_nested_views_all_have_to_end_before_the_release(owned: OwnedSegment) -> None:
    with owned.view():
        with owned.view():
            pass
        with pytest.raises(SegmentInUseError):
            owned.release()

    owned.release()


def test_a_receiver_with_an_open_view_cannot_close_and_stays_usable(owned: OwnedSegment) -> None:
    attached = AttachedSegment(owned.descriptor)

    with attached.view():
        with pytest.raises(SegmentInUseError):
            attached.close()
        assert not attached.closed

    assert attached.copy().tolist() == [1, 2, 3, 4]
    attached.close()
    attached.close()  # idempotent
    with pytest.raises(ValueError, match="closed"):
        attached.copy()
    owned.release()


def test_a_copy_outlives_the_handle_it_came_from(owned: OwnedSegment) -> None:
    attached = AttachedSegment(owned.descriptor)
    data = attached.copy()
    attached.close()
    owned.release()

    assert data.tolist() == [1, 2, 3, 4]


def test_an_unsupported_dtype_or_shape_allocates_nothing(
    new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []
    real = shared_memory.SharedMemory

    def counting(*args: Any, **kwargs: Any) -> shared_memory.SharedMemory:
        created.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(shared_memory, "SharedMemory", counting)
    ledger = SegmentLedger(new_id=new_id)

    with pytest.raises(ContractError):
        ledger.create("complex128", (4,))
    with pytest.raises(ContractError):
        ledger.create("uint8", (0, 3))

    assert ledger.names == []
    assert created == []  # refused before anything was allocated


# --- the ledger ----------------------------------------------------------------------------------


def test_the_ledger_releases_what_it_owns_and_ignores_what_it_does_not(
    new_id: SeededUUIDs, owned: OwnedSegment
) -> None:
    ledger = SegmentLedger(new_id=new_id)
    first = ledger.create("uint8", (8,))
    second = ledger.create("uint8", (8,))
    assert ledger.names == sorted([first.name, second.name])

    assert ledger.release(owned.name) is False  # someone else's: untouched
    assert not owned.closed
    assert ledger.release(first.name) is True
    assert ledger.release(first.name) is False
    assert ledger.names == [second.name]
    assert gone(first.descriptor)
    ledger.release_all()
    owned.release()


def test_release_all_releases_everything_and_says_what(new_id: SeededUUIDs) -> None:
    ledger = SegmentLedger(new_id=new_id)
    segments = [ledger.create("uint8", (8,)) for _ in range(3)]

    released = ledger.release_all()

    assert released == sorted(s.name for s in segments)
    assert ledger.names == []
    assert all(gone(s.descriptor) for s in segments)
    assert ledger.release_all() == []


def test_the_ledger_releases_everything_when_its_block_ends_even_by_an_error(
    new_id: SeededUUIDs,
) -> None:
    descriptors: list[SharedMemoryDescriptor] = []

    def die_inside_the_block() -> None:
        with SegmentLedger(new_id=new_id) as ledger:
            descriptors.append(ledger.create("uint8", (8,)).descriptor)
            descriptors.append(ledger.create("uint8", (8,)).descriptor)
            raise RuntimeError("the worker died")

    with pytest.raises(RuntimeError):
        die_inside_the_block()

    assert len(descriptors) == 2
    assert all(gone(d) for d in descriptors)


def test_one_segment_in_use_does_not_stop_the_others_being_released(new_id: SeededUUIDs) -> None:
    ledger = SegmentLedger(new_id=new_id)
    busy = ledger.create("uint8", (8,))
    free = ledger.create("uint8", (8,))

    with busy.view(), pytest.raises(SegmentInUseError):
        ledger.release_all()

    assert ledger.names == [busy.name]  # still owned, still to be released
    assert gone(free.descriptor)
    assert ledger.release_all() == [busy.name]


# --- two processes -------------------------------------------------------------------------------

READER = """
import json, sys
from backend.infrastructure.resources.shared_memory import AttachedSegment
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor
descriptor = SharedMemoryDescriptor.from_wire(json.loads(sys.argv[1]))
attached = AttachedSegment(descriptor)
print("READY", flush=True)
print(float(attached.copy().sum()), flush=True)
sys.stdin.readline()
attached.close()
"""

CREATOR = """
import json, sys, uuid
from backend.infrastructure.resources.shared_memory import OwnedSegment
segment = OwnedSegment("float32", (4,), new_id=uuid.uuid4)
segment.write([10, 20, 30, 40])
print("READY", flush=True)
print(json.dumps(segment.descriptor.to_wire()), flush=True)
sys.stdin.readline()
segment.release()
"""


def read_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return str(process.stdout.readline()).strip()


def tell(process: subprocess.Popen[str], line: str) -> None:
    assert process.stdin is not None
    process.stdin.write(line + "\n")
    process.stdin.flush()


def test_another_process_reads_what_this_one_owns(owned: OwnedSegment) -> None:
    child = start_until(READER, json.dumps(owned.descriptor.to_wire()), ready="READY")
    try:
        assert read_line(child) == "10.0"
        tell(child, "done")
        assert child.wait(timeout=30) == 0
    finally:
        kill_tree(child)
        close_streams(child)

    assert owned.copy().tolist() == [1, 2, 3, 4]  # the reader changed nothing
    owned.release()
    assert gone(owned.descriptor)


def test_a_reader_that_dies_does_not_harm_the_owner_and_the_owner_can_still_release(
    owned: OwnedSegment,
) -> None:
    child = start_until(READER, json.dumps(owned.descriptor.to_wire()), ready="READY")
    try:
        assert read_line(child) == "10.0"
    finally:
        kill_tree(child)  # killed while still attached
        close_streams(child)

    assert owned.copy().tolist() == [1, 2, 3, 4]
    owned.release()
    assert gone(owned.descriptor)


def test_an_output_made_by_another_process_is_read_and_then_released_by_its_creator() -> None:
    child = start_until(CREATOR, ready="READY")
    try:
        descriptor = SharedMemoryDescriptor.from_wire(json.loads(read_line(child)))
        with AttachedSegment(descriptor) as attached:
            assert attached.copy().tolist() == [10, 20, 30, 40]
        tell(child, "release")  # the RELEASE_OUTPUT of the protocol
        assert child.wait(timeout=30) == 0
    finally:
        kill_tree(child)
        close_streams(child)

    assert gone(descriptor)


def test_when_the_creator_dies_what_it_made_is_freed_once_every_handle_is_closed() -> None:
    child = start_until(CREATOR, ready="READY")
    try:
        descriptor = SharedMemoryDescriptor.from_wire(json.loads(read_line(child)))
        attached = AttachedSegment(descriptor)
        data = attached.copy()
    finally:
        kill_tree(child)  # the worker crashed without releasing anything
        close_streams(child)

    assert data.tolist() == [10, 20, 30, 40]  # what was copied survives the creator
    attached.close()
    if sys.platform == "win32":
        assert gone(descriptor)  # the operating system freed it with the last handle
    else:  # pragma: no cover - the suite runs on Windows
        pytest.skip("a POSIX segment outlives its creator; this application is Windows-only")
