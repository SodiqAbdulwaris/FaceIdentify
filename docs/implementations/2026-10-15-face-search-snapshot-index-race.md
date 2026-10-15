# Flaky face-search test: the index was still being saved

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 step 5b (TST-056); test-only fix, no tracker row changes
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

`tests/integration/test_api_memory.py`: `processed()` now ends with `index_caught_up()`, which runs one
`IndexCoordinator.apply_pending` pass (the backend's own `index_batch`) on a worker thread. No backend
code changed and no assertion changed.

## Why

`test_api_face_search.py::test_a_search_writes_nothing_and_repeating_it_changes_nothing` failed once on
CI (PR 197, run 38732520694; passed on re-run). Its "before" snapshot held
`indexes/<space>/manifest.json.tmp` and the old `index.<id>.usearch`; the "after" snapshot held the
finished `manifest.json` and a new index file. The search wrote nothing; the index save of the image
processed during setup overlapped the snapshot.

**Root cause.** `AcceptProcessingRunUseCase.accept` commits the run as `COMPLETED` and only then calls
`wake_index`, which runs `IndexCoordinator.apply_pending` and persists the space's index on the
scheduler thread (`backend/api/startup.py`, `_run_once_for`). The test helper `processed()` returned
as soon as `finished()` saw `COMPLETED`, so a test could act, or snapshot the files, while that save
was in flight. This is deliberate backend behaviour (SQLite is authoritative; the index is derived and
catches up), so the fix belongs in the helper's idea of "done", not in the backend.

**Why one pass is a deterministic wait.** Passes are serialized by the coordinator's lock and claim
their operations under it. If the scheduler's pass is running, the test's pass waits for it and then
finds nothing due; if it has not started, the test's pass applies and persists the operations, and the
scheduler's pass then finds nothing due and opens no index (`apply_pending` only touches spaces with
claimed operations), so it writes no file. Either way, when `processed()` returns, nothing is left to
write. No sleep, no polling, and the snapshot still covers every file, `*.tmp` and index files
included.

Fixed in the shared helper because every caller of `processed()` (directly or through
`test_api_search.face`) has the same gap; none of them depends on the index lagging. The other
file-hashing tests (`test_representation_erasure.py`, the recovery tests) drive the coordinator
synchronously and do not go through the scheduler, so they do not share the race.

## Verification

- Reproduced before the fix by temporarily delaying `wake_index` by 0.05 s and 0.1 s: the test failed
  both times (at 0.2 s and above the save fell after the second snapshot, so it passed). With the fix,
  the same delays (0, 0.05, 0.1, 0.2 and 1.0 s) all passed. The probe was removed.
- The test run 60 times in a row with the fix: 60 passed.
- Full backend gate: see the PR (ruff format, ruff check, mypy, mypy `--platform linux`, pytest).

## Open issues / follow-ups

- None.
