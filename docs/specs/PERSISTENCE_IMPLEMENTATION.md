# Persistence Implementation

## Status and scope

This document is the implementation contract for the local Windows Visual Identity / Face Memory application. It turns the locked product, processing, identity, API, and runtime decisions into a concrete SQLite and SQLAlchemy 2 design. SQLite is the authoritative store for relational meaning; the filesystem owns artifact bytes; USearch is a rebuildable candidate index. This document does not select face models, similarity thresholds, or calibration values. Those are evaluation outputs, not persistence defaults.

The first implementation uses SQLite, SQLAlchemy 2, Alembic, a single FastAPI-owned backend process, one persistent ML worker, and USearch. Do not introduce a server database, event store, generic metadata table, generic repository, or distributed transaction layer.

## 1. Persistence principles and database layout

The database is one application-owned SQLite file inside the user-selected library root, at `<Library Root>/database/library.db`, beside the managed bytes it describes. Derived and disposable state lives in machine-local state (`%LOCALAPPDATA%/<App>`):

```text
<Library Root>/                        %LOCALAPPDATA%/<App>/
  database/library.db                    indexes/          (e.g. representations/<space-key>/)
  originals/  crops/  thumbnails/        cache/
  models/     derived/                   temp/             (processing scratch)
  backups/    recovery/                  logs/
  staging/    (managed writes in flight) runtime/  installation/
```

> **Decision 2026-09-25:** the storage layout is tech-stack.md §15's two roots, and this section, which previously showed a single `data/` directory as an example, was aligned to it. Managed writes stage in `<Library Root>/staging/`, on the same volume as their final directory, so the final rename is atomic even when the library is on another drive. (Owner decision, M2 PR #14.)

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

> **Decision 2026-10-03 (owner; GitHub issue 88, CONTEXT open question 31): output-level execution provenance is a nullable `runtime_variant_id` on the output row.** `observations` gains a nullable `runtime_variant_id` FK (`RESTRICT`), the detector variant that produced the observation. The chain `observations.runtime_variant_id -> runtime_variants -> model_exports -> component_versions` supplies the export, the component version and (through the variant) the runtime package; none of those ids is duplicated on the output row, so they cannot disagree. (1) The value is the variant that **actually executed**, never the configured or preferred one: when CUDA falls back to CPU and that is a different registered variant, the CPU variant is stored. (2) The catalog rows an output references stay durable: removing the managed runtime files makes the package unavailable but never deletes the variant, export or component-version rows (the FK is `RESTRICT`), so historical provenance always resolves. (3) The column is nullable so that migrated rows and non-ML fixtures stay valid, but the application requires it: the writer of newly produced ML output never creates a detector observation or a face representation without the variant that produced it. (4) `RepresentationSpace` stays compatibility metadata and gains nothing for provenance; `ExecutionSegment` stays lifecycle and execution context (when, and under which interval) and is not split per ML stage; no provenance table is added while one output has exactly one producing variant per stage. (5) `detector_component_version_id` is kept in `0005` (removing it is later cleanup, after every consumer is known), and while both are present they must agree: the component version of the variant's export is `detector_component_version_id`. The column pair is delivered by revision `0005`.

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

> **Decision 2026-10-02 (owner; CONTEXT open question 31): the two persisted states stand, and what `component_version_id` means.** (a) A persisted `RepresentationSpace` is `ACTIVE` or `DEPRECATED`, and nothing else: the ML spec's `REGISTERED`, `VALIDATED`, `ACTIVE`, `RETIRED` (ML 9.2) mix a registration process (discover, validate, register) with the durable lifecycle. A space becomes a row only once its compatibility contract is validated enough to register, so `REGISTERED` and `VALIDATED` are not persisted states; `RETIRED` is `DEPRECATED`. A newly registered valid space is `ACTIVE`. (b) `component_version_id` is **origin provenance**: the component version that established (first registered) the space. It does not mean that only that version ever produced vectors in the space. A later component version with identical space-defining semantics shares the existing space and does not overwrite the column, and spaces are not duplicated to preserve provenance. Which component version, export and runtime actually produced a given representation is execution provenance, recorded per run and segment, not on the space. The invariant: **space identity describes compatibility; execution provenance describes what produced the data.**

### 6.2 `representations`

| Column | Rule |
|---|---|
| `id` | UUID primary key |
| `observation_id` | non-null FK, `CASCADE` because a representation is owned by its observation |
| `identity_id` | nullable FK to `identities`, `RESTRICT` |
| `processing_run_id`, `execution_segment_id` | non-null provenance FKs, `RESTRICT` |
| `representation_space_id` | non-null FK, `RESTRICT` |
| `state` | `PENDING`, `ACTIVE`, `SUPERSEDED`, `ERASING`, `ERASED`, `DELETED` |
| `ann_key` | nullable positive signed 64-bit integer, unique within its `representation_space_id` (`UNIQUE(representation_space_id, ann_key)`, decided 2026-10-01, delivered by revision `0003`); required while ANN-eligible |
| `vector` | non-null canonical float32 blob |
| `vector_dimension` | non-null positive integer, checked against its space in application validation |
| `quality_json` | nullable measured embedding/quality facts |
| `created_at`, `activated_at`, `erased_at` | lifecycle |

Use `UNIQUE(observation_id, representation_space_id)` for one persisted embedding per observation per semantic space. An active representation must have an allocated `ann_key`, a non-erased vector and an active identity (an accepted `ABSTAIN` representation is `ACTIVE` with no identity: see the decision of 2026-10-02 after section 6.2). `PENDING` representations are run-private and must never be placed in the global ANN index. `ERASED` retains provenance but has `vector = NULL`, `ann_key = NULL`, and is reached only through `ERASING` (below): its `REMOVE` operation must have been applied, and every superseded index generation that could hold its vector retired, before the vector is cleared.

> **Decision 2026-10-03 (owner; GitHub issue 88, CONTEXT open question 31): output-level execution provenance is a nullable `runtime_variant_id` on the output row.** `representations` gains a nullable `runtime_variant_id` FK (`RESTRICT`), the embedder variant that produced the representation. The chain `representations.runtime_variant_id -> runtime_variants -> model_exports -> component_versions` supplies the export, the component version and (through the variant) the runtime package; none of those ids is duplicated on the output row, so they cannot disagree. (1) The value is the variant that **actually executed**, never the configured or preferred one: when CUDA falls back to CPU and that is a different registered variant, the CPU variant is stored. (2) The catalog rows an output references stay durable: removing the managed runtime files makes the package unavailable but never deletes the variant, export or component-version rows (the FK is `RESTRICT`), so historical provenance always resolves. (3) The column is nullable so that migrated rows and non-ML fixtures stay valid, but the application requires it: the writer of newly produced ML output never creates a detector observation or a face representation without the variant that produced it. (4) `RepresentationSpace` stays compatibility metadata and gains nothing for provenance; `ExecutionSegment` stays lifecycle and execution context (when, and under which interval) and is not split per ML stage; no provenance table is added while one output has exactly one producing variant per stage. `representation_space_id` still says which space the vector is in; the variant says what computed it, and the variant must be validated for that space (`runtime_variant_representation_spaces`). The column pair is delivered by revision `0005`.

> **Decision 2026-09-23:** `vector` is nullable **only** for `ERASED`: a CHECK requires `vector` and `ann_key` to be NULL when `ERASED`, and `vector` to be present in every other state. This resolves the column table's "non-null" against the erasure rule above. (Owner decision, M1 PR #5.)

> **Decision 2026-10-01 (owner; CONTEXT open question 25): erasure is two-step, and `ERASING` is the durable marker between the steps.**
> 1. *Step one, one transaction:* the representation moves `ACTIVE` -> `ERASING` and a durable `REMOVE` operation is queued. `ERASING` still holds its `vector` and `ann_key` (the CHECK above is unchanged: they are NULL only for `ERASED`), but it is not `ACTIVE`, so it is **excluded from recognition, from candidate revalidation (section 23) and from every index rebuild from the moment step one commits**, before the index changes. A queued erasure is therefore never returned, whatever state the index file is in.
> 2. *Step two:* only when the `REMOVE` is `APPLIED`, the index generation without the vector is persisted, and every superseded generation file of the space (and every quarantined one) has been verifiably removed (section 23), does the representation move `ERASING` -> `ERASED`, clearing `vector` and `ann_key`. This keeps "SQLite precedes the index" (INDEX-01). (How the `REMOVE` is applied is decided in the note of 2026-10-02 on issue 57 below: while the index backend cannot truly delete, it is applied by rebuilding the space.)
> 3. *Bulk forget* batches: step one for every representation, then **one** rebuild of the space's index from SQLite (which already excludes them), retirement of the old generation, then step two for all. It never rebuilds once per representation.
> 4. `ERASING` only ever moves forward to `ERASED`; it is never reactivated. Startup recovery (section 28) finds `ERASING` representations, queues the `REMOVE` if it is missing, and finishes step two when its conditions hold.
> 5. This adds `ERASING` to the state CHECK of `representations`: a schema change delivered as reviewed Alembic revision `0002` (done), which is also the populated-database, batch-mode migration that CONTEXT open question 18 required.
> 6. *Retrieval.* Candidate revalidation (section 23) resolves each `ann_key` to its `representations` row and accepts it only if the row is in the same space and `ACTIVE`, with an `ACTIVE` identity or, for an accepted `ABSTAIN` representation, no identity (the candidate is then evidence only, never a match target; a representation pointing at a non-`ACTIVE` identity stays ineligible). That step is `resolve_ann_candidates` (built; `resolve_recognition_candidates` revalidates identity ids only and cannot see a representation's state): it reads the representation row, because an identity-only check would let a stale index return an `ERASING` vector.
> 7. *Ordering with the coordinator.* Queueing the `REMOVE` deletes the representation's pending `ADD` in the same transaction (open question 27), so a due batch never holds both for one representation. The coordinator's lock serializes its own passes, not the erasure transaction, so an `ADD` it claimed before step one commits can go either way: it is applied (the vector is briefly in the raw index but never returned, by item 6) and the `REMOVE` queued by step one, claimed by a later pass, removes it; or it re-reads the representation as `ERASING` and does nothing (an ineligible representation is skipped). Either way the `REMOVE` still runs afterwards and the erasure is not finished until it is `APPLIED`. Settlement tolerates the `ADD`'s row having been deleted meanwhile.
> 8. *The state machine is guarded.* `ACTIVE` -> `ERASING` and `ERASING` -> `ERASED` are guarded transitions (`UPDATE ... WHERE state = X`): a second erasure of a representation already `ERASING` or `ERASED` is a no-op, nothing moves a representation out of `ERASING` except to `ERASED`, and identity merge and split leave an `ERASING` representation's state alone.
> 9. *SQLite residue (decision 2026-10-01, issue 31).* After step two commits (the vector and key cleared), the batch ends with the truncating checkpoint of section 25. The erasure is complete only when the index generations are retired **and** that checkpoint has succeeded (recorded durably, section 25); until both, it is reported with its outstanding cleanup. The order is therefore: queue and exclude (`ERASING`); apply the index removal or publish a replacement generation; retire superseded and quarantined generations; clear the SQLite vector and key and commit; checkpoint; verify the representation cannot be retrieved.
> 10. The existing coordinator behaviour for a *keyless* `REMOVE` (rebuild the space and require the old generation to be gone) stays as the safety net for a representation that reached `ERASED` any other way.

> **Decision 2026-10-01 (owner; erasure use case, issues 29 and 52):** (a) *Erasable states.* `ACTIVE`, `PENDING` and `SUPERSEDED` representations move to `ERASING` (guarded `UPDATE ... WHERE state IN (...)`); a representation without an `ann_key` was never in an index, so it queues no `REMOVE` and bypasses ANN removal and rebuild work. `ERASED` and `DELETED` are not erasable. (b) *No Evidence for representation-level erasure.* Section 7's "durable Evidence" requirement for forget applies to the semantic, identity-level forget (`IDENTITY_FORGOTTEN`), not to low-level representation erasure, whose durable record is the representation's state, the persisted `IndexOperation`s and the erasure lifecycle itself. (c) *The "WAL truncation owed" marker* is a row of the key/value table `app_state` (key `wal_truncation_owed`), delivered as revision `0004`; see section 25. **Agent finding, decided by the owner on 2026-10-02 (issue 57; the decision note below):** item 2 above said step two "needs no rebuild for a single erasure". A probe shows that a USearch generation saved after `remove()` still contains the removed vector's bytes, and one rebuilt without it does not, so the `REMOVE` of an `ERASING` representation is applied by rebuilding the space from SQLite (which excludes it), with all of a space's `REMOVE`s in a pass sharing one rebuild; an ordinary `REMOVE` stays in place. That serves the stated aim, that the vector is in no index file, and the order of items 1 to 9 is unchanged.

> **Decision 2026-10-02 (owner; issue 57): how an erasure removes a vector from the index.** One or a few erasures use persisted `REMOVE` operations and an incremental removal **where the index backend's deletion satisfies the erasure contract** (the removed vector's bytes are gone from what is saved); they do not rebuild the space by default. Where the backend cannot (unsupported or unsafe), the affected space is rebuilt from SQLite and the replacement generation published; the same applies to bulk forgetting, which is **one consolidated rebuild per affected space**, never one per representation. The rebuild excludes the erased representations, publishes the replacement generation atomically and retires the old one. **The current backend falls in the second case:** a USearch generation saved after `remove(key)` still contains the removed vector's bytes (pinned by `test_an_ordinary_remove_is_applied_in_place_and_leaves_the_bytes_in_the_saved_file`), so an `ERASING` representation's `REMOVE` is applied by a rebuild, every `REMOVE` of a space in one pass shares one rebuild, and an ordinary `REMOVE` (merge, ineligibility) stays in place. This is what is built (`RepresentationEraser`, `IndexCoordinator`); it is revisited if the backend gains a real delete.

> **Decision 2026-10-02 (owner; M3 plan): an accepted representation may be `ACTIVE` without an identity.** `PENDING` is exclusively a pre-acceptance, run-private state and never means "unresolved identity". Identity resolution and publication are separate dimensions: a representation whose recognition outcome is `ABSTAIN` is accepted as `ACTIVE` with `identity_id` NULL, receives an `ann_key` and enters its compatible global ANN space as unresolved candidate evidence. It can never by itself constitute `MATCH_EXISTING`, which requires resolution to an Identity (assigned later through the Identity Manager). The sentence above ("An active representation must have an active identity...") therefore reads: an active representation has an allocated `ann_key` and a non-erased vector, and an active identity **unless it is an accepted `ABSTAIN` representation**. Migration `0005` relaxes exactly one half of the CHECK, from `state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)` to `state != 'ACTIVE' OR ann_key IS NOT NULL`; `ACTIVE` with a NULL `ann_key` stays rejected. Candidate revalidation (section 23) must treat an identity-less candidate as evidence only, never as a match target. Not yet built: the migration is built with the acceptance use case (M3 plan).

> **Decision 2026-10-02 (owner; issue 71): the `ABSTAIN` follow-ups.** (1) An accepted `ABSTAIN` representation creates **no `Occurrence`**: the system knows a face representation was observed, not that Identity X occurred there, and an identity-linked Occurrence would assert what the reasoner declined to assert. It does leave an `Observation`, the `ACTIVE` representation (identity NULL, `ann_key` allocated) and its candidate `Evidence`. (2) Resolving it later is an explicit Identity Manager use case (`ResolveUnresolvedRepresentation`), not an ad hoc update: it sets the identity, creates the corresponding `Occurrence` and records resolution Evidence. It does **not** allocate a new `ann_key` or remove and re-add the vector, because the visual representation has not changed, only its semantic association. It is documented here and tracked separately; M3 builds it only if its tests need it. (3) A persisted `ABSTAIN` covers the estimator's `AMBIGUOUS` and `ABSTAIN` outcomes and the policy action `PRESERVE_UNRESOLVED`. (4) Identity-level forget works through `identity_id`, so it does not reach identity-less representations; those are erased through representation or Source erasure.

### 6.3 `ann_key_sequences`

This table has one row per `representation_space_id`: the space UUID primary key/FK and `next_ann_key INTEGER NOT NULL CHECK(next_ann_key > 0)`. Allocation occurs in the same short transaction that makes a representation ANN-eligible (when it is assigned to an identity and becomes `ACTIVE`, or is accepted as an `ABSTAIN` representation; a `PENDING` representation has no key), using a guarded update; keys are never reused by a committed allocation. A gap is harmless and safer than reuse after a crash or erase.

> **Decision 2026-10-01 (owner; GitHub issue 48): an `ann_key` identifies a representation within one space, not across the application.** §6.2 said `ann_key` is unique and the schema made it unique across the whole table, while this section allocates from a sequence per space that each starts at 1: two spaces both allocate `1`, and the second `ACTIVE` representation failed with `IntegrityError` (shown by a test). The constraint is now `UNIQUE(representation_space_id, ann_key)`, matching one USearch index per space. Every index lookup and removal therefore carries both the space and the key (an index belongs to one space, and a key is resolved to its representation through the pair). The allocation policy is unchanged: a permanent key is allocated only when a representation becomes ANN-eligible (CONTEXT open question 21, finalised in the 2026-10-02 decision below), and run-local pending indexes keep their own ephemeral labels. A `NULL` key (an `ERASED` representation) is still allowed to repeat. Delivered as revision `0003`, which recreates `representations`, keeps every existing key and verifies the new uniqueness (the new constraint is weaker than the old, so no existing database can violate it). This was also CONTEXT's older open question 13.

> **Decision 2026-10-02 (owner direction 2026-10-01; CONTEXT open question 21): `ann_key` is allocated at ANN-eligibility, and the run-local index never uses it.** The key is allocated when a representation becomes ANN-eligible, unique within its space (the existing `RepresentationRepository.allocate_ann_key`). Because allocation is inside the transaction, a rolled-back allocation is handed out again; that is harmless because only committed keys are ever indexed (INDEX-01). The run-local pending index (section 23) therefore uses its own ephemeral labels (for example a per-run integer mapped to `representation_id`) and never depends on a permanent `ann_key` of a transaction that might roll back. No code change: nothing yet builds the run-local index (M3).

## 7. Identity persistence

An `Identity` is the persistent visual subject, named or unknown. It is the target of recognition reasoning; it is not a vector, a Person, or an ANN entry.

`identities` has: `id`; `state` (`PENDING`, `ACTIVE`, `MERGED`, `SPLIT`, `FORGOTTEN`, `DELETED`); nullable `created_by_processing_run_id`; nullable `representative_observation_id`; nullable `merged_into_identity_id`; `revision`; `created_at`, `activated_at`, `forgotten_at`, and `updated_at`. All identity foreign keys use `RESTRICT` except the optional representative observation uses `SET NULL`.

Only an accepted run may activate a pending identity. An active identity must not point to a merged/forgotten target. Recognition selects an existing active identity, creates a pending one, or abstains (Roadmap decision 2026-10-02; an abstention assigns and creates no Identity); it never assigns a Person directly. Merge, split, and forget are later explicit use cases. They change current associations/representation eligibility with durable Evidence and IndexOperations; they do not rewrite historical Evidence.

> **Decision 2026-09-23:** domain-level merge and split (with correction and Person association) are built in testing milestone M1; "later" above refers to their UI and integration. Forget is still later. They remain outside the first vertical slice (§30).

> **Decision 2026-10-01 (owner):** the "durable Evidence" a forget leaves applies to the semantic, identity-level forget (`IDENTITY_FORGOTTEN`), which works through `identity_id` and so does not reach an identity-less accepted `ABSTAIN` representation (section 6.2, decision of 2026-10-02). Representation-level erasure (section 6.2) writes no Evidence: its durable record is the representation state, the persisted `IndexOperation`s and the erasure lifecycle.

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

An `Occurrence` is a meaningful appearance of an Identity within a Source. For an image, one face observation creates one occurrence, except an accepted `ABSTAIN` face, which creates none (section 6.2, decision of 2026-10-02); for video it will later be a track/segment. It is distinct from the raw observation so future tracking does not change the conceptual model.

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

> **Decision 2026-10-01 (owner; GitHub issue 51): both invariants are enforced by the database.** *One snapshot per run* is `UNIQUE(processing_runs.configuration_snapshot_id)` (already in revision `0001`; the snapshot has no run column, the run holds the foreign key, so the constraint sits on the run). *Immutability* is two triggers on `processing_configuration_snapshots` (revision `0003`, built; they are defined once in the model and copied into the revision, and a test compares their text; **one known limit:** SQLite's `INSERT OR REPLACE` deletes and re-inserts without firing delete triggers, so it can rewrite a snapshot that no run references, GitHub issue 55): `BEFORE UPDATE` always aborts, so a committed snapshot's captured configuration can never change; `BEFORE DELETE` aborts while a run references the snapshot (the foreign key says so too; the trigger gives a clear message) and allows deleting one no run references. Creation is an ordinary `INSERT` in the caller's transaction. A snapshot must carry every value needed to reproduce the run inside `canonical_json` (component versions, export contracts, spaces, calibration, policies), never a reference to a mutable row.
>
> **Deleting a run retains its snapshot as historical evidence** (my decision, for the owner to confirm with the deletion work, TST-031): deleting a run does not delete its snapshot, and the trigger would refuse to while the run exists. Permanent deletion of a Source is an explicit lifecycle operation that deletes its runs and then their now-unreferenced snapshots. **The database cannot tell that operation from any other caller:** the `BEFORE DELETE` trigger allows deleting any snapshot no run references, so "only the Source-deletion lifecycle removes a snapshot" is a rule of the application (its code and tests), not a database guarantee. Ordinary updates stay prohibited either way, by the database.

## 14. ExecutionSegment persistence

An `ExecutionSegment` records what actually ran during a bounded stretch of a ProcessingRun. It is required because a requested CUDA plan may execute partially under CUDA and then continue under DirectML after an explicit backend decision.

`execution_segments` columns: `id`; `processing_run_id`; nullable `runtime_variant_id`; `ordinal`; `state` (`RUNNING`, `COMPLETED`, `FAILED`, `INTERRUPTED`, `ABANDONED`); `started_at`, `ended_at`; nullable `ended_reason` (`NORMAL`, `FALLBACK`, `CUDA_OOM`, `WORKER_CRASH`, `CANCELLED`, `SHUTDOWN`); `runtime_details_json`; and `created_at`. Enforce `UNIQUE(processing_run_id, ordinal)` and one running segment per run with a partial unique index.

Segments are closed, never reopened. Reducing a batch size within the same variant stays in the current segment. Changing provider, export, or runtime variant closes one segment and creates another. Historical segments remain resolvable even when their executable package is later uninstalled.

> **Decision 2026-10-03 (owner; GitHub issue 88):** an `ExecutionSegment` is not split per ML stage and does not carry the producing component of each output: what produced an observation or a representation is its own `runtime_variant_id` (sections 5 and 6.2). The segment still answers when, and under which execution interval, the work happened; the two are complementary.

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
- An active Representation has a canonical vector, its own space's dimension, a unique ann key, and an active identity (except an accepted `ABSTAIN` representation, which has none).
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
| `representations` | `ann_key` unique per space (`(representation_space_id, ann_key)`, revision `0003`); `(representation_space_id, state, ann_key)` streaming rebuild path; `(identity_id, state)`; `(processing_run_id, state)` |
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

Recognition searches global active vectors plus a run-local pending index. The run-local index is rebuilt from pending representations for the run after a crash and is never authoritative. ANN output is only candidate `ann_key` values; SQLite revalidates space, state, identity (an identity-less accepted `ABSTAIN` candidate is evidence only), and current eligibility before `RecognitionService` calculates an assessment. Nearest neighbor is not an identity decision.

> **Decision 2026-10-01 (owner; open question 25): retiring index generations.** A representation is eligible for recognition and for any index build only while it is `ACTIVE` with an `ACTIVE` identity (or, for an accepted `ABSTAIN` representation, with no identity); `ERASING` is never eligible (section 6.2). A `REMOVE` operation is not marked `APPLIED` until the generation without the vector is persisted **and every superseded generation file of that space has been verifiably removed** (unlinked and absent when the directory is listed again). A file that cannot be removed (locked) leaves the operation to retry with backoff; startup reports it as unresolved, and it is never reported applied while an old generation remains. Quarantined generations are kept only for diagnosis, with no time-based retention, and are deleted when an erasure in that space is finalized, because a copy of a vector that was erased is not diagnostic data; if one cannot be removed the erasure is not finalized. "Securely retired" here means this verified deletion, not a claim of physical erasure from SSD storage (TESTING_STRATEGY section 11).

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
PRAGMA secure_delete = ON;
```

`foreign_keys=ON` is mandatory because constraints/cascades otherwise do not protect the model. WAL permits readers during normal writes; it does not permit multiple writers to hold long transactions. `synchronous=NORMAL` is an acceptable local-desktop durability/performance choice because all workflows are recoverable; use `FULL` only if evaluation or product policy requires the additional cost. The application must tolerate `SQLITE_BUSY`: keep writes short, retry a small bounded number of times for known transient write conflicts, and return a diagnostic/retryable error rather than spin forever.

Do not run `VACUUM`, checkpoint pressure, index rebuilds, or storage scans inside a request transaction. Startup and maintenance can issue a bounded WAL checkpoint only when safe; it is an optimization, not a correctness mechanism. Backups copy the SQLite database using SQLite-aware backup/online methods, not an arbitrary file copy while it is active.

> **Decision 2026-10-01 (owner; GitHub issue 31): secure deletion is on, and an erasure batch ends with a truncating checkpoint.** `PRAGMA secure_delete = ON` is set on every connection (the list above): SQLite overwrites deleted content in ordinary database pages with zeros instead of leaving it in free pages. It does not reach the write-ahead log, so after an erasure batch commits the application runs `PRAGMA wal_checkpoint(TRUNCATE)`, outside any request transaction. A checkpoint can only finish when no reader holds an older snapshot; if it cannot (the call reports busy, or the log is not truncated) it is retried at the next opportunity (the next erasure batch, startup recovery, maintenance), and the erasure is reported as having outstanding cleanup, never as complete, until it has succeeded. **That needs a durable record:** `ERASED` is committed *before* the checkpoint, so a crash between them would otherwise leave the database unable to say the cleanup is still owed. The write-ahead log is database-wide and the checkpoint idempotent, so the record is database-wide too: a "WAL truncation owed" marker set in the same transaction that clears the vector and key, cleared only after a checkpoint has reported success and the log is truncated; startup recovery runs the checkpoint whenever it is set. The mechanism (a one-row settings value, or a column) is a schema/data choice to confirm with the owner when the policy is built (GitHub issue 52; the pragma and `truncate_wal` are built, the marker is not). For erasure this makes the checkpoint a privacy mechanism, not only an optimization (the sentence above, "an optimization, not a correctness mechanism", holds for every other checkpoint). **Neither is a guarantee of physical erasure:** SSD wear levelling, filesystem snapshots and backups can keep old bytes, and the application must not say otherwise (TESTING_STRATEGY section 11).

> **Decision 2026-10-01 (owner; GitHub issue 52): the marker is a key/value table.** `app_state(key TEXT PRIMARY KEY CHECK(key != ''), value TEXT NOT NULL, updated_at)`, delivered as revision `0004` (that revision contains only this table). The clearing transaction upserts the key `wal_truncation_owed` with a fresh token; after `truncate_wal` succeeds the key is deleted only if it still holds the token read before the checkpoint, so an erasure that committed meanwhile keeps its own marker. Startup recovery runs the checkpoint whenever the key is present. `app_state` holds small durable facts the application must remember across a crash; it is not a user setting group (section 19).

> **Decision 2026-10-02 (owner direction 2026-10-01; CONTEXT open question 20): write transactions begin with `BEGIN IMMEDIATE` and are retried whole.** A write unit of work takes the write lock first (waiting up to `busy_timeout`), so nothing it reads can be made stale by another writer. If SQLite still reports busy or locked (decided by result code) anywhere in it, the whole transaction is rolled back and run again a bounded number of times with the caller's back-off, then fails with a retryable `DatabaseBusyError`; it is never retried per statement, and non-idempotent work (sending, writing a file, spawning) stays outside it or is idempotent. Reads are deferred and take no lock. Built: `backend/infrastructure/db/unit_of_work.py`; the existing services still use plain sessions until they are moved onto it (issue 66).

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

> **Decision 2026-10-01 (CONTEXT open question 18, built with revision `0002`):** recreating a table that other tables reference fails on a populated database while foreign key enforcement is on (`DROP TABLE` violates the child rows' foreign keys), so migrations follow SQLite's own procedure. `env.py` turns enforcement off on the migration's private connection *outside* any transaction (the pragma is a no-op inside one), runs each revision, and runs `PRAGMA foreign_key_check` inside that revision's transaction before it commits, so a revision that leaves a dangling reference, or finds the database already inconsistent, is rolled back and refused. SQLite gives Alembic no transactional DDL, so **each revision is its own transaction**: a failing revision leaves the database at the revision before it, and earlier revisions of the same upgrade stay applied. A batch revision passes its table as a frozen definition (`copy_from`), so `upgrade --sql` still prints reviewable SQL without a live database and the revision does not depend on reflection.

> **Decision 2026-10-01 (owner; CONTEXT open question 19, issue 35): a downgrade that could destroy data is refused on a populated library.** Alembic downgrades proceed normally on a library with no user or domain data. On a *populated* library they are refused, before the revision's first statement runs (so the database is left exactly as it was), unless an explicit development-only override is set: `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1`. The override is never enabled by the application, and production recovery never depends on a downgrade: it moves forward with a corrective revision. *Populated* means a table other than the internal ones holds a row; the internal tables are the migration stamp, `app_state`, the three settings singletons, the runtime and model catalog (components, versions, exports, installations, variants and their space mappings, calibration profiles, packages) and `representation_spaces`, because a freshly initialised library has rows there; an `artifacts` row is internal only if a catalog row (a model export, an installed model export, a package installation) references it and no source or observation does, because installed models keep their bytes as artifacts and nothing stops a shared artifact. `ann_key_sequences` is deliberately data: it is the never-reused allocator of index keys. An offline run (`--sql`) only prints a script and is let through. That list is the agent's reading of the owner's "user/domain data, not merely a row of internal metadata" (revisit it if a catalog row should count as data); a table not on it counts as data. Every revision's `downgrade()` starts with `require_destructive_downgrade_allowed(op.get_bind())`, and a test fails the build for a revision that does not.

## 28. Startup recovery and reconciliation

Startup ordering is DB/migrations, storage initialization, recovery, index validation/rebuild scheduling, runtime catalog/installation validation, ML supervisor, scheduler, then readiness. Recovery is idempotent and records only durable repairs; it must be safe to repeat after another crash.

> **Decision 2026-10-01 (owner; open question 26): recovery is idempotent.** Each repair is a guarded transition out of a named state (`UPDATE ... WHERE state = X`, or a delete of a named owned file), so once a repair has been made a repeat finds nothing more to do: after one completed run, a second run reports no repair and leaves the database and files unchanged, and a crash between any two steps followed by a rerun reaches the same end state as an uninterrupted run. The one deliberate exception is a condition that keeps failing for an external reason (a locked file, an index operation that keeps failing): startup retries it once per start, bounded (`FAILED` index operations get one fresh set of attempts), and reports it as *unresolved*, not as a repair; such a run is not claimed to be a no-op. Tests inject a stop after each step and rerun (PER-06, PER-07).

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
| `Job` or `ProcessingRun` in `PAUSING` | becomes `PAUSED`: the worker that was pausing it is gone and nothing runs; a job's lease is cleared and its running segment closes `INTERRUPTED`; resuming creates a new segment |
| `Job` or `ProcessingRun` in `CANCELLING` | becomes `CANCELLED`: cancelling was the user's intent; a job gets `ended_at` and no lease; the run's pending output stays private and is never activated; its temp workspace becomes removable |
| `Representation` in `ERASING` | ensure its `REMOVE` operation exists (queue it if missing); when that is `APPLIED` and the old generations are retired, finish erasure (`ERASED`); never reactivate |

Recovery never turns a pending run's partial outputs into active library memory merely to make the UI look complete. It never assumes an ML worker response survived a crash. Readiness is capability-based: unavailable ML or rebuilding ANN can produce `DEGRADED` while SQLite/library browsing remains available.

> **Decision 2026-10-02 (owner-approved, issue 71; Architecture 12.2): the "interrupted runtime installation" row is settled from the files.** This is machine-store recovery, distinct from library recovery, although the same startup function runs both. **Built:** `RuntimePackageStore.recover()` (`backend/app/runtime/package_store.py`), run by `recover_on_startup`. Startup runs `RuntimePackageStore.recover()`: a staging directory that is complete (its marker matches its manifest) is published (replacing an incomplete published directory of that key), every other staging directory is removed, a published directory that is not complete is reported, and a repeat finds nothing to do. The rule "verify bytes/hash then finalize, remove partial bytes, or mark failed" is therefore met by the file protocol; the catalog rows (`runtime_package_installations`) are written when installed packages are registered, a later step. A crashed install leaves nothing "marked failed", because nothing depends on the crash having been recorded.

> **Decision 2026-10-01 (owner; open question 26):** the `PAUSING` and `CANCELLING` rows above are decided as written. A `RUNNING` job is still marked `INTERRUPTED` and never requeued (no spec defines when a requeue is safe). `FINALIZING` runs and pending output without a final checkpoint stay as the table says and are implemented with the M3 run lifecycle; interrupted runtime installations are built (the note above).

> **Decision 2026-10-01 (owner; CONTEXT open questions 17 and 23): the library root, and the library lock.** The desktop shell owns library selection and keeps the selected absolute library root in application-level settings *outside* the library. The backend receives exactly one resolved root at startup (an explicit value, else the development and test override `FACEIDENTIFY_LIBRARY_ROOT`, else the persisted setting the shell passes in; with none, the library has not been chosen yet, and nothing falls back to a default location), and it never changes during the process: every database, artifact, index, runtime, quarantine and lock path derives from it. A root must be absolute and usable (an existing directory, or a new one inside an existing folder). Alembic derives the database path from the same root (`<root>/database/library.db`; the bare `FACEIDENTIFY_DATABASE_PATH` is deprecated). Right after the root is resolved and minimally validated, and **before migrations, recovery, workers or any other mutation**, the backend takes an exclusive operating-system lock on `<root>/database/.lock` for the whole life of the process (`msvcrt.locking` on Windows, `flock` elsewhere): if another live process holds it, startup for that library fails and never falls back to another library; an orderly shutdown releases it, and a crash or kill frees it because the operating system does. Changing library means restarting the backend lifecycle. Built: `backend/infrastructure/storage/library_root.py`, `library_lock.py`, `backend/alembic/env.py`; wiring them into the startup order is the lifecycle (issue 33). The lock protects against a second backend, not against other programs editing the files, and a network share that does not honour byte-range locks gives no protection.

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

> **Decision 2026-10-02 (owner; CONTEXT open question 31):** a new embedding model (different weights, or any other part of the space identity of ML 18.1) is a new space, as above. A new component version whose space-defining identity is identical is not: it shares the existing space (see 6.1).

USearch manifests validate their format, space ID, and generation ID on startup. Any incompatibility rebuilds from canonical SQLite vectors. Model installation bytes may be removed without invalidating historical semantic metadata; exact historical reprocessing is unavailable unless a compatible export is installed. Managed originals are preserved exactly across storage-layout changes; `storage_key`, hashes, durable intent, and StorageManager compatibility support a later background move without an unsafe startup rewrite.

## 30. First vertical-slice persistence subset

The first vertical slice proves: import a managed image, detect multiple faces, persist representations, recognize an existing Identity, create an unknown one or abstain, create Evidence and Occurrences (none for an abstention), accept output atomically, converge USearch, and recover safely from interruption.

```text
Import image -> Artifact + Source
Process command -> immutable Snapshot + ProcessingRun + Job
Claim -> ExecutionSegment -> detection -> PENDING Observations
Embedding -> PENDING Representations -> candidate revalidation
RecognitionAssessment -> IdentityReasoner -> Evidence + PENDING Occurrences (none for an abstention)
FINAL Checkpoint -> acceptance transaction -> IndexOperations
USearch convergence -> completed Job/Run -> UI result
```

`AcceptProcessingRunUseCase` performs the critical transaction: revalidate a finalizable run; transition the run's pending observations, representations, newly-created identities, and occurrences to `ACTIVE`; create `ADD` operations for new ANN-eligible representations; set `Source.current_processing_run_id`; then mark Run and Job `COMPLETED`. Commit before waking the IndexCoordinator. A failed index update leaves valid accepted SQLite memory plus a retry/rebuildable degraded index; it does not retroactively fail the run.

For an image, an occurrence has kind `IMAGE`, null frame/time range, one observation membership, and that observation as representative. The important checkpoint is `FINAL`; it proves startup can finish acceptance after a crash without rerunning ML. Run-local candidate memory permits a pending newly-created identity to be recognized again during the same run; rebuild it from pending run representations after recovery.

The initial migration includes: artifacts, sources, configuration snapshots, runs, segments, checkpoints, jobs, runtime catalog tables, representation spaces/calibration mappings, observations, representations, ann-key sequences, identities/lineage, people/associations, occurrences/membership, evidence/link/candidate tables, index operations, and the three settings singleton tables. The slice implements only `IMAGE`, managed import, detector/embedder metadata, one preferred evaluated RepresentationSpace and calibration profile, and `ADD`/`REMOVE` index coordination.

Do not include movie/tracking/camera processing, live recognition, Person UI, merge/split/forget UI, recycle/permanent-delete UI, reprocessing UI, training, feedback learning, multiple active spaces, face-query search, FTS5, runtime installation UI, GPU benchmarking UI, storage migration, or concurrent heavy pipelines. The schema leaves room for them; the vertical slice must not build them early.

The acceptance checks for this milestone are: deleting an index and restarting rebuilds from SQLite vectors; a crash after a final checkpoint completes acceptance without duplicate memory; a crash after artifact reservation leaves no falsely available source; a lost scheduler wake is found from queued work; and an ANN failure leaves the accepted source/identity/representation visible while reporting degraded recognition capability.
