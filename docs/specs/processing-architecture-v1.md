# Processing Architecture v1.0

**Status:** Locked architectural baseline\
**Scope:** Local-only visual identity / face-memory application\
**Target development machine:** Lenovo Legion 7i (83FD0015US), Intel
Core i9-14900HX, 32 GB RAM, NVIDIA GeForce RTX 4070 Laptop GPU with 8 GB
VRAM\
**Vector database candidate:** Qdrant\
**Related specifications:** Product Definition & Requirements v1.0;
Identity & Memory Model v1.0

## 1. Purpose

This document defines the processing architecture for a private,
local-only visual identity system that discovers, remembers, recognizes,
organizes, tracks, corrects, and retrieves people across images,
videos/movies, and live cameras.

It defines architectural responsibilities, execution semantics, resource
scheduling, persistence boundaries, recovery behavior, versioning, and
processing flows. It deliberately does **not** lock the system to a
particular face detector, recognition model, representation technique,
tracking algorithm, database engine, ML framework, or process topology
unless explicitly stated.

> Process visual media efficiently while preserving identity
> correctness, recoverability, provenance, user control, and a single
> source-independent visual memory.

## 2. Architectural Principles

1.  One global visual identity memory serves images, movies, and
    cameras.
2.  Detection, tracking, selection, representation, recognition,
    identity reasoning, memory consolidation, persistence, and retrieval
    remain conceptually distinct.
3.  Long-media processing is pipelined rather than executed as giant
    sequential phases.
4.  CPU and GPU workloads should overlap where useful.
5.  Queues are bounded and backpressure-aware.
6.  Offline and live workloads have different service objectives.
7.  Recognition is selective rather than performed on every detected
    face in every frame.
8.  Chunks are processing boundaries, never identity boundaries.
9.  Authoritative and derived state are explicitly distinguished.
10. Recovery, checkpointing, idempotency, and provenance are first-class
    concerns.
11. Model and processing versions are traceable.
12. User corrections and privacy operations override stale derived
    state.
13. Logical components do not imply microservices.
14. The initial runtime is a single-machine local system.

## 3. High-Level Architecture

``` text
                           APPLICATION
                                │
                         ┌──────▼──────┐
                         │ JOB MANAGER │
                         └──────┬──────┘
                                │
                       RESOURCE SCHEDULER
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
        CPU EXECUTOR       GPU EXECUTOR       I/O EXECUTOR
              │                 │                 │
              │          ┌──────▼──────┐          │
              │          │MODEL MANAGER│          │
              │          └──────┬──────┘          │
              └─────────────────┼─────────────────┘
                                ▼
                       PIPELINE RUNTIME
                                │
             ┌──────────────────┼──────────────────┐
             ▼                  ▼                  ▼
           IMAGE              MOVIE              CAMERA
             │                  │                  │
             └──────────────────┼──────────────────┘
                                ▼
               Decode / Detect / Track / Select
                                │
                         Represent / Recognize
                                │
                        IDENTITY REASONER
                                │
                      MEMORY CONSOLIDATION
                                │
                       AUTHORITATIVE STATE
                         ┌──────┴──────┐
                         ▼             ▼
                    PRIMARY DB    FILESYSTEM
                         │
                         ▼
                    INDEXING JOBS
                         │
                         ▼
                       QDRANT
                         │
                         ▼
                  UNIVERSAL SEARCH
```

Cross-cutting responsibilities include Storage Manager,
Checkpoint/Recovery Manager, Version & Provenance Manager,
Monitoring/Diagnostics, Feedback System, Training System, and
Backup/Restore.

## 4. Processing Capabilities

### Ingest

Accept images, videos/movies, image batches, and configured camera
sources. Imported media is validated, copied/moved into managed storage,
registered as a Source, inspected for metadata, and assigned a
processing Job.

### Decode / Preprocess

Produces usable image/frame data and any preprocessing required by
downstream components.

### Detect

Answers **where are faces?** A detection may include face region,
detector confidence, landmarks where supported, and detector provenance.
A detection does not automatically become a persistent Observation.

### Track

Answers **which observations belong to the same continuously visible
subject?** Tracking establishes continuity, not identity.

### Select

Chooses useful observations from detections/tracks for expensive
analysis or durable memory. This avoids processing/storing hundreds of
nearly identical frames. Selection may later consider quality,
diversity, clarity, visibility, temporal spacing, uncertainty, and other
signals.

### Represent

Produces machine-readable information suitable for recognition,
clustering, retrieval, or related reasoning. No particular
representation technique is mandated.

### Recognize

Answers **does this visual observation correspond to something already
encountered?** Recognition returns ranked hypotheses and permits an
explicit unknown/no-match result. It proposes; it does not directly
mutate identity memory.

### Identity Reasoning

Decides whether to associate with an existing Identity, make a tentative
association, create/promote a candidate Identity, reject candidates, or
flag uncertainty/conflict/review. It can combine recognition signals,
tracking consistency, evidence quality, identity state, negative
constraints, contradictions, co-occurrence, recurrence, and human
feedback.

### Memory Consolidation

Maintains curated active recognition memory separately from rich
historical memory. It can promote/demote evidence, choose active
evidence, update maturity/health, and rebuild derived recognition state.

### Persist

Commits authoritative structured state and authoritative binary
artifacts safely.

### Index

Updates derived retrieval/search structures such as Qdrant. Indexing
failure must not erase committed identity memory.

## 5. Jobs, Tasks, and Work Units

``` text
JOB
 └── TASK
      └── WORK UNIT
```

A **Job** is a user/system operation such as PROCESS_IMAGE,
PROCESS_VIDEO, PROCESS_CAMERA_SESSION, REPROCESS_SOURCE,
REBUILD_IDENTITY_MEMORY, REBUILD_SEARCH_INDEX, or TRAIN_COMPONENT.

Potential Job states are QUEUED, RUNNING, PAUSED, COMPLETED, FAILED, and
CANCELLED.

A **Task** is a logical stage or portion of a Job, such as decode,
detect, track, represent, reconcile, persist, or index.

A **Work Unit** is the smallest safely schedulable, retryable, and
deduplicatable unit, such as a detection batch, media chunk, persistence
batch, or identity-index update.

Durable Work Units require stable identity or equivalent idempotency
semantics so retries do not duplicate semantic results.

Jobs may form a local dependency DAG, for example:

``` text
PROCESS_MOVIE
      ↓
RECONCILE_MOVIE
      ↓
CONSOLIDATE_MEMORY
      ↓
FINALIZE_INDEX
```

## 6. Pipeline and Queue Model

Long media uses bounded streaming:

``` text
Decode
  ↓
bounded queue
  ↓
Detect
  ↓
Track
  ↓
Select
  ↓
Represent
  ↓
Recognize
  ↓
Identity Reason
  ↓
Persist
  ↓
Index
```

Queues are bounded by item count and/or estimated memory usage. A slow
downstream stage must not create unbounded intermediate work.

For finite offline workloads, saturation propagates upstream as
backpressure. For live cameras, stale low-value work may instead be
dropped to preserve bounded latency.

## 7. Resource Scheduling

The scheduler coordinates CPU, GPU compute, VRAM, RAM, disk I/O,
hardware decoding where available, database writes, and vector-index
work.

Service classes are:

-   **Interactive:** user-waiting Search and similar operations;
    optimize latency.
-   **Live:** camera processing; optimize bounded latency and
    continuity.
-   **Foreground batch:** movie processing, image imports, reprocessing;
    optimize throughput without breaking interactive/live
    responsiveness.
-   **Background:** indexing, consolidation, duplicate analysis,
    thumbnails.
-   **Maintenance/Training:** retraining, evaluation, deep
    reconciliation, cleanup.

Higher-priority interactive/live work may take precedence at safe Work
Unit boundaries, but lower-priority work must not be indefinitely
starved.

Preemption normally occurs between Work Units rather than by forcibly
terminating active kernels or corrupting durable operations.

## 8. V1 Offline Video Concurrency

Only **one offline video/movie processing Job executes at a time** in
V1.

``` text
Movie A    PROCESSING
Movie B    QUEUED
Movie C    QUEUED
```

This does not make Movie A single-threaded. The active movie can exploit
substantial internal CPU/GPU parallelism. Live camera, Search, and
lightweight/background operations may coexist where scheduling permits.

Future versions may make offline movie concurrency configurable if
benchmarks justify it.

## 9. Resource Modes

Resource Policy answers **how aggressively may the application use the
machine?**

-   **ADAPTIVE** --- default
-   **QUIET**
-   **BALANCED**
-   **PERFORMANCE**

Adaptive responds to sustained real resource pressure and machine
activity. It may reduce background pressure while the machine is
actively needed and expand throughput while resources are idle. It
should not oscillate merely because of mouse movement.

Explicit user overrides take precedence until changed.

Resource Policy is separate from Processing Policy, which answers **how
much analysis should be performed?** Future processing modes such as
Fast, Balanced Accuracy, or Maximum Accuracy may be defined later.

Thus these are both valid:

``` text
Resource Mode: Adaptive
Processing Mode: High Accuracy
```

``` text
Resource Mode: Performance
Processing Mode: High Accuracy
```

## 10. CPU, GPU, RAM, and Model Residency

The goal is minimum useful end-to-end processing time, not maximum
utilization of one component.

CPU and GPU work should overlap where beneficial. A global CPU
concurrency budget prevents independent pools from oversubscribing the
machine.

GPU-consuming workloads are centrally resource-aware through a logical
GPU Executor. A Model Manager tracks loaded models/components, device
location, RAM/VRAM cost, version, usage, and runtime compatibility.

The exact number of GPU processes/streams and CPU workers is
intentionally left to benchmarking.

The target has 32 GB RAM, but the application must leave appropriate
headroom for Windows, the UI, and other workloads. Under RAM pressure it
may reduce prefetching, queue depth, batches, or background work.

On GPU OOM, the runtime should where practical release safe temporary
memory, reduce batch size, evict optional resident models, and retry the
Work Unit. Universal CPU fallback is not required.

## 11. Disk Pressure

Storage Manager monitors free disk space and managed-storage usage.
Under critically low disk space, storage-producing work should safely
pause rather than exhausting the disk.

The user may free space, manage the Recycle Bin, remove media, or change
storage arrangements before resuming.

## 12. Image Execution Flow

``` text
Import
 ↓
Managed Storage
 ↓
Decode / Validate
 ↓
Detect all faces
 ↓
Quality / usability evaluation
 ↓
Materialize meaningful Observations
 ↓
Represent
 ↓
Retrieve recognition candidates
 ↓
Identity Reasoning
 ↓
Encounter / Appearance relationships
 ↓
Memory Consolidation
 ↓
Persist
 ↓
Index
```

Images normally need no temporal Track. Multiple faces are supported.
Co-occurrence may contribute contextual evidence without becoming an
absolute identity rule.

Large image imports use batch processing for GPU efficiency, progress,
pause/resume, and deduplication while each image remains its own Source.

## 13. Movie / Video Execution Flow

``` text
Managed Movie
 ↓
Inspect media metadata
 ↓
Create processing plan
 ↓
Decode chunks/frames
 ↓
Detect
 ↓
Track
 ↓
Select useful observations
 ↓
Represent / Recognize strategically
 ↓
Build appearances
 ↓
Movie-local reconciliation
 ↓
Global reconciliation
 ↓
Memory consolidation
 ↓
Finalize indexing
```

Chunks exist for bounded memory, progress, recovery, checkpointing,
scheduling, and possible parallelism. **Chunk boundary != identity
boundary.** Subject continuity across boundaries must be reconciled.

Recognition is selective. A subject visible for hundreds of frames
should not automatically generate hundreds of equivalent recognition
operations or retained crops.

Tracking establishes continuity; observation selection chooses useful
samples; recognition occurs early and then periodically/conditionally
according to uncertainty, quality, contradictions, scene changes, or
other adaptive signals.

Transient tracks and local unknown clusters can be reconciled before
unnecessarily polluting global memory:

``` text
Tracks
 ↓
Appearances
 ↓
Movie-local unknown clusters
 ↓
Compare with global memory
 ↓
Strong match → existing identity
No match → new candidate identity
Ambiguous → uncertain/review
```

A movie is not fully complete merely because decoding reached the final
frame. Required reconciliation, memory consolidation, and index
finalization must also reach a consistent state.

## 14. Live Camera Execution Flow

``` text
Camera
 ↓
Shallow frame buffer
 ↓
Detect
 ↓
Track
 ↓
Select
 ↓
Recognize
 ↓
Identity Reason
 ↓
Encounter management
 ↓
Memory consolidation
 ↓
Persist selected history/evidence
```

Live processing prioritizes bounded end-to-end latency over processing
every frame. If the pipeline cannot keep up, stale work may be
skipped/dropped rather than producing an ever-growing backlog.

Locked camera defaults:

-   continuous recording: OFF;
-   encounter history: ON;
-   selected face snapshots: ON;
-   automatic deletion: OFF.

Continuous visibility forms meaningful tracks/encounters rather than
thousands of user-facing per-frame appearances. When an encounter
closes, useful evidence can be consolidated.

After a camera/application interruption, the system does not fabricate
continuity across unobserved time.

## 15. Progressive Results, Progress, and ETA

People Found and related results may update while processing continues,
but partial counts must not be presented as final.

The UI should be able to expose:

-   source/file;
-   duration;
-   overall progress;
-   current stage;
-   current media position;
-   elapsed time;
-   ETA;
-   faces detected;
-   tracks created;
-   people discovered;
-   known identities;
-   new identities;
-   CPU/GPU utilization;
-   RAM/VRAM;
-   throughput;
-   Pause / Resume / Cancel.

Progress is not merely current frame divided by total frames. Stage
progress, reconciliation, and indexing also matter.

## 16. Persistence Architecture

Three storage domains have different responsibilities.

### Primary Database --- authoritative structured state

Stores Person, Identity, Source, Observation metadata, Track,
Appearance, Encounter, Jobs, Events, Feedback, relationships,
model/component versions, processing manifests, provenance, artifact
references, and lifecycle/deletion state.

The primary database must support robust transactions.

### Managed Filesystem --- authoritative binary/artifact storage

Stores original images, videos/movies, selected face crops, thumbnails,
selected camera snapshots, model files, large training/model artifacts,
and temporary processing artifacts.

### Qdrant --- derived vector retrieval state

Qdrant is the initial vector-database choice. It accelerates vector
retrieval but is **not identity memory itself**. Its loss or corruption
requires index rebuilding, not rediscovery of every Person from scratch.

The architecture remains portable enough to replace Qdrant if future
benchmarks justify another solution.

## 17. Storage Manager and Stable Artifacts

Large managed artifacts have stable artifact identities rather than
allowing arbitrary paths to become domain identity.

Conceptually:

``` text
Artifact A-1081
Type: ORIGINAL_MEDIA
Owner: Source S-81
Location: managed filesystem location
Integrity metadata: ...
State: AVAILABLE
```

Storage Manager owns path construction and physical layout.

Important artifacts retain enough integrity metadata to detect missing,
wrong, corrupt, or partial content. Exact checksum algorithms remain
open.

Persistent writes use crash-safe staging/finalization. A partially
written file is never considered valid merely because a final-looking
path exists.

Conceptual artifact conditions may include STAGING, AVAILABLE, RECYCLED,
DELETED, MISSING, and CORRUPT.

## 18. Artifact Recoverability

The system distinguishes conceptually between:

-   authoritative/non-regenerable content;
-   regenerable-from-source artifacts;
-   derived caches;
-   temporary artifacts.

Examples:

-   missing thumbnail → regenerate;
-   missing crop → potentially regenerate from surviving source media;
-   missing original movie → source-integrity problem;
-   missing Qdrant index → rebuild.

Unexpected file loss is not treated as an intentional privacy deletion.

## 19. Cross-Storage Consistency

The system does not pretend that the primary DB, filesystem, and Qdrant
participate in one distributed transaction.

Instead:

-   **Strong consistency** inside the primary DB for authoritative
    structured changes.
-   **Recoverable consistency** between DB and filesystem through
    Storage Manager reconciliation.
-   **Eventual consistency** between authoritative state and
    Qdrant/search indexes.

Storage Manager detects DB references to missing files, orphan managed
files, unfinished staged artifacts, corruption, and regenerable
artifacts.

## 20. Qdrant Semantics

A successful authoritative commit may survive a failed Qdrant update:

``` text
Primary DB ✓
Filesystem ✓
Qdrant ✕
```

The index becomes dirty/pending and is retried/rebuilt asynchronously.

Vector entries should primarily reference stable authoritative IDs such
as observation ID, identity ID, and representation version. Names copied
into vector metadata are not semantic truth.

Retrieval follows conceptually:

``` text
Qdrant candidate IDs
 ↓
Authoritative Resolver
 ↓
current Identity / Person state
 ↓
ranking / presentation
```

This allows current names, merges, deletions, Forget operations, and
corrections to override temporarily stale vector metadata.

## 21. Representation Versioning

Representations belong to explicit representation spaces.

If R4 and R5 are incompatible, R4 vectors must not be silently compared
with R5 vectors.

The physical solution may use versioned Qdrant collections, namespaces,
filters, or another safe strategy.

Derived state should be rebuildable from retained authoritative evidence
where possible.

## 22. Frozen Processing Manifests

Substantial Jobs freeze relevant configuration at start, including
detector, tracker, representation, recognizer, reasoner, processing
configuration, and relevant source/version information.

If a new representation model is promoted while a movie is 40% complete,
the remaining 60% does not silently switch models.

The existing Job normally finishes with its frozen manifest; later
reprocessing may migrate the Source.

## 23. Dependency-Aware Reprocessing

Conceptually:

``` text
Original Media
 ↓
Detections
 ↓
Tracks
 ↓
Observations
 ↓
Representations
 ↓
Recognition
 ↓
Identity Decisions
 ↓
Search Index
```

A component change invalidates only affected stages and dependent
downstream state where compatibility permits.

A Search Ranker upgrade, for example, should not require decoding every
movie again.

## 24. Checkpointing and Crash Recovery

A checkpoint may claim completion only when the output required for
recovery has been durably committed.

**COMPUTED != COMMITTED.**

Anything existing only in RAM, VRAM, temporary tensors, or uncommitted
queues is disposable after a crash.

Example:

``` text
Chunk 1 COMMITTED
Chunk 2 COMMITTED
Chunk 3 COMMITTED
Chunk 4 INCOMPLETE
```

After force-kill, crash, or power loss, the system resumes/reconciles
Chunk 4 rather than restarting the movie.

Durable retries are idempotent/deduplicatable.

A local heartbeat/lease concept may identify abandoned RUNNING Jobs.

Interrupted offline Jobs do **not** automatically resume by default
after application restart. The UI shows preserved progress and allows
Resume or Cancel. Automatic resume may later be an optional setting.

## 25. Graceful Exit, Camera Recovery, and Search Recovery

On graceful exit the application should where practical stop scheduling
new offline work, secure the current safe unit, checkpoint, pause the
active offline Job, and close resources.

After a crash, camera sessions close or become interrupted and a new
session begins after restart; continuity is not fabricated.

Ordinary Search requests are ephemeral and do not require recovery.
Explicit durable actions such as feedback do.

## 26. Cancellation

For durable Jobs:

1.  mark cancellation requested;
2.  stop generating new work;
3.  discard queued work where safe;
4.  allow active work to reach a safe boundary;
5.  checkpoint/clean up;
6.  mark CANCELLED.

Cancelling processing does not delete the managed original media.

## 27. Model Training, Evaluation, and Promotion

Training never overwrites the current production component directly.

``` text
Current Production
       │
Feedback / Training
       ↓
Candidate
       ↓
Evaluation
   ┌───┴───┐
 reject   eligible
           ↓
        Promote
```

A training/evaluation crash leaves production untouched.

Representation migrations may build new versioned derived state while
the old active version continues serving the application. A failed 70%
rebuild therefore does not destroy the active version.

## 28. Identity Corrections and Derived State

Rename, merge, split, reassignment, and strong feedback commit
authoritative structural changes transactionally.

Derived Qdrant/search updates may follow asynchronously.

If a merge commits but the application crashes before Qdrant updates,
the merge remains authoritative and index repair follows later.

Invalid derived state affected by a split may be marked stale and
recognition can be conservatively degraded until rebuilding finishes.

## 29. Forget Person and Permanent Source Deletion

Privacy operations take logical effect before asynchronous cleanup
finishes.

After Forget Person commits:

-   the Person is immediately ineligible for active recognition;
-   active user-facing name/search resolution is removed;
-   relevant persistent identity memory is logically disabled;
-   derived cleanup follows.

Stale Qdrant entries cannot resurrect the Person because authoritative
resolution filters them.

Permanent source deletion works similarly: source-derived evidence
becomes logically invalid immediately, then physical
media/artifact/index cleanup completes.

Delete Media remains distinct from Forget Person.

## 30. Recycle Bin

Moving a Source to Recycle Bin is not permanent deletion.

While recycled, the original media and associated evidence remain
recoverable, normal Search excludes the Source, and restoration should
normally avoid reprocessing.

Permanent deletion performs destructive invalidation and cleanup.

## 31. Backup and Restore

The primary database and critical configuration receive automatic
rotating local backups with bounded retention.

Routine backups do **not** automatically duplicate the full managed
media library.

A future **Export / Backup Library** operation may intentionally include
DB, configuration, managed media, required artifacts, and relevant
version metadata.

Older rotating backups may temporarily contain information later
forgotten/deleted until those backups expire. Restore must reconcile
against deletion/forget information so an older backup does not silently
resurrect intentionally erased active memory.

Qdrant does not require precious-data backup semantics because it is
rebuildable.

## 32. Storage Integrity and Degraded Search

Storage Manager should support library verification/repair for missing
originals, crops, thumbnails, corrupt artifacts, orphan artifacts, and
regenerable artifacts.

If Qdrant is unavailable or rebuilding, metadata/name search may remain
available while face/vector search is degraded. The UI should
communicate degraded capabilities instead of returning misleadingly
empty results.

## 33. Monitoring and Diagnostics

Capture useful stage-level telemetry:

-   decode/detection/tracking/recognition throughput;
-   queue depths;
-   batch sizes;
-   stage latency;
-   CPU/GPU utilization;
-   RAM/VRAM;
-   disk throughput;
-   retries and failures.

Operational logs are separate from Identity Events. A GPU OOM is not
part of a person's identity history.

Diagnostics should avoid unnecessarily storing raw face images,
biometric representations, personal names, or other sensitive content.

## 34. Target Hardware

Primary development/benchmark target:

-   Lenovo Legion 7i;
-   Product number 83FD0015US;
-   Intel Core i9-14900HX;
-   32 GB RAM;
-   NVIDIA GeForce RTX 4070 Laptop GPU;
-   8 GB VRAM;
-   approximately 1 TB internal storage.

Hardware informs benchmarking but does not define hardcoded worker
counts, queue sizes, batch sizes, or device allocation.

Those must be measured.

## 35. Process Topology

Job Manager, Scheduler, GPU Executor, Storage Manager, Identity
Reasoner, Search, and related names are architectural responsibilities.

They do **not** imply separate Docker containers, HTTP services,
databases, or microservices.

The initial implementation remains a modular single-machine local
application. Process isolation may be introduced later only when
justified.

## 36. Locked Processing Invariants

1.  **Global Memory:** all source types contribute to one
    source-independent identity memory.
2.  **Bounded Work:** no stage creates unbounded intermediate work
    because a downstream stage is slower.
3.  **Live Latency:** live processing prioritizes bounded latency over
    processing every frame.
4.  **Chunk Independence:** chunk boundaries never define identity
    boundaries.
5.  **Selective Recognition:** detection/tracking does not imply
    recognition on every frame.
6.  **Authoritative State:** primary DB is authoritative structured
    state; managed filesystem is authoritative retained binary/artifact
    storage.
7.  **Derived Index:** Qdrant/vector indexes are rebuildable and cannot
    constitute identity memory.
8.  **Stable References:** derived indexes refer back to stable
    authoritative IDs.
9.  **Representation Compatibility:** incompatible representation spaces
    are never silently compared.
10. **Frozen Manifest:** substantial Jobs use stable processing
    manifests for their lifetime unless explicitly cancelled/restarted.
11. **Checkpoint:** Work Units are not checkpoint-complete until
    required recovery state is durable.
12. **Idempotency:** retried durable Work Units do not duplicate
    semantic results.
13. **Recovery:** interrupted long-running processing resumes from safe
    committed work rather than restarting unnecessarily.
14. **Privacy Precedence:** Forget/Delete semantics take effect before
    asynchronous derived cleanup finishes.
15. **Production Model Safety:** incomplete or unevaluated candidate
    models never silently replace active production components.
16. **Resource/Quality Separation:** hardware aggressiveness and
    analysis quality are independent policies.
17. **Single-Movie V1:** only one offline movie/video Job executes at
    once, while internal parallelism and higher-priority concurrent
    workloads remain allowed.

## 37. Explicitly Open Decisions

This architecture does not yet select:

-   exact face detector;
-   exact tracker;
-   exact representation/recognition model;
-   CNN vs transformer vs metric-learning vs other representation
    approach;
-   pretrained vs fine-tuned vs custom-trained model;
-   exact quality model;
-   recognition thresholds;
-   clustering/reconciliation algorithms;
-   primary database engine;
-   Qdrant collection layout;
-   vector dimensionality;
-   CPU/GPU worker counts;
-   batch sizes;
-   queue capacities;
-   media chunk strategy;
-   live latency target;
-   camera reconnect timeout;
-   exact Resource Mode ceilings;
-   exact Processing Mode definitions;
-   backup cadence/retention;
-   filesystem directory layout;
-   process/thread topology;
-   training framework;
-   Search ranking architecture.

These belong to later data-model, model/algorithm research,
benchmarking, technology-selection, and implementation phases.

## 38. Next Architecture Layer

The next planning layer is **Universal Search & Retrieval Architecture
v1**, covering:

-   query types;
-   text/name retrieval;
-   uploaded/camera-captured face queries;
-   mixed face + text/context queries;
-   People, Media, Occurrence, Appearance, and Encounter retrieval;
-   co-occurrence queries;
-   heterogeneous Top results;
-   candidate generation;
-   score normalization;
-   ranking/fusion;
-   filters;
-   incomplete-library semantics;
-   index responsibilities;
-   feedback/ranking-learning behavior;
-   the boundary between recognition confidence and search relevance.

## 39. Status

**Processing Architecture v1.0 is locked as the architectural
baseline.**

Implementation may optimize or replace internal techniques without
changing the guarantees defined here. Material architectural changes
should be explicitly versioned rather than silently introduced.
