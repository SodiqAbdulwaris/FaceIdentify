# Implementation Architecture

**Status:** Implementation Architecture v1 --- Locked Baseline\
**Platform:** Windows Desktop\
**Scope:** Application topology, implementation boundaries, runtime
architecture, persistence, storage, search/indexing, jobs, frontend,
recovery, concurrency, repository structure, testing, packaging, and
distribution.

> **Decision rule:** Implement the primary V1 architecture first.
> Alternatives documented here are escape routes, not parallel
> implementations. Change a locked technology or boundary only when a
> real requirement, measured bottleneck, reliability problem, or
> incompatibility justifies it.

------------------------------------------------------------------------

## 1. Purpose

This document is the authoritative implementation-level architecture for
the local visual identity / face-memory desktop application.

It translates the higher-level Product, Identity & Memory, Processing,
Search, and ERD designs into concrete software boundaries without
replacing those documents. If an implementation convenience conflicts
with a product, identity/memory, deletion/privacy, or
authoritative-state invariant, the higher-level invariant wins.

The system is a fully local Windows desktop application that can ingest
images, movies, and camera streams; detect and represent faces; maintain
persistent visual identities; associate identities with people when
known; retain occurrence/evidence history; and provide visual and
metadata search.

The implementation is designed around several core rules:

1.  **Sources contain observations. Identities represent persistent
    visual subjects. People provide semantic human identity.**
2.  **Model output is evidence, not authoritative identity truth.**
3.  **Query is not ingest. Searching must not create identity memory
    merely because recognition was performed.**
4.  **SQLite/domain state is authoritative; indexes and ML outputs are
    derived or evidential.**
5.  **Heavy computation must not hold database transactions open.**
6.  **The backend is the application/domain authority.**
7.  **The ML worker computes; it does not independently decide domain
    meaning.**
8.  **Graceful shutdown is an optimization; crash recovery is the
    guarantee.**
9.  **Concurrency is bounded and backpressured rather than maximized.**
10. **Prefer clear boundaries and boring code over architectural purity
    or excessive abstraction.**

------------------------------------------------------------------------

## 2. V1 Technology Stack

``` text
WINDOWS DESKTOP APPLICATION
│
├── Desktop Shell
│   └── Tauri                                      ← LOCKED
│
├── UI
│   ├── React                                      ← LOCKED
│   ├── TypeScript                                 ← LOCKED
│   ├── Vite                                       ← LOCKED
│   ├── Tailwind CSS                               ← LOCKED
│   └── shadcn/ui                                  ← LOCKED
│
├── Python Application Sidecar
│   ├── FastAPI                                    ← LOCKED
│   ├── SQLAlchemy 2                               ← LOCKED
│   ├── Alembic                                    ← LOCKED
│   ├── Domain / Application Services
│   ├── Identity & Memory Services
│   ├── Universal Search
│   ├── Job Manager / Scheduler
│   ├── Storage Manager
│   ├── Runtime Package Manager
│   └── Component Manager
│
├── Primary Database
│   └── SQLite + WAL                               ← LOCKED
│       ├── Alt: libSQL
│       │   └── trigger: real sync/replication requirement
│       └── Alt: PostgreSQL
│           └── trigger: measured sustained write bottleneck
│
├── Persistent ML Inference Worker
│   ├── separate Python process                    ← LOCKED
│   └── ONNX Runtime                               ← LOCKED
│       ├── CUDA Execution Provider                ← NVIDIA path
│       ├── DirectML                               ← Windows GPU path
│       └── CPU Execution Provider                 ← universal fallback
│
├── Development / Training
│   └── PyTorch                                    ← LOCKED
│       └── not shipped to normal users by default
│
├── Vector ANN
│   └── USearch                                    ← LOCKED
│       ├── Alt: FAISS
│       └── Alt: Voyager
│
├── Media
│   ├── FFmpeg                                     ← LOCKED
│   ├── ffprobe                                    ← LOCKED
│   ├── PyAV                                       ← LOCKED direction
│   └── OpenCV                                     ← CV/image utilities
│
├── Python Packaging
│   └── PyInstaller                                ← LOCKED baseline
│       ├── Alt: Nuitka
│       └── Alt: self-contained Python environment
│
├── Distribution
│   ├── hardware-aware online bootstrap installer  ← LOCKED
│   └── offline full bundle                        ← OPTIONAL
│
└── Optional NVIDIA Optimization
    └── TensorRT                                   ← FUTURE / OPTIONAL
```

No frontend-framework benchmark, database bake-off, ANN bake-off, or
packaging bake-off is required before implementation. Build the sealed
choice first and measure the real system.

------------------------------------------------------------------------

## 3. System Topology

The process hierarchy is:

``` text
Tauri
  └── FastAPI Application Backend
       └── Persistent ML Inference Worker
            └── future specialist workers only when justified
```

Each layer supervises only the layer directly beneath it.

-   **Tauri owns the backend lifecycle.**
-   **FastAPI owns the ML worker lifecycle.**
-   **The ML worker owns loaded inference sessions and GPU inference
    resources.**
-   **React owns presentation and user intent.**

Future specialist processes may be introduced for training, model
conversion, TensorRT compilation, or other large isolated maintenance
workloads. V1 starts with one persistent inference worker.

------------------------------------------------------------------------

## 4. Authority and Ownership Boundaries

``` text
React     = presentation + user intent
Tauri     = native shell + process host
FastAPI   = domain/application authority
ML Worker = compute executor
SQLite    = authoritative relational state
USearch   = rebuildable ANN acceleration
Filesystem= durable artifact bytes
```

### 4.1 Backend authority

Only FastAPI/backend application code may:

-   read/write authoritative SQLite state;
-   create or modify Sources, Observations, Identities, People,
    Associations, Evidence, ProcessingRuns, Jobs, runtime records, or
    authoritative deletion state;
-   decide identity semantics;
-   coordinate transactions;
-   decide what work should be processed.

React, Tauri, and the ML worker never independently mutate authoritative
domain state.

### 4.2 ML authority

The worker may return:

-   detections;
-   embeddings/representations;
-   quality signals;
-   model scores;
-   runtime timings;
-   structured ML failures;
-   model/runtime provenance.

It may not independently decide that an IdentityAssociation or
IdentityEvidence record should exist.

### 4.3 Search/index authority

USearch retrieves candidates. It does not decide identity truth.

Deleting or corrupting the ANN index must never delete identity memory.

------------------------------------------------------------------------

## 5. Recognition Boundary

Recognition computation is shared between ingest and query through a
domain/value object:

``` text
RecognitionAssessment
├── candidates[]
├── best_candidate
├── confidence / score
├── decision
├── thresholds/configuration
├── representation provenance
└── runtime/component provenance
```

The two paths are:

``` text
INGEST

Observation
  ↓
RecognitionAssessment
  ↓
RecognitionResult
  ↓
Identity Reasoner
```

``` text
QUERY

QueryFace
  ↓
RecognitionAssessment
  ↓
SearchIdentityAnswer
```

`RecognitionResult` is a persisted ingest record. `SearchIdentityAnswer`
is a query result. Neither requires the query path to create an
Observation.

> **Invariant: Search may read identity memory but shall not mutate
> identity memory merely by executing recognition.**

A query face is ephemeral by default. Persistence requires an explicit
user action such as Import to Library, Save Search, or Use as Identity
Evidence.

------------------------------------------------------------------------

## 6. Inter-Process Communication

### 6.1 React ↔ FastAPI

Use **REST + WebSocket**.

REST handles authoritative commands and queries. WebSocket carries live
notifications such as:

-   `processing.progress`
-   `processing.stage_changed`
-   `source.processed`
-   `identity.updated`
-   `runtime.fallback`
-   `worker.status`
-   `camera.event`

WebSocket events are not authoritative state. On reconnect, the frontend
can refetch current state through REST.

FastAPI binds only to loopback and should use an available dynamic port
rather than assuming port 8000.

There are no user accounts. A per-launch local secret/nonce may be used
so unrelated local processes cannot casually invoke destructive
endpoints. This is local process isolation, not user authentication.

### 6.2 Tauri ↔ FastAPI

Use child-process ownership plus a small startup handshake and HTTP
readiness verification.

``` text
Tauri
  │ spawn
  ▼
FastAPI
  ├── initialize
  └── emit structured READY + endpoint/session information
       ↓
Tauri verifies /readiness
```

The structured startup message is distinct from ordinary logs. OS
child-process ownership handles lifecycle monitoring and shutdown.

### 6.3 FastAPI ↔ ML Worker

Use a **control IPC + shared-memory data plane**.

Small control messages use a `multiprocessing.Connection`/Pipe-like
transport. Large arrays, image batches, and tensors use shared memory.

Logical contracts remain transport-independent:

``` text
MLRequest
├── request_id
├── operation
├── component_version
├── runtime_variant
├── input descriptors
├── options
└── execution context

MLResponse
├── request_id
├── status
├── outputs
├── timings
├── runtime provenance
└── error
```

Shared-memory descriptors must carry enough information for safe
ownership, dtype/shape interpretation, acknowledgment/release, timeout
handling, and worker-crash cleanup.

------------------------------------------------------------------------

## 7. Media Execution Boundary

The backend owns the processing plan. The worker may execute controlled
media segments:

``` text
MediaSegment
├── artifact path
├── start timestamp/frame
├── end timestamp/frame
├── sampling policy
└── decode configuration
```

The worker may locally decode a segment and run the expensive decode/ML
loop, but:

> **The worker may execute a segment; it does not decide what should be
> processed or what the results mean.**

FFmpeg + ffprobe are the canonical media foundation. PyAV provides
programmatic frame/timestamp access. OpenCV provides CV/image utilities.
OpenCV `VideoCapture` is not the canonical media architecture.

------------------------------------------------------------------------

## 8. Backend Module Architecture

The backend uses a **feature-oriented architecture with selective
domain/persistence separation**.

``` text
backend/
├── app/
│   ├── main.py
│   ├── bootstrap.py
│   ├── api/
│   ├── core/
│   ├── sources/
│   ├── processing/
│   ├── identities/
│   ├── people/
│   ├── memory/
│   ├── search/
│   ├── jobs/
│   ├── runtime/
│   ├── settings/
│   └── cameras/
│
├── infrastructure/
│   ├── db/
│   ├── storage/
│   ├── media/
│   ├── indexing/
│   ├── events/
│   ├── resources/
│   └── diagnostics/
│
├── ml/
│   ├── contracts/
│   ├── client/
│   ├── supervisor/
│   └── worker/
│
└── alembic/          # Alembic environment; revisions in alembic/versions/
```

### 8.1 Maintainability rules

-   FastAPI routes stay thin.
-   Business decisions do not live in routes.
-   SQLAlchemy models are persistence representations.
-   Do not create a parallel domain object for every database table.
-   Introduce explicit domain/value objects only when behaviour warrants
    them.
-   Avoid interface-for-every-class architecture.
-   Avoid DTO/mapper proliferation.
-   Prefer explicit code over framework magic.
-   Keep cross-module dependencies directional.
-   Give each feature one obvious entry point.

Useful explicit domain/value objects include:

-   `RecognitionAssessment`
-   `IdentityDecision`
-   `IdentityEvidenceInput`
-   `SearchIdentityAnswer`
-   `ProcessingPlan`
-   `RuntimeSelection`
-   `RuntimeFallback`

Focused services include:

-   `IdentityReasoner`
-   `IdentityMergeService`
-   `IdentitySplitService`
-   `MemoryConsolidator`
-   `RecognitionService`

------------------------------------------------------------------------

## 9. ML Worker Architecture

The inference worker is a separate process but remains in the same
Python workspace.

``` text
backend/ml/
├── contracts/
│   ├── request.py
│   ├── response.py
│   ├── shared_memory.py
│   ├── operations.py
│   └── errors.py
├── client/
├── supervisor/
└── worker/
    ├── main.py
    ├── server.py
    ├── runtime/
    │   ├── session_manager.py
    │   ├── model_cache.py
    │   └── batching.py
    ├── operations/
    │   ├── detect.py
    │   ├── represent.py
    │   └── quality.py
    └── media/
        └── segment_executor.py
```

Application code talks to the worker through `MLClient` and shared ML
contracts. It does not import worker implementation code directly.

ML contracts remain dependency-light and must not depend on FastAPI
routes, SQLAlchemy repositories, `IdentityReasoner`, or USearch.

The worker owns loaded ONNX sessions, device allocation, model cache,
and inference batching. The backend controls requested operations,
semantic component/version selection, priority, and domain meaning.

------------------------------------------------------------------------

## 10. ML Development, Export, and Runtime Provenance

PyTorch is used for experimentation, training, fine-tuning, and export
preparation. It is not shipped to normal users by default.

ONNX Runtime is the production inference standard.

The semantic hierarchy is:

``` text
Component
  ↓
ComponentVersion
  ↓
ModelExport
  ↓
RuntimeVariant
```

### 10.1 ComponentVersion

Represents the semantic learned/algorithmic component and may include:

-   model family;
-   training lineage;
-   checkpoint identity/hash;
-   input/output contract;
-   preprocessing contract;
-   training/fine-tuning metadata.

### 10.2 ModelExport

Represents an exported executable artifact, such as an ONNX export,
including export pipeline/version, opset, artifact hash, and relevant
conversion provenance.

### 10.3 RuntimeVariant

Represents how an export is deployed/executed, for example:

-   ONNX FP32;
-   ONNX FP16;
-   INT8;
-   TensorRT FP16.

FP32/FP16 exports derived from the same learned model are not
automatically separate semantic model versions, but their executable
behaviour remains identifiable and provenanced.

------------------------------------------------------------------------

## 11. Recognition Calibration

Recognition interpretation is versioned separately through
`RecognitionCalibrationProfile`.

``` text
ComponentVersion
"What learned component is this?"

ModelExport
"What executable artifact came from it?"

RuntimeVariant
"How is it being executed?"

RecognitionCalibrationProfile
"How should its recognition outputs be interpreted?"
```

RuntimeVariants declare compatibility with calibration profiles.
Multiple variants may share one validated calibration profile;
materially different variants may require another.

Do not assume every runtime requires unique calibration, and do not
assume all runtime outputs are equivalent without validation.

------------------------------------------------------------------------

## 12. Runtime Packages and Component Management

A `RuntimePackage` is a tested hardware-compatible deployable
configuration, not a model.

The V1 design uses **manifest-based Runtime Packages referencing shared
content-addressed artifacts**.

``` text
RuntimePackage
├── Manifest
├── Runtime requirements
├── RuntimeVariant → Detector
├── RuntimeVariant → Representation
├── RuntimeVariant → Quality
├── other RuntimeVariants
└── compatibility constraints
        │
        ▼
Content-addressed Artifact Store
├── sha256:...
├── sha256:...
└── sha256:...
```

### 12.1 Component Manager

Owns:

-   Components;
-   ComponentVersions;
-   ModelExports;
-   RuntimeVariants;
-   compatible calibration profiles.

### 12.2 Runtime Package Manager

Owns:

-   package discovery;
-   staged installation;
-   integrity verification;
-   compatibility resolution;
-   activation;
-   rollback;
-   removal/garbage collection;
-   active package selection.

`INSTALLED` is not the same as `ACTIVE`.

Runtime package manifests are declarative and versioned. Installation
logic is application code, not arbitrary executable logic embedded in a
manifest.

A package installation follows:

``` text
download
 ↓
staging
 ↓
verify
 ↓
validate manifest + compatibility
 ↓
register artifacts/package
 ↓
AVAILABLE
```

Useful states are:

-   `INSTALLING`
-   `AVAILABLE`
-   `INVALID`
-   `REMOVING`

Immutable runtime blobs are content-addressed by SHA-256 and may be
reused across CUDA, DirectML, and CPU packages.

------------------------------------------------------------------------

## 13. Hardware Profile and Runtime Selection

A centralized `HardwareProfile` records relevant machine capabilities:

-   OS/architecture;
-   CPU;
-   RAM;
-   GPU adapters/vendor/device;
-   VRAM;
-   CUDA availability;
-   DirectML availability;
-   relevant runtime capabilities.

The Compatibility Resolver combines HardwareProfile, installed packages,
and compatibility constraints.

Runtime selection is:

> **Automatic by default, with manual override in advanced settings.**

Conceptually:

``` text
Inference Runtime
● Automatic (Recommended)

Available:
○ NVIDIA CUDA
○ DirectML
○ CPU
```

Fallback is automatic but never silent.

Example:

``` text
CUDA → fail
DirectML → fail
CPU → works
```

The system records requested runtime, actual runtime, fallback reason,
and provenance, and notifies the user.

Structured runtime/worker failures include:

-   `WORKER_CRASH`
-   `MODEL_LOAD_FAILED`
-   `EXECUTION_FAILED`
-   `OUT_OF_MEMORY`
-   `ARTIFACT_INVALID`
-   `RUNTIME_UNAVAILABLE`
-   `INCOMPATIBLE_RUNTIME`

For OOM, reduce safe execution batch size before abandoning a runtime
where appropriate.

------------------------------------------------------------------------

## 14. Execution Provenance

Runtime provenance is stored at `ProcessingRun + ExecutionSegment`
granularity.

``` text
ProcessingRun
├── processing/configuration snapshot
├── ExecutionSegment 1
│   ├── RuntimePackage A
│   ├── RuntimeVariants
│   ├── CalibrationProfiles
│   ├── CUDA
│   └── processing range
└── ExecutionSegment 2
    ├── RuntimePackage B
    ├── RuntimeVariants
    ├── CalibrationProfiles
    ├── DirectML
    ├── fallback_from #1
    └── processing range
```

Do not create a database row for every inference call merely for
provenance.

An ExecutionSegment freezes the executable configuration used for that
segment. Runtime/component updates affect future eligible work; they
never silently mutate historical provenance or an active segment.

A model update does not automatically rewrite old memory.
Re-representation is an explicit migration/job.

------------------------------------------------------------------------

## 15. Persistence and Transaction Architecture

> **A processing job is not a database transaction.**

Use:

-   SQLAlchemy session per HTTP request or job step;
-   short transactions;
-   application/use-case-owned transaction boundaries;
-   selective Unit-of-Work-style coordination only where an operation
    genuinely spans repositories.

Repositories manipulate persistence state but generally do not commit
independently.

Atomic domain operations such as identity + association + evidence +
recognition result must commit together.

### 15.1 Long processing

``` text
ProcessingRun
│
├── Chunk 1 → compute → short transaction → checkpoint
├── Chunk 2 → compute → short transaction → checkpoint
└── ...
```

Never hold a transaction open during expensive ML.

Intermediate movie state may be persisted as derived/provisional state
and later reconciled/finalized. Where appropriate:

-   `PROVISIONAL`
-   `FINALIZED`
-   `SUPERSEDED`

Durable processing state is not automatically finalized semantic memory.

### 15.2 SQLite

Use:

-   WAL;
-   `foreign_keys=ON`;
-   busy timeout;
-   bounded connection pool;
-   short transactions;
-   controlled persistence batching.

Optimistic revalidation is used for mutable semantic operations where
stale processing results may race with user changes such as merge/split.
Do not pessimistically lock identities for long jobs, and do not add
version columns indiscriminately to every table.

------------------------------------------------------------------------

## 16. Storage Manager

> **SQLite knows what exists and what it means. The filesystem holds
> bytes. Storage Manager controls the relationship.**

Large movies, images, crops, and model/runtime files do not live as
SQLite BLOBs.

Storage Manager exclusively owns managed persistent application data.
Subsystems may manipulate temporary computational files only within
controlled allocated workspaces.

### 16.1 Imported media

Support:

-   `MANAGED`
-   `REFERENCED`

storage modes.

The application may choose intelligent defaults, but the exact
large-file threshold/default remains an implementation/configuration
decision rather than an architectural constant.

Referenced originals are never deleted merely because the application
forgets a Source.

Referenced-source availability may include:

-   `AVAILABLE`
-   `MISSING`
-   `RELOCATED`

and supports relinking.

### 16.2 Artifact identity

Persistent artifacts carry enough information for:

-   storage mode;
-   logical/storage location;
-   size;
-   content hash;
-   media type;
-   creation/import time;
-   availability state.

Hashing very large media may happen asynchronously rather than blocking
initial import UI.

### 16.3 Managed filesystem

The exact physical layout may evolve behind Storage Manager, but the
architectural categories are:

``` text
library/
├── sources/
├── artifacts/
├── derived/
│   ├── crops/
│   ├── previews/
│   └── thumbnails/
├── runtime/
│   ├── blobs/
│   └── manifests/
├── recycle/
└── temp/
```

Paths are ID/content-oriented, never Person/name-oriented. Renaming,
merging, or splitting identities must not reorganize storage by human
name.

Selected meaningful face crops may be retained; every transient detector
crop is not automatically persisted.

### 16.4 Artifact finalization

``` text
Artifact = PENDING
 ↓
write temp
 ↓
verify/hash
 ↓
atomic rename to final location
 ↓
Artifact = AVAILABLE
```

Startup recovery reconciles pending records, staging/temp files, missing
available files, and managed orphans.

### 16.5 Temporary workspaces

``` text
temp/jobs/<id>/
├── decode/
├── frames/
├── crops/
└── intermediate/
```

Not every frame must be written to disk. Shared memory and in-memory
processing are preferred where appropriate.

### 16.6 Recycle and deletion

Recycle is primarily a logical lifecycle state. Physical movement is not
required merely to mark a Source recycled.

Permanent deletion triggers the appropriate physical cleanup for managed
data while respecting higher-level deletion/forget invariants.

### 16.7 Disk management

Cleanup prioritizes reconstructable data:

1.  abandoned temp;
2.  caches;
3.  unused runtime artifacts/packages;
4.  reconstructable derived artifacts.

Originals, authoritative evidence, and critical state receive stronger
protection.

------------------------------------------------------------------------

## 17. Search and ANN Infrastructure

> **SQLite/domain state is authoritative. USearch is derived
> acceleration state.**

USearch stores curated identity representation entries rather than
treating one vector as the entire identity or indexing every transient
frame indefinitely.

ANN entries point toward representation/evidence and Identity, not
directly toward Person.

``` text
Query Vector
 ↓
USearch
 ↓
candidate representations
 ↓
candidate identities
 ↓
RecognitionAssessment
 ↓
Identity
 ↓
Person if known
```

### 17.1 Representation spaces

Keep separate indexes for incompatible representation
ComponentVersions/spaces. Equal vector dimension does not imply
compatibility.

Do not split an index merely because one representation was computed
through CUDA and another through DirectML if they belong to a validated
compatible representation space.

A dedicated `RepresentationSpace` concept may be introduced later if
actual model selection makes it necessary.

### 17.2 Durable index synchronization

``` text
SQLite transaction
├── persist authoritative representation/evidence state
└── persist IndexOperation ADD/REMOVE/REPLACE
 ↓ COMMIT
IndexCoordinator
 ↓
USearch
 ↓
mark synchronized
```

Never update USearch first and authoritative state second.

Interactive operations may attempt immediate synchronization. Bulk movie
work may batch index updates.

If index synchronization fails, authoritative state survives and durable
pending operations remain retryable.

### 17.3 Recognition

USearch returns top-K candidates. Candidate aggregation and calibrated
interpretation occur in application code through `RecognitionService`
and `RecognitionCalibrationProfile`.

ANN similarity is evidence, not identity truth.

### 17.4 Rebuild/degraded mode

If an index is missing, corrupt, or incompatible, the application may
operate in degraded mode while rebuilding from authoritative SQLite
state.

Index manifests record relevant compatibility metadata such as:

-   index ID;
-   representation component/version;
-   dimensions;
-   metric;
-   USearch/index format version;
-   generation/revision;
-   creation time;
-   state.

### 17.5 Universal search

Universal Search orchestrates specialized mechanisms:

-   face search → representation + USearch + recognition;
-   name/source/occurrence/metadata filters → SQLite;
-   future semantic/natural-language search → separate mechanism.

Do not force every search mode through ANN.

------------------------------------------------------------------------

## 18. Jobs, Scheduling, Events, and Progress

Use a small persistent job system inside FastAPI. V1 does **not**
require Celery, Redis, RabbitMQ, or a distributed queue.

``` text
React
  ↓
FastAPI
├── Job Manager
├── Scheduler
├── Event Bus
└── Progress Manager
     ↓
Processing Orchestrator
     ↓
ML Worker
```

### 18.1 Job vs ProcessingRun

A `Job` is an operational unit such as:

-   process source;
-   rebuild index;
-   reprocess source;
-   generate thumbnail;
-   retrain model;
-   install runtime;
-   clean storage.

A `ProcessingRun` is durable provenance/history describing source
processing.

Do not turn every frame or internal stage into its own Job.

### 18.2 Job lifecycle

``` text
QUEUED → RUNNING → COMPLETED
                 → FAILED

RUNNING → PAUSING → PAUSED → QUEUED
RUNNING → CANCELLING → CANCELLED
RUNNING → crash → INTERRUPTED
```

Cancellation is cooperative at safe boundaries. Normal cancellation does
not kill the ML worker.

Pause/resume is checkpoint-based; do not serialize a live Python stack.

### 18.3 Progress

Progress is hierarchical:

-   overall fraction where knowable;
-   current stage;
-   stage fraction;
-   completed/total units;
-   message/metrics.

Support determinate and indeterminate progress. Do not invent fake
percentages.

Fine-grained updates may remain in memory/WebSocket; meaningful coarse
progress and checkpoints are persisted.

### 18.4 Events

Use a small typed in-process event bus for notifications and secondary
reactions, with events such as:

-   `JobStarted`
-   `JobProgressed`
-   `JobCompleted`
-   `ProcessingStageChanged`
-   `IdentityUpdated`
-   `RuntimeFallbackOccurred`
-   `IndexStateChanged`
-   `WorkerStateChanged`

Do not hide core business logic in event handlers.

Domain events and frontend WebSocket events are related but distinct
concepts.

### 18.5 Priorities

Initial priorities:

-   `INTERACTIVE`
-   `HIGH`
-   `NORMAL`
-   `LOW`
-   `MAINTENANCE`

Priority affects scheduling; it does not imply uncontrolled concurrency.

Camera sessions are long-lived processing sessions rather than fake
0--100% finite jobs.

------------------------------------------------------------------------

## 19. Concurrency and Resource Management

Use **bounded, resource-aware concurrency**.

``` text
                    Job Scheduler
                          │
                          ▼
                Resource Coordinator
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
 Interactive          Heavy Lane         Maintenance
       │                  │                  │
 high priority       one heavy job       low priority
       │                  │                  │
       └──────────────┬───┴──────────────────┘
                      ▼
              Processing Pipeline
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
 Bounded CPU       ML Worker      Persistence
    pools          + GPU             batch
       │              │               │
       └──────────────┼───────────────┘
                      ▼
                  Backpressure
```

### 19.1 V1 rules

-   one heavy movie-processing pipeline at a time;
-   short interactive work may interleave at safe batch boundaries;
-   one persistent inference worker owns GPU inference;
-   CPU work uses bounded pools;
-   expensive stage boundaries use bounded queues;
-   persistence is batched/bounded;
-   maintenance yields to higher-priority work;
-   camera processing receives explicit sustained-resource budgeting;
-   no component independently consumes all available CPU cores.

### 19.2 Backpressure

``` text
Decoder
 ↓
bounded buffer
 ↓
ML Worker
```

If downstream is slower, upstream waits/yields. The system does not
respond by accumulating unbounded decoded frames or pending persistence
in RAM.

Queue capacities are determined through profiling rather than being
enormous by default.

### 19.3 Adaptive batching and OOM

Batch size may adapt based on operation, frame dimensions, runtime,
model requirements, available VRAM, and previous OOM.

On CUDA OOM:

``` text
release safe unused cache/buffers
 ↓
reduce batch size
 ↓
retry safe operation
 ↓
if still failing
 ↓
runtime fallback
```

### 19.4 Model cache

The worker maintains a bounded loaded-model cache with enough metadata
to unload unused sessions under memory pressure. A simple LRU-like
strategy is sufficient initially.

### 19.5 Camera

Live camera processing prefers timely sampling over an ever-growing
backlog. If input FPS exceeds useful inference capacity, unnecessary
stale frames may be dropped according to the sampling/resource policy.

### 19.6 Telemetry

Collect lightweight local operational telemetry such as:

-   CPU/RAM pressure;
-   GPU/VRAM pressure;
-   queue depth;
-   inference latency;
-   decode throughput;
-   persistence throughput.

This supports diagnostics and future tuning. It is not remote analytics.

### 19.7 No premature dynamic scheduler

Start with bounded pools, bounded queues, priorities, one heavy job,
adaptive ML batches, and backpressure. Profile real workloads before
adding sophisticated dynamic scheduling.

------------------------------------------------------------------------

## 20. Frontend Architecture

The React frontend is feature-oriented and deliberately thin.

``` text
frontend/src/
├── app/
│   ├── router/
│   ├── providers/
│   └── layout/
├── features/
│   ├── library/
│   ├── sources/
│   ├── people/
│   ├── identities/
│   ├── search/
│   ├── processing/
│   ├── cameras/
│   ├── runtime/
│   └── settings/
├── components/
│   ├── ui/
│   └── shared/
├── api/
│   ├── generated/
│   ├── client.ts
│   ├── websocket.ts
│   └── events.ts
├── native/
├── stores/
├── hooks/
└── lib/
```

> **React presents backend state and captures user intent. It does not
> become a second implementation of domain logic.**

### 20.1 State

-   TanStack Query → server state.
-   React local state → local component/UI state.
-   Zustand → only small genuinely cross-feature client state.
-   No Redux unless a real need emerges.

Do not maintain a shadow copy of authoritative domain state in frontend
stores.

### 20.2 WebSocket

Use one app-level WebSocket connection and event router.

Domain-change events generally invalidate/refetch relevant TanStack
queries. Ephemeral progress can update transient UI directly.

Reconnect must refetch important state because events may have been
missed.

### 20.3 Routes

Major workspaces may include:

``` text
/library
/library/source/:sourceId
/people/:personId
/identities/:identityId
/search
/cameras
/processing/:runId
/settings/general
/settings/storage
/settings/runtime
/settings/advanced
```

Not every modal or detail needs a route.

### 20.4 People vs Identity

Keep Person and Identity separate in frontend contracts. Normal UX
emphasizes People; advanced review can expose
Identity/evidence/merge/split details.

### 20.5 Search

Universal Search returns heterogeneous result types such as Person,
Identity, Source, Occurrence, and Visual Match. Ranking/semantics remain
backend-owned.

Search-upload faces are ephemeral. Persistence actions are explicit.

### 20.6 API contracts

Generate TypeScript API contracts/client from FastAPI OpenAPI, but hide
generated code behind feature-level API modules.

Do not expose raw SQLAlchemy models as API responses.

### 20.7 Tauri bridge

Native operations such as file dialogs live behind a small `native/`
layer. Tauri may select a file; FastAPI performs the domain import.

Frontend media access uses backend-controlled media endpoints rather
than depending on Windows filesystem paths.

------------------------------------------------------------------------

## 21. Configuration and Settings

Use typed, layered configuration with one owner per kind.

### 21.1 Categories

**Application configuration** - DB/storage/temp roots; - backend/IPC
startup essentials; - logging.

**User settings** - theme/gallery behaviour; - import/storage
preferences; - notifications; - camera history; - advanced UI
preferences.

**Runtime/processing settings** - runtime preference; - processing
profile; - resource limits; - fallback behaviour; - configurable batch
policy.

**Development configuration** - debug/dev ports; - mocks; - profiling.

### 21.2 Persistence

User/runtime settings are centralized through a backend Settings Service
and persisted in SQLite.

`.env` is for development, packaging, and exceptional startup overrides,
not ordinary production user settings.

Defaults live in typed code; persisted state stores overrides.

React edits settings through the backend rather than shadowing them in
localStorage.

### 21.3 Processing snapshots

At ProcessingRun creation, resolve effective settings into an immutable
`ProcessingConfigurationSnapshot`.

If the user changes settings during a run, the active run retains its
snapshot; future eligible runs receive the new settings.

Distinguish:

``` text
preference
 ↓
resolved configuration
 ↓
actual execution provenance
```

Calibration thresholds normally belong to calibration/component
configuration rather than generic user preferences.

Settings are schema/versioned and migratable. A settings change may
report that it requires a worker restart, app restart, index rebuild, or
affects only future work.

------------------------------------------------------------------------

## 22. Startup and Readiness

Startup is staged:

``` text
Tauri
 ↓
FastAPI
 ↓
Core initialization
 ↓
Database + migrations
 ↓
Storage
 ↓
Recovery
 ↓
Indexes
 ↓
Runtime resolution
 ↓
ML worker
 ↓
Scheduler/services
 ↓
READY
 ↓
React normal operation
```

Lifecycle states may include:

-   `BOOTING`
-   `INITIALIZING`
-   `RECOVERING`
-   `READY`
-   `DEGRADED`
-   `FAILED`

Readiness is capability-based, covering areas such as database, storage,
ML worker, face index, runtime, scheduler, and recovery.

A rebuildable/optional subsystem failure may yield `DEGRADED` rather
than blocking the entire application.

ML-worker readiness means the process/IPC/runtime is valid. It does not
require every model to be loaded; model loading is lazy.

Run Alembic migrations before READY.

V1 should enforce a single application instance against a library to
avoid competing SQLite/USearch/backend authorities.

One explicit Startup Coordinator controls dependency order.

------------------------------------------------------------------------

## 23. Shutdown and Crash Recovery

> **Graceful shutdown is an optimization. Crash recovery is the
> guarantee.**

Shutdown reverses ownership:

``` text
Tauri requests backend shutdown
 ↓
FastAPI = SHUTTING_DOWN
 ↓
scheduler stops accepting new work
 ↓
active work reaches safe checkpoint
 ↓
persistence/index state settles
 ↓
ML worker stops
 ↓
DB/resources close
 ↓
backend exits
 ↓
Tauri exits
```

Do not wait for an entire movie to finish. Stop at a safe
boundary/checkpoint.

Graceful shutdown has a bounded timeout. A hung worker may be
terminated, relying on durable recovery.

### 23.1 Completion ordering

``` text
compute
 ↓
durable commit
 ↓
mark run/job complete
 ↓
emit completion event
```

Never emit success before durable commit.

### 23.2 Recovery scope

Recovery reconciles durable:

-   Jobs;
-   ProcessingRuns;
-   ExecutionSegments;
-   checkpoints;
-   artifacts;
-   temp workspaces;
-   IndexOperations;
-   runtime installations.

Interrupted active runs/segments become `INTERRUPTED`. Resume creates a
new ExecutionSegment so provenance remains correct.

Ordinary resumable processing may auto-requeue/resume with user
notification. Repeated failures stop blind automatic retry.

### 23.3 Shared memory

Shared memory is never persistence. It requires ownership metadata,
request ID, lifecycle/size information, acknowledgment/release, and
worker-crash cleanup.

### 23.4 Worker crash

A worker crash does not crash FastAPI.

The supervisor:

1.  records failure;
2.  fails/interrupts in-flight requests appropriately;
3.  cleans shared resources;
4.  restarts with bounded backoff;
5.  triggers runtime fallback when appropriate.

Repeated worker/runtime failure can degrade ML capability without
corrupting the application database.

### 23.5 Referenced sources

If an external referenced source disappears:

-   keep the Source record;
-   mark availability `MISSING`;
-   preserve existing memory/evidence as required;
-   offer Locate File;
-   verify a relink appropriately.

### 23.6 USearch recovery

Pending durable IndexOperations can catch up after restart. If the index
cannot be trusted, discard/rebuild it from SQLite.

### 23.7 Runtime installation recovery

A staged/incomplete runtime install never becomes `AVAILABLE` until
validated. The previous active package remains usable.

### 23.8 Recovery idempotence

Running recovery more than once must not compound damage or duplicate
state.

------------------------------------------------------------------------

## 24. Repository Structure

Use one monorepo with clear process boundaries and one Python workspace.

``` text
visual-memory/
│
├── desktop/
│   └── src-tauri/
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── features/
│   │   ├── components/
│   │   ├── api/
│   │   ├── native/
│   │   ├── stores/
│   │   ├── hooks/
│   │   └── lib/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── sources/
│   │   ├── processing/
│   │   ├── identities/
│   │   ├── people/
│   │   ├── memory/
│   │   ├── search/
│   │   ├── jobs/
│   │   ├── runtime/
│   │   ├── settings/
│   │   └── cameras/
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   ├── storage/
│   │   ├── media/
│   │   ├── indexing/
│   │   ├── events/
│   │   ├── resources/
│   │   └── diagnostics/
│   │
│   ├── ml/
│   │   ├── contracts/
│   │   ├── client/
│   │   ├── supervisor/
│   │   └── worker/
│   │
│   └── alembic/
│
├── runtime/
│   ├── manifests/
│   └── schemas/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── recovery/
│   ├── fixtures/
│   └── e2e/
│
├── evaluation/         # ML quality evaluation (datasets kept outside Git)
├── benchmarks/
├── scripts/
├── packaging/
├── docs/
├── pyproject.toml
├── package.json
├── README.md
└── .gitignore
```

The inference worker is a separate process, not a separate independent
product/project. Keeping it in the Python workspace avoids unnecessary
versioning and duplicated contracts.

Repository-level `runtime/` contains definitions/manifests/schemas, not
downloaded runtime blobs.

Downloaded application state belongs outside Git in managed
application/library directories.

------------------------------------------------------------------------

## 25. Testing Architecture and Boundaries

The testing strategy answers different questions at different layers:

``` text
DOMAIN TESTS
"Did we make the right decision?"

INTEGRATION TESTS
"Do our real technical components work together?"

CONTRACT TESTS
"Do independently executing boundaries agree?"

RECOVERY TESTS
"Can interrupted state become valid again?"

E2E TESTS
"Can the user complete the workflow?"

EVALUATION
"Is the ML component good enough?"

BENCHMARKS
"Is the implementation fast enough?"
```

Do not collapse these into one test category.

### 25.1 Unit/domain tests

Deeply test:

-   IdentityReasoner;
-   RecognitionService;
-   MemoryConsolidator;
-   merge/split/correction behaviour;
-   ProcessingPlanner;
-   RuntimeResolver;
-   Storage policies;
-   Job state transitions;
-   resource policies.

Tests assert decisions and invariants rather than private method calls.

A critical query test verifies that face search can produce
`RecognitionAssessment` and `SearchIdentityAnswer` without creating
Source, Artifact, Observation, IdentityEvidence, or IdentityAssociation
unless persistence is explicitly requested.

### 25.2 Database integration

Use real temporary SQLite databases for:

-   foreign keys;
-   unique constraints;
-   cascades;
-   transactions/rollback;
-   WAL behaviour/configuration;
-   repository queries;
-   migration compatibility;
-   optimistic revision/revalidation behaviour.

Do not use a fake database to claim SQLite-specific correctness.

### 25.3 Transaction atomicity

Inject failures into multi-record domain operations and verify partial
authoritative state is not committed.

### 25.4 Storage integration

Use temporary directories with the real StorageManager to test
managed/referenced imports, hashing, workspaces, atomic finalization,
recycle/restore, permanent deletion, missing references, relinking, and
orphan recovery.

### 25.5 ANN integration

Use real USearch for
add/search/remove/replace/save/load/manifest/rebuild integration tests.

Recognition domain tests need not all depend on USearch.

### 25.6 Index synchronization

Explicitly test:

``` text
SQLite commit succeeds
 ↓
USearch update fails
 ↓
authoritative data survives
 ↓
IndexOperation remains pending
 ↓
retry/rebuild restores derived index
```

### 25.7 ML contracts

Test `MLRequest`, `MLResponse`, shared-memory descriptors, operation
types, error structures, and runtime provenance so backend/worker drift
is detected.

### 25.8 ML worker

Ordinary CI/development uses CPU-compatible worker tests where possible.

Hardware validation separately covers CUDA and DirectML on supported
machines.

Software correctness tests are distinct from model-quality evaluation.

### 25.9 Runtime/calibration validation

Runtime variants are not required to be bit-identical across
CPU/CUDA/DirectML/FP16/etc. Validation determines whether behaviour
remains within the accepted calibration/representation compatibility
envelope.

### 25.10 Media

Keep small fixture media for:

-   no-face/single-face/multi-face images;
-   short video;
-   orientation/timestamp cases;
-   variable frame rate;
-   damaged media.

Test probing, decode, timestamps, segment boundaries, sampling, and
failure handling.

### 25.11 Pipeline integration

The first important pipeline integration scenario is:

``` text
small image
 ↓
Source + Artifact
 ↓
Decode
 ↓
ML Worker
 ↓
Observation
 ↓
Representation
 ↓
Recognition
 ↓
Identity
 ↓
SQLite
 ↓
USearch
```

Scenarios include no face, one unknown face, multiple unknown faces,
known face again, ambiguous match, and processing failure.

### 25.12 Jobs/scheduler/backpressure

Test valid/invalid job transitions, priority scheduling, bounded queues,
persistence backpressure, cancellation at safe boundaries, and
checkpointed pause/resume.

Avoid timing-sensitive tests based on arbitrary sleeps; use
deterministic controls/fake clocks where useful.

### 25.13 Recovery

`tests/recovery/` explicitly constructs interrupted states such as:

-   RUNNING Job + dead worker;
-   RUNNING ProcessingRun;
-   active ExecutionSegment;
-   PENDING Artifact;
-   abandoned workspace;
-   pending IndexOperation;
-   INSTALLING RuntimePackage;
-   missing referenced Source.

A smaller set of process-level tests should actually kill subprocesses
and verify restart recovery.

### 25.14 Runtime packages/configuration

Test manifest validation, hashes, deduplication, compatibility, staged
install, activation, rollback, GC, interrupted installation,
defaults/overrides, settings migration, and immutable
ProcessingConfigurationSnapshots.

### 25.15 API/WebSocket/frontend/Tauri

API tests verify transport validation/schema/error behaviour without
duplicating every domain edge case.

WebSocket tests verify reconnect/refetch semantics.

Frontend tests focus on high-value interaction states rather than
snapshot-testing UI primitives.

Generated TypeScript contracts must stay synchronized with FastAPI
OpenAPI.

Tauri tests stay focused on backend launch, handshake, dynamic endpoint,
single-instance behaviour, native bridge, shutdown, and backend failure
handling.

### 25.16 E2E

Keep E2E scenarios few and meaningful:

``` text
launch
 ↓
backend/worker ready
 ↓
import image
 ↓
process
 ↓
faces displayed
 ↓
close
 ↓
reopen
 ↓
result persists
```

Later scenarios cover repeat-person recognition, ephemeral face search,
movie resume after restart, and other major product workflows.

### 25.17 Isolation

Every test uses isolated temporary DB/library/runtime/index/workspace
state. Tests must never accidentally point at a real user library.

### 25.18 Performance

Benchmarks are separate from correctness tests and provide the evidence
for any migration such as USearch→FAISS, SQLite→PostgreSQL,
ORT→TensorRT, one worker→multiple workers, or PyInstaller→Nuitka.

Useful markers include:

-   `unit`
-   `integration`
-   `gpu`
-   `slow`
-   `recovery`
-   `e2e`
-   `benchmark`

------------------------------------------------------------------------

## 26. Packaging and Distribution

PyInstaller is the V1 Python packaging baseline.

Use Nuitka only if measurement demonstrates a practical benefit in
reliability, startup, distribution, output size, or build behaviour.

If native dependency freezing remains unreliable, use a managed
self-contained Python environment.

Native dependency reliability matters more than loyalty to a bundler.

### 26.1 Hardware-aware bootstrapper

Normal distribution is an online bootstrap installer:

``` text
Setup
 ↓
detect Windows / CPU / RAM / GPU / VRAM / drivers / disk
 ↓
build installation plan
 ↓
download required runtime packages/components
 ↓
verify hashes/signatures
 ↓
install
 ↓
initialize
 ↓
run application + inference smoke test
 ↓
launch
```

An optional offline bundle may include baseline dependencies/models for
no-network installation.

Docker may be used for development, CI, reproducibility, and
experiments.

> **Docker, Docker Desktop, WSL2, and a container runtime are not
> end-user dependencies.**

------------------------------------------------------------------------

## 27. Updates and Versioning

Maintain three independent update domains:

1.  **Application updater** --- Tauri, React, Python application,
    migrations, protocols.
2.  **Runtime Package Manager** --- ONNX Runtime, execution providers,
    FFmpeg/native runtime infrastructure.
3.  **Component Manager** --- detectors, trackers, representation
    models, quality models, calibration, and other independently
    versioned ML components.

A model-only update should not require a full application reinstall.

Component activation follows an explicit lifecycle. New installed
versions do not silently become active.

------------------------------------------------------------------------

## 28. Authoritative, Derived, and Operational State

### Authoritative

-   SQLite relational/domain state;
-   retained managed source media where applicable;
-   identity corrections and feedback;
-   deletion/forget state;
-   component/version/provenance metadata;
-   critical backups.

### Derived / rebuildable

-   USearch ANN indexes;
-   other search indexes;
-   caches;
-   reconstructible recognition artifacts;
-   TensorRT engines;
-   regenerable thumbnails/crops;
-   temporary processing artifacts.

### Operational

-   Jobs;
-   ProcessingRuns;
-   ExecutionSegments;
-   checkpoints;
-   runtime/installation state;
-   pending IndexOperations.

> **USearch, ONNX outputs, TensorRT engines, caches, stale indexes, old
> runtime state, or other derived structures cannot override current
> authoritative identity, correction, deletion, or forget state.**

------------------------------------------------------------------------

## 29. Pressure Points and Escape Routes

  ----------------------------------------------------------------------------------------------------------------------
  Primary        Pressure point           Mitigation first                      Alternative           Migration trigger
  -------------- ------------------------ ------------------------------------- --------------------- ------------------
  SQLite WAL     serialized writes        short transactions, batching,         PostgreSQL            sustained measured
                                          controlled persistence                                      contention affects
                                                                                                      real workloads

  SQLite WAL     sync/replication         preserve DB boundaries                libSQL                sync/replication
                                                                                                      becomes a real
                                                                                                      requirement

  USearch        advanced/large ANN       tune indexing/rebuild                 FAISS                 scale, advanced
                                                                                                      ANN, or GPU ANN is
                                                                                                      required

  USearch        integration/packaging    fix runtime packaging                 Voyager               USearch itself
                                                                                                      becomes materially
                                                                                                      problematic

  ONNX Runtime   unsupported/unfaithful   export/runtime fixes                  PyTorch runtime       faithful ONNX
                 component                                                                            execution cannot
                                                                                                      be achieved

  One inference  workload contention      priority, batching, backpressure      specialist/multiple   interactive/live
  worker                                                                        workers               and batch
                                                                                                      workloads cannot
                                                                                                      coexist acceptably

  PyInstaller    packaging limitation     hooks/native collection               Nuitka                measurable
                                                                                                      practical benefit

  Frozen Python  native dependency        runtime separation                    self-contained        freezing remains
                 failure                                                        environment           unreliable

  Online         no network               caching/manifests                     offline bundle        offline install is
  bootstrap                                                                                           required

  React          isolated render          virtualization/workers/Canvas/WebGL   targeted native       specific workload
                 bottleneck                                                     implementation        cannot meet
                                                                                                      requirements

  ONNX CUDA      NVIDIA performance       batching/ORT optimization             TensorRT              measured
                 ceiling                                                                              bottleneck
                                                                                                      justifies
                                                                                                      machine-local
                                                                                                      acceleration
  ----------------------------------------------------------------------------------------------------------------------

Alternatives are migration paths, not parallel V1 implementations.

------------------------------------------------------------------------

## 30. Release Validation

A release pipeline should eventually perform:

``` text
dependency lock
 ↓
dependency/security checks
 ↓
backend + ML worker build
 ↓
frontend + Tauri build
 ↓
bootstrap manifests/package
 ↓
clean Windows installation
 ↓
launch
 ↓
hardware/provider detection
 ↓
open/create library
 ↓
inference smoke test
 ↓
process sample image
 ↓
search smoke test
 ↓
close/reopen
 ↓
recovery/persistence verification
 ↓
uninstall
 ↓
verify user library survived
```

Clean-machine validation is mandatory because developer machines can
hide missing DLLs, runtime packages, codecs, or other native
dependencies.

Hardware-specific validation can run separately for CUDA and DirectML
rather than on every commit.

------------------------------------------------------------------------

## 31. First Vertical Slice

The first implementation target deliberately exercises the architecture
without prematurely adding movies, cameras, training, or
natural-language search.

``` text
Launch Desktop App
        ↓
Tauri starts FastAPI
        ↓
FastAPI initializes SQLite/Storage/USearch
        ↓
FastAPI starts ML worker
        ↓
Import ONE image
        ↓
Create Source + Artifact
        ↓
Decode
        ↓
Detect faces
        ↓
Create Observations
        ↓
Represent faces
        ↓
USearch candidate retrieval
        ↓
RecognitionAssessment
        ↓
Identity Reasoner
        ↓
IdentityAssociation / new Identity as appropriate
        ↓
IdentityEvidence
        ↓
Memory consolidation
        ↓
Persist authoritative state
        ↓
Synchronize derived index
        ↓
Display People Found
```

Initial development should not require:

-   movie ingestion;
-   live camera processing;
-   training/retraining;
-   natural-language search;
-   TensorRT;
-   sophisticated dynamic scheduling;
-   multiple heavy workers;
-   production updater polish.

After the vertical slice:

``` text
Single Image
 ↓
Corrections + Evidence Review
 ↓
Face Search
 ↓
Identity Rename / Merge / Split
 ↓
Cross-source Recognition
 ↓
Movies
 ↓
Tracking + Appearances
 ↓
Movie Reconciliation
 ↓
Live Camera
 ↓
Universal / Natural-Language Search
 ↓
Training / Retraining
 ↓
Advanced Resource Management
 ↓
Production Bootstrap / Update Infrastructure
```

------------------------------------------------------------------------

## 32. Implementation Rules

1.  Implement the locked V1 architecture before escape routes.
2.  Do not implement alternatives preemptively.
3.  Preserve boundaries that make documented migrations possible.
4.  Measure a real bottleneck before changing the stack.
5.  Keep domain decisions in the application/domain layer.
6.  Keep ML execution separate from semantic identity decisions.
7.  Never allow query-only recognition to silently become ingest.
8.  Never allow derived/index state to override authoritative state.
9.  Never hold long database transactions across expensive compute.
10. Use bounded concurrency and backpressure.
11. Persist enough checkpoint/provenance state for recovery.
12. Make recovery idempotent.
13. Prefer maintainable explicit code over abstraction for abstraction's
    sake.
14. When migration becomes necessary, document the evidence, attempted
    mitigations, migration impact, and rollback strategy.
15. Never allow an implementation technology to override locked Product,
    Identity/Memory, Processing, Search, deletion, or privacy
    invariants.

------------------------------------------------------------------------

## 33. Final Locked Baseline

  -------------------------------------------------------------------------------
  Area                    Choice                          Status
  ----------------------- ------------------------------- -----------------------
  Platform                Windows                         LOCKED

  Desktop shell           Tauri                           LOCKED

  Frontend                React + TypeScript              LOCKED

  Build                   Vite                            LOCKED

  Styling                 Tailwind CSS                    LOCKED

  UI primitives           shadcn/ui                       LOCKED

  Backend                 Python + FastAPI                LOCKED

  ORM                     SQLAlchemy 2                    LOCKED

  Migrations              Alembic                         LOCKED

  Database                SQLite WAL                      LOCKED

  ANN                     USearch                         LOCKED

  Media                   FFmpeg + ffprobe + PyAV         LOCKED

  CV utilities            OpenCV                          LOCKED direction

  Training/development    PyTorch                         LOCKED

  Production inference    ONNX Runtime                    LOCKED

  NVIDIA path             CUDA EP                         LOCKED direction

  Windows GPU path        DirectML                        LOCKED direction

  CPU fallback            ORT CPU                         LOCKED

  ML isolation            Persistent dedicated Python     LOCKED
                          inference worker                

  Backend↔worker IPC      control IPC + shared memory     LOCKED

  Frontend↔backend        REST + WebSocket                LOCKED

  Runtime packages        manifest + content-addressed    LOCKED
                          artifacts                       

  Runtime selection       automatic + advanced manual     LOCKED
                          override                        

  Runtime fallback        automatic + visible             LOCKED

  Provenance              ProcessingRun +                 LOCKED
                          ExecutionSegments               

  Query-face retention    ephemeral by default            LOCKED

  Calibration             versioned                       LOCKED
                          RecognitionCalibrationProfile   

  Jobs                    persistent local FastAPI job    LOCKED
                          system                          

  Concurrency             bounded/resource-aware          LOCKED

  Large-file storage      managed/referenced filesystem   LOCKED
                          artifacts                       

  Python packaging        PyInstaller baseline            LOCKED

  Distribution            hardware-aware online           LOCKED
                          bootstrapper                    

  Offline distribution    full bundle                     OPTIONAL

  NVIDIA optimization     TensorRT                        FUTURE

  End-user Docker         none                            LOCKED
  -------------------------------------------------------------------------------

------------------------------------------------------------------------

## 34. Next Architecture Phase

With this document locked, the next design phase is **API & Internal
Contracts**.

That phase should make the boundaries in this document concrete by
specifying:

-   REST resources and command/query endpoints;
-   WebSocket event envelopes;
-   API error contracts;
-   pagination and media delivery contracts;
-   `MLRequest` / `MLResponse`;
-   shared-memory descriptors and ownership;
-   worker lifecycle/control messages;
-   Storage Manager contracts;
-   RepresentationIndex contracts;
-   Job/progress/event contracts;
-   runtime/package/component contracts;
-   internal transaction/use-case boundaries.

Only after those contracts are defined should the ERD be mapped into the
concrete SQLAlchemy/Alembic implementation plan and the first ML
components selected for the initial vertical slice.

> **Decision 2026-09-23:** the concrete schema is `PERSISTENCE_IMPLEMENTATION.md`, not a mapping of `ERD.md`, which is conceptual.
