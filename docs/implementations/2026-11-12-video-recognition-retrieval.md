# Fix: recognising a video's faces without quadratic work

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M6 step 8 (D8, the real-world check), which found it
- **Status:** done
- **Commits:** PR #252: `perf(processing): recognise a video's faces without quadratic work`

## What changed

- `retrieve` (`backend/app/recognition/retrieval.py`) asks each pool for `k` candidates and, only
  while the excluded representations leave it short of `k`, asks again for twice as many (never
  more than `k` plus every excluded one, `_enough`). Before, it always asked for
  `k + len(exclude)`.
- `_decide` (`backend/app/processing/execute_job.py`) builds no run-local index for a video, and
  builds the exclusion set once per run instead of once per face.

## Why

A video excludes every one of its own faces from each face's candidates. With 7,264 kept faces
(the first episode of the D8 sample), every face asked the global index for 7,269 neighbours and
rebuilt a run-local index holding only excluded faces: the recognition phase ran for more than
17 minutes without finishing. With the change it takes 13 to 37 s on the same run (CPU, a machine
shared with other sessions).

The nearest usable candidates are the same as one ask for the full count would give: the fetch
only grows while too few usable ones remain, stops when the pool returns fewer than asked, and is
capped at the old size. A run-local index for a video could only hold excluded faces, so skipping
it changes no decision; the track rule (D7) and "a video never creates an identity" are untouched.

## Verification

- `tests/unit/test_retrieval_fetch.py` (three tests on `_enough`: enough at once, growing while
  short, stopping when the pool runs out).
- `test_a_video_never_builds_a_run_local_index` (`tests/integration/test_execute_video_job.py`),
  added after the review: it fails if the VIDEO skip is removed (checked by mutation).
- Video executor, occurrence and retrieval tests: 48 passed; ruff clean. CI on the exact head.
- Review: Codex, read-only, found no correctness defect; it asked for the test above and this entry.
