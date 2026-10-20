# M5 close-out step 5: reconcile the status documents and issues

- **Date:** 2026-10-20
- **Milestone / tracker IDs:** M5 close-out step 5; TST-031, TST-032 (and the M5 rows re-checked: TST-054, TST-055, TST-056, TST-057A/B, TST-058, TST-059, SEC-006, TST-038/039, TST-044)
- **Status:** done; documentation only (no code, threshold, policy, model or spec changed). M5 is **not** declared complete.
- **Commits:** PR (number recorded when merged): `docs:` commits on `docs/m5-reconcile`

## What changed

`.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md`, `docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`,
`docs/plans/M5_PLAN.md`, `M5_REMAINING_WORK.md`, `M5_DOD_AUDIT.md`, `M5_CLOSEOUT_PLAN.md` and the
implementation log README now agree with what is merged (PRs 213, 219, 222, 223, 224; main `dc93779`).
Only demonstrably stale claims were changed; dated decisions and reports (`OVERNIGHT_RUN_*.md`, the
2026-10-15 "Next steps" list, the M5 plan's dated decision notes) are untouched.

- **Stale claims removed:** "step 4 not yet applied" and "Next: step 5" (CONTEXT); "Next is M5" and
  `M3 remaining | Blocked on weights` (status page: the weights were chosen and #69 is closed);
  "TST-057B ... owed / blocked" in `M5_REMAINING_WORK.md` item 8; the strikethrough issue rows that
  said "closes when its PR merges" (#177, #178, #179, #182 are closed; #188 too); "PR to be recorded"
  in the two 2026-10-20 entries and their README rows (PRs 224 and 223).
- **`M5_DOD_AUDIT.md`:** the 2026-10-16 table stays; a dated update gives each criterion's current
  verdict. Criteria 15 and 17 (full gate, CI on `main`) are left to the separate full-gate run.

## Tracker rows re-checked against `M5_PLAN.md` section 5

TST-054 (with its end-to-end test, PR 224), TST-055, TST-056, TST-057A, TST-057B, TST-058, TST-059
(4a, 4b, 4c), SEC-006, TST-038/039 and TST-044 are all `PASSING` with cited evidence; no status
changed for them. `TST-044` stays "reproducible on the owner's machine" as its entry says.

## TST-031 and TST-032

Both were `IN_PROGRESS` from 2026-10-01 and 2026-10-03. Verdict: **stale, now `PASSING`.** Re-run
2026-10-20 on main `dc93779` (`uv run pytest ... --no-cov`):

- TST-031 (erasure): `test_representation_erasure.py` 38, `test_sqlite_erasure_policy.py` 4,
  `test_forget_identity.py` 28, `test_permanent_source_delete.py` 37 and `test_index_coordinator.py`:
  passed. Its only "Remaining" item (source deletion, Recycle Bin cleanup, identity forget) is built
  and calls `RepresentationEraser` (`backend/app/sources/permanent_delete.py`, `backend/app/identities/forget.py`).
- TST-032 (migrations): `test_migrations.py` 12, `test_downgrade_guard.py` 39 and
  `test_migration_0002` to `_0010` (11, 13, 7, 13, 3, 6, 3, 5, 8): passed; the row's text had stopped
  at revision `0005`.

## Open issues, each with a current reason (status page, known-gaps table)

#174 (network roots not built; refusing by default is owner-confirmed), #175 (M6 step 2's remaining
tests), #176 (PDF query needs a product decision; not needed for M5), #180 and #221 (M6), #181
(evaluation-tool improvement, no M5 criterion), #183 (M8 release blocker), #66 (below).

## Issue #66 verdict: done as scoped (recommended close)

The issue asked for the IndexCoordinator, the RepresentationEraser and recovery on `UnitOfWork`.
Checked in the code: every write in `backend/app/memory/index_coordinator.py` (`self._uow.write`,
lines 296 and 494), `backend/app/memory/erasure.py` (lines 154, 347, 411) and
`backend/app/recovery/startup.py` (`accept_finalizing_runs`, `interrupt_in_flight_work`, `run_state`
take a `UnitOfWork`) goes through it; the remaining `self._sessions()` blocks in the first two are reads.
Landed in PR 105 (coordinator) and PR 113 (eraser, recovery), per the issue's own comments. Deliberately
left on plain sessions by the owner's 2026-10-06 decision: `recover_artifacts`
(`backend/app/sources/artifact_storage.py`), `mark_missing_managed_files` and
`mark_missing_referenced_originals` (`backend/app/sources/referenced_artifacts.py`), which interleave file
effects and run single-process at startup. No issue was closed by this change.

## Recommended closes (for the owner; none done here)

#66 (done as scoped). Keep open: #174, #175, #176, #180, #181, #183, #221.

## Noted, not changed

Tracker rows "M3 step 10", "(step 4a)" and "(step 4b)" are still `IN_PROGRESS` with "remaining"
text from 2026-10-03 to 2026-10-06 although M3 is recorded as done; they were outside the task's
named rows and have no re-run evidence here. Follow-up: review them the way TST-031 and TST-032 were.

## Verification

Test counts above come from the commands run in this session. The edits were checked with `git diff`
(CRLF preserved) and the checks listed in the PR.
