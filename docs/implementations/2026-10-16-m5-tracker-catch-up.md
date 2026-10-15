# M5 tracker catch-up: TST-054, TST-058, TST-059 and SEC-006 rows from re-run evidence

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5; TST-054, TST-058, TST-059 (4a, 4b), SEC-006, TST-038/039 (writer)
- **Status:** done; tracker only
- **Commits:** PR (number recorded when merged): `docs(tracker): bring the M5 rows up to date`

## What changed

`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`, the M5 status rows, as the M5 definition-of-done audit
(`docs/plans/M5_DOD_AUDIT.md`, step 1) found them behind the implementation log:

- **TST-054** (new row) `IN_PROGRESS`: naming and corrections are built and their suites pass; the
  criterion asks for an end-to-end test and the desktop end-to-end workflow corrects nothing yet.
- **TST-058** (new row) `PASSING`: merge and split suites, plus the real-model gate's "split then
  merge restores the person" check.
- **SEC-006** (new row) `PASSING`: the byte-level deletion and forget checks.
- **TST-059 4a and 4b** `IN_PROGRESS` → `PASSING` (4c already was).
- **TST-038 / TST-039 (writer)** `BLOCKED` → `IN_PROGRESS`: its only block, issue #69, is closed; the
  real path is the next row's (still the owner's decision on local-only evidence).
- `.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md`, this entry and its README row.

## Why

The tracker is updated only with verified evidence. The work behind these rows was built and tested
in October (implementation entries linked from each row) but the rows were never added or closed, so
the M5 definition of done could not be read from the tracker.

## Decisions

- **TST-054 stays `IN_PROGRESS`:** its completion criterion is "Correction E2E", and no end-to-end
  test makes a correction. Integration and component tests are not counted as that.
- **The rows' evidence is a re-run, not a copy:** every suite cited was run again on main
  (`4e43c58`) before the status was written.

## Verification

On main `4e43c58`, 2026-10-16, `uv run pytest -q -p no:cacheprovider` on:

| Suites | Result |
|---|---|
| `test_person_use_cases.py`, `test_api_people.py`, `test_corrections.py`, `test_api_corrections.py` | 95 passed |
| `test_identity_merge_split.py`, `test_api_identity_changes.py` | 58 passed |
| `test_api_source_lifecycle.py` | 14 passed |
| `test_permanent_source_delete.py`, `test_api_source_permanent_delete.py` | 51 passed |
| `test_forget_identity.py`, `test_api_forget.py` | 32 passed |

## Open issues / follow-ups

- A correction step in `frontend/e2e/workflow.e2e.tsx` (or a backend end-to-end test) would close
  TST-054.
