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
| 2026-09-24 | [M1 PR 7: property-based operation-sequence invariants](2026-09-24-m1-property-based-invariants.md) | done; M1 complete |
| 2026-09-24 | [M2: Alembic and the initial migration](2026-09-24-m2-alembic-initial-migration.md) | done; TST-032 in progress |
| 2026-09-24 | [M2: SQLite WAL behaviour and optimistic concurrency](2026-09-24-m2-sqlite-wal-and-concurrency.md) | done |
| 2026-09-25 | [M2: use-case transaction rollback](2026-09-25-m2-use-case-transaction-rollback.md) | done |
| 2026-09-25 | [M2: Storage Manager, managed core](2026-09-25-m2-storage-manager-managed-core.md) | done; TST-025 in progress |
| 2026-09-30 | [M2: Storage Manager, referenced artifacts](2026-09-30-m2-storage-referenced-artifacts.md) | partial; TST-025 in progress |
| 2026-09-30 | [M2: Storage Manager, relinking](2026-09-30-m2-storage-relinking.md) | partial; TST-025 in progress |
| 2026-09-30 | [M2: Storage Manager, temporary workspaces](2026-09-30-m2-storage-temporary-workspaces.md) | partial; TST-025 in progress |
| 2026-09-30 | [M2: Source recycle and restore](2026-09-30-m2-source-recycle-restore.md) | partial; TST-025 in progress |
| 2026-09-30 | [Reviewer CLI probe results](2026-09-30-reviewer-probe-results.md) | done; none newly approved |
| 2026-09-30 | [M2: Storage Manager, conservative cleanup](2026-09-30-m2-storage-conservative-cleanup.md) | partial; TST-025 in progress |
| 2026-09-30 | [M2: Storage Manager, storage usage](2026-09-30-m2-storage-usage.md) | done; TST-025 complete |
| 2026-09-30 | [M2: the per-space USearch index](2026-09-30-m2-usearch-representation-index.md) | done; TST-027 |
| 2026-09-30 | [M2: the IndexCoordinator](2026-09-30-m2-index-coordinator.md) | done; TST-028 |
| 2026-09-30 | [M2: startup recovery](2026-09-30-m2-startup-recovery.md) | partial; TST-030 in progress |
| 2026-10-01 | [M2: cross-storage failures](2026-10-01-m2-cross-storage-failures.md) | done; TST-029 |
| 2026-10-01 | [M2: Job repository](2026-10-01-m2-job-repository.md) | partial; TST-022 in progress |
| 2026-10-01 | [M2: segment and checkpoint repositories](2026-10-01-m2-segment-checkpoint-repositories.md) | partial; TST-022 in progress |
| 2026-10-01 | [M2: IndexOperation repository](2026-10-01-m2-index-operation-repository.md) | partial; TST-022 in progress; open question 27 |
| 2026-10-01 | [Decide Q25 and Q26: erasure and recovery](2026-10-01-decide-q25-q26-erasure-and-recovery.md) | done (documents); issues #29-#41 |
