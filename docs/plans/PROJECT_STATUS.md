# Project status

A one-page overview: what is built, where we are, what is next. It is a map, not a log. For the
detail behind any line, follow its link into [`docs/implementations/`](../implementations/); for
the work still to come see [`M3_M4_COMPLETION_PLAN.md`](M3_M4_COMPLETION_PLAN.md) and the per-task
status in [`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md).

_Last updated: 2026-10-06. Keep this file true and short (rules:
[`documentation.md`](../../.agents/rules/documentation.md))._

**Where we are:** M0 to M3 are done as far as they can be without real face models: M3's exit gate
is met (TST-038 and TST-039 are blocked only on the weights licence, issue #69). M4
(API and desktop vertical slice) has just the authenticated API bootstrap; the frontend and the
desktop shell are placeholders. Nothing user-visible exists yet.

| Area | Status | What exists | More detail |
|---|---|---|---|
| **M0 Foundation** | Done | Repo, tooling, CI, branch rules, test harness | [M0 testing foundation](../implementations/2026-09-23-m0-testing-foundation.md), [repo structure](../implementations/2026-09-23-repo-structure-and-scaffolding.md) |
| **M1 Domain** | Done | Identity, Person, evidence, merge and split, query-only recognition guard, property tests | [identity manager core](../implementations/2026-09-23-m1-identity-manager-core.md), [merge and split](../implementations/2026-09-24-m1-identity-merge-split.md), [invariants](../implementations/2026-09-24-m1-property-based-invariants.md) |
| **M2 Persistence** | Done | SQLite schema and migrations, repositories, storage manager, USearch index and coordinator, erasure, library lock, unit of work, startup recovery | [migrations](../implementations/2026-09-24-m2-alembic-initial-migration.md), [storage](../implementations/2026-09-25-m2-storage-manager-managed-core.md), [index coordinator](../implementations/2026-09-30-m2-index-coordinator.md), [erasure](../implementations/2026-10-01-m2-representation-erasure.md), [unit of work](../implementations/2026-10-02-m2-unit-of-work.md), [library lifecycle](../implementations/2026-10-02-m2-library-lifecycle.md) |
| **M3 ML worker and runtime** | Done | ML IPC contract, shared memory, worker and supervisor, runtime packages and catalog, ONNX handlers (fixture models only) | [IPC contract](../implementations/2026-10-02-m3-ml-ipc-contract.md), [worker loop](../implementations/2026-10-02-m3-ml-worker-loop.md), [supervisor](../implementations/2026-10-02-m3-ml-supervisor.md), [runtime packages](../implementations/2026-10-02-m3-runtime-package-store.md), [catalog registration](../implementations/2026-10-02-m3-catalog-registration.md), [ONNX handlers](../implementations/2026-10-02-m3-onnx-handlers.md) |
| **M3 Image import and perception** | Done | Image decode and import, detection and embedding contracts, perception client, pending-output writer | [import](../implementations/2026-10-02-m3-import-source.md), [decode](../implementations/2026-10-02-m3-image-decode.md), [perception client](../implementations/2026-10-03-m3-perception-client.md), [pending output](../implementations/2026-10-03-m3-pending-output-writer.md) |
| **M3 Recognition** | Done | Candidate retrieval, assessment and reasoner (match, create, abstain), run-local index | [retrieval](../implementations/2026-10-03-m3-candidate-retrieval.md), [assessment and reasoner](../implementations/2026-10-03-m3-recognition-assessment.md) |
| **M3 Processing pipeline** | Done | Request, claim, private execution, atomic acceptance, startup recovery of interrupted runs, retry | [request](../implementations/2026-10-03-m3-process-source-request.md), [execution](../implementations/2026-10-04-m3-processing-execution.md), [acceptance](../implementations/2026-10-05-m3-accept-processing-run.md), [recovery](../implementations/2026-10-06-m3-startup-recovery-finalizing.md) |
| **M3 End to end** | Done with fakes | Recognise, restart, rebuilt index, recognise again, with planted perception | [end-to-end](../implementations/2026-10-06-m3-end-to-end-recognition.md) |
| **M3 remaining** | Blocked on weights | Done: eraser and recovery writes on the unit of work; the pipeline killed at each stage in a real process. Blocked: real weights and their licence (issue #69) | [unit of work](../implementations/2026-10-06-m3-erasure-recovery-unit-of-work.md), [process kill](../implementations/2026-10-06-m3-pipeline-process-kill.md), [plan, section 3](M3_M4_COMPLETION_PLAN.md) |
| **M4 API and desktop** | Started | Authenticated FastAPI bootstrap only. No host, scheduler loop, routes, frontend or desktop shell yet | [API bootstrap](../implementations/2026-10-04-m4-api-launch-capability.md), [plan, section 4](M3_M4_COMPLETION_PLAN.md) |
| **M5 to M8** | Not started | Corrections, search, movies, cameras, packaging | [tracker](TESTING_IMPLEMENTATION_TRACKER.md) |

**Not built yet (so you know what you cannot try):** no running application, no web or desktop
UI, no real face model (weights are not selected or committed), no scheduler loop, no REST or
WebSocket routes beyond the health and readiness bootstrap.

**Open decisions and blockers:** the weights licence and selection (issue #69); the decision-policy
numbers stay a labelled development profile until the evaluation baseline exists. All
recorded decisions are in [`CONTEXT.md`](../../.agents/CONTEXT.md).
