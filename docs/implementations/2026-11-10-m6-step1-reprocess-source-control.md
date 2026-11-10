# M6 step 1: the Reprocess control and review items on the source screen

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 1, issue #180 (completes the step for images); TST-050 (source screen), TST-061
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(api): show a source's current run and its review items`, `feat(frontend): add a Reprocess control and review items`, `docs: record the Reprocess control`

## What changed

- Backend reads: `SourceDetail.current_processing_run_id` (the run whose result is current); `GET /api/v1/sources/{id}/reprocess-reviews` lists the source's open `REPROCESS_REVIEW_REQUIRED` items (identity, its name if any, reason, run, time), newest first. An item is open while its identity is `ACTIVE` and no `USER_CORRECTION` on that identity came after it (persistence 10: "an unresolved review is an evidence row of the second kind with no later resolving correction on the same identity"). OpenAPI document and frontend types regenerated.
- Frontend (`frontend/src/features/source/`): the source screen offers **Process** only before a first result and **Reprocess** once there is one (not while a run is under way); a failed reprocess still offers **Try again**. `ReprocessReviews.tsx` lists "Check after reprocessing": each named or corrected face that could not be matched, with the reason in plain words and a link to the person. `useRunActions` gains `reprocess`.
- Tests: `tests/integration/test_api_reprocess.py` (the current run on the source detail; a named face not found again is listed, then answered by a correction; unknown source 404) and `SourcePage.test.tsx` (Reprocess sent instead of Process; Reprocess and Try again after a failed reprocess; nothing offered while running; the review list with reasons and links; a load failure said).

## Why

M6 step 1's last piece (`docs/plans/M6_STEP1_REPROCESS_PLAN.md`): the owner can reprocess an image and see what needs checking, on the image's own screen.

## Decisions

> **Decision 2026-11-10 (delegated decision):** review items are read per source (`GET /sources/{id}/reprocess-reviews`) and shown on the source screen; a library-wide Review Inbox stays later UI work (persistence 10). An item leaves the list when its identity is no longer `ACTIVE` or a person corrects that identity afterwards.

## Verification

Run 2026-11-10 on this change: frontend `npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build`: 211 tests passed, build succeeded. Backend `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy --platform linux && uv run pytest -q --cov`: lint and types clean, 3322 passed, 3 deselected, coverage 100% (11318 statements, 2346 branches); one unrelated test failed under the machine's load, `tests/unit/test_label_review.py::test_the_page_needs_its_token_serves_listed_photographs_and_records_decisions` (a local HTTP server in an evaluation tool, the same one that failed once in the activation PR's run), and passes on its own (21 passed).

## Open issues / follow-ups

- The video half of reprocessing comes with M6 step 7.
- Identities created automatically by a replaced generation stay listed with no faces (spec: automatic decisions are not carried); a cleanup is not built.
