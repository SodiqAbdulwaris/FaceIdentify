# Test fix: `break_run` no longer races the index pass for the database lock

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** test infrastructure; follow-up to PR 210 (issue #179)
- **Status:** done; test-only
- **Commits:** PR (number recorded when merged): `test: drain the index pass before breaking a run`

## What changed

`tests/integration/test_api_processing_routes.py` `finished()` runs one index-coordinator pass once
the run reaches the awaited state, so a test's own write right after it never waits behind the index
pass acceptance wakes. (First done in `break_run`; the review found three more direct writes after
`finished()` with the same exposure, so the fix moved to the helper every such test goes through.)

## Why

`test_retrying_a_run_verifies_its_missing_original_first` (PR 210) failed on CI with `database is
locked` (run 38875738928, on a docs-only PR): a run reads `COMPLETED` as soon as acceptance commits,
and acceptance then wakes an index pass that writes on the scheduler thread; the test's direct write
right after `finished` waited behind it until SQLite's busy timeout. The same cause as PR 198's
face-search flake. Fixed once in `finished()`, which every such test calls, not in each test.

## Verification

- `uv run pytest -q tests/integration/test_api_source_recheck.py
  tests/integration/test_api_processing_routes.py`, three runs: 37 passed each time; the whole
  suite with the final change: 3,105 passed, 3 deselected. The CI failure
  was not reproduced locally; the mechanism is the one recorded in the 2026-10-15 face-search entry.
