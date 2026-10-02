# M3: shared-memory ownership (step 5a, TST-034)

Date: 2026-10-02. Spec: API and Contracts sections 44 to 46.

## What was built (`backend/infrastructure/resources/shared_memory.py`)
- `OwnedSegment` (created here; `write`, `view`, `copy`, `release`), `AttachedSegment` (someone else's; `view`, `copy`, `close`), and `SegmentLedger` (what a process owns, to release all of it when the peer dies or it shuts down). There is no stale-segment cleanup: on Windows there is nothing to clean, and the application is Windows-only.
- Attaching checks the real segment's size against the descriptor (`SHARED_MEMORY_INVALID` if it is smaller, `SHARED_MEMORY_UNAVAILABLE` if absent), and closes the handle it opened before refusing.

## The finding that shaped the design
Closing a segment under a live NumPy array raises nothing, and touching the array afterwards crashes the interpreter (exit code 139 in a probe). So the first design (an `.array` property, with `BufferError` expected on release) was wrong and was replaced: access is through `view()`, a context manager that counts open views, and a segment with an open view refuses to be released or closed. A view must not be kept past its `with` block; that is the one rule a caller has to follow. Recorded as a dated note in API and Contracts section 45.

## Windows semantics the tests rely on
A segment lives until its last handle is closed and `unlink` does nothing. So: the creator releases after the terminal response, a receiver always closes its own handle, and a killed process frees what it held. Tested with real child processes: a child reads the parent's segment; a reader killed mid-read does not harm the owner; an output made by a child is read, then released by its creator on request; a creator killed without releasing leaves a segment that is freed once the receiver's handle is closed (and data copied earlier survives).

## Verification
35 tests, backend coverage 100%, 26 mutations caught. Not observable on Windows, so not mutation-tested: the `unlink` call itself (a no-op here); that only the creator calls it is tested with a spy.

## Review
OpenCode (`opencode/big-pickle`, plan agent; the first run stopped without a verdict after being refused a read outside the repository, so it was repeated with the standard-library behaviour spelled out). No blocker. Fixed: the view count was not thread-safe and was incremented after the array was built (it is now counted in first, under a lock; a test releases from inside the gap); a failing `close()` no longer marks the segment closed; the context-manager exits no longer replace an error already in flight with "a view is still open"; names without our prefix are refused before they are opened; `cleanup_stale` (no caller, unobservable on Windows) was deleted; the receiver-never-unlinks rule and "allocates nothing" are now tested with spies. Documented, not enforced: a retained view or slice still dangles after a release (tracking arrays would refuse a release whenever the `as` variable of a finished `with` is still in scope), `readonly` is advisory, an owner's `size_bytes` is the OS-rounded size, and there should be one ledger per process.
