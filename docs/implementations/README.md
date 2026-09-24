# Implementation log

Every implemented change gets one entry here (see `.agents/rules/documentation.md`). Entries are
the project's history of what was built, why, and how it was verified. Specs say what *should*
exist; this log says what *does*.

## Naming

`YYYY-MM-DD-short-slug.md`, dated the day the work started. For example:
`2026-09-23-m0-testing-foundation.md`.

## Template

```markdown
# <Title>

- **Date:** YYYY-MM-DD
- **Milestone / tracker IDs:** e.g. M1 · TST-011, TST-012
- **Status:** done | partial | blocked
- **Commits:** PR #<n>: `<commit subject>`, … (not SHAs: rebase merge rewrites them)

## What changed
Files and behaviour, briefly.

## Why
The requirement or spec section this implements.

## Decisions
Choices made, alternatives rejected, and anything decided by the user.

## Verification
Commands run and their actual results. Mark anything not verified.

## Open issues / follow-ups
Blocked items, spec conflicts, out-of-scope issues noticed.
```

## Entries

| Date | Entry | Status |
|---|---|---|
| 2026-09-23 | [M0 testing foundation](2026-09-23-m0-testing-foundation.md) | done; merged in PR #1 |
| 2026-09-23 | [Repository structure, agent files and scaffolding](2026-09-23-repo-structure-and-scaffolding.md) | done; merged in PR #1 |
| 2026-09-23 | [Branch workflow and main protection](2026-09-23-branch-workflow.md) | done; ruleset active |
| 2026-09-23 | [Resolve open repository decisions](2026-09-23-resolve-open-decisions.md) | done |
| 2026-09-23 | [Align specs with M1 decisions; doc-conflict rule](2026-09-23-align-specs-with-decisions.md) | done |
| 2026-09-23 | [M1 PR 1: core persistence models](2026-09-23-m1-core-persistence-models.md) | done |
| 2026-09-23 | [M1 PR 2: memory, identity and people models; shared factories](2026-09-23-m1-memory-persistence-models.md) | done |
| 2026-09-23 | [M1 PR 3: Identity Manager core](2026-09-23-m1-identity-manager-core.md) | done |
| 2026-09-24 | [M1 PR 4: corrections and rename via Person association](2026-09-24-m1-person-corrections-rename.md) | done |
| 2026-09-24 | [M1 PR 5: merge and split](2026-09-24-m1-identity-merge-split.md) | done |
| 2026-09-24 | [M1 PR 6: query-only recognition guard](2026-09-24-m1-query-only-recognition-guard.md) | done |
