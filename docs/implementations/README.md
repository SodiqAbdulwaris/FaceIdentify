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
| 2026-10-07 | [Owner decisions on M4 and the M5 plan](2026-10-07-m4-owner-decisions-and-m5-plan.md) | done; documentation only |
| 2026-10-07 | [M4 W8: the end-to-end workflow, with a restart](2026-10-07-m4-end-to-end.md) | done; M4 definition of done met on the development profile |
| 2026-10-07 | [M4 W7.4: the people and processing screens](2026-10-07-m4-frontend-people.md) | done; W7 complete |
| 2026-10-07 | [M4 W7.3: the source screen](2026-10-07-m4-frontend-source.md) | partial; more screens follow |
| 2026-10-07 | [M4 W7.2: the library screen, import and the policy notice](2026-10-07-m4-frontend-library.md) | partial; more screens follow |
| 2026-10-07 | [M4 W7.1: the frontend foundation](2026-10-07-m4-frontend-foundation.md) | partial; screens follow |
| 2026-10-07 | [M4 W6: the Tauri shell starts, serves to and stops the backend](2026-10-07-m4-desktop-sidecar.md) | done; web view side is W7 |
| 2026-10-07 | [M4 W6 (host): stop the host by closing its standard input](2026-10-07-host-stdin-lifeline.md) | done; the shell side is next |
| 2026-10-07 | [M4: the development profile and the host's processing wiring](2026-10-07-m4-development-profile.md) | done; plan decision 1; real models still blocked |
| 2026-10-07 | [M4 W5: the generated API contract](2026-10-07-m4-api-contract.md) | done; TST-046 |
| 2026-10-07 | [M4 W4: the event connection](2026-10-07-m4-api-events.md) | done; server side; TST-049 |
| 2026-10-07 | [M4 W3.6: every run reports its policy provenance](2026-10-07-m4-api-policy-provenance.md) | done; M4 W3 complete |
| 2026-10-07 | [M4 W3.5: identities and occurrences, read-only](2026-10-07-m4-api-memory-reads.md) | partial; M4 W3 fifth part; TST-045 |
| 2026-10-07 | [M4 W3.4: cancelling a run, and reading jobs](2026-10-07-m4-api-cancel-jobs.md) | partial; M4 W3 fourth part; TST-045, TST-047 |
| 2026-10-07 | [M4 W3.3: the process command, run reads and retry](2026-10-07-m4-api-processing.md) | partial; M4 W3 third part; TST-045 |
| 2026-10-07 | [M4 W3.2: source import, list, detail and media routes](2026-10-07-m4-api-sources.md) | partial; M4 W3 second part; TST-045 |
| 2026-10-07 | [M4 W3.1: the API conventions every route inherits](2026-10-07-m4-api-conventions.md) | partial; M4 W3 first part; TST-045 |
| 2026-10-07 | [M4 W2.3: the scheduler loop and fail-closed recognition index](2026-10-07-m4-scheduler-loop.md) | done; M4 W2 complete with a fake perception provider |
| 2026-10-07 | [M4 W2.2: the processing runner](2026-10-07-m4-processing-runner.md) | done; the loop is W2.3 |
| 2026-10-07 | [M4 W2.1: revision 0007, the integer job priority rank](2026-10-07-m4-job-priority-rank.md) | done; CONTEXT Q14 built |
| 2026-10-07 | [M4 W1.2: the sidecar host](2026-10-07-m4-sidecar-host.md) | done; M4 W1 complete; TST-047/048 backend half |
| 2026-10-06 | [M4 W1.1: the API lifespan and lifecycle-backed readiness](2026-10-06-m4-api-lifespan-readiness.md) | partial; M4 W1 first part; TST-048 |
| 2026-10-06 | [M3 exit gate sweep](2026-10-06-m3-exit-gate.md) | done; docs only |
| 2026-10-06 | [M3.2: the pipeline in a real process, killed at each stage](2026-10-06-m3-pipeline-process-kill.md) | done (planted perception); TST-043 in progress |
| 2026-10-06 | [Rules: plans in docs/plans and a project status page](2026-10-06-planning-and-status-rules.md) | done; docs only |
| 2026-10-06 | [M3.1: the eraser and recovery writes on the UnitOfWork](2026-10-06-m3-erasure-recovery-unit-of-work.md) | done; issue 66 (remainder noted) |
| 2026-10-06 | [M3 and M4 completion plan](2026-10-06-m3-m4-completion-plan.md) | done; docs only |
| 2026-10-06 | [M3 step 13: end-to-end recognition, restart and a rebuilt index](2026-10-06-m3-end-to-end-recognition.md) | done (planted perception); TST-043 in progress |
| 2026-10-06 | [M3 step 12: startup recovery of FINALIZING and pre-FINAL runs](2026-10-06-m3-startup-recovery-finalizing.md) | done; TST-030; issue 34 |
| 2026-10-06 | [M3 cross-check: stale documentation resolved](2026-10-06-m3-cross-check-docs.md) | done |
| 2026-10-05 | [M3: atomic processing-run acceptance and abstention evidence](2026-10-05-m3-accept-processing-run.md) | merged in PR #106 after full gate, independent review, and exact-head CI; closed issue #104; step 11 acceptance slice |
| 2026-10-05 | [M3: IndexCoordinator write transactions use the UnitOfWork](2026-10-05-m3-index-coordinator-unit-of-work.md) | done; merged in PR #105; step 11 / issue 66 narrow slice |
| 2026-10-04 | [M4 authenticated local API bootstrap](2026-10-04-m4-api-launch-capability.md) | partial; merged in PR #103 |
| 2026-10-04 | [M3 private single-image processing execution](2026-10-04-m3-processing-execution.md) | partial; merged in PR #101 after the approved issue #102 fallback boundaries and final review/CI |
| 2026-10-04 | [M3 exact frozen-export planning](2026-10-04-m3-frozen-export-planning.md) | done; merged in PR #100 |
| 2026-10-04 | [M3 processing scheduler claim/start boundary](2026-10-04-m3-processing-scheduler.md) | partial; merged in PR #99 |
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
| 2026-10-01 | [Decide Q25 and Q26: erasure and recovery](2026-10-01-decide-q25-q26-erasure-and-recovery.md) | done (documents); issues #29-#41, #44 |
| 2026-10-01 | [Fix: settling a superseded operation](2026-10-01-fix-settle-superseded-operation.md) | done; bug fix |
| 2026-10-01 | [M2: Source repository](2026-10-01-m2-source-repository.md) | partial; TST-022 in progress |
| 2026-10-01 | [M2: recover PAUSING and CANCELLING](2026-10-01-m2-recover-pausing-cancelling.md) | done; TST-030 in progress; issue #30 |
| 2026-10-01 | [M2: the ERASING state and revision 0002](2026-10-01-m2-erasing-state-migration.md) | done; TST-032 in progress; issues #29, #35 |
| 2026-10-01 | [M2: ANN candidate revalidation](2026-10-01-m2-ann-candidate-revalidation.md) | done; issue #44; found #48 |
| 2026-10-01 | [M2: ProcessingRun and snapshot repositories](2026-10-01-m2-processing-run-repository.md) | partial; TST-022 in progress |
| 2026-10-01 | [Decide revision 0003 and the SQLite erasure policy](2026-10-01-decide-0003-and-sqlite-erasure.md) | done (documents); issues #48, #51, #52 |
| 2026-10-01 | [M2: revision 0003](2026-10-01-m2-revision-0003.md) | done; TST-032; issues #48, #51 |
| 2026-10-01 | [M2: SQLite erasure policy (pragma and checkpoint)](2026-10-01-m2-sqlite-erasure-policy.md) | partial; issue #52 |
| 2026-10-01 | [M2: representation erasure, the owed-truncation marker and erasure recovery](2026-10-01-m2-representation-erasure.md) | done; TST-031 in progress |
| 2026-10-01 | [M2: Observation and Representation repositories](2026-10-01-m2-observation-representation-repositories.md) | done; TST-022 in progress |
| 2026-10-01 | [M2: Identity, Occurrence and Evidence repositories](2026-10-01-m2-identity-occurrence-evidence-repositories.md) | done; TST-022 in progress |
| 2026-10-02 | [M2: RuntimeCatalog and Settings repositories](2026-10-02-m2-catalog-settings-repositories.md) | done; TST-022 passing |
| 2026-10-02 | [M2: refuse a destructive downgrade of a populated library](2026-10-02-m2-downgrade-guard.md) | done; issue #35 |
| 2026-10-02 | [M2: the library root and the library lock](2026-10-02-m2-library-root-and-lock.md) | done; issues #36, #39 |
| 2026-10-02 | [M2: the library lifecycle and real process-kill tests](2026-10-02-m2-library-lifecycle.md) | done; issue #33 |
| 2026-10-02 | [M2: the write unit of work](2026-10-02-m2-unit-of-work.md) | done; issue #37 |
| 2026-10-02 | [M3: planning and decisions](2026-10-02-m3-decisions.md) | done; docs only |
| 2026-10-02 | [M3: the ML worker IPC contract](2026-10-02-m3-ml-ipc-contract.md) | done; TST-033 passing |
| 2026-10-02 | [M3: the runtime package manifest](2026-10-02-m3-runtime-manifest.md) | done; step 4a |
| 2026-10-02 | [M3: the runtime package store](2026-10-02-m3-runtime-package-store.md) | done; step 4b, issue 34 in part |
| 2026-10-02 | [M3: shared-memory ownership](2026-10-02-m3-shared-memory.md) | done; TST-034 passing |
| 2026-10-02 | [M3: the ML worker loop](2026-10-02-m3-ml-worker-loop.md) | done; step 5b, first half |
| 2026-10-02 | [M3: the ML supervisor](2026-10-02-m3-ml-supervisor.md) | done; TST-035 passing |
| 2026-10-02 | [M3: decoding still images](2026-10-02-m3-image-decode.md) | done; TST-037 passing |
| 2026-10-02 | [M3: importing an image as a Source](2026-10-02-m3-import-source.md) | done; TST-036 passing |
| 2026-10-02 | [M3: the reference detector and embedder contracts](2026-10-02-m3-perception-contracts.md) | partial; step 7, first part |
| 2026-10-02 | [M3: ONNX Runtime detection and representation in the worker](2026-10-02-m3-onnx-handlers.md) | partial; step 7, second part |
| 2026-10-02 | [M3: registering an installed runtime package in the catalog](2026-10-02-m3-catalog-registration.md) | partial; step 7, third part; issue 80 first half |
| 2026-10-02 | [M3: the worker's configuration from the catalog and this machine's packages](2026-10-02-m3-worker-config.md) | partial; step 7, fourth part |
| 2026-10-02 | [Decisions: a representation space's persisted state and its component version](2026-10-02-space-state-and-provenance-decisions.md) | done |
| 2026-10-02 | [The model family leaves the representation-space identity](2026-10-02-space-identity-without-family.md) | done; provenance gap is issue 88 |
| 2026-10-03 | [Decision: output-level execution provenance (issue 88)](2026-10-03-output-provenance-decision.md) | implemented by revision `0005` and PR #96 |
| 2026-10-03 | [M3: the backend client for perception](2026-10-03-m3-perception-client.md) | partial; step 7, fifth part |
| 2026-10-03 | [M3: candidate retrieval over the global and run-local pools](2026-10-03-m3-candidate-retrieval.md) | partial; step 8; TST-040 |
| 2026-10-03 | [M3: the recognition assessment and the identity reasoner](2026-10-03-m3-recognition-assessment.md) | partial; step 9; TST-041, TST-042 |
| 2026-10-03 | [M3: revision 0005 (abstentions, output provenance, snapshot replace)](2026-10-03-m3-revision-0005.md) | partial; step 11, first part; issue 55 built |
| 2026-10-03 | [M3: readers accept an identity-less ACTIVE candidate](2026-10-03-m3-identityless-candidates.md) | done; step 11, second part |
| 2026-10-03 | [M3: the writer of a run's PENDING output](2026-10-03-m3-pending-output-writer.md) | done; step 7 complete; issue 88 |
| 2026-10-03 | [M3: durable source-processing request](2026-10-03-m3-process-source-request.md) | partial; step 10 first slice; merged in PR #97 |
