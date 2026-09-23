# ML Components and Evaluation

**Application:** Fully local Windows Visual Identity / Face Memory  
**Status:** Proposed for locking — architecture is consolidated; model choices, thresholds, licenses, runtime compatibility, and benchmark outcomes are not yet validated.  
**Companion deliverable:** `ML_BENCHMARKS_AND_EVALUATION_PROTOCOL.md`

## Document purpose and authority

This document consolidates the 18 ML planning sections for the local visual-identity application. It defines component boundaries, candidate technologies, compatibility rules, evaluation requirements, and promotion gates. It does **not** claim benchmark results, approve model licenses, select a final detector or embedder, or establish operating thresholds.

The existing persistence contract remains authoritative for SQLite records, vector storage, USearch reconciliation, processing lifecycle, and atomic acceptance. The existing Universal Search document remains authoritative for search semantics. Where implementation exposes a genuine conflict, update the affected documents together rather than silently reinterpreting either one.

### Status vocabulary

| Label | Meaning |
|---|---|
| Locked | Already established by the project architecture; implementation must preserve it. |
| Proposed for locking | Recommended architecture, awaiting explicit project lock. |
| Provisional | A direction or candidate requiring validation. |
| Deferred | Work intentionally assigned to the benchmark protocol or a later milestone. |

---

# 1. Purpose, scope, and evaluation principles

## 1.1 Objective

The application builds durable local visual memory from imported images, and later video/camera inputs. ML is a supporting pipeline: it detects faces, produces compatible embeddings, retrieves candidates, constructs evidence, and estimates recognition outcomes. It never replaces identity lifecycle, persistence authority, or user correction.

The initial deliverable is an image-to-memory vertical slice. Video tracking, camera-specific temporal evidence, learned decision models, automatic merges, and online/cloud inference are not prerequisites.

## 1.2 Principles

1. **Evaluate the pipeline, not just models.** Strong published detector or embedding scores do not prove safe local recognition after alignment, retrieval, aggregation, policy, and persistence.
2. **Separate candidate generation from identity truth.** ANN similarity is a retrieval signal; it is neither a confirmed identity nor universal relevance.
3. **Treat uncertainty as a result.** `UNKNOWN`, `AMBIGUOUS`, and `ABSTAIN` are valid safety outcomes.
4. **Keep authority one-way.** Evidence → estimate → policy → Identity Manager. Only the Identity Manager performs consequential writes.
5. **Preserve reproducibility.** Every durable decision identifies its representation space, components, runtime, retrieval configuration, estimator, calibration, and policy.
6. **Use empirical gates.** Selection, compatibility, calibration, performance, and automatic-action thresholds are evaluation outputs, never guessed defaults.

## 1.3 Scope boundary

The first ML implementation uses local model artifacts and an ONNX Runtime-based worker. It does not require cloud providers, first-run downloads, a global roster classifier, or Laya. The Identity Decision Engine borrows the useful retrieve-then-decide principle from the Laya analysis but does not adopt a language model for serialized numerical evidence.

---

# 2. ML pipeline and decision-engine boundaries

**Status:** Proposed for locking.

## 2.1 Pipeline

```text
Source / ephemeral query
        │
        ▼
decode → face detection → landmarks → alignment → quality assessment
        │
        ▼
embedding generation → representation validation → compatible ANN retrieval
        │                                             │
        └────────────────────── SQLite revalidation ──┘
                              │
                              ▼
              identity-level candidate aggregation
                              │
                              ▼
             EvidenceBuilder → DecisionEstimator → RecognitionPolicy
                                                      │
                                                      ▼
                                               Identity Manager
                                                      │
                                                      ▼
                                         authoritative SQLite memory
```

## 2.2 Responsibilities

| Component | Does | Must not do |
|---|---|---|
| Perception | Detects, aligns, assesses, and embeds faces | Choose or mutate an identity |
| Retrieval | Produces a bounded compatible candidate shortlist | Treat nearest neighbor as a match |
| EvidenceBuilder | Validates and versions factual candidate evidence | Fabricate missing values or authorize action |
| DecisionEstimator | Returns a numerical/deterministic assessment | Create, merge, or attach identities |
| RecognitionPolicy | Maps an estimate and safeguards to permitted actions | Train/recalibrate silently |
| Identity Manager | Revalidates authoritative state and writes lifecycle changes | Accept model output as a direct command |

## 2.3 Decision semantics

The estimator must distinguish: a supported existing candidate (`MATCH`); no adequately supported retrieved candidate (`UNKNOWN`); several competing plausible candidates (`AMBIGUOUS`); and unusable or unsupported evidence (`ABSTAIN`). `UNKNOWN` is not permission to create an identity. A failed ANN query, incomplete migration, invalid vector, or unsupported runtime is not evidence that a person is unseen.

## 2.4 Evolution

V1 uses a transparent deterministic estimator behind a stable interface. It may later be compared with regularized numerical models and then, only if justified, a small joint-candidate model. Any replacement consumes the same versioned evidence contract and produces the same result contract.

---

# 3. Evaluation dataset design and ground-truth methodology

**Status:** Proposed for locking.

## 3.1 Dataset layers

Use three explicitly separated sources of evidence:

| Layer | Purpose | Limitation |
|---|---|---|
| Public datasets | Detector/landmark and broad model comparisons | May not match the local application population or workflow |
| Application-specific evaluation set | End-to-end recognition, retrieval, policy, and operations | Requires governed collection and labeling |
| Local operational data | Later slice and drift checks | Never becomes ground truth merely because the app predicted it |

Record provenance, permitted use, licensing, retention, consent/privacy basis, annotation protocol, and exclusions before data is relied upon. Dataset availability or licensing approval is currently unvalidated.

## 3.2 Ground truth

Maintain separate labels for detection boxes/landmarks, visual identity, source/session/time, face quality, and any authoritative correction. An `Identity` can be unnamed; a `Person` name is not a recognition label. Ambiguous, uncertain, or disputed annotations must remain explicit rather than being forced into a class.

Use identity-disjoint and, where practical, recording/session-disjoint training, calibration, and final-test splits. Near-duplicate images, adjacent frames, and later corrections must not leak across splits. Features at a simulated decision time may only use information available then.

## 3.3 Required scenarios

The evaluation inventory must cover existing identities, genuinely unseen people, lookalikes/close candidates, low-quality faces, pose, occlusion, lighting and camera variation, age/time variation, uneven representation counts, missing artifacts, and corrected historical associations. Coverage gaps are findings, not values to impute.

---

# 4. Face detector candidates and benchmark protocol

**Status:** Proposed for locking. **Final detector:** pending.

## 4.1 Detector contract

The detector returns a versioned set of faces containing a bounding box, detector score, landmarks when supported, coordinate-frame information, and provenance. Detection is separate from recognition. Invalid, overlapping, out-of-bounds, or malformed outputs are rejected or recorded as structured failures before alignment.

## 4.2 Candidates

| Candidate | Role | Current status |
|---|---|---|
| SCRFD | Initial primary candidate | Provisional; must pass artifact, license, landmark, runtime, pipeline, and performance validation |
| RetinaFace | Comparison baseline | Provisional; same validation requirements |

Selection must consider recall, precision/false positives, small/occluded faces, landmark quality, downstream alignment/embedding impact, CPU/CUDA/DirectML execution, memory, latency, actual weight/export licensing, and end-to-end recognition. Framework licensing is not approval to redistribute a checkpoint.

## 4.3 Evaluation rules

Measure detector component quality and downstream effect separately. A detector with a favorable AP result may still produce landmarks or crops unsuitable for the selected embedder. Provider fallback is an independent variant to validate; a successful load is not equivalence.

---

# 5. Detector evaluation and selection

**Status:** Proposed for locking.

## 5.1 Selection procedure

Freeze candidate artifacts and preprocessing, verify usable licensing and local installation, run detector/landmark and downstream experiments, then compare complete pipeline behavior and operational cost. Select only an artifact/configuration that meets the agreed protocol; otherwise retain the system without claiming a production detector.

## 5.2 Measurements

Report detection precision/recall/AP with documented matching rules; false detections; missed faces; landmark error and alignment failure; quality-gated embedding yield; downstream identity retrieval/decision impact; latency percentiles, throughput, memory, and provider-specific failures. Evaluate hard cases and do not replace slice reports with a single aggregate.

## 5.3 Deferred detector benchmark register

The following identifiers are preserved for the companion protocol. Their procedure, datasets, acceptance criteria, and results remain deferred: `DET-01` through `DET-11`.

---

# 6. Face embedding-model candidates and benchmark protocol

**Status:** Proposed for locking. **Final embedder:** pending.

## 6.1 Contract

The embedding component accepts only a validated aligned/preprocessed face and emits a fixed-dimension vector with explicit model/export/runtime provenance. Before persistence it must pass exact dimension, finite-value, canonical-dtype, byte-order, and normalization checks. Canonical V1 storage is contiguous little-endian `float32` bytes, as required by the persistence contract.

## 6.2 Candidates

| Candidate family | Intended role | Decision status |
|---|---|---|
| Lightweight ArcFace-based model | Efficiency-oriented candidate | Provisional |
| Larger ArcFace-based model | Quality-oriented candidate | Provisional |
| AdaFace-based model | Comparative candidate, especially quality-aware behavior | Provisional |

No candidate is selected from paper rankings alone. Evaluate actual artifacts, export availability, licensing, preprocessing requirements, model size, local runtime behavior, representation compatibility, retrieval, and end-to-end recognition.

## 6.3 Levels of evaluation

1. **Pairwise verification:** characterize same/different-identity score distributions without pretending they transfer to action policy.
2. **Identity retrieval:** use exact search as an embedding/aggregation reference, then compare ANN recall.
3. **End-to-end recognition:** include detector, quality, retrieval, estimator, and policy.

Candidate aggregation must be evaluated for representation-count bias. A heavily observed identity must not win merely by generating more near-neighbor vectors.

## 6.4 Deferred embedding register

Preserved identifiers: `EMB-01` through `EMB-14`. Procedures, datasets, thresholds, and outcomes belong in the companion protocol.

---

# 7. Embedding-model evaluation and selection

**Status:** Proposed for locking.

## 7.1 Method

Validate each model's documented preprocessing first, then measure detector compatibility, embedding validity/yield, hard-negative behavior, retrieval, identity aggregation, and end-to-end outcomes. Compare candidate models on identical splits and frozen configurations. Results from one model's crop, alignment, or calibration must not be reused as if they validate another.

## 7.2 Growing-memory evaluation

Measure at increasing identity and representation counts, including uneven histories and visually similar identities. Report exact-search and ANN recall-at-K, candidate diversity, latency, memory, representation-count sensitivity, decision outcomes, and automatic-action coverage. The selected K is empirical, not a fixed architectural constant.

## 7.3 Leakage prevention

References and queries must be separated by image/session/source where possible. Chronological replay must not use future representations or later corrections. Track the library composition at every simulated query.

## 7.4 Deferred register

Preserved identifiers: `EMB-15` and `EMB-16`, in addition to the Section 6 register.

---

# 8. Preprocessing and postprocessing contracts

**Status:** Proposed for locking.

## 8.1 Perception contract

The pipeline must record image decode/orientation, detector input transform, crop/landmark coordinate transforms, alignment geometry, embedding pixel normalization, output normalization, and quality measurements. Each boundary validates its inputs and reports a structured reason for invalid image, face, landmarks, alignment, quality, or vector.

```text
decoded image → detector coordinates → original-image coordinates
             → aligned crop → model tensor → vector → canonical vector
```

Changing alignment, pixel normalization, vector normalization, dimension, or metric is a compatibility change, not an implementation detail. A packaging-only relocation is not, provided numerical behavior is demonstrated unchanged.

## 8.2 Quality and failure behavior

Quality assessment provides factual measurements and gates; it does not decide identity. Low quality may lead to `ABSTAIN` or unresolved processing. Invalid vectors are rejected before ANN search. Missing mandatory evidence must remain missing, not be converted to zero.

## 8.3 Process boundary and provenance

The persistent ML worker owns inference. FastAPI coordinates requests, durable work, and configured fallback; it does not duplicate model execution. Persistent ingestion creates run-private pending output; an ephemeral query creates temporary representations and must not persist biometric memory unless an explicit supported save operation occurs.

---

# 9. RepresentationSpace definition and compatibility

**Status:** Proposed for locking.

## 9.1 Definition

A `RepresentationSpace` is the versioned compatibility contract for embeddings. It identifies the semantic embedder, required alignment and preprocessing, dimension, canonical dtype and byte order, normalization, similarity metric, and a deterministic compatibility fingerprint. Equal vector length does not establish compatibility.

```text
ComponentVersion + alignment + preprocessing + dimension + dtype
       + normalization + metric  →  RepresentationSpace fingerprint
```

The fingerprint is canonical identification of an already-established configuration; it is not proof that independently developed models are compatible.

## 9.2 Invariants and lifecycle

- Vectors may be compared, indexed, calibrated, or retrieved together only inside one compatible space.
- A persistent representation's space never changes. Re-embedding creates a new immutable representation.
- V1 supports multiple persisted spaces but only one active space for new recognition processing.
- Operational states are `REGISTERED`, `VALIDATED`, `ACTIVE`, and `RETIRED`; they do not replace component/export/runtime records.
- Calibration and estimator support are representation-space-specific.

The persistence contract requires one USearch index per space. It holds compact `ann_key` values only; SQLite revalidates eligibility, state, identity, and space after ANN candidate generation. Unknown identities remain eligible. A corrupt/missing/mismatched index is rebuilt from active SQLite vectors.

## 9.3 Upgrade and partial migration

Register → validate → inventory reprocessable observations → generate new representations → build index → evaluate recognition → activate. Do not overwrite old vectors. An identity absent from the active space cannot be retrieved there; incomplete coverage must be reported and must never become an `UNKNOWN` claim.

## 9.4 Deferred register

Preserved identifiers: `RSP-01` RepresentationSpace compatibility; `RSP-02` cross-runtime numerical differences; `RSP-03` preprocessing compatibility; `RSP-04` cross-space score distributions; `RSP-05` index isolation; `RSP-06` model-upgrade migration.

---

# 10. Recognition experiment design

**Status:** Proposed for locking.

## 10.1 Experiment categories

| Experiment | Question |
|---|---|
| Existing identity | Is an already represented subject retrieved and handled correctly? |
| Previously unseen | Does a functioning pipeline avoid unsupported existing matches? |
| Ambiguous | Are close candidates preserved as uncertainty? |
| Insufficient evidence | Are quality/configuration/retrieval failures handled safely? |
| Growing memory | Do retrieval, decisions, and resources scale with identity history? |
| Historical corrections | Do later corrections constrain subsequent behavior and remain traceable? |

## 10.2 Evaluation modes

**Component-isolated** evaluation provides frozen validated evidence to estimators. **End-to-end** evaluation runs all stages. **Chronological replay** exposes the application to a time-ordered evolving library. Report these modes independently.

Chronological replay has two required configurations: **oracle-memory**, where references use independently verified associations and errors do not corrupt the reference library; and **predicted-memory**, where accepted app decisions evolve the library so error propagation is measurable. Predicted-memory does not replace ground truth.

## 10.3 Retrieval and policy separation

Report representation-level and identity-level retrieval separately. The estimator cannot repair a true identity omitted from top-K. At decision level, retain candidate ranking, evidence, outcome, reason, policy action, and any authoritative correction.

---

# 11. Similarity distributions, calibration, and decision thresholds

**Status:** Proposed for locking. **Thresholds:** not selected.

## 11.1 Three distinct quantities

1. **Embedding similarity** is a within-space comparison signal.
2. **Estimated probability/score** is an estimator output, if it has been calibrated and evaluated.
3. **Action authorization** is a policy decision under safety and state constraints.

None implies the next. Raw cosine similarity is not a probability. A probability is not permission to attach, create, merge, or confirm.

## 11.2 Calibration

Analyze genuine/impostor score distributions and close-candidate margins by relevant slice. Fit any calibration only on a dedicated calibration split, then report reliability diagrams, expected calibration error, Brier score, negative log-likelihood where labels permit, coverage, selective risk, and safety-critical slices. Do not fit temperatures on final test data or reuse external/Laya calibration.

Automatic existing-identity attachment and automatic new-identity creation have different failure modes and must receive separate, product-approved error budgets before their thresholds are chosen. V1 may keep both review-gated or unresolved pending evidence.

## 11.3 Deferred calibration register

Preserved identifiers: `CAL-01` through `CAL-07`. Their detailed procedure and acceptance criteria are deferred to the protocol.

---

# 12. IdentityReasoner, DecisionEstimator, and RecognitionPolicy

**Status:** Proposed for locking.

## 12.1 Internal architecture

`IdentityReasoner` coordinates evidence construction, estimation, and policy evaluation. It has no authority to mutate identity memory. The stable estimator interface is:

```text
DecisionEstimator.estimate(evidence: IdentityEvidence) -> IdentityDecisionEstimate
```

`IdentityEvidence` is versioned and contains observation/quality facts, representation-space and component provenance, requested/returned K, retrieval completeness, ordered candidate-specific similarities, explicitly missing features, and applicable correction constraints. Candidate IDs are opaque internal IDs, never display names.

## 12.2 V1 baseline

Use transparent rules over a small validated feature set: leading similarity, top-one/top-two margin, validated quality measurements, retrieval completeness, and authoritative correction constraints. Track-specific evidence is optional and unavailable to the first image-only slice. Do not introduce history-count features without measuring representation-count bias.

`IdentityDecisionEstimate` retains ranked candidates plus `UNKNOWN`, selected candidate only when supported, ambiguity/abstention reasons, raw versus calibrated values, and estimator/model/schema/calibration versions. Empty valid candidates and failed retrieval are distinct.

## 12.3 Policy

Possible policy actions are attach to an existing identity, create a new identity, preserve unresolved, request review, or block automatic action. The Identity Manager reloads authoritative state and validates lifecycle transitions before any write. Merges, irreversible actions, and unvalidated automation remain review-gated.

---

# 13. Runtime providers, model execution, and fallback validation

**Status:** Proposed for locking.

ONNX Runtime is the proposed production inference framework. CUDA is the initial preferred provider; CPU and DirectML are alternatives pending model-specific operator, numerical, operational, and performance validation. Neither the proposed provider nor hardware availability is a validated compatibility claim.

The worker loads only validated model/export/provider combinations. FastAPI selects an approved plan and records explicit fallback; it must not silently substitute a different export, precision, or representation space. Validate fallback at three levels: numerical output, retrieval behavior, and decision behavior.

Processing provenance is explicit: `ProcessingRun` identifies logical work, `Job` schedules work, and `ExecutionSegment` records what actually executed. A run can have more than one segment when a documented fallback occurs. Each segment records runtime variant, provider, artifact, component versions, resource observations, and reason for transition.

---

# 14. Performance, resource budgets, and processing throughput

**Status:** Proposed for locking. **Budgets:** to be measured.

Measure component performance (decode, detect, align, embed, ANN, SQLite revalidation), full-pipeline performance, and application behavior under concurrent UI/search/processing workloads. Report latency percentiles, throughput, queue wait, batch size, CPU/GPU and RAM/VRAM consumption, failures, cancellation latency, and recovery behavior—not only average model inference time.

V1 uses one heavy processing pipeline, bounded queues, backpressure, small validated batching, and simple resource-aware scheduling. It should optimize only after profiling shows a bottleneck. The scheduler must keep interactive search responsive; index rebuild and reconciliation remain derived background work.

Expensive artifact/ML work happens outside database transactions. Atomic acceptance is short: promote validated run-private output, create durable ANN `IndexOperation`s, and commit. USearch convergence failure leaves accepted SQLite memory valid and a recoverable degraded index; it must not retroactively corrupt the run.

---

# 15. Model compatibility, upgrade validation, and rollback

**Status:** Proposed for locking.

The hierarchy is locked: `Component → ComponentVersion → ModelExport → RuntimeVariant`, alongside `RepresentationSpace` and immutable `RecognitionCalibrationProfile`. Installation availability is separate from semantic metadata.

An upgrade passes independently: artifact compatibility, numerical compatibility, representation compatibility, recognition compatibility, and operational compatibility. Installation or successful initialization alone passes none of the later gates.

For an embedder change, retain historical vectors and decisions, create new spaces/representations through reprocessing, validate migration coverage, build a distinct index, evaluate it, and only then activate. Rollback changes active configuration; it does not rewrite history. Estimator/calibration/policy upgrades likewise produce new versioned records and retain prior decision provenance.

Do not activate a configuration with unapproved failure behavior, missing rollback path, unsupported evidence schema, or incomplete migration coverage whose recognition effect has not been evaluated. In-flight jobs preserve their snapshot/runtime provenance and do not silently switch configuration mid-segment.

---

# 16. ML testing architecture and validation boundaries

**Status:** Proposed for locking.

Separate software correctness from empirical quality. Unit/contract tests validate schemas, codecs, coordinate transforms, invariants, reason codes, policy boundary cases, and persistence transitions. Integration tests validate real artifacts/runtimes on controlled fixtures. Benchmarks establish model quality, calibration, and operating thresholds; they are not ordinary deterministic tests.

Maintain golden fixtures for input/crop/vector contracts where numerical tolerance is justified and documented. Test exact vector validation, representation-space/index isolation, SQLite revalidation after ANN results, approximate-index recovery, provider fallback provenance, temporal replay restrictions, authoritative correction constraints, atomic run acceptance, and ephemeral-query non-persistence.

Required policy cases include clear supported candidate, valid unknown, ambiguity, low quality, missing evidence, retrieval failure, unsupported space/schema, incomplete migration, explicit rejection/correction, and stale authoritative state at action time. A decision test never grants the estimator write authority.

---

# 17. ML implementation roadmap and evaluation gates

**Status:** Proposed for locking.

## 17.1 Vertical slices

| Milestone | Build | Gate before advancing |
|---|---|---|
| 0 — contracts | Evidence/result schema, reason codes, provenance, policy/manager boundary | Replayable valid, unknown, ambiguous, and abstain fixtures |
| 1 — perception | Artifact registration, detector, alignment, quality, embedder, vector validation | No partial authoritative acceptance; invalid inputs fail safely |
| 2 — memory/retrieval | RepresentationSpace, SQLite vectors, per-space USearch, revalidation | Rebuild and degraded-index recovery work; no cross-space query |
| 3 — baseline decision | Deterministic estimator and conservative policy | Decisions are persisted, explainable, and correction-aware |
| 4 — image vertical slice | Import, detect multiple faces, create/recognize unresolved identity, evidence, atomic acceptance | Recovery after interruption and index convergence are demonstrated |
| 5 — evaluation | Dataset governance, frozen protocol, model/retrieval/calibration/operations runs | Results are reported; no fabricated promotion claim |
| 6 — automation | Enable only actions supported by approved error budgets | Existing-match and new-identity gates pass independently |
| 7 — optimization/evolution | Profiling-led batching, alternate providers, learned-model comparison | Must beat baseline safely and retain rollback |

## 17.2 Automatic-action gates

Before any automatic attachment: compatible representation space, validated active model/runtime, functioning retrieval, sufficient quality, evaluated estimator/policy configuration, calibrated interpretation when used, approved attachment error budget, and auditable rollback/correction path.

Before any automatic new identity: all relevant gates plus a separately approved duplicate-creation budget and evaluation of retrieval/migration coverage. Ambiguous and abstained cases stay unresolved or request review. Merges remain review-gated.

---

# 18. Final architectural decisions, open questions, and handoff

## 18.1 Consolidated decisions

- **Locked:** SQLite is authoritative; filesystem owns artifacts; USearch is the rebuildable V1 recognition index; representations are immutable and canonical vectors are little-endian `float32`; the worker owns inference; runs/jobs/segments remain distinct; accepted output is atomic; derived indexes never define identity truth.
- **Proposed for locking:** componentized perception/retrieval/decision/policy architecture; representation-space isolation; deterministic V1 estimator; independently versioned policy; ONNX Runtime with CUDA as the initial candidate; one active recognition space; bounded pipeline/backpressure; benchmark-gated automation.
- **Provisional:** SCRFD versus RetinaFace; ArcFace-family versus AdaFace artifacts; CUDA/CPU/DirectML provider compatibility; K, aggregation, batching, queues, calibration, and all decision thresholds.
- **Deferred:** learned estimator, joint-candidate model, video tracking evidence, multi-space normal search, complex adaptive scheduling, automatic merge/irreversible action, and exact evaluation procedures/results.

## 18.2 Recognition-safety invariants

1. No cross-space vector comparison, indexing, calibration, or threshold reuse.
2. No infrastructure/configuration failure interpreted as `UNKNOWN`.
3. No estimator mutation authority or policy bypass.
4. No automatic action without its own validated gate.
5. No silent provider/export/precision incompatibility.
6. No partial authoritative acceptance after failed/interrupted processing.
7. No historical rewriting during upgrade; re-evaluation creates new history.
8. No future-information leakage in chronological evaluation.
9. No implicit persistence from an ephemeral face search.

## 18.3 Genuine reconciliation item

The persistence contract explicitly locks **USearch** as V1's rebuildable recognition candidate index. The Universal Search document mentions Qdrant as an optional derived vector backend in its broader search architecture. This document therefore uses USearch for V1 recognition and does not treat Qdrant as selected or compatible. If the project intends Qdrant to replace/add to the recognition index, that is an architecture revision requiring updates to persistence, retrieval, operations, and evaluation documents—not a silent implementation substitution.

## 18.4 Open questions

- Which exact weight/export artifacts are legally usable and distributable?
- Which validated runtime variants run correctly on target Windows hardware?
- Is independently verified representative calibration data sufficient for any automatic action?
- What migration coverage is required before activation of a new space?
- What measured resource budgets suit the supported hardware?
- Which lifecycle actions, if any, receive product-approved error budgets?

## 18.5 Handoff: `ML_BENCHMARKS_AND_EVALUATION_PROTOCOL.md`

The next document must turn deferred requirements into reproducible experiments, not repeat architecture. It should cover governance; data provenance/privacy/licensing; annotation and leakage controls; reproducible configurations; detector/landmark, preprocessing, embedding, retrieval/aggregation, open-set and chronological replay, calibration, estimator/policy, provider/numerical, performance, recovery, upgrade/migration, acceptance gates, result templates, the consolidated benchmark register, and promotion/rollback procedure.

Every benchmark must move through explicit states: specified → implemented → executed → passed/failed. Specification is not execution; execution is not promotion.

## 18.6 Deferred benchmark traceability

| Register | Preserved IDs | Status |
|---|---|---|
| Detector | `DET-01`–`DET-11` | Deferred to protocol |
| Embedding | `EMB-01`–`EMB-16` | Deferred to protocol |
| Representation space | `RSP-01`–`RSP-06` | Deferred to protocol |
| Calibration | `CAL-01`–`CAL-07` | Deferred to protocol |

For every identifier, the protocol must record configuration/version references, dataset/split, ground truth, procedure, measurements, predeclared acceptance criterion, result artifact, reviewer/promotion decision, and rollback implications. No identifier currently has a documented passing result in this document.

