# Persistence Implementation

## Status and scope

This document is the implementation contract for the local Windows Visual Identity / Face Memory application. It turns the locked product, processing, identity, API, and runtime decisions into a concrete SQLite and SQLAlchemy 2 design. SQLite is the authoritative store for relational meaning; the filesystem owns artifact bytes; USearch is a rebuildable candidate index. This document does not select face models, similarity thresholds, or calibration values. Those are evaluation outputs, not persistence defaults.

The first implementation uses SQLite, SQLAlchemy 2, Alembic, a single FastAPI-owned backend process, one persistent ML worker, and USearch. Do not introduce a server database, event store, generic metadata table, generic repository, or distributed transaction layer.

## 1. Persistence principles and database layout

The database is one application-owned SQLite file under the application data directory, for example `data/identity-memory.sqlite3`. Its sibling directories are application-owned:

```text
data/
  identity-memory.sqlite3
  artifacts/
  indexes/representations/<space-key>/
  processing-tmp/
  runtime/
```

The database stores semantic facts, lifecycle state, immutable provenance, durable work intent, canonical vectors, and settings. It does not store derived ANN files, temporary decoded frames, shared-memory names, or WebSocket events.

The non-negotiable rules are:

1. A foreign key expresses an authoritative relationship; an ORM relationship is only optional navigation.
2. Every durable object has an explicit lifecycle state. Visibility is a state transition, never an incidental query convention.
3. Expensive compute and filesystem work happen outside a database transaction. A short transaction reloads, revalidates, and settles authoritative state.
4. The database transaction which makes a representation ANN-eligible also creates an `IndexOperation`. No code is allowed to mutate USearch first and hope that SQLite catches up.
5. Historical provenance is append-oriented. Current identity truth can change without rewriting old evidence, snapshots, or execution segments.
6. A run's private output remains `PENDING` until the run is accepted. Queries for normal library memory use `ACTIVE` state only.

Use one SQLAlchemy declarative metadata object and one Alembic migration history. SQLAlchemy models are persistence records, not public API schemas and not a hidden domain layer.

## 2. Identifier strategy

All primary identifiers are application-generated UUIDs. Use `uuid.uuid4()` at creation time and SQLAlchemy `Uuid(as_uuid=True)` with a SQLite-compatible `CHAR(32)` representation. Python/application boundaries use `uuid.UUID`; API boundaries use canonical hyphenated UUID strings. Do not use SQLite rowids as public identifiers or cross-table references.

`ann_key` is deliberately different: it is a positive signed 64-bit integer allocated from `ann_key_sequences`. USearch receives this compact integer, while SQLite maps it back to the stable `representation_id`. Never use an `identity_id` or `person_id` as the ANN key.

Every mutable user-visible aggregate has `revision INTEGER NOT NULL DEFAULT 1`; updates which can race use `WHERE id = :id AND revision = :expected_revision`, then increment revision. Rows written only by one controlled workflow do not need artificial optimistic locking. All timestamps are UTC, `DATETIME` values produced by the application, and named `created_at`, `updated_at`, `started_at`, `ended_at`, or `deleted_at` by meaning.

## 3. Base model conventions

All tables use explicit SQLAlchemy 2 `Mapped[...]` / `mapped_column()` declarations. Use `String` plus `CHECK` constraints for finite state and kind values rather than SQLite's weak native enum behavior. Python `StrEnum` values must exactly match the database literals.

Shared conventions:

| Convention | Rule |
|---|---|
| Primary key | `id` UUID unless the table is a small singleton or association table |
| State | `state VARCHAR NOT NULL` with an explicit table-level `CHECK` |
| JSON | `JSON` / SQLite JSON text plus a `payload_schema_version` where historical interpretation matters |
| Binary | `LargeBinary`, only for hashes, vectors, and explicitly binary values |
| Booleans | SQLAlchemy `Boolean` plus a meaningful default, never nullable tri-state unless unknown is semantically real |
| Timestamps | UTC, non-null when the lifecycle transition happened |
| Deletion | explicit workflow/state first; database cascade only for true owned children |
| Names | snake_case tables and columns; singular ORM classes |

Do not add a generic `metadata JSON` field. A versioned JSON payload is permitted only where the payload is genuinely variable and historical: snapshots, checkpoints, evidence details, job payload/progress, runtime manifests, and structured diagnostics. Stable queryable data gets a typed column.

> **Decision 2026-09-23:** columns are NOT NULL unless marked nullable, **except** a column whose value only exists after an event (an attempt, a failure, an end/apply/erase time). Those are nullable even when this document does not mark them. Each such case is listed in the implementation log. (Owner decision, M1 PR #5.)

## 4. Source and Artifact persistence

### 4.1 `artifacts`

`Artifact` represents one file-like byte resource. It does not mean a public media object and it does not grant the frontend a filesystem path.

| Column | Type and rule |
|---|---|
| `id` | UUID primary key |
| `kind` | `SOURCE_ORIGINAL`, `FACE_CROP`, `THUMBNAIL`, `MODEL_EXPORT`, or `RUNTIME_PACKAGE` |
| `storage_mode` | `MANAGED` or `REFERENCED` |
| `state` | `PENDING`, `AVAILABLE`, `MISSING`, `DELETING`, `DELETE_FAILED`, `DELETED` |
| `storage_key` | nullable managed logical key, unique when non-null; never an absolute path |
| `external_path` | nullable referenced path; never returned in normal API responses |
| `sha256` | nullable 32-byte digest; required for verified managed content |
| `size_bytes` | nullable non-negative integer |
| `mime_type` | nullable string |
| `original_filename` | nullable display/provenance string |
| `created_at`, `available_at`, `delete_requested_at`, `deleted_at` | lifecycle timestamps |
| `failure_code`, `failure_detail` | bounded diagnostics; no traceback required |

Constraints: exactly one location form is valid: `MANAGED` requires `storage_key` and forbids `external_path`; `REFERENCED` requires `external_path` and forbids `storage_key`. `AVAILABLE` managed artifacts require `sha256` and `size_bytes`. The database cannot prove physical existence; `MISSING` records a verified failure to resolve bytes.

Managed creation is a three-step protocol: commit a `PENDING` row; write to a temporary file, hash/verify, then atomically rename; commit `AVAILABLE` plus the final key/hash/size. If the second commit is lost, recovery verifies the expected final key and completes or rolls back the row. Deletion is symmetrical: commit deletion intent, remove the managed bytes, then finalize the row. A referenced file is never physically deleted by this application.

### 4.2 `sources`

`Source` is the user-facing imported image or future video. It owns its semantic library lifecycle, not necessarily its bytes.

| Column | Type and rule |
|---|---|
| `id` | UUID primary key |
| `kind` | `IMAGE` or `VIDEO` |
| `state` | `ACTIVE`, `RECYCLED`, `DELETING`, `DELETED`, `UNAVAILABLE` |
| `display_name` | non-empty string |
| `original_artifact_id` | non-null FK to `artifacts`, `RESTRICT` |
| `thumbnail_artifact_id` | nullable FK to `artifacts`, `SET NULL` |
| `current_processing_run_id` | nullable FK to `processing_runs`, `SET NULL` |
| `captured_at` | nullable UTC timestamp supplied/derived from media |
| `media_duration_ms`, `width`, `height`, `frame_rate_num`, `frame_rate_den` | nullable source facts, non-negative where set |
| `revision`, `created_at`, `updated_at`, `recycled_at` | concurrency and lifecycle |

Import creates an available original artifact and then an `ACTIVE` source in one short semantic transaction. Logical recycle changes only source state; it does not move bytes. Permanent deletion is a dedicated use case which first creates durable derived-index and byte-deletion intent, then performs the physical/database finalization. The initial UI supports only managed `IMAGE` imports, but the schema retains `VIDEO` and `REFERENCED` support.

## 5. Observation persistence

An `Observation` is a concrete detected face in one source at a point/frame. It is not a persistent person and it is not automatically an occurrence.

`observations` columns are: `id`; non-null `source_id`, `processing_run_id`, and `execution_segment_id`; nullable `face_crop_artifact_id`; `state` (`PENDING`, `ACTIVE`, `SUPERSEDED`, `REJECTED`, `DELETED`); `sequence_in_run`; nullable `frame_index` and `timestamp_ms`; normalized bounding box `bbox_x`, `bbox_y`, `bbox_width`, `bbox_height`; optional landmark/quality JSON; `detector_component_version_id`; `created_at`; and `superseded_by_run_id` where appropriate.

Bounds use normalized `REAL` values in `[0, 1]`; width and height are greater than zero and `x + width <= 1`, `y + height <= 1`. An image has null frame/time values; a video observation requires them. `UNIQUE(processing_run_id, sequence_in_run)` makes replay/idempotent settlement unambiguous. The crop FK uses `SET NULL`, because a cleanup policy may remove a derivative without invalidating historical observation semantics.

> **Decision 2026-09-23:** the "optional landmark/quality JSON" is two nullable columns, `landmarks_json` and `quality_json` (matching `representations.quality_json`). Their contents are not yet defined. (Owner decision, M1 PR #5.)

Detection output is persisted before embedding settlement. A meaningful crop may be stored as an Artifact; a transient detector crop must remain temporary. Accepting a run changes only that run's `PENDING` observations to `ACTIVE`; reprocessing supersedes old active observations explicitly, never by overwriting their geometry.

## 6. Representation and RepresentationSpace persistence

`Representation` stores a canonical face vector and its provenance. Its vector is authoritative memory under one semantic space; the USearch entry is merely a derived acceleration.

### 6.1 `representation_spaces`

| Column | Rule |
|---|---|
| `id` | UUID primary key |
| `semantic_key` | immutable unique string, e.g. a model/export contract key |
| `state` | `ACTIVE` or `DEPRECATED` |
| `dimension` | positive integer |
| `metric` | currently `COSINE`; explicit for future safety |
| `normalization` | explicit contract such as `L2_NORMALIZED` |
| `component_version_id` | non-null historical provenance FK, `RESTRICT` |
| `contract_schema_version` | interpretation version |
| `contract_json` | immutable preprocessing/postprocessing compatibility contract |
| `created_at`, `deprecated_at` | lifecycle |

An equal dimension does not establish compatibility. A vector may only be compared, indexed, or calibrated with vectors in the same `representation_space_id`. Do not update a vector's space merely because a new model has the same output shape.

### 6.2 `representations`

| Column | Rule |
|---|---|
| `id` | UUID primary key |
| `observation_id` | non-null FK, `CASCADE` because a representation is owned by its observation |
| `identity_id` | nullable FK to `identities`, `RESTRICT` |
| `processing_run_id`, `execution_segment_id` | non-null provenance FKs, `RESTRICT` |
| `representation_space_id` | non-null FK, `RESTRICT` |
| `state` | `PENDING`, `ACTIVE`, `SUPERSEDED`, `ERASED`, `DELETED` |
| `ann_key` | nullable unique positive signed 64-bit integer; required while ANN-eligible |
| `vector` | non-null canonical float32 blob |
| `vector_dimension` | non-null positive integer, checked against its space in application validation |
| `quality_json` | nullable measured embedding/quality facts |
| `created_at`, `activated_at`, `erased_at` | lifecycle |

Use `UNIQUE(observation_id, representation_space_id)` for one persisted embedding per observation per semantic space. An active representation must have an active identity, an allocated `ann_key`, and a non-erased vector. `PENDING` representations are run-private and must never be placed in the global ANN index. `ERASED` retains provenance but has `vector = NULL`, `ann_key = NULL`, and a durable `REMOVE` operation must have been requested before final erasure.

> **Decision 2026-09-23:** `vector` is nullable **only** for `ERASED`: a CHECK requires `vector` and `ann_key` to be NULL when `ERASED`, and `vector` to be present in every other state. This resolves the column table's "non-null" against the erasure rule above. (Owner decision, M1 PR #5.)

### 6.3 `ann_key_sequences`

This table has one row per `representation_space_id`: the space UUID primary key/FK and `next_ann_key INTEGER NOT NULL CHECK(next_ann_key > 0)`. Allocation occurs in the same short transaction that creates representations, using a guarded update; keys are never reused. A gap is harmless and safer than reuse after a crash or erase.

## 7. Identity persistence

An `Identity` is the persistent visual subject, named or unknown. It is the target of recognition reasoning; it is not a vector, a Person, or an ANN entry.

`identities` has: `id`; `state` (`PENDING`, `ACTIVE`, `MERGED`, `SPLIT`, `FORGOTTEN`, `DELETED`); nullable `created_by_processing_run_id`; nullable `representative_observation_id`; nullable `merged_into_identity_id`; `revision`; `created_at`, `activated_at`, `forgotten_at`, and `updated_at`. All identity foreign keys use `RESTRICT` except the optional representative observation uses `SET NULL`.

Only an accepted run may activate a pending identity. An active identity must not point to a merged/forgotten target. Recognition selects an existing active identity or creates a pending one; it never assigns a Person directly. Merge, split, and forget are later explicit use cases. They change current associations/representation eligibility with durable Evidence and IndexOperations; they do not rewrite historical Evidence.

> **Decision 2026-09-23:** domain-level merge and split (with correction and Person association) are built in testing milestone M1; "later" above refers to their UI and integration. Forget is still later. They remain outside the first vertical slice (§30).

`identity_lineage` preserves structural history: `id`, `from_identity_id`, `to_identity_id`, `kind` (`MERGED_INTO`, `SPLIT_FROM`), non-null `evidence_id`, `created_at`. It has `UNIQUE(from_identity_id, to_identity_id, kind)` and restricts deletion of referenced history. A lineage edge is not a replacement for current identity state.

## 8. Person persistence

`Person` is semantic/named human identity and intentionally separate from visual Identity. A person can have zero, one, or many visual identities.

`people` contains `id`, `state` (`ACTIVE`, `RECYCLED`, `DELETED`), `display_name` (non-empty), nullable `normalized_name`, `revision`, `created_at`, `updated_at`, and `recycled_at`. Use a case-folded `normalized_name` only for search/sorting; do not impose a global unique-name constraint because distinct people may share a name. Future aliases deserve their own table only when the feature exists.

The initial schema includes this table, but V1 does not expose naming flows. An unknown identity must never cause a placeholder Person row to be created.

## 9. Identity-Person associations and current naming

`identity_person_associations` models the historical and current connection between an Identity and a Person. It contains `id`, `identity_id`, `person_id`, `state` (`ACTIVE`, `REMOVED`, `SUPERSEDED`), nullable `evidence_id`, `created_at`, `ended_at`, and `revision`.

Enforce at most one active Person association per identity with a partial unique index:

```sql
CREATE UNIQUE INDEX uq_identity_person_active
ON identity_person_associations(identity_id)
WHERE state = 'ACTIVE';
```

A Person may have many active identities. Assignment is an explicit use case: lock/reload the identity, end any current active association, create the new active association, append Evidence, and commit. Removing an association ends it; it does not delete either object. This preserves why the current name differs from an older decision.

## 10. Evidence and correction persistence

Evidence records a durable reason for an authoritative memory decision. It is immutable and append-only; it does not claim that the decision is still current.

`evidence` columns: `id`; `kind` (`IDENTITY_CREATED`, `IDENTITY_MATCHED`, `IDENTITY_ASSIGNED_TO_PERSON`, `IDENTITY_REMOVED_FROM_PERSON`, `IDENTITY_MERGED`, `IDENTITY_SPLIT`, `IDENTITY_FORGOTTEN`, `USER_CORRECTION`); nullable `processing_run_id`; nullable `source_id`; nullable `subject_identity_id`; nullable `subject_person_id`; nullable `calibration_profile_id`; `payload_schema_version`; non-null `payload_json`; `created_at`; and nullable `superseded_at` only as an explanatory marker, not mutation of payload.

`evidence_representations` is a role-bearing association: `evidence_id`, `representation_id`, `role` (`SUBJECT`, `SELECTED_CANDIDATE`, `CANDIDATE`, `SUPPORTING`), primary key `(evidence_id, representation_id, role)`. `evidence_candidates` stores bounded recognition candidates in their original order: `evidence_id`, `rank`, nullable `representation_id`, nullable `identity_id`, `raw_similarity`, nullable `calibrated_confidence`, `decision`, and `details_json`, with primary key `(evidence_id, rank)`.

> **Decision 2026-09-23:** `evidence_candidates.decision` has no defined value set yet, so it is an unconstrained string until the decision engine defines one. (Owner decision, M1 PR #5.)

Recognition Evidence must preserve the representation-space and calibration provenance through typed FKs and the snapshot payload. It records a bounded candidate set, never an unbounded raw ANN dump. Transient assessments that do not affect durable memory do not create Evidence.

## 11. Occurrence persistence

An `Occurrence` is a meaningful appearance of an Identity within a Source. For an image, one face observation creates one occurrence; for video it will later be a track/segment. It is distinct from the raw observation so future tracking does not change the conceptual model.

`occurrences` contains `id`, non-null `source_id`, `identity_id`, and `processing_run_id`; nullable `representative_observation_id`; `kind` (`IMAGE`, `TRACK`, `SEGMENT`); `state` (`PENDING`, `ACTIVE`, `SUPERSEDED`, `DELETED`); nullable `start_frame`, `end_frame`, `start_timestamp_ms`, `end_timestamp_ms`; nullable `confidence_json`; and lifecycle timestamps. Frame/time ranges are both null for `IMAGE`; otherwise start is not greater than end. An active occurrence requires an active identity.

> **Decision 2026-09-23:** the occurrence "lifecycle timestamps" are `created_at` and `activated_at` (set by run acceptance). Supersede/delete timestamps are added with those use cases. (Owner decision, M1 PR #5.)

`occurrence_observations` has `occurrence_id`, `observation_id`, `ordinal`, primary key `(occurrence_id, observation_id)`, and unique `(occurrence_id, ordinal)`. An observation may normally belong to one active occurrence per run; use a partial unique index for that state if video workflows need it. The V1 image path writes one membership and sets that observation as representative.

## 12. ProcessingRun persistence

`ProcessingRun` is the logical, provenance-bearing attempt to process a source. A Job executes it, but they are not interchangeable.

`processing_runs` contains `id`; `source_id`; `configuration_snapshot_id`; nullable `parent_run_id` for reprocessing lineage; `state` (`PENDING`, `RUNNING`, `PAUSING`, `PAUSED`, `CANCELLING`, `CANCELLED`, `FINALIZING`, `COMPLETED`, `FAILED`, `INTERRUPTED`, `NOT_RESUMABLE`); `requested_at`, `started_at`, `completed_at`, `failed_at`; nullable `failure_code` and `failure_detail`; `current_checkpoint_id`; `revision`; and `created_at`, `updated_at`.

There may be many historical runs per source but only one source pointer, `current_processing_run_id`, designates the accepted current result. A new run begins private. Cancellation/failure does not mutate the previous accepted run. `COMPLETED` means the acceptance transaction committed; it does not require all derived IndexOperations to already be applied.

## 13. ProcessingConfigurationSnapshot persistence

`processing_configuration_snapshots` records resolved semantic intent at command acceptance, never today's mutable settings. It contains `id`, `schema_version`, `canonical_json`, `fingerprint_sha256`, `created_at`, and nullable `created_by_user_action`. `canonical_json` includes source-processing choices, selected component/version/export contracts, intended representation spaces, calibration profile, allowed fallback policy, crop/quality policy, and all other semantic settings necessary to explain the run.

Use `UNIQUE(fingerprint_sha256)` only if identical snapshots are safely shareable; otherwise retain an immutable row per run. This design chooses one snapshot per run for unambiguous provenance. It must never be updated. The fingerprint helps diagnostics and is not an authorization token.

## 14. ExecutionSegment persistence

An `ExecutionSegment` records what actually ran during a bounded stretch of a ProcessingRun. It is required because a requested CUDA plan may execute partially under CUDA and then continue under DirectML after an explicit backend decision.

`execution_segments` columns: `id`; `processing_run_id`; nullable `runtime_variant_id`; `ordinal`; `state` (`RUNNING`, `COMPLETED`, `FAILED`, `INTERRUPTED`, `ABANDONED`); `started_at`, `ended_at`; nullable `ended_reason` (`NORMAL`, `FALLBACK`, `CUDA_OOM`, `WORKER_CRASH`, `CANCELLED`, `SHUTDOWN`); `runtime_details_json`; and `created_at`. Enforce `UNIQUE(processing_run_id, ordinal)` and one running segment per run with a partial unique index.

Segments are closed, never reopened. Reducing a batch size within the same variant stays in the current segment. Changing provider, export, or runtime variant closes one segment and creates another. Historical segments remain resolvable even when their executable package is later uninstalled.

## 15. Job persistence

`Job` is schedulable execution state. `jobs` contains `id`; `type` (`PROCESS_SOURCE`, `REPROCESS_SOURCE`, `REBUILD_INDEX`, `RETRAIN_MODEL`, `INSTALL_RUNTIME`, `CLEAN_STORAGE`); nullable `processing_run_id`; nullable `previous_job_id`; `state` (`QUEUED`, `RUNNING`, `PAUSING`, `PAUSED`, `CANCELLING`, `CANCELLED`, `COMPLETED`, `FAILED`, `INTERRUPTED`); `priority` (`INTERACTIVE`, `HIGH`, `NORMAL`, `LOW`, `MAINTENANCE`); `payload_schema_version`, nullable `payload_json`; `progress_mode` (`DETERMINATE`, `INDETERMINATE`); nullable `progress_completed`, `progress_total`; nullable `lease_owner`, `lease_expires_at`, `heartbeat_at`; `attempt_number`; `failure_code`, `failure_detail`; and lifecycle timestamps.

Checks require determinate values to be non-negative and `completed <= total` when a total exists. A retry creates a new Job with `previous_job_id`, not a state reset. Claiming is atomic: choose an eligible queued row by priority and creation time, conditionally transition it to `RUNNING`, record a lease/heartbeat, commit, and return a lightweight `ClaimedJob` value. SQLite has one writer, so V1 runs only one heavy processing pipeline at a time; this is a scheduler policy, not a table lock held for the job duration.

## 16. ProcessingCheckpoint persistence

A checkpoint is a durable resume boundary, not a visual progress update. `processing_checkpoints` contains `id`; `processing_run_id`; nullable `execution_segment_id`; monotonic `ordinal`; `kind` (`INTERMEDIATE`, `FINAL`); `state` (`VALID`, `INVALIDATED`); `payload_schema_version`; `payload_json`; `created_at`; nullable `invalidated_at`; and nullable `invalidated_reason`. Enforce `UNIQUE(processing_run_id, ordinal)` and one valid final checkpoint per run using a partial unique index.

Writing a checkpoint happens in a short settlement transaction after all work before its boundary is durably represented. Recovery asks for the latest valid supported checkpoint and moves backward when the payload reader cannot safely interpret it. A `FINAL` checkpoint says outputs are durably settled and acceptance may be completed without rerunning ML; it is not itself acceptance.

## 17. IndexOperation persistence

`index_operations` is the durable reconciliation queue between SQLite and USearch. Columns: `id`; `representation_id`; `representation_space_id`; `operation` (`ADD`, `REMOVE`); `state` (`PENDING`, `APPLIED`, `FAILED`); `attempt_count`; `not_before_at`; `last_attempt_at`; nullable `applied_at`; `failure_code`, `failure_detail`; `created_at`, `updated_at`.

`ADD` means ensure that this representation is currently present if it remains `ACTIVE` and eligible. `REMOVE` means ensure absence regardless of stale index contents. The coordinator re-reads authoritative representation state before acting, making both operations idempotent and safe to coalesce. A unique partial index prevents duplicate pending operations for the same `(representation_id, operation)`; creating an opposite operation must supersede/coalesce the obsolete desired state in the use case. The coordinator is the normal sole writer to USearch. It marks `APPLIED` only after the index mutation succeeds and its durable manifest is settled.

## 18. Runtime, component, and package metadata

The hierarchy is fixed: `Component -> ComponentVersion -> ModelExport -> RuntimeVariant`, alongside `RepresentationSpace`, `RecognitionCalibrationProfile`, and installable `RuntimePackage`. Installation state is separate from semantic model metadata.

| Table | Required purpose and key fields |
|---|---|
| `components` | logical capability: `id`, unique `key`, `kind`, `display_name`, `state` |
| `component_versions` | immutable semantic implementation: `id`, `component_id`, unique `(component_id, semantic_version)`, `contract_schema_version`, `contract_json`, `created_at` |
| `model_exports` | immutable executable artifact description: `id`, `component_version_id`, `format`, `precision`, `artifact_id`, `sha256`, `input_contract_json`, `created_at` |
| `installed_model_exports` | local byte/install state: `id`, `model_export_id`, `artifact_id`, `state`, `installed_at`, `verified_at`, `failure_detail` |
| `runtime_variants` | execution configuration: `id`, `model_export_id`, `provider`, `device_kind`, `variant_key`, `requirements_json`, `state` |
| `runtime_variant_representation_spaces` | explicit validated compatibility mapping: `runtime_variant_id`, `representation_space_id`, `validation_json`, `state`, primary key pair |
| `recognition_calibration_profiles` | immutable interpretation profile: `id`, `representation_space_id`, `version`, `state`, `parameters_json`, `schema_version`, `created_at`, unique `(representation_space_id, version)` |
| `runtime_packages` | trusted installable bundle metadata: `id`, unique `key`, `manifest_schema_version`, `manifest_json`, `state`, `created_at` |
| `runtime_package_installations` | local package installation state: `id`, `runtime_package_id`, `artifact_id`, `state`, `installed_at`, `verified_at`, `failure_detail` |

Use association tables for package membership only when the trusted manifest needs relational querying: `runtime_package_runtime_variants(package_id, runtime_variant_id)` and `runtime_package_model_exports(package_id, model_export_id)`. Metadata rows are retained after uninstall; only installation records/managed package bytes change. A calibration change creates a new immutable profile. Runtime fallback is decided by FastAPI after an ML error and creates a new execution segment; the worker never silently changes providers.

## 19. Settings persistence

Persist one singleton row for each normal user setting group. Settings are mutable preferences, not processing provenance.

| Table | Singleton key and content |
|---|---|
| `processing_settings` | `id = 1`; sampling/crop/processing behavior that is not model-calibration truth; `revision`, `updated_at` |
| `storage_settings` | `id = 1`; managed root policy, derivative retention and storage behavior; `revision`, `updated_at` |
| `runtime_settings` | `id = 1`; provider preference/fallback policy and installed package selection; `revision`, `updated_at` |

Each table uses typed stable columns where a value is stable, plus a small versioned JSON payload only for a genuine structured group. `CHECK(id = 1)` enforces singleton identity. Bootstrap inserts the rows transactionally. PATCH uses optimistic `revision` handling. Resolution order is application defaults, user preferences, semantic operation overrides, capability/runtime resolution, then immutable run snapshot. `.env` is development/startup override input, never the normal production settings database.

## 20. Referential constraints and state invariants

Use `ON DELETE CASCADE` only for strict owned records that have no independent historical meaning: observation-owned representations, occurrence membership rows, evidence link/candidate rows, runtime compatibility/membership rows, and checkpoints only if the owning run is actually permanently removed. Use `RESTRICT` for historical provenance and semantic objects: source originals, runs, component versions, representation spaces, identities, people, evidence, and model metadata. Use `SET NULL` for optional conveniences such as thumbnails or representative observations.

Application-level transactional validation must enforce cross-row rules SQLite cannot express cleanly:

- Active Observations, Occurrences, and Representations belong only to an accepted/currently valid run output and active source/identity context.
- An active Representation has a canonical vector, its own space's dimension, a unique ann key, and an active identity.
- A pending Representation is private to exactly one non-completed run and absent from the global index.
- A source points to a completed accepted `current_processing_run_id` for that source only.
- A final checkpoint exists before run acceptance.
- A non-terminal Job has at most one current lease and a running ProcessingRun has at most one running segment.
- Evidence payload and referenced records agree with the action being applied.

Do not encode state-machine transitions solely in database CHECK constraints. Transition validation belongs in the explicit use case so the error is comprehensible and all related durable intent is written atomically.

## 21. Index design

Indexes are part of the design, not an afterthought. Create these in the initial migration:

| Table | Index |
|---|---|
| `artifacts` | unique managed `storage_key`; `(state, created_at)` for recovery; `sha256` for verified duplicate checks |
| `sources` | `(state, created_at DESC, id DESC)` library page; `(current_processing_run_id)`; `(original_artifact_id)` |
| `processing_runs` | `(source_id, created_at DESC)`; `(state, updated_at)`; partial transient state index |
| `jobs` | `(state, priority, created_at)` claim path; `(lease_expires_at)`; `(processing_run_id)` |
| `execution_segments` | `(processing_run_id, ordinal)` unique; partial current-running index |
| `processing_checkpoints` | `(processing_run_id, ordinal DESC)`; partial valid-final index |
| `observations` | `(processing_run_id, sequence_in_run)` unique; `(source_id, state, created_at)`; `(face_crop_artifact_id)` |
| `representations` | unique `ann_key`; `(representation_space_id, state, ann_key)` streaming rebuild path; `(identity_id, state)`; `(processing_run_id, state)` |
| `occurrences` | `(source_id, state, created_at)`; `(identity_id, state, created_at)`; `(processing_run_id, state)` |
| `evidence` | `(subject_identity_id, created_at DESC)`; `(processing_run_id, created_at)`; `(kind, created_at)` |
| `index_operations` | `(state, not_before_at, created_at)` coordinator claim; `(representation_space_id, state)` |
| `people` | `(state, normalized_name)`; `identity_person_associations` partial active identity uniqueness and `(person_id, state)` |

Do not index JSON indiscriminately. Add a generated/indexed scalar only after a stable query path proves it necessary. SQLite FTS5, camera-specific indexes, general audit/event indexes, and counter tables are deferred.

## 22. ORM relationships and loading policy

Relationships are defined for useful bounded to-one navigation: `Representation -> Observation/Identity/RepresentationSpace/ProcessingRun/ExecutionSegment`, `Observation -> Source/ProcessingRun/ExecutionSegment`, `Occurrence -> Source/Identity/ProcessingRun/representative Observation`, `ProcessingRun -> Source/Snapshot`, `ExecutionSegment -> Run/RuntimeVariant`, and `IdentityPersonAssociation -> Identity/Person/Evidence`.

Do not expose ordinary navigable collections for unbounded data: `Source.observations`, `Source.occurrences`, `Identity.representations`, `Identity.occurrences`, `Identity.evidence`, `ProcessingRun` output collections, or `Evidence.candidates`. If an internal relationship is required, configure `lazy="raise"`; application code must use explicit queries. A database FK does not require symmetric ORM navigation.

Query rule:

| Shape | Loading rule |
|---|---|
| bounded to-one needed now | query-level `joinedload()` |
| small bounded collection | query-level `selectinload()` |
| large/growing collection | explicit cursor-paginated query |
| API list/read model | projection query where it avoids unwanted columns/joins |

Use bulk `update()` for acceptance state transitions when no per-row decision is needed. Never serialize ORM objects directly into API responses. API schemas and query result objects such as `RecognitionCandidateRow`, `SourceLibraryRow`, and `JobQueueCandidate` are explicit projections.

## 23. Vector persistence and ANN reconciliation

Vectors are encoded as contiguous little-endian `float32` bytes. Before storage, validate the exact dimension, finite values, and normalization required by the RepresentationSpace contract. Store canonical vectors in SQLite `LargeBinary`; do not store them as JSON arrays, base64, or only in USearch. V1's practical ceiling is a local desktop library; if vector volume later makes SQLite blob streaming a measured bottleneck, introduce a versioned external vector store without changing the representation identity/provenance contract.

Build one USearch index per RepresentationSpace, never a mixed index. Index directory manifests contain `index_format_version`, `representation_space_id`, `generation_id`, and `built_at`. The coordinator receives the durable operation, rereads the representation, performs desired-state add/remove idempotently, atomically persists the index/manifest generation, then marks the operation applied. A missing, corrupt, mismatched, or unsupported index is quarantined/discarded and rebuilt by streaming active eligible representations from SQLite.

Recognition searches global active vectors plus a run-local pending index. The run-local index is rebuilt from pending representations for the run after a crash and is never authoritative. ANN output is only candidate `ann_key` values; SQLite revalidates space, state, identity, and current eligibility before `RecognitionService` calculates an assessment. Nearest neighbor is not an identity decision.

## 24. SQLAlchemy engine and session factory

Create one synchronous SQLAlchemy engine for the FastAPI backend, with `sqlite+pysqlite:///...`, `future=True`, `pool_pre_ping=False`, and `connect_args={"check_same_thread": False, "timeout": 5}`. Use SQLAlchemy's default SQLite pool appropriate to the packaged local process; do not share sessions across threads or processes. The ML worker has no database engine and no SQLite access.

On every connection, install the SQLite pragmas in Section 25 and register any required deterministic helper functions. Build `sessionmaker(engine, autoflush=False, expire_on_commit=False)` and use sessions through scoped request/background-operation context managers. `expire_on_commit=False` prevents surprising post-commit refreshes while response values are mapped, but it does not make ORM instances long-lived truth.

FastAPI requests use one bounded session/use-case transaction. Processing, recovery, scheduler, and indexing each open a fresh session for one short settlement operation. Pass UUIDs and small value objects through long-running work, never live ORM instances. Reload records immediately before a mutation because sources/jobs can be recycled, cancelled, or changed while compute ran.

## 25. SQLite WAL, pragmas, and concurrency

For every connection, execute:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

`foreign_keys=ON` is mandatory because constraints/cascades otherwise do not protect the model. WAL permits readers during normal writes; it does not permit multiple writers to hold long transactions. `synchronous=NORMAL` is an acceptable local-desktop durability/performance choice because all workflows are recoverable; use `FULL` only if evaluation or product policy requires the additional cost. The application must tolerate `SQLITE_BUSY`: keep writes short, retry a small bounded number of times for known transient write conflicts, and return a diagnostic/retryable error rather than spin forever.

Do not run `VACUUM`, checkpoint pressure, index rebuilds, or storage scans inside a request transaction. Startup and maintenance can issue a bounded WAL checkpoint only when safe; it is an optimization, not a correctness mechanism. Backups copy the SQLite database using SQLite-aware backup/online methods, not an arbitrary file copy while it is active.

## 26. Repository and read-query patterns

Repositories are narrow feature persistence helpers. They query, add, update, delete where authorized, flush, and build explicit select/update statements. They do not commit and do not decide business truth. The use-case layer owns transactions and cross-feature orchestration.

Initial methods are intentionally small:

| Repository | Minimum responsibility |
|---|---|
| Artifact | add/get, find pending/deleting, transition state |
| Source | add/get, library page, set current run, update lifecycle |
| ProcessingRun/Snapshot | add/get/lock, list transient, create/get immutable snapshot |
| Job | add/get, atomic claim, progress/state transition, transient list |
| ExecutionSegment/Checkpoint | append/get/list/close; latest valid/final checkpoint; invalidate checkpoint |
| Observation/Representation | batch add, explicit pages/streams, candidate lookup by ann keys, ann-key allocation, lifecycle transition |
| Identity/Occurrence/Evidence | lock/get/create and append the semantic links needed by their use cases |
| IndexOperation | append batch, pending/failed batch, attempt/applied/failed transition |
| RuntimeCatalog/Settings | cohesive catalog reads/writes; singleton group reads/updates |

Examples of top-level use cases are `ImportSourceUseCase`, `ProcessSourceUseCase`, `ExecuteProcessingJob`, `AcceptProcessingRunUseCase`, `AssignIdentityToPersonUseCase`, and later merge/split/forget use cases. Top-level use cases coordinate repositories and services; they do not call other top-level use cases as hidden subroutines.

> **Decision 2026-09-23:** the domain-level merge and split use cases are built in testing milestone M1; only forget is "later" here (see the §7 note).

## 27. Alembic structure and migration policy

Use a normal Alembic environment at `backend/alembic/` with migrations under `backend/alembic/versions/`. The first revision is `0001_initial_schema` and creates the coherent baseline tables listed here. It includes Person/association/lineage and runtime metadata because their contracts are already stable, but excludes cameras, training datasets/runs, search history, generic audit logs, generic events, notifications, ANN generation tables, and speculative feedback tables.

Migration rules:

1. Every schema change is an explicit reviewed Alembic revision. Never use `create_all()` in production startup.
2. Startup upgrades supported older databases to the packaged head revision before scheduler or ML work starts.
3. A database newer than the application fails safely with `DATABASE_SCHEMA_NEWER_THAN_APPLICATION`; do not downgrade automatically.
4. Migrations are forward-only in production. Development-only downgrade support is convenience, not the recovery plan.
5. Make additive, backfill, then enforce changes in separate revisions when a table can be large. Do not hold a long application-wide migration transaction while copying media or recomputing vectors.
6. Schema migration changes relational structure. Re-embedding, thumbnail regeneration, USearch rebuilding, and artifact layout changes are durable background workflows, not Alembic data guesses.
7. Test migration from the previous released revision and a fresh database. Verify foreign keys and required partial indexes after upgrade.

Alembic revisions use SQLite-safe operations: batch table recreation when SQLite cannot alter a constraint in place, explicit data validation before adding non-null/unique constraints, and no assumption that a downgrade can restore discarded data.

## 28. Startup recovery and reconciliation

Startup ordering is DB/migrations, storage initialization, recovery, index validation/rebuild scheduling, runtime catalog/installation validation, ML supervisor, scheduler, then readiness. Recovery is idempotent and records only durable repairs; it must be safe to repeat after another crash.

| Durable state found | Recovery action |
|---|---|
| `Artifact PENDING` | verify final/temp bytes and finalize to `AVAILABLE`, retry/clean owned temp data, or mark failure |
| `Artifact DELETING` | verify absence, repeat managed deletion, finalize `DELETED`, or retain retryable failure |
| expired/running Job | mark `INTERRUPTED` or requeue only when safe; clear lease |
| running run/segment | close segment as `INTERRUPTED`/`ABANDONED`; use latest valid checkpoint |
| final checkpoint + unaccepted run | revalidate and run acceptance transaction without redoing ML |
| pending run output without final checkpoint | resume from supported checkpoint or safely fail/not-resumable; it remains private |
| pending/failed IndexOperation | wake coordinator with bounded retry/backoff |
| missing/corrupt/mismatched USearch file | quarantine/discard and queue `REBUILD_INDEX` from active SQLite vectors |
| orphan processing temp workspace | remove only application-owned workspace after verifying no live run needs it |
| interrupted runtime installation | verify bytes/hash then finalize, remove partial managed bytes, or mark failed |

Recovery never turns a pending run's partial outputs into active library memory merely to make the UI look complete. It never assumes an ML worker response survived a crash. Readiness is capability-based: unavailable ML or rebuilding ANN can produce `DEGRADED` while SQLite/library browsing remains available.

## 29. Migration and data-version compatibility policy

There is no single application data version. Version dimensions include the release version, Alembic revision, snapshot/checkpoint/evidence payload schemas, RepresentationSpace contract, calibration profile, component/model/runtime contracts, runtime manifest, USearch index format, and managed storage layout. Never collapse these into a generic `version = 7`.

| Persisted category | Upgrade policy |
|---|---|
| authoritative semantic state: Source, Identity, Person, Occurrence, Representation vector | preserve; use explicit relational migration when required |
| historical provenance: snapshots, segments, Evidence, component/calibration contracts | preserve unchanged and read with a version-aware reader |
| operational checkpoint | read/resume only when safely supported; fall back to an older valid checkpoint or invalidate |
| derived state: USearch, thumbnails, run-local ANN, temporary files | discard/quarantine and rebuild or regenerate |

Versioned JSON rows retain their original payload and schema version. Readers may normalize old versions in memory, but the application writes only the current version. An old snapshot uses its documented historical default semantics, never current Settings. An unknown newer semantic version is rejected safely; an unsupported old version remains preserved but may have reduced detail available.

Vectors remain attached to their original RepresentationSpace forever. A new embedding model creates a new ComponentVersion, RepresentationSpace, and Representations through re-embedding from retained imagery; it is not an SQL update of old `representation_space_id` values. Deprecated spaces remain historical and can be excluded from V1 normal recognition. Calibration profiles are immutable; a newer profile can interpret eligible old vectors in the same validated space, but it never rewrites historical Evidence confidence.

USearch manifests validate their format, space ID, and generation ID on startup. Any incompatibility rebuilds from canonical SQLite vectors. Model installation bytes may be removed without invalidating historical semantic metadata; exact historical reprocessing is unavailable unless a compatible export is installed. Managed originals are preserved exactly across storage-layout changes; `storage_key`, hashes, durable intent, and StorageManager compatibility support a later background move without an unsafe startup rewrite.

## 30. First vertical-slice persistence subset

The first vertical slice proves: import a managed image, detect multiple faces, persist representations, recognize an existing or create an unknown Identity, create Evidence and Occurrences, accept output atomically, converge USearch, and recover safely from interruption.

```text
Import image -> Artifact + Source
Process command -> immutable Snapshot + ProcessingRun + Job
Claim -> ExecutionSegment -> detection -> PENDING Observations
Embedding -> PENDING Representations -> candidate revalidation
RecognitionAssessment -> IdentityReasoner -> Evidence + PENDING Occurrences
FINAL Checkpoint -> acceptance transaction -> IndexOperations
USearch convergence -> completed Job/Run -> UI result
```

`AcceptProcessingRunUseCase` performs the critical transaction: revalidate a finalizable run; transition the run's pending observations, representations, newly-created identities, and occurrences to `ACTIVE`; create `ADD` operations for new ANN-eligible representations; set `Source.current_processing_run_id`; then mark Run and Job `COMPLETED`. Commit before waking the IndexCoordinator. A failed index update leaves valid accepted SQLite memory plus a retry/rebuildable degraded index; it does not retroactively fail the run.

For an image, an occurrence has kind `IMAGE`, null frame/time range, one observation membership, and that observation as representative. The important checkpoint is `FINAL`; it proves startup can finish acceptance after a crash without rerunning ML. Run-local candidate memory permits a pending newly-created identity to be recognized again during the same run; rebuild it from pending run representations after recovery.

The initial migration includes: artifacts, sources, configuration snapshots, runs, segments, checkpoints, jobs, runtime catalog tables, representation spaces/calibration mappings, observations, representations, ann-key sequences, identities/lineage, people/associations, occurrences/membership, evidence/link/candidate tables, index operations, and the three settings singleton tables. The slice implements only `IMAGE`, managed import, detector/embedder metadata, one preferred evaluated RepresentationSpace and calibration profile, and `ADD`/`REMOVE` index coordination.

Do not include movie/tracking/camera processing, live recognition, Person UI, merge/split/forget UI, recycle/permanent-delete UI, reprocessing UI, training, feedback learning, multiple active spaces, face-query search, FTS5, runtime installation UI, GPU benchmarking UI, storage migration, or concurrent heavy pipelines. The schema leaves room for them; the vertical slice must not build them early.

The acceptance checks for this milestone are: deleting an index and restarting rebuilds from SQLite vectors; a crash after a final checkpoint completes acceptance without duplicate memory; a crash after artifact reservation leaves no falsely available source; a lost scheduler wake is found from queued work; and an ANN failure leaves the accepted source/identity/representation visible while reporting degraded recognition capability.
