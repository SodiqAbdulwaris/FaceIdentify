# Identity Decision Engine Plan

**Status:** Architecture decision record and implementation plan  
**Scope:** Fully local Windows face-memory application  
**Decision owner:** Product and architecture team  
**Source context:** `Laya_ARCHITECTURE_ANALYSIS.md`

## 1. Decision at a glance

### Locked decisions

1. We will **not** build, adopt, or fine-tune Laya as a separate prerequisite before continuing the application.
2. We will design a **replaceable, Laya-inspired numerical decision engine inside the application**.
3. The first production-capable version will use **deterministic rules**, not a neural model.
4. The **Identity Manager is authoritative** for identity lifecycle, user-visible state, persistence, and consequential mutations. A decision engine estimates evidence; it does not create, merge, confirm, or delete identities directly.
5. The engine must support a runtime-varying shortlist of candidate identities, explicit `UNKNOWN`, ambiguity, and abstention.
6. Any probability used by policy must be calibrated and evaluated on held-out data from this application. A raw model confidence is not an authorization signal.

### Proposals to validate

- Use a versioned numerical evidence schema and a stable `DecisionEstimator` interface from the first deterministic baseline.
- Compare a lightweight supervised tabular model with the deterministic baseline before considering a neural model.
- If a neural model is justified, use a small per-candidate model with shallow cross-candidate attention, an `UNKNOWN` pseudo-candidate, and a shared scorer. Treat a roughly 1-3M parameter model as an initial design hypothesis, not a requirement.
- Fit calibration separately by decision type and candidate-count bucket when the evaluation data supports doing so.

### Unresolved details

- The final feature list, retrieval `K`, decision thresholds, policy outcomes, and retention/privacy rules.
- The volume and labeling process required before model training.
- Whether an MLP/gradient-boosted baseline is already sufficient, making cross-candidate attention unnecessary.
- Whether any automatic identity assignment is acceptable, and under what measured error budget.

## 2. Context and rationale

Laya is a text-oriented, bidirectional decision model. Its useful architectural pattern is to jointly score a variable set of candidates and return a probability distribution rather than a single opaque label. Those ideas fit a face-memory application whose identity roster changes over time.

Its implementation is not a good production dependency for this problem. Laya turns structured state into JSON text and tokenizes it; it has no native numerical feature-vector input. Our strongest evidence is already numerical or structured: face embeddings, retrieval similarities, face-quality signals, track continuity, observation history, candidate margins, corrections, and cluster statistics. A large language encoder adds a modality mismatch, runtime cost, and a new training burden without demonstrated transfer value.

The source analysis also found that Laya's calibration is post-hoc temperature scaling and can be wrong outside the distribution on which it was fitted. The analysis documents a shipped temperature that sharply increased confidence and notes a failure mode where high confidence did not track accuracy on unsupported input. Therefore, neither Laya's confidence nor any future local model's raw score may be treated as a guarantee.

The application should instead retain the transferable principles:

- dynamic shortlist-to-decision processing;
- joint comparison of competing candidates;
- explicit `UNKNOWN` rather than forced assignment;
- calibrated probability estimates evaluated on our data; and
- deterministic policy and auditable identity lifecycle actions outside the model.

## 3. Alternatives considered

| Alternative | Decision | Why |
|---|---|---|
| Use Laya directly | Rejected as the default | It accepts numerical evidence only as text, has no evidence of reliable zero-shot performance on this domain, and requires domain-specific calibration before its confidence is usable. |
| Fine-tune Laya first | Rejected as a prerequisite | The shipped training path is full fine-tuning shaped for two T4 GPUs, has no supplied LoRA/PEFT path, and retains the numeric-as-text mismatch. It would delay the application before we have the real evidence and labels needed to judge its value. |
| Borrow Laya's architecture ideas | Accepted | Dynamic candidate scoring, joint comparison, proper scoring objectives, and post-hoc calibration are portable ideas. |
| Build a small local numerical model immediately | Deferred | It may be valuable, but must first beat a deterministic baseline and a lightweight supervised comparison on measured safety and calibration outcomes. |
| Deterministic baseline behind a stable interface | Accepted | It enables the application, establishes measurable performance, and creates labeled evidence for later model selection. |

## 4. Target architecture and authority boundaries

```text
Face input
  -> Detection and quality assessment
  -> Tracking and temporal aggregation
  -> Embedding generation
  -> Candidate retrieval (dynamic top-K)
  -> Evidence builder and schema validation
  -> Decision estimator
       returns ranked candidates, UNKNOWN, ambiguity, abstention, calibration metadata
  -> Policy engine
       applies thresholds, safeguards, and user-review rules
  -> Identity Manager
       performs authorized lifecycle changes and writes durable events
  -> Persistence and audit history
```

### Evidence generation

**Responsibility:** Produce factual, timestamped observations and candidate-specific measurements. Examples include face quality, embedding similarity, top-one/top-two margin, track consistency, source/camera context, observation counts, prior confirmations, and relevant correction history.

**Must not:** Choose an identity, modify lifecycle state, or hide missing/invalid measurements behind a fabricated default.

### Decision estimator

**Responsibility:** Consume validated evidence for a dynamic top-`K` candidate set plus `UNKNOWN`. Estimate candidate probabilities or deterministic scores, identify ambiguity, and indicate whether it abstains.

**Must not:** Mutate identity records, bypass policy, interpret a probability as permission, or depend on an unversioned feature layout.

### Policy engine

**Responsibility:** Apply deterministic, reviewable rules to an estimate. It maps a result to actions such as attach an observation, keep it unresolved, request review, create a potential-match record, or block automation.

**Must not:** Retrain or silently recalibrate a model during an identity decision. Policy thresholds are configuration and must be supported by recorded evaluation evidence.

### Identity Manager

**Responsibility:** Own identity lifecycle and persistence. It validates permitted transitions, performs writes, records provenance, and preserves auditability.

**Must not:** Treat model output as a direct command. High-confidence merge, confirmation, or deletion recommendations require explicit policy authorization; merge and irreversible operations should remain review-gated unless a future, separately approved policy changes that rule.

## 5. Stable contracts from the baseline onward

The engine must be replaceable without changing retrieval, identity lifecycle, or persistence code. Version both the input evidence and the decision result.

### 5.1 Versioned evidence envelope

```json
{
  "schema_version": "1.0",
  "observation_id": "uuid",
  "observed_at": "ISO-8601 timestamp",
  "source": {"camera_id": "local-camera-1"},
  "observation": {
    "face_quality": 0.91,
    "track_consistency": 0.76,
    "track_observation_count": 14
  },
  "retrieval": {
    "requested_k": 8,
    "returned_k": 3,
    "retriever_version": "...",
    "true_match_in_top_k": null
  },
  "candidates": [
    {
      "identity_id": "uuid",
      "rank": 1,
      "embedding_similarity": 0.83,
      "identity_observation_count": 47,
      "history": {"prior_rejections": 0, "manual_override": false}
    }
  ],
  "missing_features": [],
  "provenance": {"detector_version": "...", "embedder_version": "..."}
}
```

Rules for this contract:

- `schema_version` changes only for intentional compatibility changes. Additive fields are optional until a new version makes them required.
- Candidate order is explicit and stable for the one decision; identity identifiers are opaque internal IDs, never display names.
- Absence, invalidity, and unavailable evidence are represented explicitly. The estimator or policy must abstain when required features are missing.
- Persist the input schema version, estimator version, calibration version, policy version, and result with each decision event. This enables replay and regression investigation.
- Do not place biometric templates or raw face images in the decision envelope unless separately justified by the application privacy design. The decision layer should receive derived, minimally necessary evidence.

### 5.2 Stable estimator interface

```text
DecisionEstimator.estimate(evidence: IdentityEvidence) -> IdentityDecisionEstimate
```

An estimate should contain:

- a ranked distribution over returned candidate IDs plus `UNKNOWN`;
- `top_candidate_id` only when a candidate is selected by the estimator;
- `ambiguity` metadata, including the leading-candidate margin and a reason code;
- an `abstain` flag and reason code for unsupported schema, failed retrieval, insufficient quality, missing required evidence, or out-of-distribution conditions;
- raw score/probability and calibrated probability as distinct fields;
- estimator, model, feature-schema, and calibration versions;
- diagnostics safe to persist for audit and evaluation.

The interface deliberately does not include commands such as `merge_identity`, `confirm_identity`, or `write_identity`.

## 6. Decision behavior

### Dynamic top-K

Candidate retrieval limits the decision space from the full identity store to a runtime top-`K`. `K` is a retrieval/policy parameter, not a fixed classifier output dimension. The result must record the requested and returned candidate counts.

Retrieval recall is a hard precondition: the estimator cannot select a true identity that retrieval omitted. Evaluation must therefore report both retrieval recall-at-`K` and downstream decision metrics. A high decision score does not compensate for a low-recall shortlist.

### UNKNOWN, ambiguity, and abstention

- **`UNKNOWN`:** a first-class candidate meaning none of the retrieved identities is sufficiently supported. It prevents forced assignment.
- **Ambiguous:** evidence supports more than one candidate too similarly for policy to act automatically. This is a decision state/reason, not a hidden tie-breaker.
- **Abstain:** the estimator declines to make a usable comparison because the evidence is insufficient, malformed, unavailable, or outside its validated operating conditions.

`UNKNOWN`, ambiguous, and abstained results must be preserved as valid outcomes in persistence and review workflows. They are safety mechanisms, not errors to be optimized away.

### False-identification safeguards

1. No automatic match may occur unless the true-match candidate is available in the evaluated top-`K` operating range.
2. Require both an accepted calibrated probability and a minimum separation from the second candidate; a high top score with a small margin is ambiguous.
3. Enforce quality and track-consistency gates before automatic action.
4. Honor explicit prior corrections or rejections as policy constraints; they cannot be silently overwhelmed by similarity alone.
5. Use conservative default behavior: unresolved/review rather than a potentially false identity attachment.
6. Keep merges, confirmations, and other high-impact lifecycle changes review-gated by default.
7. Log the full decision provenance so any automated attachment can be traced, reviewed, and reversed according to the application's event/identity design.

## 7. Phased implementation plan

### Phase 0: define contracts and guardrails

Define the evidence schema, estimator result schema, reason codes, persisted decision event, and policy boundary before model work. Add schema validation and replay fixtures based on representative valid, ambiguous, `UNKNOWN`, and abstained evidence.

**Exit criteria:** retrieval, policy, and Identity Manager can integrate against the stable contract without knowing whether the estimator is deterministic or learned.

### Phase 1: build the evidence foundation

Implement or complete face detection, quality signals, tracking, embedding generation, candidate retrieval, identity persistence, and authoritative lifecycle management. Record observation evidence and subsequent user feedback with sufficient provenance for offline evaluation.

**Exit criteria:** a local observation can produce a versioned evidence envelope and a top-`K` shortlist; decisions and subsequent corrections are durably traceable.

### Phase 2: deterministic decision baseline

Implement the first `DecisionEstimator` with transparent rules using features such as similarity, top-one/top-two margin, face quality, track consistency, observation count, and correction history. It must emit candidate ranking, `UNKNOWN`, ambiguity, and abstention through the stable interface.

The purpose is a measurable safety baseline, not a temporary shortcut to discard without evaluation.

**Exit criteria:** replayable benchmark set, baseline metrics, documented policy thresholds, and explicit review behavior for uncertain cases.

### Phase 3: collect labeled evidence and evaluate

Collect labels from confirmed observations, explicit corrections, rejections, and carefully reviewed uncertain cases. Preserve temporal ordering so training features never include information unavailable at decision time. Split data by identity and recording/session where practical to avoid leakage from near-duplicate faces.

**Exit criteria:** a versioned dataset with coverage reports for hard negatives, lookalikes, low-quality images, occlusion, lighting variation, camera changes, time/age variation, conflicted candidates, and corrections.

### Phase 4: lightweight supervised comparison

Train and compare simple numerical models such as regularized logistic regression and/or gradient-boosted trees against the deterministic baseline. They must consume the same evidence contract and return the same result format. Calibrate each candidate model on a dedicated calibration split, not the training set.

**Exit criteria:** a candidate model demonstrates a pre-agreed, statistically credible improvement over the baseline on false-identification safeguards, calibration, and operational latency; otherwise retain the baseline.

### Phase 5: small joint-candidate model only if justified

If simple models cannot adequately use relative candidate evidence, test a small set model: normalized per-candidate numerical feature rows, a shallow cross-candidate attention layer or equivalent set interaction, a shared scorer, and an `UNKNOWN` pseudo-row. Use ordinary supervised optimization with proper scoring objectives where beneficial; do not reproduce Laya's RL/GRPO machinery merely for resemblance.

**Exit criteria:** it outperforms both prior approaches under the same held-out protocol, meets local Windows runtime/resource targets, and can be versioned and rolled back through the stable interface.

## 8. Calibration and evaluation protocol

Calibration is a separate deliverable, not a checkbox implied by use of a probability-producing model.

### Required measurements

| Area | Required measurement |
|---|---|
| Retrieval | Recall-at-`K`, including the rate at which the eventual true identity is absent from the shortlist |
| Identity safety | False-identification rate, false-rejection rate, and error rate among automatic actions |
| Uncertainty | `UNKNOWN` accuracy/appropriateness, ambiguity detection, and abstention rate with reason breakdown |
| Probability quality | Reliability diagrams, expected calibration error, Brier score, and negative log-likelihood where labels support them |
| Coverage | Results by face quality, camera/source, lighting, occlusion, time variation, candidate-count bucket, and correction history |
| Operations | Local CPU/GPU latency, memory use, throughput, failure behavior, and replayability |

### Evaluation rules

- Keep training, calibration, and final test data separate. Do not fit temperatures on the final test set or reuse Laya temperatures.
- Report results by candidate-count bucket because candidate competition changes probability behavior.
- Treat aggregate calibration metrics as incomplete. Inspect safety-critical slices, especially close lookalikes and low-quality observations.
- Select automatic-action thresholds from measured error budgets, not an arbitrary confidence value such as `0.90`.
- Compare models against the deterministic baseline on the same frozen test protocol. A more accurate model that increases false identity attachments is not an acceptable replacement.
- Evaluate correction loops for feedback contamination: a prior incorrect automatic attachment must not become unreviewed ground truth for future training.

## 9. Acceptance criteria

The following are required before a learned estimator may influence automatic policy:

1. Evidence and result schemas are versioned, validated, persisted, and replayable.
2. The Identity Manager remains the only component able to make lifecycle writes.
3. `UNKNOWN`, ambiguity, and abstention are represented end-to-end and have safe policy outcomes.
4. A deterministic baseline exists with documented metrics on a held-out evaluation set.
5. Retrieval recall-at-`K` is measured and reported alongside estimator metrics.
6. The learned candidate is compared with the baseline under identical splits and has a documented rollback path.
7. Calibration is fitted on a dedicated held-out calibration set and verified with reliability and slice-level reporting.
8. Automatic-action thresholds meet a product-approved false-identification budget; high-impact actions remain review-gated unless separately approved.
9. The local Windows build meets agreed latency, memory, offline, and persistence requirements without introducing mandatory online inference or first-run model downloads.
10. Every decision event includes enough provenance to reconstruct which evidence, estimator, calibration, and policy produced it.

## 10. Open questions and decision gates

| Question | Why it matters | Gate |
|---|---|---|
| Which evidence fields are reliable enough to require in v1? | Defines schema quality and abstention behavior | Resolve before Phase 2 |
| What top-`K` range meets retrieval recall and runtime needs? | Bounds the estimator's operating regime | Measure in Phase 1/2 |
| Which lifecycle actions, if any, may be automatic? | Determines safety thresholds and review design | Product/policy decision before enabling automation |
| How are labels produced and reviewed? | Determines whether training targets are trustworthy | Resolve before Phase 3 dataset freeze |
| What privacy, retention, and consent requirements govern stored evidence and feedback? | Evidence logging is essential but biometric data is sensitive | Resolve with the application data design before persistence is finalized |
| Is a simple supervised model enough? | Avoids unnecessary neural-model complexity | Decide after Phase 4 comparison |
| Does a joint model materially reduce unsafe close-candidate decisions? | Justifies Phase 5 complexity | Decide only with held-out evidence |

## 11. How to fold this into existing planning documents

Apply the following targeted updates rather than creating a parallel identity architecture:

1. **System architecture document:** add the evidence builder, `DecisionEstimator`, policy engine, and Identity Manager as separate components; document the one-way authority flow from evidence to estimate to policy to identity mutation.
2. **Identity/domain model document:** define `UNKNOWN`, ambiguity, abstention, candidate retrieval result, decision event provenance, and review-required states. Keep lifecycle states such as confirmed or merged separate from a model classification result.
3. **Data/persistence plan:** add versioned evidence envelopes, estimator/calibration/policy versions, immutable decision events, feedback/correction links, and retention/privacy requirements.
4. **Face pipeline plan:** make top-`K` retrieval and retrieval recall explicit deliverables. The decision engine begins after detection, tracking, embedding, and retrieval; it does not replace those stages.
5. **ML/evaluation plan:** make the deterministic baseline Phase 1 of decision intelligence; add dataset governance, leakage controls, calibration, slice evaluation, false-identification budgets, and promotion/rollback criteria.
6. **Roadmap:** sequence work as foundation and baseline first, labeled feedback second, lightweight comparison third, and a small joint-candidate model only after evidence demonstrates a need.
7. **Risk register:** add unsafe automated attachment, retrieval omission, calibration drift, correction feedback contamination, schema incompatibility, and local resource pressure with their respective mitigations in this plan.

## 12. Deferred work

The following are explicitly out of scope until later evidence justifies them:

- Bundling, running, or fine-tuning Laya in the application.
- A large language encoder for JSON-serialized numerical evidence.
- Laya's RL/GRPO-style training loop.
- A fixed global identity classifier that must be retrained for every roster change.
- Automatic identity merges or other irreversible lifecycle actions based solely on a model probability.
- Any claimed calibrated confidence before the application's own held-out evaluation supports it.

## 13. Traceability to the Laya analysis

This plan intentionally carries forward the source analysis findings that Laya jointly evaluates dynamically supplied options, but it does not copy its modality or training apparatus. The design preserves the valuable retrieve-then-rerank and dynamic-candidate principles while avoiding its text-only numerical representation, large candidate token-budget limitation, and unverified calibration transfer. The source analysis should remain attached to the ML research record; this document is the application architecture decision and delivery plan.
