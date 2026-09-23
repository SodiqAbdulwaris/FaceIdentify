# FaceIdentify — Testing Strategy

**Version:** 1.0  
**Status:** Consolidated testing specification  
**Platform:** Windows desktop  
**Architecture baseline:** Implementation Architecture v1  
**Related specifications:** API & Internal Contracts; Persistence Implementation

---

## 1. Purpose

This document defines how FaceIdentify will be tested throughout development, integration, model evaluation, packaging and release.

Testing must establish that FaceIdentify:

- Preserves authoritative identity and observation data.
- Maintains consistent historical evidence.
- Handles incomplete and interrupted operations safely.
- Produces valid and measurable ML results.
- Enforces application and process boundaries.
- Protects locally stored biometric information.
- Recovers from supported failures.
- Remains usable on supported Windows hardware.

The testing strategy must not introduce new product behaviour or override established architectural contracts.

When a test conflicts with an authoritative specification, the conflict must be resolved before changing either the implementation or the test.

---

## 2. Architectural baseline

### 2.1 Locked technology stack

| Layer | Technology |
|---|---|
| Desktop shell | Tauri |
| Frontend | React, TypeScript, Vite |
| Styling | Tailwind CSS, shadcn/ui |
| Backend | Python, FastAPI |
| ORM | SQLAlchemy 2 |
| Migrations | Alembic |
| Primary database | SQLite WAL |
| Vector index | USearch |
| Production inference | ONNX Runtime |
| ML development | PyTorch |
| Media | FFmpeg, ffprobe, PyAV |
| CV utilities | OpenCV |
| Python packaging | PyInstaller baseline |

Alternatives such as PostgreSQL, FAISS, TensorRT and multiple inference workers are not part of the initial implementation.

Testing may provide evidence supporting a future migration, but must not require alternative implementations before a demonstrated need exists.

### 2.2 Process ownership

The process hierarchy is:

```text
Tauri
  └── FastAPI
       └── Persistent ML Worker
```

Tauri supervises FastAPI.

FastAPI supervises the ML worker.

The ML worker owns inference sessions and GPU resources.

The backend owns authoritative domain decisions and persistence.

Tests must verify these boundaries.

### 2.3 Authoritative and derived state

SQLite is authoritative for relational and domain state.

The filesystem stores durable artifact bytes under Storage Manager control.

USearch is a derived, rebuildable candidate-retrieval index.

ML outputs are evidence rather than authoritative identity truth.

Derived state must never override current identity assignments, corrections, deletion state or other authoritative domain information.

---

## 3. Testing principles

### 3.1 Test behaviour, not implementation details

Tests should verify public contracts, domain decisions and observable behaviour.

They should avoid unnecessary coupling to private methods, internal call ordering or incidental implementation details.

### 3.2 Use real dependencies where their behaviour matters

Use real temporary SQLite databases for database integration.

Use real USearch indexes for index integration.

Use the real Storage Manager with isolated temporary directories for filesystem integration.

Mocks and fakes are appropriate for external dependencies that are not the subject of a particular test.

### 3.3 Make tests deterministic

Control clocks, identifiers, random seeds, worker scheduling and fault-injection checkpoints where appropriate.

Avoid relying on arbitrary sleeps to coordinate concurrency tests.

GPU numerical tests may require explicitly documented tolerances rather than exact floating-point equality.

### 3.4 Separate correctness from quality

A technically correct embedding implementation is not necessarily an accurate recognition model.

Model-quality evaluation must remain separate from software-correctness tests.

Similarly, benchmarks measure performance rather than functional correctness.

### 3.5 Preserve test isolation

Every destructive test must use isolated application data.

Tests must never operate on a real user library.

---

## 4. Test suites

FaceIdentify will maintain the following logical test suites.

| Suite | Responsibility |
|---|---|
| Unit | Individual component behaviour |
| Contract | API, IPC and component interfaces |
| Property | Invariants across generated inputs and operation sequences |
| Integration | Interactions involving real dependencies |
| Recovery | Interrupted operations and restart behaviour |
| Security | Trust boundaries and data protection |
| Concurrency | Scheduling, races and resource coordination |
| E2E | Complete application workflows |
| ML evaluation | Detection, tracking, representation and recognition quality |
| Benchmarks | Performance and resource consumption |

Test suites may share fixtures and infrastructure, but their purposes must remain distinguishable.

---

## 5. Critical invariants

The following requirements are release-blocking wherever the relevant functionality is included in a release.

### ID-01: Stable identity identifiers

An identity's identifier must remain stable throughout ordinary lifecycle operations.

Renaming must not change its identifier.

### ID-02: Authoritative assignment consistency

An observation must not have conflicting authoritative identity assignments.

Historical assignments may remain available as historical evidence.

### ID-03: Correction integrity

Corrections must preserve the original observation evidence and record the authoritative change.

### ID-04: Merge and split integrity

Merge and split operations must preserve the historical relationships required by their documented contracts.

### ID-05: Uncertainty preservation

The recognition pipeline must support uncertainty without forcing every observation into an existing identity.

### ID-06: Domain authority

The ML worker, frontend and ANN index must not independently modify authoritative identity relationships.

### OBS-01: Stable observation identity

Each observation has a stable identifier.

### OBS-02: Source provenance

An observation retains the provenance needed to identify its originating source and relevant location or timestamp.

### OBS-03: Historical integrity

Corrections and later recognition decisions must not silently rewrite historical evidence.

### OBS-04: Reprocessing integrity

Retries and overlapping processing segments must not create unintended duplicate authoritative observations.

### OBS-05: Current-state search

Normal searches must reflect current authoritative relationships and applicable visibility rules.

### PER-01: Transaction atomicity

Multi-record authoritative domain operations must commit atomically.

### PER-02: Cross-storage recoverability

Incomplete filesystem or index operations must be detectable and recoverable.

### PER-03: Restart durability

Committed authoritative state must survive application restart.

### PER-04: Deletion integrity

Deletion must respect the documented ownership, retention and lifecycle rules.

### PER-05: Deletion isolation

Deleting one source or identity must not inadvertently destroy unrelated or shared data.

### PER-06: Recovery idempotence

Running recovery repeatedly must not duplicate state or compound damage.

### JOB-01: Valid job transitions

Jobs may transition only according to the documented state machine.

### JOB-02: Cancellation correctness

A cancelled job must not be reported as successfully completed.

### JOB-03: Retry correctness

Retries must not create unintended duplicate committed work.

### JOB-04: Interrupted-state recovery

Recovery must distinguish completed, incomplete and interrupted work.

### JOB-05: Failure isolation

A failed job or worker must not corrupt unrelated application state.

### SEARCH-01: Query is not ingest

Query-only recognition must not create persistent identity memory without explicit user intent.

### INDEX-01: SQLite precedes index mutation

An authoritative representation change and its durable indexing intent must commit before USearch is updated.

### INDEX-02: Rebuildability

A missing, incompatible or corrupt index must not destroy authoritative identity memory.

---

## 6. Identity and memory testing

### 6.1 Identity lifecycle

Unit and integration tests must cover:

- Identity creation.
- Observation assignment.
- Renaming.
- Correction.
- Merging.
- Splitting.
- Eligible reversal operations.
- Deletion and restoration.
- Concurrent semantic changes.

Tests must distinguish persistent visual Identity from semantic Person information.

### 6.2 Historical events

Tests must verify that historical events retain sufficient information to explain changes in authoritative relationships.

Failed operations must not be represented as successfully committed changes.

### 6.3 Property-based testing

Use Hypothesis to generate valid operation sequences involving identity creation, assignment, correction, merging and deletion.

Verify critical invariants after every operation.

Invalid-state generators should be maintained separately for negative testing.

### 6.4 Recognition boundaries

Recognition tests must distinguish:

- Technical candidate retrieval.
- Recognition assessment.
- Identity reasoning.
- Authoritative identity mutation.

The decision engine evaluates evidence.

Authoritative identity changes occur through the appropriate backend domain services.

---

## 7. Persistence testing

### 7.1 SQLite

Use isolated real SQLite databases configured according to the production contract.

Test:

- Foreign-key enforcement.
- Unique constraints.
- Check constraints.
- Transaction rollback.
- WAL behaviour.
- Concurrent connections.
- Optimistic revision checks.
- Repository queries.
- Migration compatibility.

Do not substitute an in-memory fake database for SQLite-specific integration tests.

### 7.2 Storage Manager

Use temporary filesystem roots to test:

- Managed imports.
- Referenced imports.
- Hashing.
- Artifact staging.
- Atomic finalization.
- Missing referenced files.
- Relinking.
- Temporary workspaces.
- Recycle and restoration.
- Permanent deletion.
- Orphan reconciliation.

Referenced originals must not be deleted merely because their Source records are removed.

### 7.3 USearch

Use real USearch indexes to test:

- Addition.
- Search.
- Removal.
- Persistence.
- Reloading.
- Manifest validation.
- Compatibility.
- Rebuilding.

Candidate results must be revalidated against authoritative SQLite state.

### 7.4 Durable index synchronization

Test the following sequence:

```text
SQLite transaction
  ├── Authoritative state change
  └── IndexOperation
          |
        COMMIT
          |
    IndexCoordinator
          |
        USearch
          |
    Operation settled
```

Inject failures before and after index mutation.

Verify that replay is safe even when USearch was updated immediately before a crash.

### 7.5 Recovery

Construct representative interrupted states involving:

- Running jobs.
- Active processing runs.
- Execution segments.
- Pending artifacts.
- Pending index operations.
- Abandoned temporary workspaces.
- Interrupted runtime installations.

Run recovery repeatedly and verify idempotence.

Include a smaller set of process-level tests that terminate real subprocesses.

### 7.6 Migrations

Maintain fixtures for supported schema versions.

Test migrations against populated databases containing representative relationships.

Verify data preservation, constraints, indexes and startup compatibility.

Destructive migrations require explicit backup and recovery validation.

---

## 8. ML testing and evaluation

### 8.1 Component-level evaluation

Evaluate each ML component independently before relying on complete-pipeline results.

| Component | Principal measurements |
|---|---|
| Detection | Precision, recall, localisation quality, latency |
| Tracking | Identity continuity, ID switches, fragmentation |
| Representation | Genuine/impostor separation and verification performance |
| Retrieval | Recall@K, latency, index compatibility |
| Decision engine | False identification, false rejection, abstention |
| Complete pipeline | End-to-end identity and occurrence performance |

### 8.2 Versioned datasets

Every evaluation dataset must have documented provenance, permitted usage, annotation version, split definitions and integrity checksums.

Keep synthetic infrastructure fixtures separate from real facial datasets used to measure model quality.

### 8.3 Decision-engine evaluation

The initial deterministic decision engine must satisfy the versioned evidence and decision-result contracts.

Future learned implementations must be evaluated independently before promotion.

Do not equate raw similarity scores with calibrated probabilities.

### 8.4 Runtime compatibility

Validate supported ONNX Runtime execution providers and runtime variants.

Different providers are not assumed to produce bit-identical results.

Compatibility must be established through defined numerical and behavioural tolerances.

### 8.5 Model promotion

A new ML component version must pass:

1. Interface validation.
2. Artifact-integrity verification.
3. Relevant component evaluation.
4. Regression evaluation.
5. Pipeline compatibility testing.
6. Runtime compatibility testing.
7. Rollback validation.

Model updates must not silently rewrite historical identity memory.

---

## 9. Processing and scheduling tests

### 9.1 Job lifecycle

Enforce the documented lifecycle:

```text
QUEUED → RUNNING → COMPLETED
                 → FAILED

RUNNING → PAUSING → PAUSED → QUEUED
RUNNING → CANCELLING → CANCELLED
RUNNING → crash → INTERRUPTED
```

Tests must reject invalid transitions.

### 9.2 Processing provenance

Distinguish Jobs, ProcessingRuns and ExecutionSegments.

An interrupted processing run must retain its historical execution provenance.

Resumption must not silently rewrite an earlier execution segment.

### 9.3 Media processing

Test:

- Frame timestamps.
- Variable frame rates.
- Sampling.
- Chunk boundaries.
- Overlapping segments.
- Corrupt media.
- Partial processing.
- Reprocessing.
- Cancellation.

### 9.4 Resource management

Verify:

- One active heavy movie-processing pipeline in v1.
- Bounded CPU pools.
- Bounded processing queues.
- Persistence backpressure.
- Priority scheduling.
- Adaptive inference batching.
- Safe runtime fallback.
- Appropriate camera-resource budgeting.

Use deterministic scheduling tests before introducing hardware-dependent stress tests.

### 9.5 Progress

Backend progress is authoritative.

Test determinate and indeterminate progress, stage transitions, persistence checkpoints, interrupted connections and frontend state recovery.

A completed event must not be emitted before durable completion.

---

## 10. API, frontend and desktop testing

### 10.1 FastAPI

Use pytest and HTTPX for endpoint and schema tests.

Validate requests, responses, errors, pagination and resource lifecycle operations against the authoritative API contract.

Avoid duplicating every domain unit test at the API layer.

### 10.2 Contract compatibility

Validate generated OpenAPI specifications.

Ensure generated TypeScript contracts remain synchronized with FastAPI.

### 10.3 React

Use Vitest and React Testing Library as the initial frontend testing tools.

Focus on meaningful user interactions, loading states, errors, correction workflows and state recovery.

Do not rely primarily on snapshots of UI primitives.

### 10.4 WebSocket

Test:

- Event delivery.
- Connection loss.
- Reconnection.
- Duplicate notifications.
- Missed notifications.
- Authoritative REST refetching.

WebSocket notifications must not become an independent source of domain truth.

### 10.5 Tauri

Test backend spawning, startup handshake, dynamic endpoint discovery, readiness, native operations, shutdown and backend failure handling.

Validate single-instance protection for a library.

### 10.6 E2E

The first E2E scenario is:

```text
Launch application
        ↓
Initialize backend and worker
        ↓
Import one image
        ↓
Detect faces
        ↓
Create observations
        ↓
Generate representations
        ↓
Perform recognition
        ↓
Persist identity memory
        ↓
Display results
        ↓
Close application
        ↓
Reopen application
        ↓
Verify persisted results
```

Later E2E scenarios will cover corrections, face search, cross-source recognition, movie processing, recovery, deletion and live cameras.

---

## 11. Security and privacy testing

Security tests must cover the following boundaries.

**Local API:** Loopback binding, local process isolation, input validation and destructive operations.

**Filesystem:** Path traversal, Windows junctions and symlinks, malformed media, oversized files and managed-storage boundaries.

**Biometric data:** Images, face crops, representations, historical observations, logs and diagnostic artifacts.

**Offline processing:** Core functionality must not transmit biometric data to external services without explicit authorised functionality.

**Model artifacts:** Manifest validation, checksums, compatible runtime packages and safe loading.

**Deletion:** Cleanup and recovery must respect authoritative deletion state.

Logical deletion must not be represented as guaranteed physical erasure from SSD storage.

---

## 12. Test fixtures and data management

Use deterministic factories for identities, observations, sources, jobs, events and evidence.

Maintain small synthetic media fixtures for ordinary infrastructure testing.

Maintain controlled, appropriately permissioned facial datasets for ML evaluation.

Use versioned database snapshots for migration and recovery testing.

Fault-injection fixtures must provide stable checkpoints for database, filesystem, indexing, worker and resource failures.

All test data must be isolated from actual application libraries.

Sensitive evaluation datasets must not be uploaded automatically as ordinary CI artifacts.

---

## 13. CI/CD execution policy

### Tier 0 — Static validation

Run on every pull request.

Includes formatting, linting, type checking, dependency checks and contract-generation validation.

### Tier 1 — Fast tests

Run on every pull request.

Includes unit tests, contract tests, deterministic domain tests and frontend tests.

### Tier 2 — Integration

Run on pull requests and merges.

Includes real SQLite, USearch, filesystem, API, CPU-worker and selected recovery tests.

### Tier 3 — Extended validation

Run periodically and when relevant components change.

Includes extended property-based testing, process-level recovery, concurrency stress, ML evaluation and hardware validation.

### Tier 4 — Release validation

Run against immutable release candidates.

Includes clean Windows installation, runtime installation, inference, representative E2E workflows, restart, recovery, update and uninstall validation.

Hardware-specific validation may run on trusted dedicated machines.

---

## 14. Release gates

A release is blocked by reproducible failures involving:

- Authoritative-state corruption.
- Lost or incorrectly rewritten identity corrections.
- Invalid authoritative assignments.
- Broken deletion isolation.
- Unrecoverable critical persistence operations.
- Unauthorized sensitive-data access.
- Accidental query-to-ingest mutation.
- Broken required API or IPC contracts.
- Failed clean-install startup.
- Failed required migrations.
- Required ML components failing their established acceptance criteria.

Performance thresholds and model-quality thresholds must be established using documented baselines and evaluation datasets.

Do not invent numerical acceptance thresholds without supporting measurements.

---

## 15. Update validation

Maintain independent validation for:

1. Application updates.
2. Runtime-package updates.
3. ML-component updates.

Each update domain requires compatibility, failure, rollback and recovery tests appropriate to its responsibilities.

A newly installed runtime package or ML component must not become authoritative merely because installation succeeded.

---

## 16. Implementation sequence

The recommended order is:

1. Testing foundation.
2. Identity and observation domain tests.
3. Persistence and recovery tests.
4. Single-image ML integration.
5. API and desktop integration.
6. Corrections and historical search.
7. Movie processing and scheduling.
8. Live-camera integration.
9. Extended ML evaluation.
10. Packaged release validation.

Security and contract testing begin with the components they protect rather than waiting until the final milestone.

---

## 17. Requirements traceability

Every critical invariant must map to one or more executable tests.

Each test requirement must record:

- Stable identifier.
- Responsible component.
- Test level.
- Priority.
- Dependencies.
- Execution tier.
- Implementation status.
- Applicable release gate.

A critical requirement without an executable test must remain visibly incomplete.

---

## 18. Documentation maintenance

This strategy is subordinate to the authoritative product, identity, processing, API and persistence contracts.

When an architectural contract changes:

1. Identify affected requirements.
2. Update corresponding test cases.
3. Update fixtures and compatibility expectations.
4. Run affected regression suites.
5. Record any change to release gates.

Historical regression fixtures should be retained when they represent supported compatibility requirements.

---

## 19. Outstanding implementation details

The following must be established through implementation or measurement rather than invented in this specification:

- Exact numerical ML acceptance thresholds.
- Hardware-specific performance budgets.
- Test execution-time budgets.
- Final fixture and dataset inventories.
- Supported historical migration range.
- Final CI runner configuration.
- Component-specific coverage targets.

These details must be documented before they become enforceable release requirements.

---

**End of Testing Strategy v1.0**