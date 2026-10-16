# The overnight run report of 2026-10-16

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** none (a report)
- **Status:** done; documentation only
- **Commits:** PR (number recorded when merged): `docs: report the overnight run of 2026-10-16`

## What changed

- `docs/plans/OVERNIGHT_RUN_2026-10-16.md` (new): what the overnight run planned and did, the PRs
  merged and open, the decisions taken on the owner's behalf, and what was not done.
- `docs/implementations/2026-10-16-m5-weights-provenance-and-install-guide.md`: its note that the
  policy backup held the matching policy is corrected (it was read mid-install; the backup holds
  `buffalo-l-abstain-only-v1`).
- `.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md`, this entry and its README row.

## Why

The overnight instructions asked for a morning report through a small docs PR.

## Verification

- Merged PRs and their subjects checked against `gh pr view` and `git log origin/main`; open PRs'
  reasons against their review comments; the policy files read at 08:50 (local, Git-ignored).
- Not verified by this report: the night's numbers beyond their own entries (DirectML, coverage),
  which are recorded and verified in those entries.
