# M6 step 1: reprocessing images, spec proposal
- **Date:** 2026-10-22
- **Milestone / tracker IDs:** M6 step 1, issue #180; TST-061, TST-064, TST-067 (image halves)
- **Status:** proposal; documentation only (no code, threshold, policy, model or dependency changed); spec text awaits the owner's approval (D1)
- **Commits:** PR #229 (draft), `docs:` commits on `feat/reprocess-images`

## What changed

Spec text proposed, labelled "Proposed decision 2026-10-22": persistence 4.2, 5, 6.2, 10, 11, new 12.1, 20 and 28; API 5.4; identity model new 60.1; one cross-reference each in the ERD and the processing spec. Outline of revision `0011`, the use cases and the seven acceptance tests: `docs/plans/M6_STEP1_REPROCESS_PLAN.md`. `.agents/CONTEXT.md` and `PROJECT_STATUS.md` say the step is a proposal.

## Why

Issue #180 locked the design (2026-10-14) and decision D1 requires the exact spec text to be approved before code.

## Decisions

None taken. Eleven open questions, each with a recommendation, are in the PR description.

## Verification

Documentation only: CRLF preserved, `git diff --check`. Independent read-only Codex review of the spec text (five findings, all addressed in this PR).

## Open issues / follow-ups

Phase 2 (code) starts only on the owner's approval of the text.
