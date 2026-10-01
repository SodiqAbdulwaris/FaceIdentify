# M2: recover PAUSING and CANCELLING at startup

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-030, part); implements GitHub issue #30
- **Status:** done for `PAUSING` and `CANCELLING`; `FINALIZING`, pending output and runtime installs stay
  open for M3 (issue #34)
- **Commits:** PR (number added when opened): `feat(recovery): recover work that was being paused or
  cancelled`, `test(recovery): cover paused and cancelled work at startup`, `docs: record the
  PAUSING and CANCELLING recovery`

## What changed

`interrupt_in_flight_work` (`backend/app/recovery/startup.py`), still one transaction of guarded
`UPDATE ... RETURNING` statements, now also moves:

- a job found `PAUSING` to `PAUSED` and one found `CANCELLING` to `CANCELLED`, clearing the lease; a
  cancelled job gets `ended_at`;
- a run found `PAUSING` to `PAUSED` and one found `CANCELLING` to `CANCELLED`, bumping its revision.

`InterruptedWork` gains `jobs_paused`, `jobs_cancelled`, `runs_paused`, `runs_cancelled`;
`StartupReport.repaired_nothing` counts them. The two helpers `_move_jobs` and `_move_runs` keep the four
statements to one pattern. The module docstrings say what is and is not handled.

## Why

The owner approved CONTEXT open question 26 on 2026-10-01 (PR 42): a job or run found `PAUSING` becomes
`PAUSED` (nothing runs; the worker pausing it is gone) and one found `CANCELLING` becomes `CANCELLED` (the
user's intent). Before, recovery left both exactly as found, so a run could stay `PAUSING` forever with no
process to finish pausing it. Persistence §28 and architecture §23.2 carry the decision.

## Decisions

- **A cancelled job gets `ended_at`, a paused one does not:** cancelled is a finished state (nothing resumes
  it), paused is not. The same rule `JobRepository.transition` follows.
- **Partial output is not touched.** A cancelled run's pending observations and representations stay
  `PENDING` (tested): recovery never turns pending output into library memory (§28). Nothing in the
  recovery step deletes it either; its fate belongs to the cancellation use case.
- **The workspace follows from the state, with no new code:** a `PAUSED` job is not over, so its temp
  workspace is kept; a `CANCELLED` one is, so it is removed (both asserted).
- **A segment still `RUNNING` under a paused or cancelled run** is closed `INTERRUPTED` by the step that was
  already there, with no `ended_reason` (nothing recorded why it stopped); resuming creates a new segment.
- **A job or run is judged by its own state**, whatever the other says (tested: a `PAUSING` run with a
  `QUEUED` job, a `CANCELLING` run with a `COMPLETED` job).
- **A `PAUSING` or `CANCELLING` job is reported as moved, not as a bare lease clear:** its lease is cleared
  as it moves, so it is not in `leases_cleared`.

## Tests changed on purpose

Seven existing tests pinned the old "left exactly as found" behaviour and were updated, not weakened: the
"other states are left as they were" test no longer lists a pausing run; the stale-lease test no longer
takes `PAUSING` and `CANCELLING` (they now move; a new test covers them with each lease shape); the
workspace expectations include the paused job; and the report tests list the four new repairs. The "failure
part way rolls everything back" test now fails at each of the three run updates (RUNNING, PAUSING,
CANCELLING), not only the first.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 837 passed (8 more than the 829 before: 10 new, 6
  removed from the stale-lease parametrization, 0 regressions); `backend/` coverage 100%. The recovery
  directory was run 5 times in a row: 123 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 20 (each of the four moves removed, each
  target state changed, the `ended_at` rule removed and applied to every state, each of the two lease
  columns left uncleared, each source-state filter removed, the revision bump, each of the four
  `repaired_nothing` terms, the sorting). One survived at first (the lists were never given more than one
  row, so sorting was unobservable); a test now stores rows in descending id order.
- **Not verified:** a real process killed while pausing or cancelling (process-level kill tests wait for
  the backend process, issue #33).

## Open issues / follow-ups

- Issue #34 (M3): `FINALIZING` runs, a run with pending output and no final checkpoint, interrupted
  runtime installations.
- Issue #33: lifespan wiring and process-level kill tests.
