# M5 close-out: coverage measured and the definition of done audited

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 (plan section 5)
- **Status:** done; documentation only (no test was needed: coverage is already 100%)
- **Commits:** PR (number recorded when merged): `docs(plans): audit the M5 definition of done`

## What changed

- `docs/plans/M5_DOD_AUDIT.md` (new): each criterion of `M5_PLAN.md` section 5 as met, not met or
  owner-blocked, with its evidence, and what would close M5 in order.
- `.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md`, this entry and its README row.

## Why

The overnight run of 2026-10-16 asked for coverage to the 100% the M5 definition of done requires,
adding tests only for real gaps, and a short audit of the definition of done.

## Decisions

- **No tests were added:** the measurement found no gap.
- **The audit changes no tracker status.** Several rows lag the implementation log (TST-054,
  TST-058, SEC-006 have no status row; TST-059 4a and 4b, TST-044 and a TST-038/039 row are stale);
  closing them needs the suites re-run and quoted, which is a separate tracker PR (the audit's step 1).

## Verification

- `uv run pytest -q --cov --cov-report=term-missing:skip-covered` on main at `16323bf`: 3,081 passed,
  3 deselected (the `e2e` marker), in 10 min 48 s; `TOTAL 10435 0 2136 0 100%` (statements, missed,
  branches, partial). PRs 205 and 206 merged after it change nothing under `backend/` (checked with
  `git diff --stat 16323bf 210bcce -- backend`: empty).
- Tracker rows, issue states (#69 open, #80 and #137 closed) and the CI workflow read directly.

## Open issues / follow-ups

- The tracker PR of the audit's step 1, and the owner's steps in its step 3.
