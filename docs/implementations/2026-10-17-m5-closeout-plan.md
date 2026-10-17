# M5 close-out plan

- **Date:** 2026-10-17
- **Milestone / tracker IDs:** M5 · TST-054, TST-057B, TST-044, TST-038, TST-039
- **Status:** in progress
- **Commits:** pending PR

## What changed

Added the ordered M5 close-out plan in `docs/plans/M5_CLOSEOUT_PLAN.md`.

## Why

The remaining work crosses two open PRs, local-only real-model evidence, a missing correction E2E
test and tracker reconciliation. A shared order prevents a stale status update or M6 follow-up from
being mistaken for M5 completion.

## Decisions

The owner approved the plan on 2026-10-17. Existing policy, model and threshold decisions remain
unchanged.

## Verification

- Documentation links and stated PR/issue dependencies inspected against the repository and GitHub
  state on 2026-10-17.
- Independent review of PR #213 head `02921ee` found a shutdown race; it is recorded in the
  close-out plan and on the PR. No source change was made.
- No runtime, policy, model, user media or ignored local state was changed.

## Open issues / follow-ups

PR #213 needs a shutdown-drain fix before re-review. M5 is not yet complete.
