# API & Internal Contracts

## 1. Purpose

This document defines the application-facing and internal contracts for the local visual identity and face-memory desktop application.

It translates the product, domain, system, and implementation architecture into explicit boundaries between:

- React and FastAPI
- FastAPI routes and application use cases
- application services and persistence
- FastAPI and the ML worker
- application code and filesystem storage
- application code and the vector index
- persistent jobs and their executors
- runtime/model management and ML execution
- mutable user settings and immutable processing configuration
- SQLite transactions and external side effects

This document is an implementation contract.

It should be treated as authoritative for API shape, subsystem responsibilities, ownership boundaries, and cross-component behavior unless superseded by a later documented architectural decision.

---

# 2. Core Contract Principles

The following rules apply throughout the system.

## 2.1 Query is not ingest

Searching with an image must not create persistent memory merely because the system recognizes a face.

```text
Query
→ reads existing memory
→ ephemeral computation
→ no Source
→ no Observation
→ no Evidence
→ no Identity mutation
```

Persistent state is created only through explicit ingest, import, processing, correction, or memory operations.

---

## 2.2 Model output is evidence, not truth

ML output does not directly create authoritative identity truth.

```text
ML output
    ↓
RecognitionAssessment
    ↓
Identity reasoning
    ↓
authoritative domain decision
```

The ML worker never independently creates:

- Person
- Identity
- IdentityAssociation
- Evidence
- semantic memory

---

## 2.3 SQLite is authoritative

SQLite owns authoritative relational state.

USearch, caches, thumbnails, temporary artifacts, runtime caches, and other reconstructible state are derived.

Deleting the ANN index must cause temporary search degradation, not memory loss.

---

## 2.4 Jobs are not transactions

A long-running processing operation may contain many short transactions.

```text
Job
├── compute
├── transaction
├── checkpoint
├── compute
├── transaction
├── checkpoint
└── ...
```

No transaction should remain open across expensive media or ML processing.

---

## 2.5 REST is authoritative

WebSocket messages provide live notifications.

They are not authoritative application state.

On reconnection, sequence gaps, or uncertainty, the frontend refetches state through REST.

---

# 3. API Versioning

Application API routes use:

```text
/api/v1/
```

Health probes remain outside the versioned application API:

```http
GET /health
GET /readiness
```

`/health` answers whether the backend process is alive.

`/readiness` answers whether required application capabilities are sufficiently initialized.

The application may be usable in a degraded state when reconstructible capabilities such as ANN search are unavailable.

---

# 4. REST Resource Structure

Primary resources:

```text
sources
artifacts
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

The REST API describes application capabilities rather than mirroring the ERD.

Internal concepts such as the following do not automatically receive CRUD endpoints:

- IdentityAssociation
- RecognitionResult
- ExecutionSegment
- IndexOperation
- RuntimeVariant
- ModelExport

---

# 5. Source API

## 5.1 Import

```http
POST /api/v1/sources/import
```

Import creates application knowledge of a source.

Import does not automatically mean process.

The command supports the application's storage semantics:

```text
MANAGED
REFERENCED
```

For managed imports, application-owned bytes are copied into managed storage.

For referenced imports, the application stores a verified reference to an external user-owned file.

Referenced originals are never deleted by the application.

---

## 5.2 Source queries

```http
GET /api/v1/sources
GET /api/v1/sources/{source_id}
```

Related resources:

```http
GET /api/v1/sources/{source_id}/observations
GET /api/v1/sources/{source_id}/occurrences
GET /api/v1/sources/{source_id}/people
GET /api/v1/sources/{source_id}/identities
GET /api/v1/sources/{source_id}/processing-runs
```

---

## 5.3 Process

```http
POST /api/v1/sources/{source_id}/process
```

Processing is asynchronous.

The command:

1. validates the source
2. resolves processing configuration
3. creates an immutable ProcessingConfigurationSnapshot
4. creates a ProcessingRun
5. creates a PROCESS_SOURCE Job
6. commits them atomically
7. wakes the scheduler after commit

Response:

```http
202 Accepted
```

The response contains trackable Job and ProcessingRun resources.

---

## 5.4 Reprocess

```http
POST /api/v1/sources/{source_id}/reprocess
```

Reprocessing creates:

- a new ProcessingRun
- a new configuration snapshot
- a new Job

Historical processing provenance is preserved.

---

## 5.5 Recycle

```http
DELETE /api/v1/sources/{source_id}
```

This performs logical recycling.

It does not normally move physical media.

A successful request may return:

```http
204 No Content
```

---

## 5.6 Restore

```http
POST /api/v1/sources/{source_id}/restore
```

Restores a logically recycled Source where possible.

---

## 5.7 Permanent deletion

```http
POST /api/v1/sources/{source_id}/permanent-delete
```

Permanent deletion removes application-owned managed artifacts according to retention and reference rules.

For REFERENCED media, the external original is never physically deleted.

---

# 6. Processing Runs

```http
GET  /api/v1/processing-runs
GET  /api/v1/processing-runs/{run_id}
GET  /api/v1/processing-runs/{run_id}/segments
GET  /api/v1/processing-runs/{run_id}/progress

POST /api/v1/processing-runs/{run_id}/pause
POST /api/v1/processing-runs/{run_id}/resume
POST /api/v1/processing-runs/{run_id}/cancel
POST /api/v1/processing-runs/{run_id}/retry
```

A ProcessingRun represents logical processing history and provenance.

A Job represents schedulable/executable work.

They are related but not equivalent.

---

# 7. People API

A Person represents semantic human identity.

```http
POST  /api/v1/people
GET   /api/v1/people
GET   /api/v1/people/{person_id}
PATCH /api/v1/people/{person_id}
DELETE /api/v1/people/{person_id}
```

Related resources:

```http
GET /api/v1/people/{person_id}/identities
GET /api/v1/people/{person_id}/occurrences
GET /api/v1/people/{person_id}/sources
GET /api/v1/people/{person_id}/evidence
```

Identity assignment:

```http
POST /api/v1/people/{person_id}/assign-identity
POST /api/v1/people/{person_id}/remove-identity
```

These operations represent semantic human corrections.

They must not be implemented as raw foreign-key edits without correction/evidence history.

One Person may own multiple visual Identities.

An unknown Identity does not require a fake Person.

---

# 8. Identity API

An Identity represents persistent visual identity.

```http
GET /api/v1/identities
GET /api/v1/identities/{identity_id}
```

Related resources:

```http
GET /api/v1/identities/{identity_id}/observations
GET /api/v1/identities/{identity_id}/occurrences
GET /api/v1/identities/{identity_id}/evidence
GET /api/v1/identities/{identity_id}/sources
```

---

## 8.1 Merge

```http
POST /api/v1/identities/merge
```

Conceptual request:

```json
{
  "identity_ids": ["...", "..."],
  "preferred_identity_id": "..."
}
```

Merge is a domain operation, not CRUD.

It may affect:

- identity associations
- Person relationships
- Evidence
- Occurrences
- memory state
- representation eligibility
- IndexOperations
- correction history

---

## 8.2 Split

```http
POST /api/v1/identities/{identity_id}/split
```

A split identifies selected observations/evidence that should form a new Identity.

The backend reconstructs the resulting memory and index state.

---

## 8.3 Forget

```http
POST /api/v1/identities/{identity_id}/forget
```

Forgetting is a semantic memory operation.

It is not equivalent to generic DELETE.

It may:

- retire biometric representations
- remove index eligibility
- create REMOVE IndexOperations
- remove or retain evidence according to policy
- schedule eligible managed artifacts for deletion
- preserve necessary correction/deletion history

---

# 9. Observations

Observations are system-generated.

Normal API access is primarily read-only:

```http
GET /api/v1/observations
GET /api/v1/observations/{observation_id}
```

The normal frontend does not POST arbitrary observations.

A conceptual observation response includes:

```text
id
source_id
normalized bounding box
face crop media reference
identity if known
person if known
timestamp/frame metadata where applicable
created_at
```

Bounding boxes use normalized coordinates.

---

# 10. Occurrences

```http
GET /api/v1/occurrences
GET /api/v1/occurrences/{occurrence_id}
```

Filters may include:

```text
person_id
identity_id
source_id
```

For video/camera sources, occurrences may later include:

```text
start_ms
end_ms
representative preview
```

---

# 11. Evidence

```http
GET /api/v1/evidence
GET /api/v1/evidence/{evidence_id}
```

Evidence may include types such as:

```text
RECOGNITION
HUMAN_CORRECTION
```

Recognition evidence distinguishes:

```text
raw similarity
calibrated confidence
decision
```

These concepts must never be conflated.

Full evidence details may expose model/runtime/calibration provenance for advanced inspection.

Normal UI responses should avoid unnecessary raw ML diagnostics.

---

# 12. Search

## 12.1 General search

```http
GET /api/v1/search?q=alice
```

Search may return heterogeneous results such as:

- Person
- Identity
- Source
- Occurrence
- visual match

---

## 12.2 Face search

```http
POST /api/v1/search/face
```

Face search is logically a query even though POST is used for binary/body input.

Flow:

```text
temporary input
→ decode
→ detect
→ represent
→ ANN candidate retrieval
→ authoritative SQLite revalidation
→ recognition/calibration
→ ranking
→ response
→ temporary cleanup
```

By default it creates no:

- Source
- Observation
- Identity
- Evidence
- persistent memory

Persistence requires an explicit later command such as import/save/use-as-evidence.

Repeating the same face search must not grow memory.

---

# 13. Jobs

Initial Job types:

```text
PROCESS_SOURCE
REPROCESS_SOURCE
REBUILD_INDEX
RETRAIN_MODEL
INSTALL_RUNTIME
CLEAN_STORAGE
```

Job API:

```http
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}

POST /api/v1/jobs/{job_id}/pause
POST /api/v1/jobs/{job_id}/resume
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
```

---

# 14. Job State Machine

States:

```text
QUEUED
RUNNING
PAUSING
PAUSED
CANCELLING
CANCELLED
COMPLETED
FAILED
INTERRUPTED
```

Normal lifecycle:

```text
QUEUED
  ↓
RUNNING
 ├──────────────→ COMPLETED
 ├──────────────→ FAILED
 │
 ├→ PAUSING → PAUSED → QUEUED
 │
 └→ CANCELLING → CANCELLED
```

Unexpected loss of active execution may result in:

```text
INTERRUPTED
```

Active/transitional work discovered after process crash is not silently treated as still running.

---

# 15. Resume vs Retry

Resume continues a paused Job.

```text
PAUSED
→ QUEUED
→ RUNNING
```

Retry creates a new Job attempt linked to the previous Job.

Conceptually:

```text
Job B.retry_of_job_id = Job A.id
```

Terminal Job history is not rewritten.

For resumable processing, a retry may continue the same logical ProcessingRun from a valid checkpoint with a new ExecutionSegment.

Explicit source reprocessing creates a new ProcessingRun.

---

# 16. Job Priority

Priorities:

```text
INTERACTIVE
HIGH
NORMAL
LOW
MAINTENANCE
```

Scheduling is cooperative.

V1 supports one heavy movie-processing pipeline at a time.

The scheduler must not evolve into a general distributed resource scheduler without measured need.

---

# 17. Progress Contract

Progress supports:

```text
DETERMINATE
INDETERMINATE
```

Determinate:

```json
{
  "mode": "DETERMINATE",
  "completed": 43,
  "total": 100,
  "fraction": 0.43
}
```

Indeterminate:

```json
{
  "mode": "INDETERMINATE",
  "message": "Analyzing media"
}
```

No fake percentages.

`fraction` is derived from `completed / total`.

Progress is informational.

A checkpoint is durable recovery state.

They are not the same concept.

---

# 18. Checkpoints

A checkpoint means:

> All work before this point is durably settled enough that execution can safely resume from here.

Checkpoint payloads are job-specific and versioned.

For processing they may include:

```text
processing_run_id
source position
completed chunk/segment
durable output watermark
created_at
```

Pause reaches a safe checkpoint before transitioning to PAUSED.

Checkpoint advancement must never move ahead of durable output.

---

# 19. API Response Conventions

Use:

```text
200 OK
→ synchronous success with body

201 Created
→ resource created synchronously

202 Accepted
→ durable asynchronous operation accepted

204 No Content
→ successful operation with no useful response body
```

Async responses must provide trackable resources.

Do not return only:

```json
{
  "message": "Started"
}
```

A processing command should return Job and ProcessingRun identifiers.

---

# 20. API Schema Conventions

API schemas represent application concepts, not database rows.

Use explicit Pydantic request and response schemas.

Do not directly serialize SQLAlchemy models as the public API contract.

IDs are UUIDs internally and opaque strings to the frontend.

Timestamps are timezone-aware ISO-8601 UTC values.

Enums use stable uppercase machine values.

Example:

```text
AVAILABLE
MISSING
RUNNING
COMPLETED
```

---

# 21. Summary vs Detail

Collection endpoints return compact summaries.

Detail endpoints return richer resources.

Example Source summary:

```text
id
type
display_name
availability
processing_status
thumbnail
created_at
updated_at
```

Source detail may additionally include:

```text
storage_mode
media metadata
artifact information
latest_processing_run
counts
deletion state
```

Physical filesystem paths are not normally exposed.

---

# 22. Media References

API resources refer to media through an abstract MediaReference.

Conceptually:

```json
{
  "id": "...",
  "kind": "FACE_CROP",
  "url": "/api/v1/media/...",
  "content_type": "image/jpeg"
}
```

Optional dimensions may be included.

No filesystem path is exposed to ordinary frontend code.

---

# 23. Error Contract

All REST errors use one shape:

```json
{
  "error": {
    "code": "SOURCE_NOT_FOUND",
    "message": "The requested source could not be found.",
    "details": null,
    "retryable": false,
    "diagnostic_id": "..."
  }
}
```

Fields:

```text
code
→ stable semantic machine code

message
→ safe human-readable description

details
→ structured contextual data where useful

retryable
→ whether repeating the operation may succeed

diagnostic_id
→ optional correlation identifier for logs
```

---

# 24. Error Codes

Representative codes:

```text
SOURCE_NOT_FOUND
SOURCE_UNAVAILABLE
SOURCE_ALREADY_PROCESSING

PERSON_NOT_FOUND

IDENTITY_NOT_FOUND
IDENTITY_MERGE_CONFLICT
IDENTITY_SPLIT_INVALID

JOB_NOT_FOUND
JOB_INVALID_TRANSITION

MEDIA_NOT_FOUND
MEDIA_UNAVAILABLE
MEDIA_CORRUPT
MEDIA_FORMAT_UNSUPPORTED
SOURCE_FILE_MISSING
SOURCE_RELOCATION_REQUIRED

RUNTIME_UNAVAILABLE
RUNTIME_PACKAGE_INVALID

ML_WORKER_UNAVAILABLE
ML_INFERENCE_FAILED

INDEX_UNAVAILABLE
SEARCH_INDEX_REBUILDING

VALIDATION_ERROR
INVALID_CURSOR
CONFLICT
INTERNAL_ERROR
```

Expected application errors are deliberately mapped.

Unexpected errors return `INTERNAL_ERROR` and a diagnostic ID without exposing tracebacks.

---

# 25. HTTP Error Semantics

Use conventional status codes:

```text
400
→ malformed semantic request

404
→ resource not found

409
→ current state conflicts with requested transition

413
→ payload too large

415
→ unsupported media type

422
→ validation failure

500
→ unexpected internal failure

503
→ required capability temporarily unavailable
```

FastAPI/Pydantic validation errors are normalized into the same application error shape.

---

# 26. Pagination

Growing collections use cursor/keyset pagination.

Response:

```json
{
  "items": [],
  "page": {
    "next_cursor": "...",
    "has_more": true
  }
}
```

Default:

```text
limit = 50
```

Maximum:

```text
limit = 200
```

The cursor is opaque.

It may encode:

- sort value
- unique ID tie-breaker
- query/sort context
- cursor version

Cursor pagination is forward-only in V1.

---

# 27. Pagination Rules

Ordering must be deterministic.

Every ordering includes a unique tie-breaker.

Queries normally fetch:

```text
limit + 1
```

to determine `has_more`.

`total_count` is not required.

A cursor is valid only for the query/filter/sort context for which it was created.

Invalid cursors return:

```text
400 INVALID_CURSOR
```

---

# 28. Face Search Pagination

ANN face search does not use cursor pagination initially.

It uses bounded:

```text
top_k
limit
```

because the uploaded query face is ephemeral and ANN ranking is fundamentally different from ordinary relational list pagination.

---

# 29. Media Delivery

Metadata travels as JSON.

Media bytes use dedicated endpoints.

```http
GET /api/v1/media/{media_id}
GET /api/v1/sources/{source_id}/media
```

Possible derived media kinds:

```text
THUMBNAIL
FACE_CROP
PREVIEW
VIDEO_FRAME
```

Do not embed ordinary media as base64 in JSON.

---

# 30. Media HTTP Behavior

Images should use appropriate:

```text
Content-Type
ETag
Cache-Control
```

Large media is streamed.

Video delivery should support HTTP Range requests when implemented.

A future frame endpoint may look like:

```http
GET /api/v1/sources/{source_id}/frame?timestamp_ms=...
```

No arbitrary filesystem-serving endpoint is allowed.

---

# 31. WebSocket

One primary event connection:

```text
WS /api/v1/events
```

REST remains authoritative.

WebSocket is used for:

- progress notification
- state-change notification
- runtime fallback notification
- index/runtime status changes
- future camera notifications

---

# 32. WebSocket Envelope

```json
{
  "version": 1,
  "event_id": "...",
  "sequence": 1842,
  "type": "processing_run.updated",
  "occurred_at": "2026-01-01T00:00:00Z",
  "resource": {
    "type": "processing_run",
    "id": "..."
  },
  "data": {}
}
```

Fields:

```text
version
event_id
sequence
type
occurred_at
resource
data
```

---

# 33. WebSocket Event Namespaces

Examples:

```text
job.*
processing_run.*
source.*
identity.*
person.*
runtime.*
worker.*
index.*
system.*
camera.*      future
```

Events are notifications.

The frontend should normally invalidate/refetch authoritative REST data instead of reconstructing complex state exclusively from events.

---

# 34. WebSocket Reliability

Delivery is not treated as exactly-once.

Events may occasionally be:

```text
duplicated
missed
coalesced
```

`sequence` allows the frontend to detect gaps.

On reconnect or sequence uncertainty:

```text
refetch through REST
```

No durable WebSocket replay/event-sourcing system is required.

---

# 35. ML Worker Boundary

FastAPI communicates with one persistent ML worker process.

Control plane:

```text
multiprocessing.Connection
```

Large-data plane:

```text
multiprocessing.SharedMemory
```

The worker owns loaded inference sessions.

The worker has no direct SQLite dependency.

---

# 36. MLRequest

Base conceptual structure:

```text
MLRequest
├── version
├── request_id
├── operation
├── component
├── input
├── options
└── execution_context
```

`request_id` correlates request and response.

Execution context may include:

```text
job_id
processing_run_id
execution_segment_id
```

for diagnostics/provenance correlation.

---

# 37. ML Operations

Initial operations:

```text
DETECT_FACES
GENERATE_REPRESENTATIONS
```

Potential:

```text
ASSESS_FACE_QUALITY
```

only if the selected quality approach genuinely warrants a model-backed worker operation.

The worker does not expose application-domain operations such as:

```text
RECOGNIZE_PERSON
CREATE_IDENTITY
REMEMBER
MERGE_IDENTITIES
FIND_PERSON
```

---

# 38. Detection Contract

Detection input uses decoded image/frame data, normally through SharedMemory.

Recommended canonical representation:

```text
RGB
uint8
HWC
contiguous
orientation already applied
```

Exact preprocessing is finalized with the selected detector.

Output includes:

```text
input_index
detection_index
normalized bounding box
detection score
optional landmarks
```

Zero detected faces is a successful result, not an inference error.

---

# 39. Representation Contract

Representation generation receives:

```text
frame/image
face geometry
optional landmarks
```

The representation component owns model-specific:

```text
alignment
resize
normalization
tensor conversion
output normalization
```

Output includes:

```text
input_index
face_index
dimension
dtype
normalization information
embedding
```

The system must not assume a permanent fixed embedding dimension such as 512.

---

# 40. Representation Spaces

Every durable representation belongs to a semantic RepresentationSpace.

RepresentationSpace determines whether vectors may legitimately be compared.

It defines concepts such as:

```text
dimension
dtype
normalization
distance/similarity metric
semantic compatibility
```

Two models producing the same vector dimension are not automatically compatible.

Separate incompatible spaces use separate ANN indexes.

---

# 41. MLResponse

Every accepted MLRequest terminates as:

```text
SUCCESS
ERROR
```

unless the worker/process/IPC itself fails.

Conceptual structure:

```text
MLResponse
├── version
├── request_id
├── status
├── output
├── execution
├── timings
└── error
```

---

# 42. ML Execution Provenance

Every response reports actual execution information such as:

```text
component_version_id
runtime_variant_id
provider
device
```

The worker must not silently change from CUDA to CPU.

Runtime fallback is controlled by FastAPI.

---

# 43. ML Error Codes

Representative worker errors:

```text
INVALID_REQUEST
UNSUPPORTED_PROTOCOL_VERSION

COMPONENT_NOT_AVAILABLE
COMPONENT_LOAD_FAILED

RUNTIME_VARIANT_NOT_AVAILABLE
RUNTIME_INITIALIZATION_FAILED

INVALID_INPUT
INFERENCE_FAILED
OUT_OF_MEMORY

SHARED_MEMORY_UNAVAILABLE
SHARED_MEMORY_INVALID

INTERNAL_WORKER_ERROR
```

A worker crash may produce no MLResponse.

The supervisor handles that separately.

---

# 44. SharedMemory Descriptor

Large inputs/outputs are transferred using descriptors rather than copying through the control channel.

Conceptually:

```text
SharedMemoryDescriptor
├── name
├── size_bytes
├── dtype
├── shape
├── strides
├── layout
└── readonly
```

Descriptors are validated before access.

---

# 45. SharedMemory Ownership

Core rule:

> The creator owns lifetime.

For FastAPI-created input:

```text
FastAPI allocates
→ worker reads
→ terminal response
→ FastAPI closes/unlinks
```

For worker-created output:

```text
worker allocates
→ FastAPI reads/copies/persists
→ RELEASE_OUTPUT
→ worker unlinks
```

The receiver does not silently assume ownership.

---

# 46. SharedMemory Recovery

Each process tracks owned segments in memory.

On worker death:

```text
FastAPI cleans its input segments
```

On parent loss:

```text
worker cleans owned outputs and exits
```

On whole-application crash:

```text
startup performs best-effort stale application-owned SharedMemory cleanup
```

SharedMemory is never authoritative state.

---

# 47. ML Worker Lifecycle

Ownership:

```text
Tauri
  ↓
FastAPI
  ↓
MLSupervisor
  ↓
ML Worker
```

Worker lifecycle conceptually includes:

```text
STOPPED
STARTING
READY
BUSY
STOPPING
UNAVAILABLE
FAILED
```

`READY` means the worker process and IPC protocol are usable.

It does not require every model to be preloaded.

Components are loaded lazily.

---

# 48. Worker Handshake

Conceptually:

```text
Worker → HELLO
FastAPI → INITIALIZE
Worker → READY
```

HELLO includes:

```text
protocol_version
worker_instance_id
capabilities
```

The worker instance ID is ephemeral diagnostic identity.

---

# 49. Worker Control Messages

Initial protocol includes concepts such as:

```text
HELLO
INITIALIZE
READY

EXECUTE
RESPONSE

RELEASE_OUTPUT

PING
PONG

SHUTDOWN
SHUTDOWN_ACK
```

The protocol remains intentionally small.

---

# 50. Worker Failure

Failure levels are distinct:

```text
operation failure
component/runtime failure
worker/process failure
```

Operation failures return MLResponse errors.

Component/runtime failures may trigger backend fallback.

Worker/process failure is handled by MLSupervisor.

The supervisor may perform bounded automatic restart.

Crash loops transition ML capability to FAILED/UNAVAILABLE rather than restarting forever.

---

# 51. StorageManager

Core rule:

> SQLite owns meaning. The filesystem owns bytes. StorageManager is the controlled boundary between them.

StorageManager owns:

- managed imports
- referenced-file inspection
- artifact creation
- byte access
- streaming
- range reads
- integrity verification
- relink verification
- managed physical deletion
- temporary workspaces
- storage usage
- conservative cleanup

StorageManager does not decide:

- whether a Source should be deleted
- whether an Identity should be forgotten
- which face should represent a Person
- whether Evidence should be retained
- whether a ProcessingRun succeeded

---

# 52. Storage Modes

```text
MANAGED
REFERENCED
```

MANAGED means application-owned bytes.

REFERENCED means external user-owned bytes.

The application may delete MANAGED bytes when domain rules permit.

The application never deletes REFERENCED originals.

---

# 53. Artifact Metadata

Conceptual Artifact metadata includes:

```text
id
kind
storage_mode
availability
content_type
size
hash
storage key or referenced location
created_at
```

Ordinary feature code should not depend on absolute physical paths.

Managed storage uses stable application-controlled storage keys.

---

# 54. Artifact Kinds

Initial conceptual kinds:

```text
SOURCE_ORIGINAL
THUMBNAIL
FACE_CROP
PREVIEW
EXPORT
```

Runtime/model artifacts remain under the specialized runtime package layer.

---

# 55. Managed Artifact Creation

Recommended durable pattern:

```text
Transaction 1
→ Artifact PENDING
→ commit

Filesystem
→ write temp
→ flush/close
→ verify/hash
→ atomic rename

Transaction 2
→ Artifact AVAILABLE
→ commit
```

Never write directly to final destination.

---

# 56. Managed Source Import

Recommended flow:

```text
reserve Artifact(PENDING)
→ commit

StorageManager copies/hash/verifies/finalizes

Artifact → AVAILABLE
create Source
→ commit

return Source
```

A Source is not normally exposed as successfully imported before its managed original is ready.

---

# 57. Referenced Source Import

```text
inspect external file
→ validate
→ probe media
→ collect fingerprint metadata

short transaction
→ Artifact(REFERENCED, AVAILABLE)
→ Source
→ commit
```

The external file may later become missing.

That is handled by availability state rather than corrupting Source history.

---

# 58. Artifact Availability

Conceptual availability includes:

```text
AVAILABLE
MISSING
```

Additional implementation states may include:

```text
PENDING
FAILED
DELETING
```

`RELOCATED` may be used only if it proves useful as an explicit recovery state.

Exact persisted enums are finalized in the persistence design.

---

# 59. Relinking

Relinking a referenced Source must verify that the selected candidate represents the expected underlying media.

Selecting genuinely different media is replacement, not relinking.

V1 does not automatically scan entire disks looking for missing files.

---

# 60. Recycle vs Permanent Delete

Logical recycle is primarily database state.

Files are not normally physically moved merely because a Source was recycled.

Permanent deletion is a separate explicit operation.

For managed artifacts:

```text
durable deletion intent
→ physical deletion
→ metadata finalization
```

For referenced artifacts:

```text
remove application metadata/reference
→ external original remains untouched
```

---

# 61. RepresentationIndex

RepresentationIndex is the application-facing ANN boundary.

It accelerates candidate retrieval.

It does not own recognition truth.

Conceptual methods:

```text
search
add
remove
contains
status
verify
statistics
```

Rebuild orchestration belongs to a higher-level IndexRebuildService.

---

# 62. What Gets Indexed

The ANN index contains durable representations eligible for recognition retrieval.

The canonical application pointer is:

```text
representation_id
```

not:

```text
person_id
identity_id
```

Multiple representations may belong to one Identity.

Unknown Identities may be indexed.

---

# 63. Index Search

Conceptually:

```text
search(
    representation_space_id,
    query_vector,
    limit
)
```

returns technical matches such as:

```text
representation_id
distance/raw score
```

The index does not return:

```text
recognized = true
Person
calibrated confidence
final Identity decision
```

---

# 64. Recognition Pipeline

```text
query representation
      ↓
RepresentationIndex
      ↓
candidate representation IDs
      ↓
authoritative SQLite revalidation
      ↓
current Identity associations
      ↓
RecognitionService
      ↓
RecognitionCalibrationProfile
      ↓
RecognitionAssessment
```

ANN distance is not recognition confidence.

---

# 65. Index States

```text
UNAVAILABLE
INITIALIZING
READY
DEGRADED
REBUILDING
FAILED
```

An empty valid index can be READY with zero vectors.

Known-invalid or corrupt indexes must not silently serve recognition.

---

# 66. Index Rebuild

USearch is rebuildable from authoritative SQLite representations.

Flow:

```text
Job(REBUILD_INDEX)
→ read authoritative representations
→ build temporary index
→ verify
→ atomic replacement
→ reconcile pending operations
→ READY
```

V1 may reject searches for a RepresentationSpace while its index is rebuilding.

Zero-downtime dual-index rebuilding is not required initially.

---

# 67. IndexOperation

SQLite and USearch cannot share a transaction.

Therefore every durable change requiring ANN mutation records an IndexOperation in the same SQLite transaction as the authoritative change.

```text
BEGIN
→ domain change
→ representation change
→ IndexOperation
COMMIT

then:

IndexCoordinator
→ USearch
→ mark IndexOperation APPLIED
```

---

# 68. IndexOperation Types

Initial types:

```text
ADD
REMOVE
```

No UPDATE is required initially.

Representations should normally be treated as immutable.

Replacement means:

```text
REMOVE old
ADD new
```

---

# 69. IndexOperation States

Initial states:

```text
PENDING
APPLIED
FAILED
```

Transient failures generally remain PENDING with attempt/error metadata.

A persistent PROCESSING state is not required initially.

---

# 70. IndexOperation Idempotency

Operations must be replay-safe.

ADD means:

> Ensure the authoritative representation is present in the index.

REMOVE means:

> Ensure it is absent.

After a crash, a PENDING operation may have already modified USearch.

Replaying it must remain safe.

---

# 71. IndexCoordinator

IndexCoordinator is the sole normal owner of index mutation.

Responsibilities:

```text
load pending operations
revalidate current authoritative state
apply index changes
record attempts/errors
mark operations APPLIED
monitor health/backlog
trigger/suggest rebuild when appropriate
```

Feature modules do not directly mutate USearch.

---

# 72. Runtime Component Model

Runtime/model concepts remain separate:

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

---

# 73. Component

A Component is a logical ML capability.

Examples:

```text
FACE_DETECTOR
FACE_REPRESENTATION
FACE_QUALITY
```

A CUDA implementation and CPU implementation are not separate Components merely because their execution differs.

---

# 74. ComponentVersion

ComponentVersion represents a specific semantic implementation.

It owns compatibility information for:

```text
input contract
output contract
preprocessing
postprocessing
representation space where applicable
```

Preprocessing is part of model semantics.

It must not be treated as unrelated utility code.

---

# 75. ModelExport

ModelExport represents a concrete executable model artifact.

Examples:

```text
ONNX FP32
ONNX FP16
ONNX INT8
TensorRT FP16
```

It contains integrity metadata such as:

```text
hash
size
format
precision
component version
```

---

# 76. RuntimeVariant

RuntimeVariant answers:

> How is this export executed?

Examples:

```text
ONNX FP16 + CUDA
ONNX FP32 + DirectML
ONNX FP32 + CPU
TensorRT FP16 + TensorRT
```

RuntimeVariant is execution configuration, not semantic model identity.

---

# 77. Calibration

RecognitionCalibrationProfile interprets similarity behavior for recognition.

It is separate from:

```text
USearch
ModelExport
RuntimeVariant
```

Calibration compatibility is explicit.

A heavily quantized runtime must not automatically reuse another runtime's calibration unless evaluation establishes compatibility.

---

# 78. RuntimePackage

RuntimePackage is a tested installable set of compatible runtime variants and artifacts.

Conceptually:

```text
RuntimePackage
├── manifest
├── detector runtime
├── representation runtime
├── optional quality runtime
├── compatibility requirements
└── integrity metadata
```

Packages may share content-addressed artifacts.

---

# 79. Runtime Package States

```text
INSTALLING
AVAILABLE
INVALID
REMOVING
```

AVAILABLE does not mean active.

---

# 80. Runtime Installation

Runtime installation is normally asynchronous:

```http
POST /api/v1/runtime/packages/{package_id}/install
```

creates:

```text
Job(INSTALL_RUNTIME)
```

Flow:

```text
resolve manifest
→ compatibility check
→ obtain/stage artifacts
→ verify hashes
→ validate exports
→ smoke test
→ AVAILABLE
```

Partial installation must never be treated as usable.

---

# 81. Runtime Activation

```http
POST /api/v1/runtime/packages/{package_id}/activate
```

Activation changes preferred runtime configuration for future work.

It does not rewrite active ProcessingRun snapshots.

Existing worker model sessions may be lazily replaced where safe.

A full worker restart is required only when the runtime implementation genuinely requires one.

---

# 82. Runtime Fallback

Normal preference on compatible Windows/NVIDIA hardware may be:

```text
CUDA
→ DirectML
→ CPU
```

but fallback order is resolved from:

- hardware
- installed packages
- component compatibility
- calibration compatibility
- user preference

It is not assumed universally.

---

# 83. Worker Fallback Rule

The ML worker never silently changes provider.

Example:

```text
CUDA request
→ runtime error
→ MLResponse ERROR
→ FastAPI fallback policy
→ new ExecutionSegment if execution environment changes
→ new request using DirectML
```

This preserves truthful provenance.

---

# 84. ExecutionSegment

ExecutionSegment represents a period of stable actual execution configuration.

It records concepts such as:

```text
processing_run_id
sequence
runtime package
runtime variants
provider/device
calibration
started_at
finished_at
fallback reason
```

A new segment is created for meaningful provenance changes such as:

- runtime/provider fallback
- runtime package change
- component version change
- calibration profile change
- resume after interruption

A batch-size reduction using the same semantic/runtime configuration does not require a new segment.

---

# 85. Runtime API

```http
GET /api/v1/runtime/status
GET /api/v1/runtime/packages
GET /api/v1/runtime/packages/{package_id}
GET /api/v1/runtime/components
GET /api/v1/runtime/components/{component_id}
GET /api/v1/runtime/capabilities

POST /api/v1/runtime/packages/{package_id}/install
POST /api/v1/runtime/packages/{package_id}/activate
POST /api/v1/runtime/packages/{package_id}/remove

POST /api/v1/runtime/smoke-test
```

Normal inference remains fully local once required runtime packages are installed.

---

# 86. Settings API

Persistent user settings are grouped:

```http
GET   /api/v1/settings/processing
PATCH /api/v1/settings/processing

GET   /api/v1/settings/storage
PATCH /api/v1/settings/storage

GET   /api/v1/settings/runtime
PATCH /api/v1/settings/runtime
```

Settings are typed.

The system does not use an unrestricted key-value settings API.

---

# 87. Settings Storage

Persistent user settings live in SQLite.

`.env` and environment variables are for:

- development
- CI
- startup/developer overrides

They are not the ordinary production user settings mechanism.

---

# 88. Settings Resolution

General precedence:

```text
Application defaults
        ↓
Persistent user preferences
        ↓
Operation-specific semantic override
        ↓
Capability/runtime resolution
        ↓
Resolved configuration
```

Hardware constrains what can execute.

It does not silently rewrite stored user preference.

---

# 89. ProcessingConfigurationSnapshot

When a ProcessingRun is created, its resolved configuration is frozen.

```text
settings
+
component versions
+
calibration
+
command options
+
runtime policy
        ↓
ConfigurationResolver
        ↓
ProcessingConfigurationSnapshot
```

The snapshot is immutable.

Settings changed after Job creation affect future runs, not the queued or active run.

---

# 90. Requested vs Actual Configuration

```text
ProcessingConfigurationSnapshot
→ requested/resolved configuration

ExecutionSegment
→ actual execution
```

Example:

```text
Snapshot:
prefer CUDA
allow fallback

Segment 1:
CUDA

Segment 2:
DirectML
fallback reason = CUDA_OOM
```

Both are preserved.

---

# 91. Configuration Snapshot Rules

Snapshots:

- are immutable
- have a schema version
- store resolved mutable values
- reference immutable/versioned entities where appropriate

Do not merely store a pointer to the current mutable settings row.

Historical processing must remain interpretable after settings change.

---

# 92. Internal Backend Boundaries

The backend is feature-oriented.

Recommended high-level structure:

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
│   ├── db/
│   ├── storage/
│   ├── media/
│   ├── indexing/
│   ├── events/
│   ├── resources/
│   └── diagnostics/
└── ml/
    ├── contracts/
    ├── client/
    ├── supervisor/
    └── worker/
```

Do not force every feature to contain the same set of files.

Create structure only when responsibilities justify it.

---

# 93. Route Boundary

Routes:

```text
validate HTTP request
→ call query/use case
→ map result
→ return response
```

Routes do not contain:

- SQLAlchemy business queries
- filesystem operations
- USearch operations
- ML inference
- identity reasoning
- transaction orchestration

---

# 94. Command and Query Separation

The application maintains conceptual command/query separation without introducing a formal CQRS framework.

Queries read authoritative state.

Commands request domain transitions.

A feature may use:

```text
service.py
→ mutations/use cases

queries.py
→ optimized read projections
```

when useful.

No CommandBus is required.

---

# 95. Use Cases

Cross-subsystem workflows should have explicit application use cases.

Examples:

```text
ImportSourceUseCase
ProcessSourceUseCase
MergeIdentitiesUseCase
SplitIdentityUseCase
ForgetIdentityUseCase
FaceSearchUseCase
AssignIdentityToPersonUseCase
```

Simple feature-local mutations may remain normal service methods.

---

# 96. Use-Case Composition Rule

Top-level use cases should not recursively compose other top-level use cases as workflow building blocks.

Instead, they share lower-level:

- repositories
- domain helpers
- infrastructure capabilities

This avoids:

- nested transaction ownership
- circular workflows
- hidden side effects

---

# 97. RecognitionService

RecognitionService owns:

```text
ANN candidate retrieval
→ authoritative candidate revalidation
→ candidate grouping
→ similarity interpretation
→ calibration
→ RecognitionAssessment
```

It does not create:

- Identity
- Person
- Evidence
- associations

---

# 98. IdentityReasoner

IdentityReasoner consumes:

```text
Observation
Representation
RecognitionAssessment
current memory context
```

and proposes a domain decision such as:

```text
associate existing Identity
create new Identity
uncertain/provisional outcome
```

It does not independently commit database state.

Its proposal is revalidated before semantic commit.

---

# 99. Repositories

Repositories focus on authoritative persistence mechanics.

They may:

```text
query
add
update
delete
flush
refresh
perform persistence-specific operations
```

They generally do not:

```text
commit
open independent business transactions
mutate USearch
write filesystem artifacts
run ML
emit WebSocket events
coordinate cross-feature workflows
```

No generic CRUD BaseRepository is required.

---

# 100. SQLAlchemy Models

SQLAlchemy models are persistence models.

The architecture does not require a duplicate domain class, DTO, mapper, and persistence model for every table.

Explicit domain/value objects are introduced only where meaningful behavior or invariants justify them.

---

# 101. Query Projections

Read queries may use purpose-built joins/projections.

For example, People list may efficiently retrieve:

```text
Person
representative face
identity count
occurrence count
source count
```

in optimized SQL.

Do not introduce N+1 queries merely to preserve repository purity.

---

# 102. Internal Events

The application may use a typed in-process event bus for:

- notifications
- cache invalidation
- WebSocket projection
- operational reactions

Core workflow correctness must not depend on hidden event handlers.

For example, Identity merge itself must update authoritative state explicitly.

An `IdentityMerged` event may then notify other non-authoritative consumers.

---

# 103. Transaction Ownership

The application/use-case layer owns transaction boundaries.

Repositories participate in the transaction provided by the caller.

Repositories generally do not call `commit()`.

`flush()` is allowed when required.

---

# 104. Transaction Pattern

General mutation pattern:

```text
1. PREPARE
   ├── compute
   ├── IO
   ├── ML
   └── construct proposal

2. BEGIN SHORT TRANSACTION

3. REVALIDATE

4. MUTATE AUTHORITATIVE STATE

5. RECORD DURABLE FOLLOW-UP INTENT

6. COMMIT

7. POST-COMMIT
   ├── wake coordinators
   ├── cleanup
   ├── publish events
   └── WebSocket notification
```

---

# 105. Expensive Work Outside Transactions

Do not hold DB transactions while performing:

- media decoding
- ML inference
- ANN search
- FFmpeg work
- large hashing
- file copies
- runtime downloads
- long cleanup

Compute first.

Then perform a short transaction.

---

# 106. Optimistic Revalidation

Long-running computation does not lock semantic entities.

Instead:

```text
compute proposal
→ begin transaction
→ reload relevant authoritative state
→ validate assumptions
→ persist or reconcile
```

Potential checks include:

```text
entity still exists
entity not forgotten
entity not superseded
association unchanged
source still active
representation still eligible
```

This avoids long locks.

---

# 107. Session Lifetime

SQLAlchemy sessions are short-lived.

Never retain a session for:

- an entire movie job
- a camera session
- the lifetime of the application

Long-running handlers carry durable IDs/value objects and open fresh sessions when persistence is required.

Do not carry live ORM objects across long processing boundaries.

---

# 108. Filesystem Transaction Boundary

SQLite and the filesystem cannot share a transaction.

Managed durable artifact creation therefore uses:

```text
reserve metadata
→ commit

write temp
→ verify
→ atomic rename

finalize metadata
→ commit
```

Managed deletion uses:

```text
durable deletion intent
→ commit

physical deletion

finalize metadata
→ commit
```

Recovery reconciles incomplete states.

---

# 109. Index Transaction Boundary

SQLite and USearch cannot share a transaction.

Therefore:

```text
authoritative DB mutation
+
IndexOperation
→ same SQLite transaction
→ commit

USearch mutation
→ after commit
```

The IndexOperation makes synchronization recoverable.

---

# 110. Post-Commit Reliability Rule

Every required post-commit side effect must be either:

```text
recoverable from durable state
```

or:

```text
safe to lose
```

Examples:

```text
Index wake
→ recoverable from IndexOperation

Scheduler wake
→ recoverable from QUEUED Job

Managed deletion
→ recoverable from deletion state

WebSocket notification
→ safe to lose

cache invalidation
→ reconstructible
```

---

# 111. Job Creation Transaction

Processing command:

```text
BEGIN
→ validate Source
→ create ProcessingConfigurationSnapshot
→ create ProcessingRun
→ create Job
COMMIT

then:
→ wake scheduler
```

If scheduler wake is lost, the durable QUEUED Job is rediscovered.

---

# 112. Processing Persistence Transaction

After expensive ML/recognition work:

```text
BEGIN
→ revalidate
→ Observation
→ Representation
→ Identity/association
→ Evidence
→ Occurrence where applicable
→ IndexOperation
COMMIT
```

Then IndexCoordinator converges USearch.

---

# 113. Job Completion Transaction

A processing Job becomes COMPLETED only after its authoritative results are settled.

Conceptually:

```text
BEGIN
→ finalize ProcessingRun
→ finalize ExecutionSegment
→ finalize checkpoint
→ Job COMPLETED
COMMIT

then:
→ notify
```

---

# 114. Merge Transaction

Identity merge is one authoritative transaction:

```text
prepare merge plan

BEGIN
→ reload/revalidate
→ select survivor
→ reconcile Person relationship
→ update associations
→ update evidence/memory
→ record correction
→ create required IndexOperations
→ supersede merged Identity
COMMIT

then:
→ wake index
→ notify
```

No partial merge should become visible.

---

# 115. Split Transaction

```text
prepare split

BEGIN
→ revalidate
→ create new Identity
→ move selected associations
→ update memory
→ record correction
→ create IndexOperations
COMMIT
```

Again, no partial split.

---

# 116. Forget Transaction

```text
prepare forget plan

BEGIN
→ revalidate
→ update Identity/memory state
→ retire representation eligibility
→ record correction/history
→ create REMOVE IndexOperations
→ create required artifact deletion intent
COMMIT

then:
→ index reconciliation
→ physical managed cleanup
→ notifications
```

Authoritative forgetting happens before physical cleanup.

A cleanup failure must not cause the forgotten identity to remain recognizable.

---

# 117. SQLite Configuration

The persistence implementation must use:

```text
SQLite WAL
foreign keys enabled
busy timeout
short transactions
bounded connection behavior
```

Exact SQLAlchemy engine/session configuration is defined in the persistence implementation document.

---

# 118. First Vertical Slice Contract

The first implementation target is intentionally narrow.

## Import one image

```text
POST /sources/import
→ Artifact
→ Source
```

## Process it

```text
POST /sources/{id}/process
→ ProcessingRun
→ ConfigurationSnapshot
→ Job
```

## Execute

```text
decode image
→ DETECT_FACES
→ GENERATE_REPRESENTATIONS
→ RepresentationIndex search
→ RecognitionService
→ RecognitionAssessment
→ IdentityReasoner
```

## Persist

```text
Observation
Representation
Identity / association
Evidence
IndexOperation
```

## Index

```text
IndexCoordinator
→ USearch
→ IndexOperation APPLIED
```

## Complete

```text
ProcessingRun COMPLETED
ExecutionSegment finalized
Job COMPLETED
```

## Display

Frontend retrieves:

```text
Source
People Found
Identities
Observations
processing status
```

---

# 119. Explicitly Deferred Capabilities

The first vertical slice does not require:

- movie processing
- camera processing
- tracking
- retraining
- natural-language search
- TensorRT
- multiple heavy workers
- sophisticated scheduler
- advanced runtime installer UI
- automatic disk-wide relinking
- zero-downtime index rebuilding
- elaborate configuration profiles

The contracts should permit these later without requiring them now.

---

# 120. Hard Architectural Invariants

The following are implementation rules, not suggestions.

### Identity and memory

```text
Sources contain observations.

Identities represent persistent visual subjects.

People represent semantic human identity.

Evidence connects observations/representations to identity decisions.

Model output is evidence, not authoritative truth.
```

### Search

```text
Query != Ingest.

Face search is ephemeral by default.

Search must not mutate memory merely because recognition succeeded.
```

### Persistence

```text
SQLite is authoritative.

USearch is derived.

Filesystem owns bytes, not meaning.

Index loss must not cause memory loss.
```

### Transactions

```text
Use cases own transaction boundaries.

Repositories generally do not commit.

Long Jobs are not DB transactions.

Expensive computation stays outside DB transactions.

Semantic assumptions are revalidated before commit.
```

### Indexing

```text
SQLite changes first.

IndexOperation is committed with authoritative changes.

USearch changes after commit.

Index operations are idempotent.
```

### Storage

```text
Managed files may be deleted only through explicit domain decisions.

Referenced external originals are never deleted.

Durable artifact writes use temp + verification + atomic finalization.

Logical recycle does not require physical file movement.
```

### ML

```text
Worker performs bounded compute.

Worker does not own application truth.

Worker does not access SQLite.

Worker never silently changes runtime provider.

Runtime fallback is explicit and visible.
```

### Jobs

```text
Jobs are durable before scheduling.

Pause/cancel are cooperative.

PAUSED means safe durable resume state exists.

Retry creates a new Job attempt.

No fake progress percentages.
```

### Configuration

```text
Persistent settings live in SQLite.

Processing configuration is resolved when the command is accepted.

ProcessingConfigurationSnapshot is immutable.

Settings changes do not mutate existing runs.

ExecutionSegment records actual execution.
```

### Events

```text
REST is authoritative.

WebSocket is notification.

Required durability never depends solely on in-memory events.

Reconnect/gap means REST refetch.
```

---

# 121. Implementation Philosophy

The application should prefer:

```text
explicit code
small clear services
short transactions
typed contracts
recoverable state
idempotent reconciliation
feature-oriented organization
measured optimization
```

over:

```text
framework ceremony
generic abstractions
distributed-system patterns without need
hidden event workflows
service-to-service call chains
premature optimization
```

The architecture should remain understandable enough that a developer can predict where a behavior belongs.

---

# 122. Relationship to Other Architecture Documents

This document should be read alongside:

```text
Product Definition & Requirements
Identity & Memory Model
Processing Architecture
Universal Search & Retrieval Architecture
ERD.md
IMPLEMENTATION_ARCHITECTURE.md
```

This document specifically owns:

```text
external REST contracts
WebSocket contracts
ML IPC contracts
SharedMemory ownership
StorageManager boundary
RepresentationIndex boundary
IndexOperation behavior
Job/progress behavior
runtime/component contracts
settings/configuration contracts
internal use-case boundaries
transaction ownership
```

Concrete table definitions, SQLAlchemy mappings, indexes, constraints, migration mechanics, and session configuration belong in the next persistence implementation document.

Concrete detector, representation, quality, preprocessing, calibration, benchmarking, and evaluation decisions belong in the ML components/evaluation document.

---

# 123. Status

```text
API & Internal Contracts: LOCKED FOR IMPLEMENTATION DESIGN

REST Resource Structure                    LOCKED
Command / Query Endpoints                  LOCKED
API Schemas                                LOCKED
Error Contract                             LOCKED
Pagination                                 LOCKED
Media Delivery                             LOCKED
WebSocket Envelope                         LOCKED
MLRequest                                  LOCKED
MLResponse                                 LOCKED
ML Operations                              LOCKED
SharedMemory Ownership                     LOCKED
Worker Lifecycle                           LOCKED
StorageManager                             LOCKED
RepresentationIndex                        LOCKED
IndexOperation                             LOCKED
Jobs / Progress                            LOCKED
Runtime Packages / Components              LOCKED
Settings / Configuration                   LOCKED
Use-Case Boundaries                        LOCKED
Transaction Ownership                      LOCKED
```

The next architecture phase is:

```text
PERSISTENCE_IMPLEMENTATION.md
```

which maps these contracts and the existing ERD onto concrete:

```text
SQLAlchemy 2 models
SQLite tables
foreign keys
constraints
indexes
relationship loading
vector persistence
Job/Run/Segment persistence
Artifact lifecycle
IndexOperation persistence
Settings persistence
session management
WAL configuration
Alembic migrations
repository/query implementation
concurrency/revision strategy
recovery queries
```