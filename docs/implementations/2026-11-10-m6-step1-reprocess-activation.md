# M6 step 1: reprocessing images, request, activation and API

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 1, issue #180; TST-061, TST-064, TST-067 (image halves `PASSING`, rows `IN_PROGRESS` until video)
- **Status:** done for the backend; the Reprocess control on the source screen is the next PR
- **Commits:** PR (number recorded when merged): `feat(processing): add the reprocess face correspondence rule`, `feat(processing): reprocess images with atomic supersession`, `test: cover reprocessing end to end, including process kills`, `docs: record reprocessing activation`

## What changed

- `backend/app/processing/correspondence.py` (pure): the D3 rule of identity model 60.1 (same space, both vectors, box IoU >= 0.7, cosine >= 0.9, mutual and unique pairs) and its box-only half for erased faces.
- `process_source.py`: `ProcessSourceUseCase.reprocess` (a `REPROCESS_SOURCE` job whose run names the current generation in `supersedes_run_id`; refused before a first result and while a run is in flight); `process` is refused once a result exists. `retry.py` handles both job types and keeps `supersedes_run_id`; `scheduler.py` claims both; `execute_job.py` leaves the replaced generation's representations out of the new run's candidates; `permanent_delete.py` clears `supersedes_run_id` before deleting runs.
- `supersession.py` and `accept_run.py`: the activation branch of persistence 12.1 item 5 in the one acceptance transaction: the compare-and-swap on the current generation, supersession of V1 (states, `superseded_at`, `REMOVE` operations), carry-over of human decisions (`REPROCESS_DECISION_CARRIED_OVER`), review evidence for the rest (`REPROCESS_REVIEW_REQUIRED`), suppression of a forgotten or erased face (observation `REJECTED`, representation `ERASING` then erased after the commit), disposal of the pending identity a carried or suppressed face created, and revalidation of a completed reprocess run.
- API: `POST /api/v1/sources/{source_id}/reprocess` (202 with the run; 409 `SOURCE_STATE_CONFLICT` or `SOURCE_BUSY`); `process` on a processed source is 409 `SOURCE_ALREADY_PROCESSED`; run details include `supersedes_run_id`. The backend announces `source.updated` when a reprocess run is accepted and hands suppressed faces to the eraser. OpenAPI document and frontend types regenerated.
- Tests: issue 180's seven acceptance tests (`tests/integration/test_reprocess_images.py`, `tests/recovery/test_reprocess_process_kill.py`), `tests/unit/test_correspondence.py`; the pipeline fixture plants several faces and can reprocess; tests that processed one source repeatedly now reprocess after the first run.

## Why

Persistence 12.1, identity model 60.1 and API 5.4, approved on 2026-11-09 (PR #229, D1).

## Decisions

> **Decision 2026-11-10 (delegated decision):** a carried-over decision (`REPROCESS_DECISION_CARRIED_OVER` on the representation) counts as human-decided, so a second reprocessing carries it again.

> **Decision 2026-11-10 (delegated decision):** superseding a generation bumps the revision of each identity that owned one of its representations (a view taken before is stale); no other identity field changes.

> **Decision 2026-11-10 (delegated decision):** acceptance refuses a first run on a Source that already has a result, and a retry refuses to create one (a reprocess retry is refused unless its predecessor is still current and nothing else of the Source is in flight): either would make a second generation.

> **Decision 2026-11-10 (delegated decision):** a suppressed face's representation loses its identity link (`identity_id` NULL) and gets no evidence row; the eraser clears its vector right after the commit (and at the next start if that fails).

> **Decision 2026-11-10 (delegated decision):** persistence 12.1 item 7's pointer condition is met by the one-`ACTIVE`-generation invariant, not a second condition in revalidation (note in persistence 12.1).

## Verification

Run 2026-11-10 on this change (before the rebase over docs-only `main` commits): `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy --platform linux && uv run pytest -q --cov`: lint and types clean, 3301 passed, 3 deselected, backend coverage 100% (11258 statements, 2342 branches); one unrelated test failed in that run, `tests/unit/test_label_review.py::test_the_page_needs_its_token_serves_listed_photographs_and_records_decisions` (a local HTTP server in an evaluation tool, while other sessions ran their suites), and passes on its own (21 passed). An earlier run of the same suite hit the known shared-memory name collision (`WinError 183`) in `tests/integration/test_ml_supervisor.py` because another session ran its tests at the same time; those tests pass on their own. Frontend: `npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build`: 206 tests passed, build succeeded (only the generated API types changed). The new tests: `test_reprocess_images.py` 29, `test_reprocess_process_kill.py` 4, `test_api_reprocess.py` 4, `test_correspondence.py` 12, all passing.

## Open issues / follow-ups

- Identities created automatically by the replaced generation (never named or corrected) stay listed with no faces after reprocessing, because automatic decisions are not carried (spec).
- A library processed twice before `SOURCE_ALREADY_PROCESSED` existed may hold two `ACTIVE` generations of one Source; repairing that is not done.
- The Reprocess control and the review items on the source screen: next PR.
