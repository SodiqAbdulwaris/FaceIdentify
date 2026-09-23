# Visual Identity / Face Memory — Project Plan

## 1. Purpose of This Plan

This document is the master roadmap for the local Visual Identity / Face Memory application.

It is not intended to duplicate every technical detail from the architecture documents. Instead, it answers:

- What are we building?
- What architectural decisions are already locked?
- What is intentionally still undecided?
- What documentation remains before development?
- What should be implemented first?
- In what order should the system expand?
- What must be validated before features are considered complete?
- What happens after the initial development phase?
- What should **not** be built prematurely?

The project follows a deliberate sequence:

```text
PRODUCT DEFINITION
        ↓
DOMAIN / MEMORY MODEL
        ↓
PROCESSING ARCHITECTURE
        ↓
SEARCH ARCHITECTURE
        ↓
DATA MODEL
        ↓
IMPLEMENTATION ARCHITECTURE
        ↓
API & CONTRACTS
        ↓
PERSISTENCE IMPLEMENTATION
        ↓
ML COMPONENT EVALUATION
        ↓
TESTING STRATEGY
        ↓
REPOSITORY BOOTSTRAP
        ↓
FIRST VERTICAL SLICE
        ↓
VALIDATION / HARDENING
        ↓
FEATURE EXPANSION
        ↓
PERFORMANCE OPTIMIZATION
        ↓
PACKAGING / RELEASE
        ↓
POST-RELEASE EVOLUTION
```

The key principle is:

> **Reduce feature scope before weakening architecture.**

The first implementation can be small, but it should prove the architecture we actually intend to keep.

---

# 2. Product We Are Building

The application is a completely local Windows desktop visual-memory system.

Its purpose is not merely to run face recognition.

It should be able to:

```text
observe a face
    ↓
form a durable visual Identity
    ↓
remember that Identity
    ↓
encounter the same visual subject later
    ↓
recognize that it has seen them before
    ↓
optionally associate that Identity with a named Person
    ↓
remember where and when that person appeared
```

The system eventually supports:

- images;
- movies/videos;
- multiple faces per Source;
- camera streams;
- persistent unknown identities;
- named People;
- face tracking;
- appearance history;
- face search;
- Person/name search;
- Source/movie search;
- occurrence search;
- corrections;
- merge;
- split;
- forgetting;
- reprocessing;
- model/runtime upgrades;
- feedback;
- eventual model retraining.

All biometric processing remains local.

Cloud biometric processing is not part of the architecture.

---

# 3. Hardware Target

Primary development hardware:

```text
Lenovo Legion 7i
Intel Core i9-14900HX
NVIDIA RTX 4070 Laptop GPU
32 GB RAM
~1 TB SSD
Windows
```

However, the architecture must not assume this exact machine.

Runtime execution must support validated fallback such as:

```text
CUDA
  ↓
DirectML
  ↓
CPU
```

where compatible runtime variants exist.

Hardware execution and semantic model identity remain separate concepts.

---

# 4. Core Domain Model — LOCKED

The most important conceptual distinction is:

```text
Source
   │
   ▼
Observation
   │
   ▼
Representation
   │
   ▼
Identity
   │
   ▼
Person
```

These are not interchangeable.

### Source

Media supplied to the system.

Examples:

```text
image
video
camera
```

### Observation

One detected face instance at a particular spatial/temporal location inside a Source.

### Representation

A machine-readable biometric vector generated from an Observation under a specific RepresentationSpace.

### Identity

The persistent visual subject the system believes represents the same individual across observations.

Identity exists even when the person's name is unknown.

### Person

The semantic human identity.

Example:

```text
Identity I27
        ↓
Person "John"
```

A Person may have multiple visual Identities.

An Identity does not require a Person.

This distinction is foundational and locked.

---

# 5. Memory Model — LOCKED

The application must support:

> "I've seen this visual subject before."

without requiring:

> "I know this person's name."

Therefore we do **not** create fake People such as:

```text
Unknown Person 1
Unknown Person 2
```

Unknownness is represented naturally:

```text
ACTIVE Identity
+
no active Person association
```

This allows recognition before semantic identification.

---

# 6. Observation vs Occurrence — LOCKED

Observation and Occurrence are different.

```text
Observation
= individual detected face instance

Occurrence
= meaningful appearance of an Identity within a Source
```

For an image:

```text
1 Observation
≈
1 Occurrence
```

For video:

```text
many Observations
        ↓
one tracked Occurrence
```

This distinction allows video tracking without distorting the face-detection model.

---

# 7. Query vs Ingest — LOCKED

This is a major invariant.

```text
QUERY
≠
INGEST
```

If a user uploads a face only to search for matches:

```text
face
 ↓
temporary representation
 ↓
search
 ↓
results
```

it does **not** automatically create:

```text
Source
Observation
Representation
Identity
Occurrence
Evidence
```

Persistent memory is created only through explicit ingest/persistence actions.

---

# 8. ML Is Evidence, Not Truth — LOCKED

ML does not directly mutate identity truth.

The pipeline is:

```text
ML output
    ↓
RecognitionAssessment
    ↓
IdentityReasoner
    ↓
domain decision
    ↓
authoritative persistence
```

Never:

```text
embedding model
    ↓
nearest neighbour
    ↓
UPDATE identity
```

The ML worker never decides:

```text
Person
Identity truth
merge
split
forget
```

Those belong to application/domain logic.

---

# 9. Authoritative State — LOCKED

SQLite is the sole authoritative relational state.

```text
SQLite
= truth
```

USearch is:

```text
derived ANN acceleration
```

Filesystem stores:

```text
media/artifact bytes
```

Caches and temporary structures are reconstructible.

The fundamental test is:

> If deleting it changes what the application believes happened or who it remembers, it belongs in authoritative persistence.

---

# 10. ANN Architecture — LOCKED

Canonical representation vectors are stored in SQLite.

USearch contains derived searchable copies.

```text
SQLite Representation.vector
        │
        ▼
IndexOperation
        │
        ▼
USearch
```

Destroying the entire USearch directory must **not** destroy memory.

It should be rebuildable from SQLite.

---

# 11. Representation Compatibility — LOCKED

Every vector belongs to a:

```text
RepresentationSpace
```

which defines its semantic compatibility contract.

Same:

```text
dimension
dtype
similarity metric
```

does not prove compatibility.

Two RuntimeVariants may share a RepresentationSpace only after validation.

---

# 12. Representation Storage — LOCKED

Canonical representation format:

```text
SQLite BLOB
little-endian IEEE-754
float32
contiguous 1-D
uncompressed
```

Dimension, normalization and similarity semantics come from RepresentationSpace.

Vectors are immutable.

Re-embedding creates new Representations.

---

# 13. ANN Key Strategy — LOCKED

Canonical Representation identifier:

```text
UUIDv7
```

> **Decision 2026-09-23:** identifiers are `uuid.uuid4()` stored as SQLAlchemy `Uuid` (CHAR(32)), per PERSISTENCE_IMPLEMENTATION.md §2. This supersedes UUIDv7 above.

USearch key:

```text
ann_key INTEGER
```

`ann_key` is:

```text
unique
monotonic
never intentionally reused
```

Do not hash/truncate UUIDs into ANN keys.

---

# 14. Identity Lifecycle — LOCKED

Identity states:

```text
PENDING
ACTIVE
MERGED
FORGOTTEN
```

PENDING supports processing isolation.

A ProcessingRun can build memory privately before the run is accepted.

---

# 15. Representation Lifecycle — LOCKED

```text
PENDING
ACTIVE
SUPERSEDED
INVALID
PENDING_DELETION
```

Only eligible ACTIVE representations participate in the global ANN index.

PENDING representations may participate in a run-local candidate index.

---

# 16. Processing Isolation — LOCKED

Processing output is not immediately global truth.

A run produces:

```text
PENDING Observations
PENDING Representations
PENDING Identities
PENDING Occurrences
```

After successful processing:

```text
FINAL checkpoint
        ↓
atomic acceptance transaction
        ↓
PENDING → ACTIVE
```

This prevents partially processed Sources from contaminating global memory.

---

# 17. ProcessingRun vs Job vs ExecutionSegment — LOCKED

These represent different concepts.

```text
ProcessingRun
= logical processing attempt/configuration

Job
= schedulable executable work/attempt

ExecutionSegment
= actual contiguous ML execution environment
```

Example:

```text
ProcessingRun R1
    │
    ├── Job J1
    │
    ├── CUDA Segment
    │
    └── CPU fallback Segment
```

Runtime fallback does not create a new ProcessingRun.

---

# 18. ProcessingConfigurationSnapshot — LOCKED

Every ProcessingRun receives an immutable snapshot.

It represents:

> resolved semantic configuration + requested execution preferences

It does not represent actual runtime execution.

Actual execution belongs to ExecutionSegment.

Changing Settings later never changes existing snapshots.

---

# 19. Runtime/Model Hierarchy — LOCKED

```text
Component
    ↓
ComponentVersion
    ↓
ModelExport
    ↓
RuntimeVariant
```

Alongside:

```text
RepresentationSpace
RecognitionCalibrationProfile
RuntimePackage
```

Examples:

```text
Component
FACE_EMBEDDER

ComponentVersion
specific architecture/weights/preprocessing contract

ModelExport
ONNX FP32

RuntimeVariant
ONNX FP32 + CUDA
```

---

# 20. Runtime Fallback — LOCKED

Worker fallback is never silent.

Correct:

```text
CUDA request
    ↓
failure
    ↓
MLResponse ERROR
    ↓
backend decides fallback
    ↓
close CUDA ExecutionSegment
    ↓
create DirectML/CPU ExecutionSegment
```

Changing batch size under the same RuntimeVariant does not require a new segment.

---

# 21. ML Worker Architecture — LOCKED

FastAPI owns one persistent ML worker.

```text
Tauri
  ↓
FastAPI
  ↓
MLSupervisor
  ↓
persistent Python ML worker
```

Worker communication:

```text
control
→ multiprocessing.Connection

large frames/tensors
→ multiprocessing.SharedMemory
```

Worker initially supports:

```text
DETECT_FACES
GENERATE_REPRESENTATIONS
```

It does not support domain commands like:

```text
CREATE_IDENTITY
RECOGNIZE_PERSON
MERGE_IDENTITY
REMEMBER_PERSON
```

---

# 22. Tech Stack — LOCKED

### Desktop

```text
Tauri
```

### Frontend

```text
React
TypeScript
Vite
Tailwind
shadcn/ui
TanStack Query
```

Zustand only for small cross-feature client state.

### Backend

```text
Python
FastAPI
SQLAlchemy 2
Alembic
SQLite WAL
```

### ML

```text
ONNX Runtime
CUDA
DirectML
CPU
```

PyTorch is primarily development/training.

### ANN

```text
USearch
```

### Media

```text
FFmpeg
ffprobe
PyAV
OpenCV
```

### Packaging baseline

```text
PyInstaller
```

---

# 23. Persistence Architecture — LOCKED

One SQLite database:

```text
app-data/
├── database/
│   └── memory.db
├── artifacts/
├── indexes/
├── runtimes/
├── temp/
└── logs/
```

Do not split domains into separate SQLite databases.

Cross-domain mutations require atomic transactions.

---

# 24. SQLAlchemy Strategy — LOCKED

Use synchronous SQLAlchemy 2.

Baseline:

```text
autoflush=False
expire_on_commit=False
foreign_keys=ON
journal_mode=WAL
synchronous=NORMAL
busy_timeout≈5 seconds
```

One FastAPI backend process.

Sessions are short-lived and never shared across threads/tasks.

Long ProcessingRuns do not retain Sessions.

---

# 25. Transaction Ownership — LOCKED

Use-case/application layer owns transactions.

Repositories:

```text
query
insert
update
flush
```

but normally do not:

```text
commit
```

Pattern:

```text
PREPARE
expensive ML/filesystem work
        ↓
SHORT TRANSACTION
reload/revalidate
authoritative mutation
durable follow-up intent
COMMIT
        ↓
POST-COMMIT
wake coordinators / notifications
```

---

# 26. Repository Architecture — LOCKED

No generic:

```text
BaseRepository<T>
```

Use feature-specific repositories and explicit read queries.

Examples:

```text
IdentityRepository
RepresentationRepository
CheckpointRepository
IndexOperationRepository
ArtifactRepository
```

Read projections may cross feature tables where appropriate.

No business logic in repositories.

---

# 27. SQLite Concurrency — LOCKED

Accept SQLite's single-writer model.

Do not introduce a global Python database lock.

Long computation occurs outside transactions.

`BEGIN IMMEDIATE` is reserved for tiny coordination-sensitive operations such as:

```text
Job claiming
ann_key allocation
```

Persistent write contention is considered an architecture/performance signal, not something to hide behind huge timeouts.

---

# 28. IndexOperation — LOCKED

SQLite and USearch cannot share a transaction.

Therefore:

```text
authoritative DB change
+
IndexOperation
        ↓
COMMIT
        ↓
IndexCoordinator
        ↓
USearch mutation
        ↓
durable flush
        ↓
IndexOperation APPLIED
```

Operations:

```text
ADD
REMOVE
```

States:

```text
PENDING
APPLIED
FAILED
```

Current SQLite state always determines desired ANN presence.

Historical operation type never overrides current truth.

---

# 29. Crash Recovery — LOCKED

Graceful shutdown is an optimization.

Crash recovery is the guarantee.

Startup recovery reconciles:

```text
Jobs
ProcessingRuns
ExecutionSegments
Checkpoints
Artifacts
Sources being deleted
IndexOperations
ANN indexes
runtime installations
temp workspaces
```

Recovery is:

```text
state-based
idempotent
short-transaction
```

and derived from SQLite.

---

# 30. Application Health — LOCKED

States:

```text
BOOTING
INITIALIZING
RECOVERING
READY
DEGRADED
FAILED
```

Readiness is capability-based.

Example:

```text
SQLite healthy
ANN rebuilding
```

should mean:

```text
application = DEGRADED
library browsing = AVAILABLE
face recognition = REBUILDING
```

not total application failure.

---

# 31. API Architecture — LOCKED

Base:

```text
/api/v1/
```

Health:

```text
/health
/readiness
```

Primary resources:

```text
sources
processing-runs
observations
occurrences
identities
people
evidence
search
jobs
cameras
runtime
settings
system
media
```

Long operations return:

```text
202 Accepted
```

with Job/related identifiers.

---

# 32. Media API — LOCKED

Frontend does not receive arbitrary filesystem paths.

Bytes use dedicated endpoints such as:

```text
GET /api/v1/media/{media_id}
GET /api/v1/sources/{source_id}/media
```

Large media eventually supports HTTP range streaming.

---

# 33. WebSocket Architecture — LOCKED

One event endpoint:

```text
WS /api/v1/events
```

Events are notifications, not authoritative state.

If connection drops or sequence gap occurs:

```text
REST refetch
```

No event sourcing.

---

# 34. Pagination — LOCKED

Growing relational collections use cursor/keyset pagination.

Default:

```text
50
```

Maximum:

```text
200
```

Typical ordering:

```text
created_at DESC
id DESC
```

ANN face search uses top-K rather than cursor pagination.

---

# 35. Storage Architecture — LOCKED

Storage modes:

```text
MANAGED
REFERENCED
```

MANAGED:

```text
application owns bytes
```

REFERENCED:

```text
user owns original
application references it
```

The application must never delete the original external file of a REFERENCED Source.

---

# 36. Artifact Write Safety — LOCKED

Managed artifact creation:

```text
Artifact PENDING
    ↓
COMMIT
    ↓
write temp file
    ↓
verify/hash
    ↓
atomic rename
    ↓
Artifact AVAILABLE
```

Deletion uses durable deletion intent before physical deletion.

---

# 37. Alembic — LOCKED

Alembic is the sole production schema evolution mechanism.

No:

```text
Base.metadata.create_all()
```

for production schema management.

Fresh databases also run Alembic.

Existing databases are never automatically deleted because migration failed.

---

# 38. Version Compatibility — LOCKED

There is no single global version.

Independent versions include:

```text
Alembic revision
application version
Snapshot schema
Checkpoint schema
Evidence schema
RepresentationSpace contract
CalibrationProfile
runtime manifest
USearch format
```

Authoritative historical state is preserved.

Derived incompatible state is rebuilt where possible.

Historical semantics are never silently reinterpreted.

---

# 39. Documentation Completed

We have completed the design of:

```text
Product Definition & Requirements
Identity & Memory Model
Processing Architecture
Universal Search & Retrieval Architecture
ERD
Implementation Architecture
API & Contracts
Persistence Implementation
```

`PERSISTENCE_IMPLEMENTATION.md` is conceptually complete with 30 sections.

---

# 40. What Is Still Pending Before Development

Two major design documents remain.

## 40.1 `ML_COMPONENTS_AND_EVALUATION.md`

This is the most important unresolved technical area.

We deliberately **have not locked the actual ML models yet**.

We need to evaluate:

```text
face detector
face embedder
possibly face quality model
```

and determine:

```text
preprocessing
postprocessing
input resolution
output format
embedding dimension
normalization
similarity metric
batch behavior
GPU memory usage
CPU performance
CUDA performance
DirectML performance
cross-provider embedding compatibility
accuracy
false match behavior
false non-match behavior
calibration
recognition thresholds
candidate top-K
face quality requirements
```

The architecture should not choose thresholds from tutorials.

They must come from evaluation.

---

# 41. ML Evaluation Deliverables

`ML_COMPONENTS_AND_EVALUATION.md` should ultimately lock:

```text
Detector ComponentVersion
Embedder ComponentVersion

ModelExports

validated RuntimeVariants

RepresentationSpace

RecognitionCalibrationProfile

preprocessing contract

postprocessing contract

benchmark results

fallback compatibility matrix
```

Only after this should the actual production recognition policy be locked.

---

# 42. `TESTING_STRATEGY.md`

After ML evaluation, design the complete testing architecture.

It should cover:

```text
unit tests
repository tests
SQLite constraint tests
migration tests
API contract tests
ML worker protocol tests
SharedMemory tests
recognition tests
ANN consistency tests
IndexOperation tests
crash-recovery tests
runtime fallback tests
storage tests
end-to-end tests
performance tests
ML evaluation tests
compatibility fixtures
```

Testing is particularly important because many failures in this application occur at subsystem boundaries rather than within individual functions.

---

# 43. Stop Architecture Work After Those Two

After:

```text
ML_COMPONENTS_AND_EVALUATION.md
TESTING_STRATEGY.md
```

we should stop expanding architecture documents.

Do not continue designing hypothetical future subsystems indefinitely.

Move into implementation.

---

# 44. Repository Bootstrap

After documentation:

```text
create actual repository structure
```

approximately:

```text
project/
├── src-tauri/
├── frontend/
├── backend/
├── docs/
├── scripts/
├── tests/
└── ...
```

Backend:

```text
backend/app/
├── api/
├── core/
├── sources/
├── processing/
├── identities/
├── people/
├── memory/
├── search/
├── jobs/
├── runtime/
├── settings/
├── cameras/
├── infrastructure/
└── ml/
```

Only implemented features need full modules initially.

---

# 45. Development Guide

At repository bootstrap, create:

```text
DEVELOPMENT_AND_REPOSITORY_GUIDE.md
```

covering:

```text
repository structure
development environment
Python setup
Node setup
Tauri setup
ML dependencies
database location
migration commands
frontend generation
OpenAPI client generation
testing commands
formatting/linting
running backend independently
running worker independently
running desktop application
debugging
logs
data reset for development
```

This document should describe the real repository after bootstrap rather than speculate before it exists.

---

# 46. Implementation Strategy

Development should proceed by vertical capability rather than implementing every layer independently.

Don't do:

```text
build every repository
then every service
then every API
then every UI
then integrate everything
```

Instead:

```text
small end-to-end capability
        ↓
prove it
        ↓
expand
```

---

# 47. Implementation Phase 1 — Database Foundation

Implement:

```text
SQLAlchemy Base
UUIDv7 TypeDecorator
UTCDateTime
enum conventions
engine
SessionFactory
SQLite PRAGMAs
Alembic
0001 migration
constraints
indexes
```

> **Decision 2026-09-23:** primary keys are uuid4 (`Uuid`), not a UUIDv7 TypeDecorator (PERSISTENCE_IMPLEMENTATION.md §2).

Then prove:

```text
fresh DB
→ migrate
→ reopen
→ integrity valid
```

---

# 48. Phase 2 — Storage & Source Import

Implement:

```text
StorageManager
Artifact
ArtifactRepository
Source
SourceRepository
ImportSourceUseCase
```

First support:

```text
IMAGE
MANAGED
```

Prove:

```text
select image
→ managed copy
→ hash
→ Artifact AVAILABLE
→ Source ACTIVE
→ restart
→ Source remains accessible
```

---

# 49. Phase 3 — Execution Foundation

Implement:

```text
ProcessingConfigurationSnapshot
ProcessingRun
Job
ExecutionSegment
Checkpoint
scheduler
```

Prove:

```text
POST process
→ Snapshot
→ Run
→ Job
→ scheduler claim
→ state transitions
```

before real ML complexity.

---

# 50. Phase 4 — ML Boundary

Implement:

```text
MLSupervisor
MLClient
persistent worker
Connection control channel
SharedMemory transport
HELLO
INITIALIZE
DETECT_FACES
GENERATE_REPRESENTATIONS
RELEASE_OUTPUT
SHUTDOWN
```

Prove worker crash doesn't crash FastAPI.

---

# 51. Phase 5 — Memory Persistence

Implement:

```text
Observation
Representation
ann_key allocation
Identity
Occurrence
Evidence
```

Then connect actual evaluated detector/embedder.

---

# 52. Phase 6 — Recognition

Implement:

```text
RepresentationIndex
USearch
RecognitionCandidateQuery
RecognitionService
RecognitionAssessment
IdentityReasoner
run-local candidate memory
```

Only two IdentityReasoner decisions initially:

```text
MATCH_EXISTING_IDENTITY
CREATE_NEW_IDENTITY
```

---

# 53. Phase 7 — Atomic Acceptance

Implement:

```text
FINAL checkpoint
AcceptProcessingRunUseCase
PENDING → ACTIVE
IndexOperation creation
Source.current_processing_run_id
Run COMPLETED
Job COMPLETED
```

This is one of the most important milestones.

---

# 54. Phase 8 — Index Convergence

Implement:

```text
IndexCoordinator
ADD
REMOVE
flush
APPLIED
retry
FAILED
REBUILD_INDEX
```

Then prove:

```text
delete USearch
→ rebuild from SQLite
```

without losing memory.

---

# 55. Phase 9 — Recovery

Implement first-slice recovery for:

```text
RUNNING Job
RUNNING ProcessingRun
RUNNING ExecutionSegment
FINAL checkpoint
PENDING Artifact
DELETING Artifact
PENDING IndexOperation
missing/corrupt ANN index
orphan temp workspace
```

---

# 56. Phase 10 — API

Expose only what first slice needs.

Approximately:

```text
POST /sources/import
GET /sources
GET /sources/{id}

POST /sources/{id}/process

GET /processing-runs/{id}
GET /jobs/{id}

GET /identities
GET /identities/{id}

GET /sources/{id}/occurrences

GET /media/{id}

GET /system/status

WS /events
```

---

# 57. Phase 11 — Frontend

Initial routes:

```text
/library
/library/source/:sourceId
/identities/:identityId
/processing/:runId
```

Initial UI should prioritize observability over polish.

We need to see:

```text
what was imported
what faces were detected
which Identity each face resolved to
processing state
errors
where an Identity has appeared
```

---

# 58. First Development Milestone

The first major milestone is:

> **Persistent Unknown Identity Recognition**

Demonstration:

```text
Image A
contains Person X
    ↓
Identity I1 created

Image B
contains Person X
    ↓
I1 recognized

Image C
contains Person Y
    ↓
Identity I2 created

restart application

Image D
contains Person X
    ↓
I1 recognized again
```

At that point the application genuinely has local visual memory.

---

# 59. Required First-Milestone Failure Tests

It isn't complete until we also prove:

```text
delete ANN index
→ memory rebuilds

crash after SQLite acceptance
before USearch ADD
→ recovery converges

crash after USearch flush
before IndexOperation APPLIED
→ idempotent reconciliation

crash after FINAL checkpoint
before acceptance
→ finalize without rerunning ML

ML worker crash
→ backend survives

CUDA failure
→ explicit compatible fallback

network disconnected
→ application still works
```

---

# 60. What Comes Immediately After First Development Milestone

> **Decision 2026-09-23:** the **domain-level** use cases and invariant tests for Person naming (Phase A), the query-only recognition guard (Phase B), corrections (Phase C), merge (Phase D) and split (Phase E) are built in testing milestone M1 (TST-011 to TST-020), before the ML pipeline. These phases still cover their API, UI and ML-state integration after the first milestone.

Once unknown visual memory is reliable:

## Phase A — Person Naming

Implement:

```text
Person
Identity ↔ Person association
rename Person
remove association
Person detail
```

Flow:

```text
Identity I1
    ↓
"This is Alice"
    ↓
Person Alice
    ↓
I1 associated
```

Recognition still resolves Identity first.

Person is semantic interpretation afterward.

---

# 61. Phase B — Face Query Search

Implement:

```text
upload/query face
    ↓
ephemeral Representation
    ↓
ANN
    ↓
Identity results
    ↓
Person/Occurrence context
```

No persistent memory unless user explicitly chooses to ingest/save.

This proves the Query != Ingest invariant.

---

# 62. Phase C — Corrections

Implement explicit user correction:

```text
confirm match
reject match
reassign Identity
Person association corrections
```

Every meaningful correction creates Evidence.

This also begins collecting useful future training/evaluation feedback.

---

# 63. Phase D — Identity Merge

Implement:

```text
I1
I7
    ↓
merge
    ↓
surviving Identity
```

including:

```text
Representation reassignment
Occurrence reassignment
Person conflict handling
IdentityLineage
Evidence
revision protection
```

No ANN mutation required solely because identity ownership changes.

---

# 64. Phase E — Identity Split

Allow selected Representations/Occurrences to move to a new Identity.

This is more complicated than merge and should come afterward.

Need careful mixed-Occurrence handling.

---

# 65. Phase F — Forget

Implement the complete privacy/destructive workflow:

```text
Identity ACTIVE
    ↓
FORGOTTEN

Person association ended

Representations
    ↓
PENDING_DELETION

REMOVE IndexOperations
    ↓
USearch absence
    ↓
physical Representation deletion
```

Evidence/history retained appropriately.

This is a critical privacy milestone.

---

# 66. Phase G — Source Reprocessing

Then implement:

```text
REPROCESS_SOURCE
```

with:

```text
new ProcessingRun
new PENDING outputs
old current outputs remain active
    ↓
new run succeeds
    ↓
atomic replacement
```

Failed reprocessing must leave previous accepted memory intact.

---

# 67. Video Comes After Memory Corrections

Only after:

```text
recognition
naming
correction
merge
split
forget
reprocessing
```

are trustworthy should we add video.

This avoids debugging identity semantics and video complexity simultaneously.

---

# 68. Video Development Phase

Add:

```text
video Source
ffprobe metadata
PyAV/FFmpeg decode
sampling
chunk processing
bounded checkpoints
tracking
Occurrence aggregation
adaptive processing
pause
resume
cancel
```

Video uses the same core:

```text
Observation
Representation
Identity
Evidence
Occurrence
ProcessingRun
```

No new memory architecture should be required.

---

# 69. Video Acceptance Goal

Process a movie and produce:

```text
Person/Identity X
appears:
00:04:21 – 00:04:47
00:17:12 – 00:18:02
01:03:11 – 01:03:18
```

with multiple tracked Observations supporting each Occurrence.

---

# 70. Video Resume Goal

Start long video processing.

Then:

```text
pause
restart app
resume
```

without starting from zero.

Also:

```text
crash
restart
resume from safe checkpoint
```

This is where our checkpoint architecture gets fully exercised.

---

# 71. Camera Phase

Only after video.

Implement Sources managed as:

```text
CAMERA
```

with:

```text
live detection
live recognition
Occurrence creation
history
```

Camera history is stored by default according to the previously defined product requirement.

Users can later delete it.

---

# 72. Universal Search Expansion

Then fully expose:

```text
search by Person/name
search by Identity
search by Source/movie
search by Occurrence
search by face
```

Results can include:

```text
People
Identities
Sources
Occurrences
face matches
```

The UX can use the previously discussed multi-result/TikTok-like browsing approach.

---

# 73. Feedback & Learning Phase

After corrections are mature, persist structured feedback.

Examples:

```text
confirmed match
rejected match
merge
split
manual reassignment
```

These become evaluation/training signals.

Do **not** call this RLHF.

It is supervised feedback derived from user corrections.

---

# 74. Retraining Phase

Eventually:

```text
feedback accumulated
    ↓
threshold reached
or
manual Retrain
    ↓
training/evaluation pipeline
    ↓
new model candidate
    ↓
validation
    ↓
new ComponentVersion / RepresentationSpace if necessary
```

Never mutate existing semantic model versions in place.

---

# 75. Training Is Not Automatically Deployment

A newly trained model must pass evaluation before becoming active.

Flow:

```text
TRAIN
  ↓
EVALUATE
  ↓
COMPARE
  ↓
ACCEPT / REJECT
```

Only accepted models become new production ComponentVersions/RepresentationSpaces.

---

# 76. Performance Optimization Comes After Correctness

Do not prematurely introduce:

```text
TensorRT
FAISS
PostgreSQL
multiple ML workers
distributed processing
custom CUDA
complex vector compression
```

First profile the actual system.

---

# 77. Performance Metrics to Measure

Once functionality is stable, measure:

```text
face detection throughput
embedding throughput
GPU utilization
VRAM
CPU utilization
RAM
video decode throughput
ANN search latency
SQLite settlement duration
acceptance duration
Job queue latency
startup time
index rebuild speed
WAL growth
storage growth
```

Optimization decisions should come from these measurements.

---

# 78. Potential Future Escape Routes

Already accepted as possibilities, not commitments:

```text
SQLite
→ PostgreSQL/libSQL

USearch
→ FAISS/Voyager

PyInstaller
→ Nuitka

ONNX Runtime
→ TensorRT

single ML worker
→ multiple workers
```

None should happen without evidence that the existing component is actually limiting us.

---

# 79. Hardening Phase

After major features work:

```text
fuzz/error handling
crash testing
long-duration processing
large libraries
low disk
missing referenced media
corrupt artifacts
GPU reset
worker crash loops
migration failures
index corruption
application forced termination
Windows sleep/resume
```

This phase is essential for a local long-running desktop system.

---

# 80. Data Integrity Tooling

Eventually expose diagnostics capable of checking:

```text
SQLite integrity
foreign keys
orphan artifacts
missing managed files
Representation vector validity
Identity invariants
Occurrence membership
IndexOperation backlog
ANN eligibility/index consistency
runtime asset hashes
```

Potentially:

```text
System Diagnostics
```

inside Settings.

---

# 81. Packaging Phase

Once functionality is stable:

```text
Tauri desktop packaging
FastAPI sidecar packaging
ML worker packaging
Python dependency bundling
ONNX Runtime/provider packaging
model asset installation
FFmpeg distribution
application data root
upgrade behavior
uninstaller behavior
```

PyInstaller remains baseline until profiling/deployment proves otherwise.

---

# 82. Installer Must Preserve Data

Application update/uninstall semantics need explicit testing.

An ordinary update must preserve:

```text
memory.db
managed Sources
face artifacts
runtime data where appropriate
settings
```

The user must never lose accumulated memory because the application updated.

---

# 83. Release Preparation

Before first meaningful release:

```text
freeze migration baseline
freeze payload schema v1
freeze RepresentationSpace contract
freeze runtime manifest v1
freeze API v1
freeze storage layout baseline
```

and retain compatibility fixtures.

At that point persisted data becomes a long-term compatibility commitment.

---

# 84. What Comes After Development

"Development complete" should not mean the project stops.

After the feature-complete initial product:

```text
VALIDATE
    ↓
HARDEN
    ↓
BENCHMARK
    ↓
OPTIMIZE
    ↓
PACKAGE
    ↓
RELEASE
    ↓
OBSERVE
    ↓
IMPROVE
```

---

# 85. Post-Development ML Evaluation

Once users/real datasets produce realistic conditions, reevaluate:

```text
false matches
false non-matches
lighting
pose
occlusion
age variation
low resolution
movie compression
multiple faces
cross-camera behavior
```

The initial calibration is not assumed permanently optimal.

---

# 86. Post-Development Performance Evaluation

Use actual libraries:

```text
1,000 faces
10,000 faces
100,000 faces
large movie collections
```

before deciding whether SQLite or USearch needs replacement.

Architecture already provides escape routes.

---

# 87. Post-Development UX Work

Only after core behavior is reliable should substantial UI polish become a priority.

Then improve:

```text
Identity browsing
timeline
Occurrence browsing
Person profiles
movie navigation
search result presentation
correction workflows
processing visualization
storage management
runtime diagnostics
```

---

# 88. Post-Development Privacy Work

Because this application stores biometric representations locally, privacy controls should become first-class before public release.

Include:

```text
clear local-only messaging
forget Identity
delete Source
permanent deletion
storage visibility
backup behavior
data export
data reset
camera retention controls
```

Avoid claiming forensic erasure where normal filesystem/SQLite deletion cannot guarantee it.

---

# 89. Backup & Restore

After core product stability, design proper:

```text
backup
restore
migration to another PC
```

Because the application database becomes valuable personal data.

Backup needs to preserve compatible combinations of:

```text
SQLite
managed media
artifacts
semantic metadata
```

Derived ANN indexes do not necessarily need backup because they can be rebuilt.

---

# 90. Long-Term Product Direction

Eventually the system can become less like a face-recognition utility and more like:

> **a local visual memory engine.**

The architectural distinction matters.

Face recognition answers:

```text
"Who is this?"
```

Visual memory answers:

```text
"Have I seen this person before?"

"Where?"

"When?"

"In which movie?"

"How often?"

"What did I previously believe?"

"Was that identity corrected later?"

"What other appearances belong to them?"
```

The architecture we've locked is aimed at the second problem.

---

# 91. Current Project Status

At this moment:

### Product/domain architecture

```text
LOCKED
```

### Identity/memory architecture

```text
LOCKED
```

### Processing architecture

```text
LOCKED
```

### Search architecture

```text
LOCKED
```

### ERD

```text
LOCKED
```

### Implementation architecture

```text
LOCKED
```

### API/contracts

```text
LOCKED
```

### Persistence implementation

```text
LOCKED
```

### ML component selection

```text
PENDING EVALUATION
```

### Recognition thresholds/calibration

```text
PENDING EVALUATION
```

### Testing strategy

```text
PENDING
```

### Repository bootstrap

```text
NOT STARTED
```

### Production implementation

```text
NOT STARTED
```

---

# 92. Immediate Plan From Here

The sequence from **right now** should be:

```text
1. Finalize/save PERSISTENCE_IMPLEMENTATION.md
        ↓
2. Create ML_COMPONENTS_AND_EVALUATION.md
        ↓
3. Benchmark/select detector + embedder
        ↓
4. Define RepresentationSpace V1
        ↓
5. Establish calibration methodology
        ↓
6. Validate CUDA / DirectML / CPU compatibility
        ↓
7. Lock ML architecture
        ↓
8. Create TESTING_STRATEGY.md
        ↓
9. Review all architecture docs for contradictions
        ↓
10. Freeze Implementation V1
        ↓
11. Bootstrap repository
        ↓
12. Create DEVELOPMENT_AND_REPOSITORY_GUIDE.md
        ↓
13. Implement first vertical slice
        ↓
14. Run end-to-end/crash/recovery tests
        ↓
15. Stabilize
        ↓
16. Begin Person/naming phase
```

---

# 93. The Main Rule Going Forward

We have enough architecture.

The remaining documentation should answer unresolved questions—not invent more abstraction.

Once ML evaluation and testing strategy are done:

> **Build.**

During development, if implementation reveals a contradiction, we update the architecture deliberately.

But we should not return to broad architecture planning every time a small coding decision appears.

The next meaningful step is therefore **`ML_COMPONENTS_AND_EVALUATION.md`**.