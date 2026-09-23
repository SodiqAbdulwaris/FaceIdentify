# ERD --- Local Visual Identity & Face-Memory System

**Status:** Canonical architecture reference\
**Schema stage:** Final consolidated model after eight locked design
clusters\
**Purpose:** Handoff reference for implementation in Codex/Claude
without requiring them to infer relationship semantics from diagrams
alone.

------------------------------------------------------------------------

## 1. Scope and Architectural Rules

This system is a **local-only visual identity and face-memory
application**. It detects faces in images, videos/movies, and camera
streams; tracks visible subjects; remembers unknown identities; later
associates names with those identities; supports cross-media
recognition; retains source-aware encounter history; and exposes a
universal search layer.

The schema deliberately separates:

-   **Source history** --- what was observed, where, and when.
-   **Identity memory** --- what persistent visual identity an
    observation is believed to represent.
-   **Machine outputs** --- representations and recognition results
    produced by versioned components.
-   **Derived recognition memory** --- optimized recognition artifacts
    rebuilt from authoritative evidence.
-   **Search state** --- retrieval, ranking, aggregation, and result
    presentation.
-   **Operational state** --- jobs, tasks, work units, attempts, and
    recovery.
-   **Destructive state** --- recycle, permanent deletion, forgetting,
    backup, and anti-resurrection records.

Core global invariants:

1.  `Person != Identity`.
2.  `Observation` never owns an `identity_id`.
3.  Recognition output is not current identity truth.
4.  Machine association is not automatically trusted recognition
    evidence.
5.  Identity evidence must always be traceable to real source-grounded
    observations.
6.  Qdrant/vector indexes are derived and disposable.
7.  Query-time face inputs are not silently ingested as Sources.
8.  Delete Source and Forget Person are different operations.
9.  Recycle and Permanent Delete are different operations.
10. Missing/corrupt files do not imply user deletion.
11. Running processing jobs never silently change model/component
    versions.
12. Current-state tables are authoritative; the system is **not
    event-sourced**.
13. User corrections outrank conflicting automatic inference.
14. False split is safer than false merge.
15. Destructive intent becomes authoritative before asynchronous cleanup
    completes.
16. Restoring an old backup must not resurrect newer deleted/forgotten
    state.

------------------------------------------------------------------------

## 2. Domain Classification

  -----------------------------------------------------------------------
  Domain                  Responsibility          Classification
  ----------------------- ----------------------- -----------------------
  Source & History        What was observed,      Authoritative
                          where and when          

  Identity & Memory       Persistent identity     Authoritative
                          belief and evidence     

  Artifacts &             Managed files and       Mixed
  Representations         machine-readable        
                          representations         

  Processing & Jobs       Scheduling, execution,  Operational
                          checkpointing, recovery 

  Models & Versioning     Versioned components,   Authoritative
                          training, evaluation,   provenance
                          activation              

  Feedback & Events       Corrections,            Authoritative
                          operations, semantic    provenance
                          history                 

  Search & Indexing       Retrieval, ranking,     Primarily
                          presentation,           derived/query-state
                          aggregation             

  Deletion & Recovery     Destructive intent,     Authoritative
                          backups,                
                          anti-resurrection       
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 3. Master System ERD

``` mermaid
erDiagram
    SOURCE ||--o{ ENCOUNTER : contains
    ENCOUNTER ||--o{ APPEARANCE : contains
    APPEARANCE ||--o{ TRACK : contains
    TRACK ||--o{ OBSERVATION : contains

    PERSON o|--o{ IDENTITY : names
    OBSERVATION ||--o{ IDENTITY_ASSOCIATION : has
    IDENTITY ||--o{ IDENTITY_ASSOCIATION : receives
    IDENTITY_ASSOCIATION ||--o{ IDENTITY_EVIDENCE : justifies
    IDENTITY ||--o{ IDENTITY_EVIDENCE : supported_by
    OBSERVATION ||--o{ IDENTITY_EVIDENCE : grounds

    OBSERVATION ||--o{ REPRESENTATION : represented_by
    OBSERVATION ||--o{ RECOGNITION_RESULT : evaluated_by
    RECOGNITION_RESULT ||--o{ RECOGNITION_HYPOTHESIS : proposes
    IDENTITY ||--o{ RECOGNITION_HYPOTHESIS : candidate

    IDENTITY ||--o{ RECOGNITION_ARTIFACT : derives
    RECOGNITION_ARTIFACT ||--o{ RECOGNITION_ARTIFACT_EVIDENCE : uses
    IDENTITY_EVIDENCE ||--o{ RECOGNITION_ARTIFACT_EVIDENCE : contributes

    SOURCE ||--o{ SOURCE_ARTIFACT : owns
    OBSERVATION ||--o{ OBSERVATION_ARTIFACT : owns
    ARTIFACT ||--o{ SOURCE_ARTIFACT : referenced
    ARTIFACT ||--o{ OBSERVATION_ARTIFACT : referenced

    PROCESSING_JOB ||--|| PROCESSING_MANIFEST : freezes
    PROCESSING_MANIFEST ||--o{ MANIFEST_COMPONENT : includes
    COMPONENT_VERSION ||--o{ MANIFEST_COMPONENT : selected
    PROCESSING_JOB ||--o{ TASK : contains
    TASK ||--o{ WORK_UNIT : contains
    WORK_UNIT ||--o{ WORK_UNIT_ATTEMPT : attempts

    COMPONENT ||--o{ COMPONENT_VERSION : versions
    COMPONENT ||--o{ COMPONENT_ACTIVATION : activates
    COMPONENT_VERSION ||--o{ COMPONENT_ACTIVATION : selected
    DATASET_SNAPSHOT ||--o{ DATASET_ITEM : contains
    TRAINING_RUN ||--o{ TRAINING_RUN_OUTPUT : produces
    COMPONENT_VERSION ||--o{ TRAINING_RUN_OUTPUT : candidate
    EVALUATION_SUITE ||--o{ EVALUATION_RUN : defines
    COMPONENT_VERSION ||--o{ EVALUATION_RUN : evaluated
    EVALUATION_RUN ||--o{ EVALUATION_METRIC : reports
    VERSION_DECISION ||--o{ VERSION_DECISION_EVALUATION : supported_by
    EVALUATION_RUN ||--o{ VERSION_DECISION_EVALUATION : evidence

    FEEDBACK_EVENT o|--o{ IDENTITY_OPERATION : motivates
    IDENTITY_OPERATION ||--o{ IDENTITY_OPERATION_PARTICIPANT : affects
    IDENTITY_OPERATION o|--o{ DOMAIN_EVENT : records

    SEARCH_QUERY ||--o{ QUERY_INPUT : contains
    SEARCH_QUERY ||--o{ SEARCH_EXECUTION : executes
    SEARCH_EXECUTION ||--|| SEARCH_PLAN : plans
    SEARCH_PLAN ||--o{ SEARCH_PLAN_STEP : contains
    SEARCH_EXECUTION ||--o{ SEARCH_CANDIDATE : retrieves
    SEARCH_CANDIDATE ||--o| RANKING_DECISION : ranked
    RANKING_DECISION ||--o| SEARCH_RESULT_PRESENTATION : shown

    SEARCH_INDEX ||--o{ SEARCH_INDEX_VERSION : versions
    SEARCH_INDEX ||--o{ SEARCH_INDEX_ACTIVATION : activates
    SEARCH_INDEX_VERSION ||--o{ SEARCH_INDEX_ACTIVATION : selected
    SEARCH_INDEX_VERSION ||--o{ REPRESENTATION_INDEX_ENTRY : indexes
    REPRESENTATION ||--o{ REPRESENTATION_INDEX_ENTRY : projected

    DELETION_OPERATION ||--o{ DELETION_OPERATION_ITEM : cleans
    DELETION_OPERATION ||--o{ DELETION_LEDGER : commits
    BACKUP_RECORD }o--|| ARTIFACT : stored_as
    BACKUP_RECORD o|--o{ RECOVERY_OPERATION : restored_by
```

The master diagram intentionally omits many secondary FKs to stay
readable. The domain diagrams and relationship reference below are
authoritative for detailed semantics.

------------------------------------------------------------------------

# 4. Domain 1 --- Source & History

## 4.1 ERD

``` mermaid
erDiagram
    SOURCE ||--o| IMAGE_SOURCE_METADATA : subtype
    SOURCE ||--o| VIDEO_SOURCE_METADATA : subtype
    SOURCE ||--o| CAMERA_SOURCE_METADATA : subtype

    SOURCE ||--o{ ENCOUNTER : contains
    ENCOUNTER ||--o{ APPEARANCE : contains
    APPEARANCE ||--o{ TRACK : contains
    TRACK ||--o{ OBSERVATION : contains

    TRACK ||--o{ TRACK_DERIVATION : parent
    TRACK ||--o{ TRACK_DERIVATION : derived
```

## 4.2 Tables

### `source` --- **Authoritative**

-   `id` PK
-   `source_type` NOT NULL
-   `display_name` NOT NULL
-   `lifecycle_state` NOT NULL
-   `processing_state` NOT NULL
-   `integrity_state` NOT NULL
-   `created_at`
-   `updated_at`
-   recommended concurrency/version field where needed

Three state axes are independent. A Source can, for example, be ACTIVE +
PROCESSED + MISSING.

### `image_source_metadata`

One-to-zero-or-one extension of Source for image-specific metadata.

### `video_source_metadata`

One-to-zero-or-one extension for video/movie metadata.

### `camera_source_metadata`

One-to-zero-or-one extension for camera configuration/source metadata.

### `encounter` --- **Authoritative**

-   `id` PK
-   `source_id` FK NOT NULL
-   `encounter_type` NOT NULL
-   `started_at`, `ended_at` nullable
-   `start_frame`, `end_frame` nullable
-   timestamps

Encounter is **source/event-centric**, never person-centric.

### `appearance` --- **Authoritative**

-   `id` PK
-   `encounter_id` FK NOT NULL
-   temporal/frame boundaries nullable
-   timestamps

Represents one meaningful visible subject presence within an Encounter.

### `track` --- **Authoritative**

-   `id` PK
-   `appearance_id` FK NOT NULL
-   `source_id` FK NOT NULL --- controlled denormalization
-   `track_confidence` nullable
-   `lifecycle_state` NOT NULL
-   temporal/frame boundaries nullable
-   timestamps

Invariant:

`track.source_id = track.appearance.encounter.source_id`

### `track_derivation` --- **Authoritative provenance**

-   `id` PK
-   `parent_track_id` FK NOT NULL
-   `derived_track_id` FK NOT NULL
-   `derivation_type` NOT NULL
-   `identity_operation_id` nullable
-   `reason` nullable
-   `created_at`

Constraints: - parent != derived - same Source - no cycles - original
may become SUPERSEDED - no cross-source derivation

### `observation` --- **Authoritative**

-   `id` PK
-   `track_id` FK NOT NULL
-   `source_id` FK NOT NULL --- controlled denormalization
-   `timestamp` nullable
-   `frame_number` nullable
-   `bbox_x`, `bbox_y`, `bbox_width`, `bbox_height` NOT NULL
-   `detection_confidence` nullable
-   `detector_component_version_id` FK
-   `produced_by_work_unit_id` FK nullable
-   `created_at`

Invariant:

`observation.source_id = observation.track.source_id = hierarchical Source`

**There is no `observation.identity_id`.**

## 4.3 Ownership

Authorized permanent Source deletion owns:

`Source -> Encounter -> Appearance -> Track -> Observation`

This hierarchy may use ownership-cascade semantics. Cross-domain
identity cleanup is application-controlled and must not blindly cascade
to Person/Identity.

------------------------------------------------------------------------

# 5. Domain 2 --- Identity, Memory & Recognition

## 5.1 ERD

``` mermaid
erDiagram
    PERSON ||--o{ PERSON_ALIAS : has
    PERSON o|--o{ IDENTITY : groups

    OBSERVATION ||--o{ RECOGNITION_RESULT : evaluated
    RECOGNITION_RESULT ||--o{ RECOGNITION_HYPOTHESIS : ranks
    IDENTITY ||--o{ RECOGNITION_HYPOTHESIS : candidate

    OBSERVATION ||--o{ IDENTITY_ASSOCIATION : associated
    IDENTITY ||--o{ IDENTITY_ASSOCIATION : target

    IDENTITY_ASSOCIATION ||--o{ IDENTITY_EVIDENCE : justifies
    OBSERVATION ||--o{ IDENTITY_EVIDENCE : grounds
    IDENTITY ||--o{ IDENTITY_EVIDENCE : supports

    IDENTITY ||--o{ RECOGNITION_ARTIFACT : derives
    RECOGNITION_ARTIFACT ||--o{ RECOGNITION_ARTIFACT_EVIDENCE : uses
    IDENTITY_EVIDENCE ||--o{ RECOGNITION_ARTIFACT_EVIDENCE : contributes

    OBSERVATION ||--o{ OBSERVATION_IDENTITY_CONSTRAINT : constrained
    IDENTITY ||--o{ OBSERVATION_IDENTITY_CONSTRAINT : excluded

    IDENTITY ||--o{ IDENTITY_PAIR_CONSTRAINT : side_a
    IDENTITY ||--o{ IDENTITY_PAIR_CONSTRAINT : side_b
```

## 5.2 `person` --- **Authoritative semantic identity**

-   `id` PK
-   `display_name` NOT NULL for normal named Person
-   `state` NOT NULL
-   `canonical_person_id` self-FK nullable
-   `forget_state` NOT NULL
-   timestamps
-   `row_version`

A Person can exist with zero visual Identities as an unsupported
semantic shell.

Canonical merge rules: - superseded Persons point directly to final
canonical Person - canonical chain must be acyclic/flattened - active
Identities cannot remain attached to superseded Persons

### `person_alias`

-   `id` PK
-   `person_id` FK
-   `alias`
-   `alias_normalized`
-   `created_at`
-   unique `(person_id, alias_normalized)`

## 5.3 `identity` --- **Authoritative visual identity**

-   `id` PK
-   `person_id` FK nullable
-   `generated_label` globally unique/stable
-   `memory_maturity`
-   `human_validation`
-   `identity_health`
-   `recognition_eligible`
-   timestamps
-   `row_version`

State dimensions:

**Memory maturity:** EPHEMERAL / CANDIDATE / ESTABLISHED\
**Human validation:** UNREVIEWED / CONFIRMED\
**Identity health:** STABLE / UNCERTAIN / CONFLICTED / UNDER_REVIEW

Do not collapse these into one status.

## 5.4 Recognition output

### `recognition_result` --- **Historical machine output**

-   `id` PK
-   `observation_id` FK NOT NULL
-   `result_type`: MATCH / UNKNOWN / TENTATIVE
-   recommended/selected `identity_id` nullable
-   recognizer component version FK
-   reasoner/version provenance where applicable
-   `representation_id` nullable
-   `representation_space_id` nullable
-   `produced_by_work_unit_id` nullable
-   `created_at`

Immutable after production/correction.

### `recognition_hypothesis`

-   `id` PK
-   `recognition_result_id` FK
-   `identity_id` FK
-   `rank`
-   `similarity_score` nullable
-   `calibrated_score` nullable
-   `created_at`

UNKNOWN is meaningful and may produce no association.

## 5.5 Association

### `identity_association` --- **Authoritative current/history relationship**

-   `id` PK
-   `observation_id` FK
-   `identity_id` FK
-   `association_status`: TENTATIVE / INFERRED / CONFIRMED / REJECTED
-   `origin`: SYSTEM / USER / DERIVED_FROM_CONFIRMED_CONTEXT
-   `association_certainty` nullable
-   `recognition_result_id` nullable
-   `supersedes_association_id` nullable self-FK
-   `is_current`
-   timestamps

Constraints: - `supersedes_association_id` must concern same
Observation - at most one operative current positive association per
Observation - corrections append/supersede; do not rewrite history

## 5.6 Evidence

### `identity_evidence` --- **Authoritative recognition-memory evidence**

-   `id` PK
-   `identity_id` FK
-   `observation_id` FK
-   `association_id` FK
-   `evidence_level`: TENTATIVE / SUPPORTING / CORE
-   `recognition_utility`
-   `active_for_recognition`
-   `selection_reason` nullable
-   timestamps

Rules: - association/identity/observation must match - one current
evidence row per `(identity_id, observation_id)` - rejected/invalid
backing association immediately makes evidence unusable - user-confirmed
association does not imply high recognition utility - evidence is always
source-grounded

## 5.7 Constraints

### `observation_identity_constraint`

Represents `Observation != Identity`. - unique current pair - origin -
HARD/SOFT mode - active - feedback/event provenance - revoke rather than
erase

### `identity_pair_constraint`

Represents `Identity A != Identity B`. - canonical unordered pair - no
self-pair - unique current pair - HARD/SOFT - active - provenance

## 5.8 Recognition artifacts

### `recognition_artifact` --- **Derived**

-   `id` PK
-   `identity_id` FK
-   `artifact_kind`
-   `component_version_id`
-   `representation_space_id` nullable
-   `state`
-   `produced_by_work_unit_id` nullable
-   timestamps
-   payload uses the same inline-or-Artifact-backed principle as
    Representation

### `recognition_artifact_evidence`

Many-to-many: - `recognition_artifact_id` - `identity_evidence_id` -
composite PK

RecognitionArtifact is optimized machine memory, not authoritative
evidence.

------------------------------------------------------------------------

# 6. Domain 3 --- Artifacts, Representations & Storage

## 6.1 ERD

``` mermaid
erDiagram
    SOURCE ||--o{ SOURCE_ARTIFACT : owns
    OBSERVATION ||--o{ OBSERVATION_ARTIFACT : owns
    ARTIFACT ||--o{ SOURCE_ARTIFACT : referenced
    ARTIFACT ||--o{ OBSERVATION_ARTIFACT : referenced

    ARTIFACT ||--o{ ARTIFACT_DEPENDENCY : source
    ARTIFACT ||--o{ ARTIFACT_DEPENDENCY : derived

    OBSERVATION ||--o{ REPRESENTATION : has
    COMPONENT_VERSION ||--o{ REPRESENTATION : produces
    REPRESENTATION_SPACE ||--o{ REPRESENTATION : belongs

    QUERY_INPUT ||--o{ QUERY_REPRESENTATION : represented
    COMPONENT_VERSION ||--o{ QUERY_REPRESENTATION : produces
    REPRESENTATION_SPACE ||--o{ QUERY_REPRESENTATION : belongs
```

## 6.2 `artifact` --- **Authoritative storage metadata**

-   `id` PK
-   `artifact_type`
-   `recoverability_class`
-   `lifecycle_state`
-   `integrity_state`
-   `storage_key`
-   `size_bytes` nullable
-   `checksum` nullable
-   `checksum_algorithm` nullable
-   timestamps

Lifecycle: STAGING / AVAILABLE / RECYCLED / DELETED\
Integrity: UNKNOWN / VALID / MISSING / CORRUPT

Recoverability examples: - AUTHORITATIVE_NONREGENERABLE -
REGENERABLE_FROM_SOURCE - DERIVED_CACHE - TEMPORARY

`storage_key` is Storage-Manager-controlled. Domain tables do not store
arbitrary absolute paths.

## 6.3 Ownership relations

### `source_artifact`

Composite relationship `(source_id, artifact_id, role)`.

Typical roles: - ORIGINAL_MEDIA - THUMBNAIL - PREVIEW - DERIVED_MEDIA

Stored image/video/movie Sources normally have exactly one current
ORIGINAL_MEDIA Artifact. Camera Sources are exempt.

### `observation_artifact`

Composite relation `(observation_id, artifact_id, role)`.

Typical roles: - FACE_CROP - THUMBNAIL

Face crops are regenerable by default where original source media
survives.

### `artifact_dependency`

-   source Artifact FK
-   derived Artifact FK
-   dependency type
-   created_at
-   no self-dependency
-   cycles generally invalid

This is physical derivation dependency, not semantic identity
provenance.

## 6.4 Representation

### `representation_space`

-   `id` PK
-   `space_key`
-   `version_label`
-   `description` nullable
-   compatibility metadata nullable
-   created_at
-   conceptual uniqueness `(space_key, version_label)`

### `representation` --- **Historical machine output / derived payload**

-   `id` PK
-   `observation_id` FK
-   `representation_type`
-   `component_version_id` FK
-   `representation_space_id` FK
-   `state`
-   `produced_by_work_unit_id` nullable
-   `payload_storage_type`
-   `payload_inline` nullable
-   `payload_artifact_id` nullable
-   `created_at`

Ordinary durable uniqueness:

`(observation_id, representation_type, component_version_id, representation_space_id)`

Exactly one usable payload route when materialized.

Qdrant must not be the only durable copy if cheap rebuild without
recomputation is expected.

## 6.5 Query representation

### `query_representation`

Separate from Observation Representation. - `id` - `query_input_id` -
`component_version_id` - `representation_space_id` - temporary payload -
`created_at` - `expires_at` nullable

A query representation does not create
Source/Observation/Identity/Evidence.

## 6.6 Index-entry relations

### `representation_index_entry`

-   `search_index_version_id`
-   `representation_id`
-   `external_key`
-   `index_state`
-   `indexed_at`

### `recognition_artifact_index_entry`

-   `search_index_version_id`
-   `recognition_artifact_id`
-   `external_key`
-   `index_state`
-   `indexed_at`

Both are derived and disposable.

------------------------------------------------------------------------

# 7. Domain 4 --- Processing, Jobs & Manifests

## 7.1 ERD

``` mermaid
erDiagram
    PROCESSING_JOB ||--|| PROCESSING_MANIFEST : freezes
    PROCESSING_MANIFEST ||--o{ MANIFEST_COMPONENT : includes
    COMPONENT_VERSION ||--o{ MANIFEST_COMPONENT : selected

    PROCESSING_JOB ||--o{ TASK : contains
    TASK ||--o{ TASK_DEPENDENCY : depends
    TASK ||--o{ WORK_UNIT : contains
    WORK_UNIT ||--o{ WORK_UNIT_ATTEMPT : attempts

    PROCESSING_JOB ||--o{ CHECKPOINT : checkpoints
    TASK o|--o{ CHECKPOINT : checkpoints
    WORK_UNIT o|--o{ CHECKPOINT : checkpoints
```

## 7.2 `processing_job` --- **Operational**

Fields: - `id` - `job_type` - `source_id` nullable - `state` -
`service_class` - `priority` - `processing_manifest_id` NOT NULL -
progress/detail - lifecycle timestamps - failure class/summary -
`pause_requested_at` nullable - `cancel_requested_at` nullable -
`row_version`

Types include: - PROCESS_IMAGE - PROCESS_VIDEO -
PROCESS_CAMERA_SESSION - REPROCESS_SOURCE - REBUILD_IDENTITY_MEMORY -
REBUILD_SEARCH_INDEX - TRAIN_COMPONENT

States: QUEUED / RUNNING / PAUSED / COMPLETED / FAILED / CANCELLED\
RECOVERING may exist internally.

Source processing state is separate from Job state.

## 7.3 `processing_manifest` --- **Authoritative provenance**

-   `id`
-   `manifest_version`
-   processing configuration reference/snapshot
-   source version/integrity context nullable
-   `created_at`
-   `frozen_at`

Immutable once execution starts.

### `manifest_component`

Links frozen Manifest to ComponentVersions by role.

Examples: - detector - tracker - representation - recognizer -
reasoner - scene analyzer - ranker

## 7.4 `task`

-   `id`
-   `processing_job_id`
-   `task_type`
-   state
-   sequence hint nullable
-   progress/detail
-   timestamps
-   failure class/summary

### `task_dependency`

Intra-job DAG. - same Job - no self - no cycles

## 7.5 `work_unit`

-   `id`
-   `task_id`
-   `unit_key`
-   state
-   structured `input_boundary`
-   progress weight nullable
-   attempt count
-   created/started/computed/committed/updated timestamps
-   unique `(task_id, unit_key)`

Logical lifecycle:

PENDING -\> RUNNING -\> COMPUTED -\> COMMITTED

Only COMMITTED counts as durable completed work.

## 7.6 `work_unit_attempt`

-   `id`
-   `work_unit_id`
-   `attempt_number`
-   state
-   start/end
-   device type/identifier nullable
-   failure class/code/summary
-   retry reason
-   runtime metrics
-   lease owner
-   lease expiry
-   heartbeat
-   unique `(work_unit_id, attempt_number)`

Expired RUNNING attempt becomes ABANDONED and WorkUnit may retry.

## 7.7 `checkpoint`

-   `id`
-   `processing_job_id`
-   `task_id` nullable
-   `work_unit_id` nullable
-   checkpoint type
-   position data
-   state data nullable
-   created_at

A checkpoint does not make uncommitted outputs authoritative.

## 7.8 Important rules

-   important outputs reference `produced_by_work_unit_id`, not normally
    Attempt
-   one offline movie/video job active in V1 is scheduler policy, not DB
    constraint
-   movie work-unit ranges may overlap
-   pause/cancel request is distinct from achieved PAUSED/CANCELLED
    state
-   cancellation may leave committed partial work and Source
    PARTIALLY_PROCESSED
-   reprocessing creates a new Job/Manifest/provenance chain

------------------------------------------------------------------------

# 8. Domain 5 --- Models, Versioning, Training & Evaluation

## 8.1 ERD

``` mermaid
erDiagram
    COMPONENT ||--o{ COMPONENT_VERSION : versions
    COMPONENT_VERSION ||--o{ COMPONENT_VERSION_ARTIFACT : owns
    ARTIFACT ||--o{ COMPONENT_VERSION_ARTIFACT : stores

    COMPONENT_VERSION ||--o{ COMPONENT_VERSION_DEPENDENCY : depends
    COMPONENT_VERSION ||--o{ COMPONENT_VERSION_REPRESENTATION_SPACE : compatible
    REPRESENTATION_SPACE ||--o{ COMPONENT_VERSION_REPRESENTATION_SPACE : defines

    COMPONENT ||--o{ COMPONENT_ACTIVATION : activates
    COMPONENT_VERSION ||--o{ COMPONENT_ACTIVATION : selected

    DATASET_SNAPSHOT ||--o{ DATASET_ITEM : contains

    TRAINING_RUN ||--o{ TRAINING_RUN_OUTPUT : produces
    COMPONENT_VERSION ||--o{ TRAINING_RUN_OUTPUT : candidate
    DATASET_SNAPSHOT ||--o{ TRAINING_RUN : trains

    EVALUATION_SUITE ||--o{ EVALUATION_RUN : defines
    COMPONENT_VERSION ||--o{ EVALUATION_RUN : evaluates
    DATASET_SNAPSHOT o|--o{ EVALUATION_RUN : dataset
    EVALUATION_RUN ||--o{ EVALUATION_METRIC : reports

    VERSION_DECISION ||--o{ VERSION_DECISION_EVALUATION : supported
    EVALUATION_RUN ||--o{ VERSION_DECISION_EVALUATION : evidence
```

## 8.2 `component`

Stable capability: - `id` - `component_key` unique - `component_type` -
`display_name` - description - created_at

Examples: detector, tracker, representation generator, recognizer,
identity reasoner, search ranker.

## 8.3 `component_version`

Immutable implementation version: - `id` - `component_id` -
`version_label` - `implementation_type`: MODEL / ALGORITHM / RULE_BASED
/ HYBRID - `lifecycle_state` - `origin` - immutable behavior-defining
configuration - timestamps - unique `(component_id, version_label)`

Normal terminal lifecycle is RETIRED, not hard deletion.

## 8.4 `component_version_artifact`

Role-based files: - WEIGHTS - CONFIG - VOCABULARY - RUNTIME_ASSET -
CALIBRATION

Rule-based components may have no weight file.

## 8.5 Dependencies and representation compatibility

### `component_version_dependency`

May require: - a concrete ComponentVersion, or - a RepresentationSpace

Prefer compatible space dependency over unnecessarily exact
producer-version dependency.

### `component_version_representation_space`

Explicit PRODUCES / CONSUMES compatibility.

## 8.6 `component_activation`

Historical activation: - component - component version - scope -
activated_at - superseded_at - reason - version decision reference

Rollback creates another activation; it does not rewrite history.

## 8.7 Dataset provenance

### `dataset_snapshot`

Final canonical name; do not use `TrainingDatasetSnapshot`. - `id` -
`purpose`: TRAINING / EVALUATION / CALIBRATION - snapshot type - schema
version - item count - created_at - created-by Job nullable

### `dataset_item`

Bounded typed nullable FKs, such as: - observation - identity evidence -
track - appearance - source

`item_kind` defines valid target combination. Avoid unconstrained
`type + id`.

Deleted/forgotten biometric payload cannot survive here as a loophole.

## 8.8 Training

### `training_run`

Semantic ML lifecycle record: - processing job FK - target component -
optional base ComponentVersion - DatasetSnapshot - training config -
state - timestamps

### `training_run_output`

TrainingRun may produce 0..N candidate ComponentVersions.

Training success does not activate a version.

## 8.9 Evaluation

### `evaluation_suite`

Versioned evaluation methodology.

### `evaluation_run`

Evaluates one immutable ComponentVersion under a known suite and
optional DatasetSnapshot.

### `evaluation_metric`

Extensible metric rows with context. Do not hardcode only
face-recognition metrics.

## 8.10 `version_decision`

Final canonical name; do not use `PromotionDecision`.

Decisions: - PROMOTE - REJECT - ROLLBACK

Links candidate/target version, previous active version where relevant,
actor/reason, and evaluation evidence.

### `version_decision_evaluation`

Many-to-many supporting EvaluationRuns.

Component activation and SearchIndex activation/readiness remain
independent.

------------------------------------------------------------------------

# 9. Domain 6 --- Feedback, Events & Identity Operations

## 9.1 ERD

``` mermaid
erDiagram
    FEEDBACK_EVENT o|--o{ IDENTITY_OPERATION : motivates
    IDENTITY_OPERATION ||--o{ IDENTITY_OPERATION_PARTICIPANT : affects
    IDENTITY_OPERATION o|--o{ DOMAIN_EVENT : records

    RECOGNITION_RESULT o|--o{ FEEDBACK_EVENT : corrected
    SEARCH_EXECUTION o|--o{ FEEDBACK_EVENT : context
    SEARCH_RESULT_PRESENTATION o|--o{ FEEDBACK_EVENT : context

    IDENTITY_OPERATION o|--o{ IDENTITY_OPERATION : reverses
```

## 9.2 `feedback_event` --- **Append-oriented authoritative provenance**

Fields may include: - `id` - feedback domain/type - actor type -
feedback source: EXPLICIT / IMPLICIT / SYSTEM_DERIVED - optional search
execution/result-presentation context - optional
observation/identity/person/association/recognition-result typed FKs -
semantic value - comment - created_at

Rules: - feedback is historical, not current truth - corrections create
new feedback - clicks/search interactions never silently become
biometric confirmation - no universal feedback-strength score - explicit
identity correction can create authoritative constraints/associations

## 9.3 `identity_operation`

Complex identity-memory transformations: - `id` - operation type -
state: PENDING / COMMITTED / FAILED - actor - optional FeedbackEvent -
`reverses_operation_id` nullable - correlation ID - timestamps - reason

Types include: - MERGE_PERSON - SPLIT_PERSON - MERGE_IDENTITY -
SPLIT_IDENTITY - ATTACH_IDENTITY - DETACH_IDENTITY - RENAME_PERSON -
FORGET_PERSON

Undo uses a compensating operation. Generic undo of an undo is not
supported; subsequent semantic changes use explicit operations.

## 9.4 `identity_operation_participant`

Typed participants: - person - identity - observation - identity
association - identity evidence

Exactly one principal participant target per row.

Roles may include: SOURCE / TARGET / CANONICAL / MOVED / DETACHED /
CREATED / INVALIDATED.

Do not store giant participant arrays in JSON.

## 9.5 `domain_event`

Append-oriented meaningful transition history: - `id` - event type -
`aggregate_type` - `aggregate_id` - actor - correlation ID - causation
event nullable - identity operation nullable - feedback event nullable -
processing job nullable - small structured event data - optional
sequence number within correlation - created_at

**Intentional exception:** `aggregate_type + aggregate_id` is generic
because DomainEvent is historical provenance and must survive target
deletion.

Event payload must not contain face crops, vectors, full Person
snapshots, or other content that would defeat deletion/forget semantics.

The system is not event-sourced; replaying DomainEvents is not required
to reconstruct current DB state.

------------------------------------------------------------------------

# 10. Domain 7 --- Universal Search & Indexing

## 10.1 ERD

``` mermaid
erDiagram
    SEARCH_QUERY ||--o{ QUERY_INPUT : contains
    QUERY_INPUT ||--o{ QUERY_REPRESENTATION : represented
    SEARCH_QUERY ||--o| QUERY_INTERPRETATION : interpreted

    SEARCH_QUERY ||--o{ SEARCH_EXECUTION : executes
    SEARCH_EXECUTION ||--|| SEARCH_PLAN : plans
    SEARCH_PLAN ||--o{ SEARCH_PLAN_STEP : contains
    SEARCH_PLAN_STEP ||--o{ SEARCH_PLAN_STEP_DEPENDENCY : depends

    SEARCH_EXECUTION ||--o{ SEARCH_CANDIDATE : retrieves
    SEARCH_CANDIDATE ||--o| RANKING_DECISION : ranked
    RANKING_DECISION ||--o| SEARCH_RESULT_PRESENTATION : shown
    SEARCH_EXECUTION ||--o| SEARCH_IDENTITY_ANSWER : identifies
    SEARCH_EXECUTION ||--o{ AGGREGATION_RESULT : aggregates

    SEARCH_INDEX ||--o{ SEARCH_INDEX_VERSION : versions
    SEARCH_INDEX ||--o{ SEARCH_INDEX_ACTIVATION : activates
    SEARCH_INDEX_VERSION ||--o{ SEARCH_INDEX_ACTIVATION : selected
    SEARCH_INDEX_VERSION ||--o{ INDEX_BACKEND_BINDING : backend
    SEARCH_INDEX ||--o{ INDEX_MUTATION : mutates
```

## 10.2 Search principles

-   Recognition != Search.
-   Query != Ingest.
-   Candidate generation != ranking.
-   Identity certainty != relevance.
-   Raw scores from different retrievers are not directly comparable.
-   Search always resolves indexed candidates against authoritative DB
    state before presentation.
-   Search queries indexes, not raw movies.
-   Partial processing must be represented honestly.

## 10.3 `search_query`

-   `id`
-   query type: TEXT / FACE / MIXED
-   retention class
-   expires_at nullable
-   created_at

### `query_input`

Typed input: - text value or temporary Artifact - sequence number -
input type

Face query imagery is temporary by default and does not become a Source.

### `query_interpretation`

Structured intent: - intent type - hard constraints - soft preferences -
interpreter version - created_at

Natural-language implementation remains open.

### `query_representation`

Defined in the representation domain but belongs to Search lifecycle.
Ephemeral by default.

## 10.4 `search_execution`

One SearchQuery can execute multiple times. - state - search config
version - start/end - completeness state: COMPLETE / PARTIAL /
DEGRADED - failure summary

### `search_plan`

Plan type: - RETRIEVAL - AGGREGATION - HYBRID

### `search_plan_step`

Logical steps such as: - PERSON_RETRIEVAL - VISUAL_RETRIEVAL -
OCCURRENCE_RETRIEVAL - SOURCE_FILTER - COOCCURRENCE_RETRIEVAL -
AUTHORITATIVE_RESOLUTION - RANK - FUSE - DIVERSIFY - AGGREGATE

### `search_plan_step_dependency`

Same-plan DAG; no cycles.

## 10.5 Search indexes

### `search_index`

Stable logical index capability.

Examples: - FACE_OBSERVATIONS - IDENTITY_MEMORY - PEOPLE_TEXT -
SOURCE_TEXT - OCCURRENCES - COOCCURRENCE

### `search_index_version`

-   version
-   state: BUILDING / READY / DIRTY / DEGRADED / FAILED / RETIRED
-   representation space nullable
-   producer component version nullable
-   build job nullable
-   coverage state: COMPLETE / PARTIAL / UNKNOWN
-   ready_at

State and coverage are separate.

### `search_index_activation`

Historical active index version by scope.

### `index_backend_binding`

Backend-specific locator. Qdrant is an initial candidate, not
architectural authority.

## 10.6 `index_mutation`

Durable incremental bridge from authoritative changes to derived
indexes.

Types may include: - UPSERT - REMOVE - INVALIDATE

Uses bounded typed nullable targets such as Person, Identity, Source,
Observation, Representation, RecognitionArtifact.

Large migrations use `REBUILD_SEARCH_INDEX` ProcessingJobs instead of
enormous mutation queues.

## 10.7 Search candidates

### `search_candidate`

-   search execution
-   optional plan step
-   exactly one target FK:
    -   Person
    -   Identity
    -   Source
    -   Appearance
    -   Observation
-   candidate type
-   retriever type
-   raw score nullable
-   retrieval rank nullable
-   resolution state
-   created_at

There is **no `SearchableEntity` table in V1**.

Candidate resolution states may include ELIGIBLE / FILTERED / STALE /
FORGOTTEN / DELETED / INELIGIBLE.

### `ranking_decision`

-   candidate
-   optional ranker ComponentVersion
-   type-specific score
-   fusion score
-   compact feature snapshot
-   decision
-   created_at

Feature snapshot must not duplicate biometric payload.

### `search_result_presentation`

What the user actually saw: - search execution - ranking decision -
position - section - presented_at

Sections may include TOP / PEOPLE / MEDIA / OCCURRENCES /
POSSIBLE_PEOPLE.

## 10.8 Face-query identity answer

### `search_identity_answer`

Exists **only for a sufficiently accepted identity answer**. - search
execution - identity - Person nullable - recognition result - created_at

It is pinned separately from ordinary ranked results.

Uncertain candidates remain normal SearchCandidates, potentially under
POSSIBLE_PEOPLE.

SearchIdentityAnswer never creates persistent memory by itself.

## 10.9 Co-occurrence

### `cooccurrence_index_entry` --- **Derived**

-   SearchIndexVersion
-   canonical identity pair
-   evidence type
-   Encounter nullable
-   Appearance A/B nullable
-   strength nullable
-   created_at

Evidence hierarchy: 1. DIRECT_CO_VISIBILITY 2. SAME_SCENE 3.
SAME_ENCOUNTER 4. TEMPORAL_PROXIMITY

Source/history remains authoritative; this table is acceleration only.

## 10.10 Aggregation

### `aggregation_result`

Separate from normal ranking. - search execution - group type - typed
group target - measure type/value - position nullable -
uncertainty/completeness metadata as needed - created_at

Tentative associations must not silently count the same as
confirmed/strong associations.

------------------------------------------------------------------------

# 11. Domain 8 --- Deletion, Recycle, Forget, Backup & Recovery

## 11.1 ERD

``` mermaid
erDiagram
    IDENTITY_OPERATION o|--o| DELETION_OPERATION : forget_cleanup
    DELETION_OPERATION ||--o{ DELETION_OPERATION_ITEM : cleans
    DELETION_OPERATION ||--o{ DELETION_LEDGER : commits

    BACKUP_RECORD }o--|| ARTIFACT : stored_as
    BACKUP_RECORD o|--o{ RECOVERY_OPERATION : restored_by
```

`DESTRUCTIVE_JOURNAL` is intentionally shown outside the primary
relational ERD because its physical implementation is independently
durable and remains open.

## 11.2 `deletion_operation`

-   `id`
-   operation type
-   state
-   actor
-   Source nullable
-   Person nullable
-   IdentityOperation nullable
-   correlation ID
-   requested/committed/cleanup-completed/failed timestamps
-   failure summary
-   timestamps

Types: - RECYCLE_SOURCE - RESTORE_SOURCE - PERMANENT_DELETE_SOURCE -
FORGET_PERSON

States: - PENDING - COMMITTED - CLEANING - COMPLETED - FAILED_CLEANUP

**Deletion becomes semantically effective at COMMITTED.**

FAILED_CLEANUP never restores eligibility.

## 11.3 Recycle semantics

RECYCLE_SOURCE: - Source lifecycle -\> RECYCLED - retains original
media - retains Source hierarchy - retains
observations/crops/representations/evidence - excluded from normal
Search/library - evidence may initially remain usable for recognition -
restore can be cheap if retained state remains valid

No automatic permanent-expiry timer by default in V1.

## 11.4 Permanent Source deletion

Removes source-owned: - original media - Encounter - Appearance -
Track - Observation - source-derived crops/thumbnails -
Representations - source-derived associations/evidence - affected
recognition-artifact dependencies - co-occurrence/index state -
future-training eligibility

It **does not automatically delete Person/Identity**.

Identity memory is reconsolidated from surviving evidence.
Maturity/health may change by Reasoner policy.

Zero surviving evidence is derived; no ORPHANED lifecycle state is
required.

## 11.5 Forget Person

Forget is cross-domain:

``` text
IdentityOperation(FORGET_PERSON)
        |
        v
DeletionOperation(FORGET_PERSON)
```

Semantic effects: - Person becomes forgotten/ineligible - attached
current Identities lose persistent recognition eligibility - active
name/alias search mapping removed - recognition memory invalidated -
stale indexes blocked immediately

Source media/history remains.

New encounters may rediscover the human as a new unknown identity
generation. The system must not secretly reconnect it to the forgotten
generation.

Forget is **not** implemented as a biometric blacklist.

## 11.6 `deletion_operation_item`

Durable cleanup units: - Artifact cleanup - Source hierarchy cleanup -
Identity-memory rebuild - Index invalidation - training-eligibility
cleanup

Do not create one item for every Observation in a huge Source unless
operationally necessary.

Items retry independently and cleanup is idempotent.

## 11.7 `deletion_ledger`

Minimal anti-resurrection record: - `id` - `operation_id` -
`sequence_number` unique monotonic - `subject_kind` -
`subject_stable_id` - destructive action - generation marker nullable -
committed_at - superseded_at nullable

No names, face crops, vectors, or media copies.

Historical stable ID is intentional because the target row may no longer
exist.

## 11.8 Destructive Journal --- **external recovery subsystem**

Conceptual minimal record: - destructive sequence - subject kind -
subject stable ID - action - generation marker nullable - committed
timestamp - prepared/committed recovery state as needed

Its physical technology remains open: small SQLite file, append-only
file, or another durable local mechanism.

Purpose:

> Restoring an older primary DB backup must not erase newer destructive
> intent.

Conceptual recoverable protocol: 1. allocate destructive sequence 2.
durably journal PREPARED 3. commit authoritative DB operation/ledger 4.
mark journal COMMITTED 5. reconcile incomplete states on startup

## 11.9 `backup_record`

-   `id`
-   backup type
-   state
-   `artifact_id` FK
-   created/completed timestamps
-   schema version
-   destructive watermark
-   size/checksum
-   expires_at nullable

States: CREATING / AVAILABLE / FAILED / EXPIRED / DELETED

Automatic V1 backup covers: - primary DB - critical configuration -
destructive-state metadata

It does **not** automatically duplicate the full media library.

Available BackupRecord protects its Artifact from ordinary garbage
collection.

## 11.10 Restore rule

Backup carries the greatest destructive sequence it already contains.

Restore workflow:

1.  verify backup
2.  restore into staging
3.  read backup destructive watermark
4.  read newer DestructiveJournal entries
5.  reapply/reconcile newer destructive intent
6.  invalidate affected derived state
7.  verify DB/integrity
8.  activate restored DB
9.  rebuild/repair indexes asynchronously

Search and Recognition must not run before destructive reconciliation
completes.

## 11.11 `recovery_operation`

Operational provenance: - operation type - state - BackupRecord
nullable - start/end - from/to destructive watermark - failure summary -
created_at

Types may include: - STARTUP_RECONCILIATION - RESTORE_BACKUP -
REPAIR_DATABASE

Corruption or missing files are integrity failures, not deletion.

------------------------------------------------------------------------

# 12. FK and Deletion Behavior Reference

Every FK should be assigned one of four semantic categories.

## A. Ownership Cascade

Used where the parent truly owns the child and authorized permanent
deletion should remove the child.

Primary example:

``` text
Source
  -> Encounter
      -> Appearance
          -> Track
              -> Observation
```

Also appropriate for child rows that have no independent meaning outside
their parent, subject to retention rules.

## B. Historical Weak Reference

The historical record may survive after the target is deleted/forgotten.

Behavior: - SET NULL, or - retain historical stable ID instead of FK

Examples: - retained Search history - DomainEvent aggregate reference -
DeletionLedger subject stable ID

## C. Semantic Restrict

The target should normally not be hard-deleted while required for
provenance.

Examples: - ComponentVersion referenced by protected
ProcessingManifest - version/provenance records

Prefer RETIRED over hard deletion.

## D. Application-Controlled Semantic Cleanup

SQL CASCADE alone cannot express the correct behavior.

Examples: - Source deletion -\> IdentityEvidence - Source deletion -\>
RecognitionArtifact - Forget Person -\> Identity/association/search
state - evidence invalidation -\> RecognitionArtifact rebuild - deletion
-\> vector/search index cleanup

These require domain services/transactions plus asynchronous cleanup.

------------------------------------------------------------------------

# 13. Authoritative vs Derived vs Operational Reference

## 13.1 Authoritative semantic/history state

-   source and source metadata
-   encounter
-   appearance
-   track
-   track_derivation
-   observation
-   person
-   person_alias
-   identity
-   identity_association
-   identity_evidence
-   identity constraints
-   artifact metadata/ownership/dependencies
-   component/component-version provenance
-   component activation
-   dataset snapshots/items
-   training/evaluation/version decisions
-   feedback events
-   identity operations/participants
-   domain events
-   deletion operations/items/ledger
-   backup records

## 13.2 Historical machine outputs

-   representation
-   recognition_result
-   recognition_hypothesis

These authoritatively record **what the machine produced**, but do not
override corrected semantic state.

## 13.3 Derived/rebuildable state

-   recognition_artifact
-   recognition_artifact_evidence
-   SearchIndexVersion contents
-   backend bindings
-   representation index entries
-   recognition-artifact index entries
-   co-occurrence index entries
-   Qdrant/vector backend contents

## 13.4 Operational state

-   processing_job
-   task
-   task_dependency
-   work_unit
-   work_unit_attempt
-   checkpoint
-   index_mutation
-   recovery_operation

## 13.5 Query/session state

-   search_query
-   query_input
-   query_interpretation
-   query_representation
-   search_execution
-   search_plan
-   search_plan_step
-   search candidates
-   ranking decisions
-   presentations
-   identity answers
-   aggregation results

Query state may have much shorter retention than library state.

------------------------------------------------------------------------

# 14. Cardinality Reference

  ------------------------------------------------------------------------
  Relationship            Cardinality             Notes
  ----------------------- ----------------------- ------------------------
  Source -\> Encounter    1 : 0..N                strict ownership

  Encounter -\>           1 : 0..N                strict ownership
  Appearance                                      

  Appearance -\> Track    1 : 0..N                one Track belongs to
                                                  exactly one Appearance

  Track -\> Observation   1 : 0..N                strict ownership

  Person -\> Identity     1 : 0..N                Identity.person_id
                                                  nullable

  Observation -\>         1 : 0..N                historical associations
  IdentityAssociation                             

  Identity -\>            1 : 0..N                current + historical
  IdentityAssociation                             

  Association -\>         1 : 0..N                only valid positive
  Evidence                                        association can support
                                                  active evidence

  Observation -\>         1 : 0..N                source-grounded
  Evidence                                        

  Identity -\> Evidence   1 : 0..N                supports recognition
                                                  memory

  Observation -\>         1 : 0..N                versioned coexistence
  Representation                                  

  Observation -\>         1 : 0..N                reprocessing/versioned
  RecognitionResult                               runs

  RecognitionResult -\>   1 : 0..N                ranked candidates
  Hypothesis                                      

  Identity -\>            1 : 0..N                derived
  RecognitionArtifact                             

  RecognitionArtifact     N : M                   explicit join
  \<-\> Evidence                                  

  ProcessingJob -\> Task  1 : 0..N                operational

  Task -\> WorkUnit       1 : 0..N                durable scheduling unit

  WorkUnit -\> Attempt    1 : 0..N                retries

  Component -\>           1 : 0..N                immutable versions
  ComponentVersion                                

  DatasetSnapshot -\>     1 : 0..N                frozen provenance
  DatasetItem                                     

  TrainingRun -\>         N : M via output        one run may produce
  ComponentVersion                                multiple candidates

  EvaluationRun -\>       1 : 0..N                extensible metrics
  Metric                                          

  SearchQuery -\>         1 : 0..N                reruns allowed
  SearchExecution                                 

  SearchExecution -\>     1 : 0..N                retrieval
  Candidate                                       

  Candidate -\>           1 : 0..1                may be filtered before
  RankingDecision                                 ranking

  RankingDecision -\>     1 : 0..1                not every ranked item
  Presentation                                    must be shown

  SearchIndex -\>         1 : 0..N                derived versions
  SearchIndexVersion                              

  DeletionOperation -\>   1 : 0..N                cleanup units
  Item                                            

  DeletionOperation -\>   1 : 1..N as needed      destructive subjects
  Ledger                                          

  BackupRecord -\>        N : 1                   one principal Artifact
  Artifact                                        per backup in V1
  ------------------------------------------------------------------------

------------------------------------------------------------------------

# 15. Critical Constraints and Invariants

## Source/history

-   Track and Observation direct Source FKs must match hierarchy.
-   TrackDerivation same-source, acyclic, no self-reference.
-   Observation source facts are immutable-ish; corrections should
    preserve provenance.

## Identity

-   active Identities attach only to canonical Persons.
-   one operative current positive Association per Observation.
-   association supersession only within same Observation.
-   Evidence must match backing Association's Observation and Identity.
-   rejected/invalid Association makes Evidence unusable immediately.
-   user correction outranks system inference.
-   Identity pair constraint uses canonical unordered pair and cannot
    self-reference.
-   false merge prevention should be stricter than ordinary observation
    matching.

## Representation

-   version/space compatibility must be explicit.
-   incompatible representation spaces are never compared.
-   QueryRepresentation cannot create persistent identity memory.
-   Qdrant is never sole authority.

## Processing

-   every executable Job has frozen Manifest.
-   Manifest does not mutate after execution starts.
-   only COMMITTED WorkUnit outputs count as durable progress.
-   Attempt lease expiry may abandon/retry execution without corrupting
    logical WorkUnit.
-   resource policy does not rewrite semantic processing provenance.

## Models

-   ComponentVersion behavior is immutable.
-   activation history is append-oriented.
-   training completion does not imply promotion.
-   promotion does not synchronously rebuild the entire library.
-   old/new component and representation versions may coexist during
    migration.

## Feedback/events

-   FeedbackEvent semantic content is append-oriented.
-   correction creates new feedback/association/evidence rather than
    rewriting old semantic history.
-   Search click is not biometric confirmation.
-   DomainEvent payload must not defeat deletion.
-   IdentityOperation reversal is compensating history.

## Search

-   candidate generation != final result.
-   raw scores from different retrievers are not directly comparable.
-   authoritative resolution is mandatory before presentation.
-   forgotten/deleted stale index hits must be filtered immediately.
-   accepted face identity answer is pinned outside normal rank.
-   uncertain identity candidates are not presented as confirmed.
-   aggregation must expose uncertainty/completeness.

## Deletion/recovery

-   Recycle != Permanent Delete.
-   Delete Source != Forget Person.
-   deletion becomes true at authoritative COMMITTED state.
-   cleanup failure cannot resurrect eligibility.
-   missing/corrupt file != deletion.
-   Delete Source cascade stops before global Person/Identity.
-   Forget does not retain a biometric blacklist.
-   newer destructive intent must be reconciled before restored DB
    becomes usable.
-   backups may temporarily contain old deleted/forgotten state until
    retention expiry, but restore reconciliation must prevent
    resurrection.

------------------------------------------------------------------------

# 16. Provenance Chains

## 16.1 Visual identity provenance

``` text
Source
 -> Encounter
 -> Appearance
 -> Track
 -> Observation
 -> Representation
 -> RecognitionResult
 -> IdentityAssociation
 -> IdentityEvidence
 -> RecognitionArtifact
```

This answers: **Where did this identity belief come from?**

## 16.2 Processing provenance

``` text
ProcessingJob
 -> ProcessingManifest
 -> ManifestComponent
 -> ComponentVersion

Task
 -> WorkUnit
 -> Observation / Representation / RecognitionResult / Artifact
```

This answers: **Which software/configuration/work unit produced this
output?**

## 16.3 Training provenance

``` text
Source
 -> Observation
 -> IdentityAssociation
 -> IdentityEvidence
 -> DatasetItem
 -> DatasetSnapshot
 -> TrainingRun
 -> TrainingRunOutput
 -> ComponentVersion
 -> EvaluationRun
 -> VersionDecision
 -> ComponentActivation
```

## 16.4 Correction provenance

``` text
RecognitionResult
 -> IdentityAssociation
 -> User FeedbackEvent
 -> Constraint / IdentityOperation
 -> superseding IdentityAssociation
 -> new IdentityEvidence
```

Original machine output and original feedback remain historical.

## 16.5 Search provenance

``` text
SearchQuery
 -> SearchExecution
 -> SearchPlan
 -> SearchPlanStep
 -> SearchCandidate
 -> RankingDecision
 -> SearchResultPresentation
```

This answers: **Why did the user see this result?**

It is intentionally different from identity-belief provenance.

## 16.6 Deletion provenance

``` text
Destructive request
 -> DeletionOperation
 -> authoritative semantic commit
 -> DeletionLedger
 -> immediate ineligibility
 -> DeletionOperationItem cleanup
 -> filesystem/index/derived cleanup
```

Recovery additionally uses:

``` text
BackupRecord + DestructiveJournal
 -> RecoveryOperation
 -> reconciled authoritative database
 -> derived rebuild
```

------------------------------------------------------------------------

# 17. Relationship Reference for Implementers

This section is intentionally explicit so implementation agents do not
infer semantics only from ERD lines.

### Person ↔ Identity

Person is the semantic/user-facing human entity. Identity is a
machine-maintained visual identity. Multiple Identities may attach to
one Person. An Identity may remain unnamed with `person_id = NULL`.

### Observation ↔ Identity

There is **no direct FK**. Identity belief always goes through
IdentityAssociation. This preserves correction history and prevents
source observations from becoming mutable identity records.

### RecognitionResult ↔ IdentityAssociation

RecognitionResult is immutable machine provenance. IdentityAssociation
is semantic belief/current relationship. User correction
changes/supersedes the latter, never the former.

### IdentityAssociation ↔ IdentityEvidence

Association means "this Observation is believed to be this Identity."
Evidence means "this source-grounded association is allowed to support
recognition memory." These are not equivalent.

### IdentityEvidence ↔ RecognitionArtifact

Evidence is authoritative source-grounded memory. RecognitionArtifact is
derived optimized machine state. Deleting/inactivating evidence
invalidates/rebuilds dependent artifacts.

### Source ↔ Person

There is deliberately no ownership relationship. Deleting a Source must
not cascade into Person.

### Track ↔ Identity

There is deliberately no direct identity FK. Tracking says "same
continuous visible subject," not "this is David."

### Artifact ↔ domain entities

Artifact owns storage metadata, not semantic meaning. Typed relation
tables define why a domain entity references an Artifact.

### ComponentVersion ↔ ProcessingManifest

Manifest freezes exact versions for a Job. Active-version changes after
Job start do not mutate the Job.

### ComponentActivation ↔ SearchIndexActivation

Independent. A new component can be active while a compatible older
Search index remains active during migration.

### FeedbackEvent ↔ IdentityOperation

Feedback records what the user/system said. IdentityOperation records
the complex semantic transformation performed because of an action. Not
every FeedbackEvent needs an IdentityOperation.

### DomainEvent ↔ target

DomainEvent may use generic historical `aggregate_type + aggregate_id`.
This is intentional and should not be replaced with a universal
active-entity table.

### SearchCandidate ↔ domain targets

Unlike DomainEvent, SearchCandidate uses real typed nullable FKs and
exactly one active target. No universal SearchableEntity table.

### SearchIdentityAnswer ↔ Search results

An accepted identity answer is not ordinary rank #1. It is a separate
answer pinned outside heterogeneous ranked results.

### DeletionOperation ↔ IdentityOperation

FORGET_PERSON uses both: IdentityOperation for semantic identity
transformation and DeletionOperation for destructive cleanup.

### DeletionLedger ↔ deleted target

Uses historical stable ID rather than live FK because the target may be
physically deleted.

### BackupRecord ↔ DestructiveJournal

Backup stores a destructive watermark. Journal entries newer than that
watermark must be reconciled before restore activation.

------------------------------------------------------------------------

# 18. Implementation-Open Decisions

The following are intentionally **not locked** and must not be invented
as though they were product requirements:

-   primary relational database technology
-   ORM
-   final vector backend after benchmarking; Qdrant is only the initial
    candidate
-   detector implementation/model
-   tracker implementation/model
-   representation technique
-   recognizer implementation
-   identity-reasoner algorithm
-   model frameworks
-   pretrained vs fine-tuned vs from-scratch choices
-   representation payload encoding
-   exact inline-vs-Artifact storage threshold
-   checksum algorithm
-   storage-root/path layout
-   exact component activation scopes
-   exact identity thresholds
-   maturity promotion/demotion thresholds
-   evidence-promotion policy
-   recognition calibration policy
-   Search ranking weights/models
-   natural-language query technology
-   scene-detection implementation
-   co-occurrence thresholds
-   Search retention durations
-   backup rotation schedule
-   DestructiveJournal physical technology
-   WorkUnit boundary encoding
-   processing chunk sizes/overlap
-   batch sizes
-   CPU/GPU scheduling formula
-   quality metrics
-   evaluation suites/metrics
-   training methodology
-   artifact garbage-collection timing
-   exact database-level realization of some semantic constraints where
    application-level validation is more appropriate

These should be selected through implementation research, benchmarking,
and operational experience.

------------------------------------------------------------------------

# 19. Do Not Infer

Implementation agents must **not** introduce these assumptions:

``` text
Observation.identity_id                     ❌
Track.identity_id                           ❌
Appearance.identity_id                      ❌

Identity == Person                          ❌

RecognitionResult == current identity truth ❌

Qdrant == authoritative memory              ❌

Query face == imported Source               ❌

Search result == recognition decision       ❌

top visual similarity == confirmed identity ❌

recycled Source == permanently deleted      ❌

delete Source == forget Person              ❌

forget Person == biometric blacklist        ❌

missing file == user deletion               ❌

training completed == model promoted        ❌

active model changed == running Job changes ❌

event log == source of all current state     ❌

machine association == trusted evidence      ❌

all evidence == active recognition memory    ❌

Encounter == Person encounter                ❌

Track continuity overrides identity conflict ❌

same Encounter proves direct co-visibility   ❌

different DatasetSnapshot IDs prevent leakage ❌
```

------------------------------------------------------------------------

# 20. Canonical Naming

Use these final names:

  -----------------------------------------------------------------------
  Canonical                           Do not use
  ----------------------------------- -----------------------------------
  `dataset_snapshot`                  `training_dataset_snapshot`

  `dataset_item`                      `training_dataset_item`

  `version_decision`                  `promotion_decision`

  `version_decision_evaluation`       `promotion_decision_evaluation`

  `search_identity_answer`            uncertain answer rows
  accepted-only                       

  Destructive Journal as recovery     assuming ordinary primary-DB
  subsystem                           `destructive_journal` table
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 21. Final Architectural Summary

The schema is designed around **source-grounded, correctable, versioned
memory**.

The Source hierarchy records what physically happened. Recognition
produces immutable machine outputs. IdentityAssociation converts those
outputs into correctable semantic belief. IdentityEvidence determines
which source-grounded beliefs may support active recognition.
RecognitionArtifacts and vector indexes optimize that memory but remain
rebuildable. Person provides semantic naming without being confused with
machine identity.

Processing is version-frozen and recoverable. Model training,
evaluation, promotion, activation, and migration are explicitly
separate. Search consumes authoritative memory without becoming identity
authority. Feedback and operations preserve corrections without
requiring event sourcing. Deletion and forgetting become authoritative
before cleanup and remain protected against resurrection through backup
restore.

The central safety property of the design is therefore:

> **No derived structure --- model output, recognition artifact, vector
> index, search result, cache, stale file, historical event, or old
> backup --- is allowed to override current authoritative identity,
> correction, deletion, or forget state.**
