# M6 step 1: reprocessing schema (revision 0011)

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 1, issue #180; groundwork for TST-061, TST-064, TST-067 (no row changes yet)
- **Status:** done (schema only; the reprocess use case, activation and UI follow in later PRs)
- **Commits:** PR (number recorded when merged): `feat(db): add reprocessing generations in revision 0011`, `docs: record the reprocessing schema`

## What changed

- `backend/alembic/versions/0011_reprocessing_generations.py`: `processing_runs.supersedes_run_id` (nullable self-FK, `RESTRICT`, `CHECK != id`) with the partial unique index `uq_processing_runs_one_completed_superseder` (`WHERE state = 'COMPLETED'`); nullable `superseded_at` on `observations`, `representations` and `occurrences`, each with `ck_<table>_superseded_has_time` (`SUPERSEDED` needs it; an observation also needs `superseded_by_run_id`); the `evidence.kind` CHECK gains `REPROCESS_DECISION_CARRIED_OVER` and `REPROCESS_REVIEW_REQUIRED`. The five tables are rebuilt from frozen definitions (batch mode). Downgrade restores the earlier shape, guarded like every destructive downgrade.
- Models: `ProcessingRun.supersedes_run_id`, the three `superseded_at` columns and CHECKs, the two `EvidenceKind` values.
- `ObservationRepository.transition` (with `now`), `RepresentationRepository.transition` and `OccurrenceRepository.transition` stamp `superseded_at` on becoming `SUPERSEDED`.
- Tests: `tests/integration/test_migration_0011.py` (a populated 0010 library keeps every row; each new rule refuses a violating row; a predecessor may have several unfinished successors; downgrade on empty and populated libraries; a reprocessing Evidence row stops a forced downgrade; offline SQL). Fixtures that make rows `SUPERSEDED` now give them `superseded_at`; the spec value-set and foreign-key tests list the additions; three older-revision tests that wrote through the current models now check their rules after migrating on to head.

## Why

Persistence 12.1 item 1 and sections 5, 6.2, 10 and 11, approved on 2026-11-09 (PR #229, D1).

## Decisions

> **Decision 2026-11-10 (delegated decision):** the snapshot delete trigger names `processing_runs`, so SQLite refuses to rename the rebuilt table into place while it exists; revision 0011 drops it for the rebuild and recreates it byte-identical (the migration tests compare it with `create_all`).

> **Decision 2026-11-10 (delegated decision):** the test factory defaults `superseded_at` (and, for an observation, `superseded_by_run_id` to the row's own run) when a test asks for a `SUPERSEDED` row; a test that wants either missing passes `None` explicitly. Production code never relies on this.

## Verification

Full backend gate, run 2026-11-10 on this branch (before the review's three small follow-ups, which add two assertions and fix one status phrase): `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy --platform linux && uv run pytest -q --cov`: all clean, 3253 passed, 3 deselected, backend coverage 100% (10908 statements, 2240 branches, none missed). After the follow-ups the two touched test files were rerun and pass. Independent read-only Codex review posted on the PR (three minor findings, all fixed). No frontend change.

## Open issues / follow-ups

The reprocess use case, activation transaction, API route and Reprocess control are the next PRs (`docs/plans/M6_STEP1_REPROCESS_PLAN.md`). The empty folder `.claude/worktrees/reprocess-images-fbcef7` is left behind (another process holds it open); git no longer tracks it.
