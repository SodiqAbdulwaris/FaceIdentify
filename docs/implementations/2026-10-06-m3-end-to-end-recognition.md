# M3 step 13: end-to-end recognition, restart and a rebuilt index

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M3 step 13 · TST-043 (partial: perception is a planted fake)
- **Status:** done for the planted-perception slice; real-weights runs wait for issue #69
- **Commits:** PR (this change): `test(processing): end-to-end recognition across restarts`

## What changed

Test-only. `tests/integration/test_m3_end_to_end.py` drives the real pipeline through
`open_library`: `ProcessSourceUseCase` → `ProcessingScheduler` → `ExecuteProcessingJob` → FINAL →
`AcceptProcessingRunUseCase` → `IndexCoordinator` → restart → startup recovery. Only perception is
faked (a client returning planted detections and 4-d unit vectors; no weights). The story:

1. image A creates identity I1;
2. image B (a face near A) matches I1 with no new identity;
3. image C (unlike A and B) creates I2;
4. the process stops, the global index directory is deleted, and the library reopens: recovery
   rebuilds the index from SQLite (all three vectors);
5. image D (near A) matches I1 through the rebuilt index.

Final state asserted: two ACTIVE identities, evidence `IDENTITY_CREATED` ×2 and `IDENTITY_MATCHED`
×2, four ACTIVE occurrences, I1 holding A, B and D and I2 holding C, every `IndexOperation`
`APPLIED`, four vectors in the index. Image B is run three ways (crash points): fully done, accepted
but the index not applied, and executed with FINAL written but not accepted; the next start finishes
each without calling perception (the planted client's call count is unchanged across the restart).

`processing_request` moved to `tests/fixtures/processing_request.py` so the process-source and
end-to-end tests share it.

## Why

Persistence §30's acceptance checks: deleting an index and restarting rebuilds it from SQLite
vectors; a crash after FINAL completes acceptance without duplicate memory.

## Decisions

None. The vectors and thresholds are fixture values for the test, not product defaults (the
decision policy still has no shipped defaults; TST-044 is post-M3).

## Verification

- Full gate (2026-10-06): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,351 passed in 232.82s, 100% line and branch coverage**.
- Mutation: skipping recovery's acceptance of `FINALIZING` runs makes the `execute` crash-point case
  fail. The index-rebuild and "D matches I1" assertions are direct (`indexes_rebuilt`, three
  vectors back, two identities at the end).

## Open issues / follow-ups

- Real SCRFD/ArcFace weights cannot be committed or run here (issue #69); the same story with real
  models is a release-gate run, not a CI test.
- Tracker TST-043 is `IN_PROGRESS`, not `PASSING`: perception is a planted fake, and the crash
  points are simulated in-process (the pipeline stops where a crash would) rather than by killing a
  real process (`tests/recovery/test_process_kill.py` covers that for jobs and erasure only).
