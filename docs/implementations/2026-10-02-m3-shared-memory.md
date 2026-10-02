# M3: shared-memory ownership (step 5a, TST-034)

Date: 2026-10-02. Spec: API and Contracts sections 44 to 46.

## What was built (`backend/infrastructure/resources/shared_memory.py`)
- `OwnedSegment` (created here; `write`, `view`, `copy`, `release`), `AttachedSegment` (someone else's; `view`, `copy`, `close`), `SegmentLedger` (what a process owns, to release all of it when the peer dies or it shuts down) and `cleanup_stale` (POSIX only).
- Attaching checks the real segment's size against the descriptor (`SHARED_MEMORY_INVALID` if it is smaller, `SHARED_MEMORY_UNAVAILABLE` if absent), and closes the handle it opened before refusing.

## The finding that shaped the design
Closing a segment under a live NumPy array raises nothing, and touching the array afterwards crashes the interpreter (exit code 139 in a probe). So the first design (an `.array` property, with `BufferError` expected on release) was wrong and was replaced: access is through `view()`, a context manager that counts open views, and a segment with an open view refuses to be released or closed. A view must not be kept past its `with` block; that is the one rule a caller has to follow. Recorded as a dated note in API and Contracts section 45.

## Windows semantics the tests rely on
A segment lives until its last handle is closed and `unlink` does nothing. So: the creator releases after the terminal response, a receiver always closes its own handle, and a killed process frees what it held. Tested with real child processes: a child reads the parent's segment; a reader killed mid-read does not harm the owner; an output made by a child is read, then released by its creator on request; a creator killed without releasing leaves a segment that is freed once the receiver's handle is closed (and data copied earlier survives).

## Verification
28 tests, backend coverage 100%, 19 mutations caught. Not observable on Windows, so not mutation-tested: the `unlink` call (a no-op here, needed on POSIX) and `cleanup_stale`'s POSIX branch (excluded from coverage like the other platform branches).
