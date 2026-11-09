# M6 step 1: reprocessing images, spec proposal
- **Date:** 2026-10-22
- **Milestone / tracker IDs:** M6 step 1, issue #180; TST-061, TST-064, TST-067 (image halves)
- **Status:** done; documentation only (no code, threshold, policy, model or dependency changed); spec text approved by the owner on 2026-11-09 (D1)
- **Commits:** PR #229: `docs(specs): propose reprocessing generations and supersession`, `docs: address review of the reprocessing spec proposal`, `docs(specs): record the owner's approval of the reprocessing text`, `docs: record the approval in the plan and status pages`

## What changed

Spec text proposed on 2026-10-22 and approved on 2026-11-09 (each note now a dated owner decision): persistence 4.2, 5, 6.2, 10, 11, new 12.1, 20 and 28; API 5.4; identity model new 60.1; one cross-reference each in the ERD and the processing spec. Outline of revision `0011`, the use cases and the seven acceptance tests: `docs/plans/M6_STEP1_REPROCESS_PLAN.md`. `.agents/CONTEXT.md` and `PROJECT_STATUS.md` say the text is approved and phase 2 has started. The approval commit also moves the headings of persistence section 13 and identity-model section 61 back above their own text (the new sections 12.1 and 60.1 had been inserted below them).

## Why

Issue #180 locked the design (2026-10-14) and decision D1 requires the exact spec text to be approved before code.

## Decisions

> **Decision 2026-11-09 (owner, on PR #229):** "accept all 11 and i'll leave the rest of the decisions entirely to you". The spec text is approved and all eleven open questions are answered as recommended (listed in `docs/plans/M6_STEP1_REPROCESS_PLAN.md`); later design choices are delegated to the agent.

## Verification

Documentation only: CRLF preserved, `git diff --check`. Independent read-only Codex review of the spec text (five findings, all addressed in this PR); a fresh read-only review of the final head is posted on PR #229.

## Open issues / follow-ups

Phase 2 (code) follows in separate PRs, tracked in the step plan.
