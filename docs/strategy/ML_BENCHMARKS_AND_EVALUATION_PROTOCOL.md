# ML Benchmarks and Evaluation Protocol

**Project:** Local Visual Identity / Face Memory Application  
**Document status:** Consolidated working draft — review required  
**Scope:** Windows V1 managed-image recognition, persistent identity memory, runtime, recovery and future upgrades  
**Important editorial note:** Sections 1–14 below have been reconstructed from the detailed section summaries retained in this conversation, rather than copied verbatim from the original writing blocks. Sections 15–20 are consolidated from their drafted content. This is a usable unified working document, **not** a claim of verbatim archival reproduction. All benchmarks and acceptance criteria are proposed; no experiments or approvals are claimed.

## Contents

1. [Evaluation Objectives and Governance](#1-evaluation-objectives-and-governance)
2. [Dataset Selection, Provenance, Licensing, and Privacy](#2-dataset-selection-provenance-licensing-and-privacy)
3. [Ground-Truth Definitions, Annotation Standards, and Label Quality](#3-ground-truth-definitions-annotation-standards-and-label-quality)
4. [Dataset Partitioning, Leakage Prevention, and Experimental Sampling](#4-dataset-partitioning-leakage-prevention-and-experimental-sampling)
5. [Experimental Configuration, Reproducibility, and Artifact Management](#5-experimental-configuration-reproducibility-and-artifact-management)
6. [Detector and Landmark Benchmarks](#6-detector-and-landmark-benchmarks)
7. [Alignment and Preprocessing Validation](#7-alignment-and-preprocessing-validation)
8. [Embedding and Representation Benchmarks](#8-embedding-and-representation-benchmarks)
9. [Retrieval and Candidate-Aggregation Benchmarks](#9-retrieval-and-candidate-aggregation-benchmarks)
10. [Open-Set Recognition and Chronological Memory Replay](#10-open-set-recognition-and-chronological-memory-replay)
11. [Similarity Calibration and Threshold Selection](#11-similarity-calibration-and-threshold-selection)
12. [DecisionEstimator and RecognitionPolicy Evaluation](#12-decisionestimator-and-recognitionpolicy-evaluation)
13. [Runtime-Provider and Numerical Compatibility](#13-runtime-provider-and-numerical-compatibility)
14. [Performance, Memory, and Throughput](#14-performance-memory-and-throughput)
15. [Recovery and Operational Validation](#15-recovery-and-operational-validation)
16. [Model Upgrades and Migration Evaluation](#16-model-upgrades-and-migration-evaluation)
17. [Acceptance Criteria and Release Gates](#17-acceptance-criteria-and-release-gates)
18. [Results Templates and Reporting Requirements](#18-results-templates-and-reporting-requirements)
19. [Consolidated Benchmark Register](#19-consolidated-benchmark-register)
20. [Final Evaluation and Promotion Procedure](#20-final-evaluation-and-promotion-procedure)

---

## Project-wide architectural constraints

The application processes biometric data locally. The initial vertical slice imports managed images, detects multiple faces, aligns and embeds them, retrieves candidate identities and persists unnamed identities, observations, representations, evidence, occurrences, and processing history. Video, temporal tracking, live cameras, advanced person management and retraining are deferred. Target hardware is a Lenovo Legion 7i with Intel i9-14900HX, RTX 4070 Laptop GPU (8 GB VRAM), 32 GB RAM and approximately 1 TB SSD.

The domain is **Source → Observation → Representation → Identity → Person**. An observation is an individual detected face; a representation is an immutable embedding within one RepresentationSpace; an identity is a persistent visual subject, including unnamed subjects; a person is an optional semantic human record. An occurrence records a meaningful source appearance and is not synonymous with an individual observation.

The pipeline is **ML worker → Representation → USearch ANN → SQLite revalidation → identity-level aggregation → versioned IdentityEvidence → DecisionEstimator → deterministic RecognitionPolicy → IdentityReasoner → Identity Manager → authoritative SQLite**. Identity Manager alone commits authoritative identity mutations. Similarity scores are neither calibrated probabilities nor authorization. Retrieval failure, invalid evidence or incomplete migration must never be treated as valid UNKNOWN evidence for automatic creation.

SQLite is authoritative; USearch is derived and reconstructible. Representations are immutable contiguous little-endian float32 vectors. Persistence supports multiple RepresentationSpaces, with one active recognition space in V1. Inference runs in a persistent Python worker with bounded IPC and shared memory; FastAPI orchestrates explicit provider fallback with new ExecutionSegments. CUDA is primary; CPU/DirectML require separate validation. The Laya-inspired DecisionEstimator is replaceable and deterministic in V1; no Laya build or fine-tuning prerequisite is approved.

---

## 1. Evaluation Objectives and Governance

### 1.1 Objectives

The protocol exists to select perception components, establish RepresentationSpace compatibility, evaluate open-set recognition, authorize identity actions, verify operational reliability and support safe model evolution. Component quality, full recognition quality and operational reliability must be reported independently; no aggregate score may conceal a mandatory failure.

### 1.2 Evidence classes

Use four complementary evidence classes: approved public detection datasets, approved public recognition datasets, consented application-specific samples and synthetic deterministic fixtures. Public benchmarks measure standardized tasks; app-specific samples measure intended operating conditions; synthetic fixtures validate numerical and state-machine invariants. None substitutes for the others.

### 1.3 Benchmark contract

Every benchmark specification declares an objective, evaluated requirement, approved dataset/fixtures, ground truth, configuration, procedure, metrics, statistical method, **predeclared** acceptance criteria, evidence artifacts, limitations and applicable release gate. The benchmark lifecycle is **PROPOSED → PROTOCOL DEFINED → DATASET APPROVED → IMPLEMENTED → EXECUTED → RESULTS VALIDATED → ACCEPTED / REJECTED / INCONCLUSIVE**. Implementation, execution and approval are distinct statuses.

### 1.4 Governance

Freeze independent final-test data before model selection. Approve statistical rules and operating-point criteria before final testing. Record deviations, failed executions, exclusions and changes. Re-run affected gates when material dependencies change. Neither a model nor an automatic identity operation is approved merely because its benchmark specification exists.

## 2. Dataset Selection, Provenance, Licensing, and Privacy

### 2.1 Provisional dataset register

| ID | Dataset | Intended use | Approval |
|---|---|---|---|
| DATA-001 | WIDER FACE | Detection | Rights/acquisition/protocol verification pending |
| DATA-002 | FDDB | Detection | Rights/acquisition/protocol verification pending |
| DATA-003 | LFW | Face verification | Rights/acquisition/protocol verification pending |
| DATA-004 | CFP-FP | Pose-sensitive verification | Rights/acquisition/protocol verification pending |
| DATA-005 | AgeDB-30 | Age-variation verification | Rights/acquisition/protocol verification pending |
| DATA-006 | IJB-C | Advanced recognition | Rights/acquisition/protocol verification pending |
| DATA-007 | Consented app-specific | Local use cases, chronological memory | Consent/protocol pending |
| DATA-008 | Synthetic numerical fixtures | Contracts, fault injection | Fixture validation pending |

Dataset names are candidates, not confirmation that their licensing permits the intended use. The proposed 30–50 consented app-specific participants is an **initial engineering development target**, not a statistically justified final sample size.

### 2.2 Dataset manifest and approval

For every acquisition, record source, exact version, hashes, rights and restrictions, consent basis where applicable, permitted purposes, annotation format, subject/sample counts, acquisition date, storage location, retention policy and deletion mechanism. The lifecycle is **PROPOSED → ACQUIRED → RIGHTS VERIFIED → QUALITY CHECKED → PARTITIONED → APPROVED → VERSIONED/FROZEN**. Only approved data may support formal claims.

### 2.3 Privacy

Keep biometric data local and outside source control. Restrict access to original media, crops, embeddings and predictions; prefer pseudonymous identifiers in reports. Deletion requirements extend to derived vectors, crops, temporary files, indexes and applicable benchmark copies. Backups must have an explicit retention/deletion policy; do not claim instantaneous erasure of immutable backups without supporting implementation evidence.

## 3. Ground-Truth Definitions, Annotation Standards, and Label Quality

### 3.1 Evaluation ontology

Maintain an evaluation-only ontology: **GroundTruthSubject → GroundTruthSample → GroundTruthFace → GroundTruthRelationship → GroundTruthSequence → AnnotationRecord**. Ground-truth subjects are independent of the application's mutable Identity and Person records. Define coordinate systems, bounding-box conventions, landmarks, visibility, occlusion, pose, ignore regions and source/time identifiers before annotation.

### 3.2 Relationships and temporal state

A genuine relationship requires independently verified same-subject evidence; an impostor relationship requires independently verified different subjects. Unresolved pairs are neither genuine nor impostor. Existing-versus-unseen is derived **at each replay event** from eligible prior enrollment, not assigned permanently to a subject. AMBIGUOUS and ABSTAIN are system outputs, not intrinsic subject labels.

### 3.3 Annotation quality

Use annotation states **VERIFIED, PROVISIONAL, DISPUTED, UNRESOLVED, EXCLUDED**. Preserve annotator, timestamp, guideline version, adjudication and amendment history. Keep evaluation truth outside the production recognition path; never allow future annotations to leak into chronological decisions.

### 3.4 Memory error taxonomy

Track incorrect attachment, incorrect duplicate creation, fragmentation, contamination, missed attachment and unnecessary review separately. Compare actual memory state to the time-appropriate verified reference, not merely to the immediately preceding prediction.

**Register:** `GT-01`–`GT-10` cover schema, subject consistency, face annotation, relationship validation, unresolved labels, chronological truth, enrollment state, disagreement, versioning and truth isolation. Exact original subtest wording must be checked before canonical publication.

## 4. Dataset Partitioning, Leakage Prevention, and Experimental Sampling

Use independent **development, calibration and final-test** partitions. For app-specific data, use subject-disjoint partitions where required by the question; within a partition, separate enrollment from query by session/source where feasible. Preserve official public benchmark protocols instead of retrofitting incompatible partitions.

Detect exact and near duplicates; document any suspected pretrained-model overlap separately, since absence of evidence is not proof of absence. Stratify by available verified metadata without inferring unsupported demographic labels. Sample genuine and impostor pairs with explicit subject dependence; difficult impostors may be mined only from allowed development/calibration data. Use subject- or sequence-aware resampling when estimating uncertainty.

Evaluate controlled gallery sizes, representation counts per identity, exact versus ANN retrieval, enrolled/unseen prevalence and feedback schedules. In chronological replay, construct gallery snapshots using only information eligible at that event. Report oracle-memory and predicted-memory replay separately. Freeze manifests and hashes before final evaluation. Plan sample sizes against required precision rather than choosing them after results are known.

**Register:** `SPLIT-01`–`SPLIT-14`; import exact original definitions during reconciliation. Required coverage includes partition independence, leakage, sampling, galleries, chronology, feedback, manifests and sample-size planning.

## 5. Experimental Configuration, Reproducibility, and Artifact Management

Distinguish **benchmark_id** (procedure), **experiment_id** (frozen configuration) and **execution_id** (attempt). Every experiment manifest identifies datasets, ground-truth/partition versions, full recognition configuration, model artifacts, RepresentationSpace, calibration, policy, actual runtime requirements, seeds, metrics, statistical method and acceptance criteria.

Preserve **Component → ComponentVersion → ModelExport → RuntimeVariant** provenance and the full recognition configuration fingerprint; a fingerprint identifies configuration but does not prove compatibility. Record Windows version, CPU/GPU, RAM/VRAM, drivers, dependencies, power conditions when relevant, actual execution provider and precision. Execution states are **CREATED → VALIDATING → READY → RUNNING → COMPLETED / FAILED / CANCELLED / INVALIDATED**; benchmark approval is separate.

A suggested layout is `benchmarks/experiments/<experiment-id>/executions/<execution-id>/` with manifest, environment, predictions, measurements, logs, failures, metrics, statistics and report. Preserve raw pseudonymous predictions sufficient to recalculate metrics while enforcing privacy restrictions. Validate artifact integrity, repeated execution and comparisons before approval.

**Register:** `EXP-01`–`EXP-14`, exact original subtest definitions pending reconciliation.

## 6. Detector and Landmark Benchmarks

Compare a specified SCRFD variant with a specified RetinaFace comparator only after confirming exact weights, exports, runtime support and rights. Test four levels: detector alone; landmarks; detector-plus-alignment-plus-embedder; and complete recognition. WIDER FACE/FDDB and consented app-specific data are candidates, subject to Section 2 approval; use an approved landmark dataset when available.

| ID | Test |
|---|---|
| DET-01 | Detection accuracy under the approved matching protocol |
| DET-02 | Bounding-box localization / IoU |
| DET-03 | Confidence-threshold operating points |
| DET-04 | Small-face performance |
| DET-05 | Occlusion and pose robustness |
| DET-06 | Per-face recall and per-image complete multi-face coverage |
| DET-07 | Duplicate detections and NMS behavior |
| DET-08 | Landmark normalized mean error with specified normalization |
| DET-09 | Downstream alignment and embedding impact |
| DET-10 | End-to-end recognition and coverage impact |
| DET-11 | Latency and memory under declared runtime |

Report no-face inputs separately from detector errors, and preserve actual provider, resolution, batch, thresholds, matching conventions and paired uncertainty. No detector variant is approved by this document.

## 7. Alignment and Preprocessing Validation

Preprocessing is part of the embedding's semantic contract. Version the actual pipeline: **decode → orientation → canonical image → detect landmarks → align → resize → color/channel handling → model-specific normalization → input tensor → embed → output validation → canonical representation**. Validate its actual order rather than assuming this schematic is universal.

| ID | Test |
|---|---|
| PRE-01 | Decoding and supported formats |
| PRE-02 | EXIF/orientation, including prevention of double rotation |
| PRE-03 | Coordinate conventions and geometric transformations |
| PRE-04 | Landmark mapping from detector to alignment contract |
| PRE-05 | Alignment correctness against reference fixtures |
| PRE-06 | Alignment robustness |
| PRE-07 | Resize and interpolation |
| PRE-08 | Color and channel ordering |
| PRE-09 | Model-specific input normalization |
| PRE-10 | Input tensor shape/type/value validation |
| PRE-11 | Embedding dimensions, finite values, nonzero norm and canonical normalization |
| PRE-12 | Contiguous little-endian float32 codec roundtrip |

Compare CPU/GPU preprocessing where relevant and evaluate downstream embedding compatibility. A semantic preprocessing change normally requires a new RepresentationSpace unless validated otherwise. Invalid preprocessing is a **PREPROCESSING_FAILURE**, never a valid UNKNOWN. Include decoding, dimensions, orientation, coordinate, landmark, alignment, tensor, embedding and space error categories.

## 8. Embedding and Representation Benchmarks

Benchmark exact, versioned lightweight ArcFace-family candidates first; compare a larger ArcFace-family model and an AdaFace candidate if justified. Weights, export format, pretrained-data overlap, licensing and runtime suitability remain unverified until investigated. Canonical vectors are normalized float32; raw vector storage is `4 × dimension` bytes, excluding metadata and index overhead.

**Provisional `EMB-01`–`EMB-23` coverage:** output correctness; reference agreement; dimensionality; genuine and impostor distributions; verification (FMR, FNMR, TAR at declared FMR and diagnostic EER); difficult genuine/impostor cases; cross-session stability; repeated execution; exact identity-level retrieval; representation-count effects; open-set suitability; quality sensitivity; cross-model incompatibility; runtime consistency; precision; latency; throughput; storage/indexing; failure injection; statistical comparison; and error analysis.

Evaluate both embedding discrimination and its effect on the complete recognition pipeline. Equal-dimensional embeddings from different model versions are not interchangeable. A stronger verification result does not authorize automatic identity attachment or creation. Reconcile these provisional IDs against the earlier architecture document's embedding IDs before publishing a canonical register.

## 9. Retrieval and Candidate-Aggregation Benchmarks

Use exhaustive exact cosine similarity over normalized compatible vectors as the reference. Compare USearch ANN at both **representation** and **distinct identity** levels. Dynamic expansion has separate representation depth and distinct-identity candidate count; record both. Start with deterministic maximum-similarity identity aggregation, explicitly measuring representation-count bias and support dependence.

SQLite revalidates every ANN result against current eligible ACTIVE representations, ACTIVE identities, authoritative mappings and the active RepresentationSpace. Stale entries may be filtered, but filtering can make retrieval incomplete. Record explicit completeness; incomplete retrieval must not produce valid UNKNOWN or automatic new-identity creation.

**Provisional `RET-01`–`RET-20` coverage:** exact reference; ANN recall; representation and identity recall@K; dynamic expansion; aggregation; representation-count bias; leading/runner-up margin; SQLite revalidation; completeness; space isolation; index construction/reconstruction; update consistency; gallery growth; latency; memory; failure injection; and downstream recognition. Preserve query, candidate, score, supporting representation IDs and retrieval provenance in CandidateEvidence. Retrieval proposes candidates; it never authorizes identity mutation.

## 10. Open-Set Recognition and Chronological Memory Replay

At each query time, classify the ground-truth subject as **enrolled** only if an eligible prior representation is in the then-valid gallery; otherwise **unseen**. Evaluate both frozen-gallery open-set identification and chronological replay. Preserve query prevalence, gallery size, enrollment protocol, sample/subject dependence and per-face versus per-image results. Include appropriate DIR/TPIR at specified FPIR where supported by the exact protocol.

Separate estimator outcomes **MATCH, UNKNOWN, AMBIGUOUS, ABSTAIN** from policy actions **ATTACH_EXISTING, CREATE_NEW, PRESERVE_UNRESOLVED, REQUIRE_REVIEW, BLOCK**, and from actual committed Identity Manager effects. UNKNOWN requires valid complete recognition, not a failed lookup or migration gap.

Run **oracle-memory replay** with verified prior memory to isolate recognition quality, and **predicted-memory replay** using the application's own earlier accepted decisions to expose compounding errors. Use event-level provenance, realistic feedback timing (none, delayed, immediate or selective as predeclared), no future information, and authoritative correction constraints. Report incorrect attachment, incorrect duplicate creation, fragmentation, contamination, missed attachment, review and memory growth separately. Evaluate action-specific risk–coverage with sequence-aware uncertainty.

**Register:** `REC-01`–`REC-15` provisional; explicitly reconcile frozen-gallery metrics, event schema, retrieval eligibility and per-image/per-face distinctions before canonical publication.

## 11. Similarity Calibration and Threshold Selection

Keep three concepts separate: **similarity score**, **calibrated estimate**, and **policy authorization**. A versioned CalibrationProfile belongs to a compatible complete recognition configuration but is not the RepresentationSpace or RecognitionPolicy. Evaluate pairwise genuine/impostor distributions, identity-level leading/second scores, margins, UNKNOWN/ambiguity and gallery-size effects.

Use development data to choose calibration methods and a separate calibration partition to fit/select operating points as prescribed; reserve independent final data for assessment. For future probability estimators, specify each probability target (for example, leading-candidate correctness or enrolled/unseen) before evaluating Brier score, log loss, reliability diagrams or ECE. Do not interpret a raw cosine value as probability.

Automatic **attachment** and **creation** require distinct thresholds, error budgets and risk–coverage evaluation. Recheck calibration after changes to embedding, preprocessing, retrieval, aggregation, runtime numerical behavior or estimator inputs. Use sample-size and uncertainty planning for rare errors; zero observed failures is not proof of zero risk.

**Register:** `CAL-01`–`CAL-15`, provisional exact definitions pending reconciliation. No numerical thresholds are selected here.

## 12. DecisionEstimator and RecognitionPolicy Evaluation

Evaluate four independent boundaries: **EvidenceBuilder**, **DecisionEstimator**, **RecognitionPolicy** and **Identity Manager**. The versioned immutable decision-time IdentityEvidence contains query/space provenance, retrieval status, candidate scores and supporting representations, relevant constraints and configuration references. The stable interface is `DecisionEstimator.estimate(evidence: IdentityEvidence) -> IdentityDecisionEstimate`.

The V1 estimator is deterministic and must have fixed fixtures for MATCH, UNKNOWN, AMBIGUOUS and ABSTAIN, including ties, score boundaries, candidate-list changes, valid empty retrieval and invalid/incomplete retrieval. Distinguish estimator reason codes from policy reason codes. The policy independently checks attachment/creation requirements, retrieval completeness, calibration, correction constraints and action permissions. Identity Manager revalidates authoritative state at commit and rejects stale or duplicate mutations.

Evaluate end-to-end predicted replay and fault injection. A future lightweight supervised estimator may replace the deterministic baseline only after verified training labels, frozen baseline comparison, leakage controls, action-specific evaluation and applicable release gates. A small joint-candidate neural estimator is only a future research option if measured benefits justify it. No Laya prerequisite is approved.

**Register:** `IDE-01`–`IDE-14`, provisional exact definitions pending reconciliation.

## 13. Runtime-Provider and Numerical Compatibility

Validate **Component → ComponentVersion → ModelExport → RuntimeVariant**. CUDA is the intended primary ONNX Runtime provider; CPU and DirectML are optional independently validated fallbacks. Verify **actual operator/provider assignment**, not merely requested provider availability. Use an approved reference execution (for example, development PyTorch FP32 where appropriate), with versioned opset, I/O binding and input preprocessing.

| ID | Evaluation |
|---|---|
| RUN-01 | Provider/runtime availability |
| RUN-02 | Actual provider assignment |
| RUN-03 | Reference execution |
| RUN-04 | Model load consistency |
| RUN-05 | Detector output compatibility |
| RUN-06 | Landmark/alignment compatibility |
| RUN-07 | Embedding numerical compatibility |
| RUN-08 | Downstream recognition compatibility |
| RUN-09 | RepresentationSpace compatibility |
| RUN-10 | Precision, including optional FP16 |
| RUN-11 | CUDA execution |
| RUN-12 | CPU execution |
| RUN-13 | DirectML execution |
| RUN-14 | Cross-provider comparison |
| RUN-15 | Explicit fallback behavior |
| RUN-16 | ExecutionSegment provenance |
| RUN-17 | Mixed-provider processing |
| RUN-18 | Runtime failure injection |
| RUN-19 | Worker restart |
| RUN-20 | Runtime performance |

Measure raw and normalized vector differences, norm, cosine, candidate rankings, estimator outputs and policy actions. Test mixed old-gallery/new-query and new-gallery/old-query execution at score boundaries. Sharing a RepresentationSpace requires demonstrated numerical **and downstream** compatibility. FastAPI explicitly starts a new ExecutionSegment on fallback; unsupported fallback aborts or uses a separately approved migration, never silently mixes incompatible vectors.

## 14. Performance, Memory, and Throughput

Measure three levels: component, complete image-processing pipeline and full desktop application. Target the specified Legion 7i configuration and record Windows, drivers, runtime, power, thermal state, actual provider, batch size, gallery size and workload manifest. Include small/large/multi-face images and collections of controlled size; future video benchmarks are deferred.

| ID | Evaluation | ID | Evaluation |
|---|---|---|---|
| PERF-01 | Environment | PERF-02 | Decode |
| PERF-03 | Detection | PERF-04 | Alignment |
| PERF-05 | Embedding | PERF-06 | Batch size |
| PERF-07 | Adaptive processing | PERF-08 | VRAM |
| PERF-09 | System RAM | PERF-10 | IPC/shared memory |
| PERF-11 | Queue/backpressure | PERF-12 | One-heavy-pipeline scheduling |
| PERF-13 | USearch retrieval | PERF-14 | SQLite |
| PERF-15 | Vector codec | PERF-16 | Filesystem |
| PERF-17 | Source registration through FINAL checkpoint | PERF-18 | Sustained processing/leaks |
| PERF-19 | Thermal/power | PERF-20 | UI responsiveness |
| PERF-21 | Cancellation | PERF-22 | Recovery overhead |
| PERF-23 | Resource contention | | |

Report median, tails, time series, throughput, success/coverage and resource peaks. Distinguish cold/warm, queue wait, decode, inference, IPC, index, database and complete end-to-end time. Test bounded queues, memory leaks, GPU OOM and user overrides for adaptive processing. Predeclare operational targets; none are approved here.

## 15. Recovery and Operational Validation

### 15.1 Governing invariants

SQLite is authoritative, USearch is reconstructible, results remain provisional until the applicable atomic **FINAL** acceptance checkpoint, and retries must be idempotent. Identity Manager alone commits identity mutations. Preserve ProcessingRun, Job and ExecutionSegment history. An interrupted response does not establish whether a transaction committed; distinguish rollback from committed-but-unacknowledged operations. Never convert operational failure into UNKNOWN.

### 15.2 Failure matrix

Inject controlled failures before/during/after source registration, filesystem staging, decoding, detection, alignment, embedding, ANN query, SQLite revalidation, evidence, estimator, policy, Identity Manager transaction, index update and FINAL checkpoint. Include worker/API/app termination, IPC/shared-memory failure, GPU OOM, disk full, SQLite busy/lock, index corruption, invalid model, incompatible fallback and interrupted migration. Run destructive scenarios only on disposable fixtures and backed-up test databases.

### 15.3 Recovery benchmark register

| ID | Benchmark | Required validation |
|---|---|---|
| RECOV-01 | Atomic acceptance | No partially authoritative output |
| RECOV-02 | Transaction recovery | SQLite rollback/commit integrity |
| RECOV-03 | Idempotent retries | No duplicate authoritative effects |
| RECOV-04 | Worker termination | Interrupted work classified safely |
| RECOV-05 | Worker restart | Correct resumed work and provenance |
| RECOV-06 | Shared-memory recovery | Orphan cleanup and bounded resources |
| RECOV-07 | Application termination | Committed work retained |
| RECOV-08 | Graceful shutdown | Bounded, consistent shutdown |
| RECOV-09 | Cancellation | FINAL work preserved, provisional work handled |
| RECOV-10 | Filesystem consistency | DB/media/crop reconciliation |
| RECOV-11 | ANN-index consistency | Stale results rejected by SQLite |
| RECOV-12 | Index reconstruction | Eligible membership and retrieval parity |
| RECOV-13 | Interrupted index update | DB-to-index reconciliation |
| RECOV-14 | Identity-operation recovery | No unauthorized/duplicate mutation |
| RECOV-15 | Decision recovery | Stale evidence revalidated |
| RECOV-16 | Runtime-provider failure | Explicit validated fallback/new segment |
| RECOV-17 | ProcessingRun recovery | Job/checkpoint consistency |
| RECOV-18 | Recovery ordering | Prerequisites respected |
| RECOV-19 | Repeated failure | Idempotent recovery-of-recovery |
| RECOV-20 | Database integrity | SQLite and domain invariants |
| RECOV-21 | Recovery observability | Structured privacy-safe provenance |
| RECOV-22 | Recovery performance | Detection, restart, rebuild and resume times |

### 15.4 Index and file consistency

Rebuild per-space indexes from eligible ACTIVE representations linked to ACTIVE identities. Verify `ann_key` mapping, duplicate/stale keys and functional query results; approximate indexes need not be byte-identical. During rebuild, block unsafe recognition or use a verified old index with explicit completeness status. Stage media/crops and reconcile missing/orphaned files; define garbage collection, recycle-bin and permanent-deletion behavior. Deletion includes representations, crops, indexes and applicable temporary/backup retention.

### 15.5 Concurrency, backup and restart

Revalidate identity mappings and user corrections at commit; user-confirmed corrections must not be overwritten by stale in-flight evidence. Use safe SQLite backup/restore procedures and integrity checks; avoid unsafe live file copying. Record backup recovery-point and recovery-time targets once selected. Worker restart must clean up shared memory and restore approved model/runtime state. Incompatible provider fallback must not enter the active space. Interrupted migration leaves the prior approved space active.

### 15.6 Reporting and approval

For each injected failure, preserve before/after DB, index and file manifests, failure point, expected invariants, recovery actions, final state and comparison with an uninterrupted control. Report attempts, success, duplicates, integrity violations, leaks and recovery-time distributions with uncertainty. Formal acceptance requires no observed violation of mandatory integrity invariants and satisfaction of predeclared statistical/operational rules; numerical targets, retry budgets, backup periods and shutdown deadlines remain pending.

## 16. Model Upgrades and Migration Evaluation

### 16.1 Upgrade contract

A model upgrade is a controlled configuration change, not merely replacing weights. Classify detector, landmark, preprocessing, embedder, export, runtime, retrieval, aggregation, estimator, calibration and policy changes by their affected contracts. Version an upgrade manifest with source/target artifacts, dependencies, migration needs, benchmarks, activation prerequisites and rollback.

A semantically changed embedder, weights or alignment/preprocessing normally requires a **new RepresentationSpace**. Equal vector dimensions do not establish compatibility. A different export/provider may share an existing space only after numerical and downstream recognition compatibility tests. Existing representations are immutable; do not compare or fuse raw vectors from incompatible spaces.

### 16.2 Migration benchmark register

| ID | Benchmark | Core requirement |
|---|---|---|
| MIG-01 | Upgrade manifest | Complete provenance |
| MIG-02 | Component compatibility | Affected contracts identified |
| MIG-03 | RepresentationSpace compatibility | New-space decision supported |
| MIG-04 | Migration registration | Target remains inactive |
| MIG-05 | Observation eligibility | Rights, retention and artifact availability |
| MIG-06 | Historical reprocessing | New immutable representations |
| MIG-07 | Representation continuity | Existing observations/identities preserved |
| MIG-08 | Migration coverage | Observation and identity coverage |
| MIG-09 | Representation quality | Valid vectors and provenance |
| MIG-10 | Identity continuity | Remembered subjects remain recognizable |
| MIG-11 | Partial migration | Missing history never becomes ordinary UNKNOWN |
| MIG-12 | Index construction | Separate validated target-space index |
| MIG-13 | Cross-space isolation | Unsupported mixing rejected |
| MIG-14 | Recognition comparison | Old/new under comparable conditions |
| MIG-15 | Chronological replay | Historical memory consequences |
| MIG-16 | Calibration migration | New evidence distribution validated |
| MIG-17 | Estimator compatibility | Evidence schema/semantics validated |
| MIG-18 | Policy compatibility | Identity-safety requirements preserved |
| MIG-19 | Runtime compatibility | Approved provider/resource behavior |
| MIG-20 | Migration interruption | Safe resume |
| MIG-21 | Migration idempotency | No duplicate effects |
| MIG-22 | Activation readiness | All applicable gates satisfied |
| MIG-23 | Atomic activation | No mixed active configuration |
| MIG-24 | Post-activation validation | Actual deployed configuration checked |
| MIG-25 | Rollback | Previous approved configuration restored safely |
| MIG-26 | Historical retention | Deletion and retention honored |
| MIG-27 | Migration performance | Duration, CPU/GPU, memory and storage |
| MIG-28 | Migration observability | Stage, counts, failures and provenance |

### 16.3 Safe migration sequence

Register the inactive target space; inventory **eligible** historical observations; reprocess permitted retained source/crop artifacts; accept immutable new representations through approved persistence; build the target index from SQLite; validate observation-level **and identity-level** coverage, quality and retrieval; recalibrate as required; compare open-set and chronological replay against the approved baseline; validate runtime/recovery; explicitly approve activation; atomically switch the complete active configuration; run post-activation fixtures.

An unavailable or permanently deleted artifact is not eligible for resurrection. A successfully completed reprocessing job is not automatically a successful migration. If coverage is insufficient, preserve the old active configuration or restrict unsafe operations. Rollback must account for authoritative identity mutations committed **after** activation; restoring old model files alone does not undo history.

## 17. Acceptance Criteria and Release Gates

### 17.1 Eight independent gates

| Gate | Scope | Principal evidence |
|---|---|---|
| GATE-01 | Evaluation integrity | Dataset rights, truth, splits, leakage, manifests and reports |
| GATE-02 | Detection/preprocessing | Detector, landmarks, alignment and fixtures |
| GATE-03 | Embedding/RepresentationSpace | Vector validity, discrimination and compatibility |
| GATE-04 | Retrieval/open-set recognition | ANN, complete retrieval, enrolled/unseen and calibration |
| GATE-05 | Estimator/policy | Evidence, outcomes, constraints and authorized actions |
| GATE-06 | Runtime/operations | Actual providers, performance and recovery |
| GATE-07 | Memory/migration | Transactionality, replay, index rebuild and safe activation |
| GATE-08 | Integrated release | All applicable validated evidence for declared mode |

Every mandatory criterion declares gate, benchmark, configuration, population, metric/invariant, threshold, statistical rule, evidence and failure classification **before final evaluation**. Approval statuses: PROPOSED, READY_FOR_EVALUATION, EVALUATING, PASSED, FAILED, INCONCLUSIVE, SUPERSEDED. INCONCLUSIVE is not PASSED.

### 17.2 Separate operation authorization

Supervised recognition may be approved independently of automatic actions, but still requires valid embeddings, retrieval, policy boundaries and persistence. **Automatic attachment** requires its own incorrect-attachment error budget, calibration, predicted-memory replay and recovery. **Automatic creation** requires a separate incorrect-duplicate budget, verified UNKNOWN semantics, complete retrieval and adequate migration coverage. A MATCH/UNKNOWN estimate never directly authorizes an Identity Manager mutation.

### 17.3 Evidence and regressions

Report numerator/denominator, evaluation population, sample dependence, confidence/uncertainty and predeclared acceptance rule. Zero observed errors does not imply zero true risk. Mandatory integrity or action-safety failure cannot be offset by better aggregate accuracy, speed or a different metric. A material change triggers dependency-based reassessment, not indiscriminate rerunning nor automatic transfer of approval. Freeze candidates and issue versioned approval records with actual validated execution references and explicit authorized operating modes.

### 17.4 V1 scope

Approve only implemented managed-image capabilities. Video, cameras, advanced naming/merge/split and retraining are not approved by image-only evidence. Runtime fallback is authorized per validated RuntimeVariant, not automatically by CUDA approval.

## 18. Results Templates and Reporting Requirements

### 18.1 Reporting layers

Use **Benchmark Specification → Experiment Manifest → Execution Record → Validated Results → Comparison/Approval Report**. A benchmark definition is not an execution, and an execution is not an approval. Keep raw measurements, calculated metrics, interpretations and gate decisions separate.

### 18.2 Universal report schema

Every report includes benchmark/experiment/execution IDs, report-schema version, objective, frozen configuration, approved dataset/partition/ground-truth hashes, procedure, actual environment/provider, metric definitions, raw eligible counts, uncertainty, failures/exclusions, artifact references, limitations, validation status and applicable acceptance criteria. Preserve pseudonymous raw predictions sufficient to recompute metrics, subject to privacy and deletion restrictions.

### 18.3 Specialized reports

- **Detection:** boxes, IoU, precision/recall, landmarks, difficult conditions and multi-face coverage.
- **Preprocessing:** decode/orientation/geometry, color/normalization, reference fixtures and downstream impact.
- **Embedding:** genuine/impostor distributions, verification operating points, invalid vectors, numerical stability.
- **Retrieval:** representation and identity recall@K, expansion, completeness, SQLite filtering, latency and index memory.
- **Open-set/chronological:** gallery/enrollment conditions, enrolled/unseen prevalence, estimator outcomes, actual policy actions, oracle versus predicted memory and event-level errors.
- **Calibration:** score distributions, declared targets, threshold selection, separate attachment/creation risk and final-test assessment.
- **Estimator/policy:** evidence schema, ranking/outcomes, action-specific errors, guards and deterministic baseline comparison.
- **Runtime/performance:** model export, actual provider, precision, numerical and recognition differences, cold/warm, tails, throughput, CPU/RAM/VRAM and workload conditions.
- **Recovery:** failure injection, before/after authoritative state, invariants, duplicates, leaks and time.
- **Migration:** source/target spaces, eligible and accepted observations, identity coverage, index integrity, recognition comparison, activation/rollback.

### 18.4 Reporting register

| ID | Required report validation |
|---|---|
| REPORT-01 | Standard report completeness |
| REPORT-02 | Configuration provenance |
| REPORT-03 | Dataset provenance |
| REPORT-04 | Execution environment |
| REPORT-05 | Raw prediction artifacts |
| REPORT-06 | Metric recalculation |
| REPORT-07 | Statistical reporting |
| REPORT-08 | Explicit failure reporting |
| REPORT-09 | Predeclared exclusion reporting |
| REPORT-10 | Controlled comparisons |
| REPORT-11 | Regression reporting |
| REPORT-12 | Release-gate evidence |
| REPORT-13 | Failure analysis |
| REPORT-14 | Artifact organization |
| REPORT-15 | Versioned machine-readable schema |
| REPORT-16 | Human-readable technical report |
| REPORT-17 | Result validation |
| REPORT-18 | Biometric privacy/retention |
| REPORT-19 | Independent reproduction |
| REPORT-20 | Historical report integrity |

Suggested structure: `benchmarks/specifications/`, `manifests/`, `experiments/<experiment-id>/executions/<execution-id>/{environment,measurements,predictions,failures,metrics,statistics,execution-report}`, `comparisons/`, `regression-reports/`, `approval-reports/`. This is a logical suggestion, not an approved physical implementation. Corrections to historical reports must be auditable, not silent overwrites.

## 19. Consolidated Benchmark Register

### 19.1 Registry design

Maintain separate **Benchmark**, **Experiment** and **Approval** registers. Each canonical benchmark records objective, protocol section, dependencies, datasets/fixtures, evaluated configuration, procedure, metrics/invariants, statistical requirements, required artifacts, release gates, acceptance criteria, priority, implementation status and version. Distinguish NOT_IMPLEMENTED/IN_PROGRESS/IMPLEMENTED/VALIDATED/DEPRECATED from execution and approval states.

### 19.2 Provisional inventory

| Domain | Provisional IDs | Count |
|---|---|---:|
| Ground truth | GT-01–GT-10 | 10 |
| Partitioning | SPLIT-01–SPLIT-14 | 14 |
| Experimental reproducibility | EXP-01–EXP-14 | 14 |
| Detection | DET-01–DET-11 | 11 |
| Preprocessing | PRE-01–PRE-12 | 12 |
| Embedding | EMB-01–EMB-23 | 23 |
| Retrieval | RET-01–RET-20 | 20 |
| Recognition | REC-01–REC-15 | 15 |
| Calibration | CAL-01–CAL-15 | 15 |
| Estimator/policy | IDE-01–IDE-14 | 14 |
| Runtime | RUN-01–RUN-20 | 20 |
| Performance | PERF-01–PERF-23 | 23 |
| Recovery | RECOV-01–RECOV-22 | 22 |
| Migration | MIG-01–MIG-28 | 28 |
| Reporting | REPORT-01–REPORT-20 | 20 |
| **Total** | **Provisional benchmark identifiers** | **261** |

Eight additional `GATE-01`–`GATE-08` identifiers define release gates, not benchmark executions. These counts are allocated IDs, **not completed or independently reconciled tests**.

### 19.3 Canonical reconciliation procedure

Retrieve the full earlier `ML_COMPONENTS_AND_EVALUATION.md` register and the original detailed Section 1–18 definitions. Preserve original IDs and meanings, identify exact duplicates versus related independent checks, resolve conflicting IDs, create canonical IDs with historical aliases, then update references. In particular, reconcile earlier `EMB` IDs and the exact `GT`, `SPLIT`, `EXP`, `EMB`, `RET`, `REC`, `CAL` and `IDE` per-ID descriptions before declaring the registry canonical. The reconstructed summaries in this compilation do **not** substitute for that audit.

### 19.4 Priorities and dependencies

**P0 foundational** verifies correctness/safety required by enabled V1 capabilities; **P1 release qualification** verifies production operation or a separately authorized automatic mode; **P2 future/exploratory** covers deferred capabilities and optional comparisons. Priorities inform implementation scheduling but do not override applicable release-gate requirements. Foundational evaluation flows from dataset/ground truth/splits through perception, representation, retrieval, recognition, calibration, estimator/policy and memory; runtime, recovery and reporting cut across stages.

Build benchmark infrastructure in stages: foundational contracts → integrated recognition → operational qualification → all mandatory benchmarks for the declared release. Audit requirement-to-criterion-to-benchmark-to-execution-to-validated-result-to-approval traceability. Detect registry ID collisions, broken dependencies, missing evidence, cycles and invalid gate references automatically. Preserve versioned historical snapshots.

## 20. Final Evaluation and Promotion Procedure

### 20.1 Promotion unit

Promote a complete versioned **RecognitionConfiguration**, not an isolated model. It identifies detector and export/runtime, preprocessing, embedder and export/runtime, RepresentationSpace, retrieval and aggregation, DecisionEstimator, CalibrationProfile, RecognitionPolicy and compatible application/persistence dependencies. A configuration fingerprint identifies the frozen target but does not prove compatibility.

### 20.2 Promotion lifecycle

**CANDIDATE → DEVELOPMENT_EVALUATION → CONFIGURATION_SELECTED → CONFIGURATION_FROZEN → FINAL_EVALUATION → EVIDENCE_VALIDATED → APPROVAL_REVIEW → APPROVED → DEPLOYMENT_VALIDATION → ACTIVE**. Rejected or inconclusive candidates return to an explicitly documented stage. These are proposed logical states pending reconciliation with actual implementation contracts.

### 20.3 Twelve-phase procedure

1. **Register candidate:** identify actual weights/exports, objective, dependencies, space, runtime and limitations.
2. **Establish readiness:** approve rights, ground truth, partitions, executable benchmarks, metric definitions and predeclared criteria.
3. **Run development evaluation:** compare candidates, calibrate, profile and analyze errors with full provenance.
4. **Select complete configuration:** use comparable evidence across all required components.
5. **Freeze configuration:** record exact versions, artifacts, parameters, calibration, policy and application revision; material changes create a new candidate.
6. **Run independent final evaluation:** execute all applicable benchmarks without tuning on final-test outcomes.
7. **Validate results:** check manifests, data partitions, metric calculations, uncertainty, failures, exclusions and artifact integrity.
8. **Evaluate release gates:** resolve each mandatory criterion as passed, failed or inconclusive; authorize attachment and creation separately.
9. **Review and approve:** issue a scoped, versioned approval record with actual evidence and operating-mode limits.
10. **Prepare deployment:** package only approved compatible artifacts and required recovery procedures.
11. **Validate deployment:** verify artifact hashes, active space/index, estimator, calibration, policy, actual provider and approved reference fixtures.
12. **Activate and monitor:** enable only approved capabilities, preserve provenance, validate operation and retain controlled rollback.

### 20.4 Initial V1 and upgrades

V1 first implements source/observation/representation/identity persistence, vector codec, processing history and atomic checkpoints; then perception and ML-worker integration; then USearch, revalidation, evidence, deterministic estimator and policy; then recovery, bounded scheduling and minimal UI; finally formal qualification. The first space still requires explicit activation, even without a previous production space.

A later incompatible upgrade registers an inactive target space, reprocesses eligible retained history, validates representation/identity coverage and index, recalibrates, runs recognition and chronological replay, validates runtime/recovery and explicitly activates the complete configuration. Rollback must preserve and reconcile identity mutations committed after promotion.

A future learned estimator requires eligible verified feedback, subject/time leakage controls, a frozen deterministic baseline, action-specific error comparisons, chronological replay and the same applicable release gates. Image-only approval does not authorize video, tracking or live-camera processing.

### 20.5 Promotion checklist

Before approval, confirm: approved datasets/rights; validated truth and frozen partitions; reproducible manifests; approved detector/preprocessing/embedder and space; complete retrieval; approved estimator/calibration/policy; separately authorized identity actions; approved RuntimeVariants; performance/resource qualification; persistence and recovery integrity; migration where applicable; validated final-test reports; all mandatory gate reports; approval record; deployment fixtures; and rollback procedure. Every item remains **PENDING** until backed by actual evidence.

---

## Outstanding decisions and editorial reconciliation

1. **Recover original wording:** Sections 1–14 in this compilation are faithful reconstructions from retained summaries, not verbatim copies of their earlier writing blocks. Replace with original section text if available before treating this as the archival master.
2. **Reconcile canonical IDs:** Compare all 261 provisional identifiers and exact per-ID definitions with the earlier architecture document. Preserve aliases; do not silently renumber.
3. **Verify dataset rights:** Exact licenses, acquisition, approved purposes, pretrained-data overlap and permitted retention are not established by this document.
4. **Choose actual model artifacts:** Exact detector/embedder variants, weights, exports and supported providers remain unapproved.
5. **Set acceptance criteria:** Numerical operating points, action-specific error budgets, sample sizes, statistical precision, performance/memory limits, retry budgets, backup retention and recovery targets must be approved before formal final testing.
6. **Finalize implementation contracts:** Exact FINAL checkpoint granularity, idempotency keys, migration state names, atomic activation and rollback behavior must be reconciled with persistence architecture.
7. **Scope V1 release:** Identify mandatory P0/P1 tests and explicitly approved supervised/automatic operating modes. No benchmarks are represented as executed or passed here.

**End of consolidated working draft.**
