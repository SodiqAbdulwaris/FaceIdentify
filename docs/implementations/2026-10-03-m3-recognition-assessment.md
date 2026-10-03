# M3: the recognition assessment and the identity reasoner (step 9; TST-041, TST-042 first half)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 · TST-041, TST-042 (in progress)
- **Status:** partial: the assessment and the proposal are done and commit nothing. Applying a proposal (Identity Manager, Evidence, Occurrences, the PENDING identity) is step 10 and 11.
- **Commits:** PR (this branch): `feat(recognition): assess candidates and propose a decision`

## What changed
- `backend/app/recognition/assessment.py`: `RecognitionService(k).assess(...)` retrieves (step 8, both pools, revalidated) and returns a `RecognitionAssessment`; `assess(retrieval, quality)` is the pure half. The assessment groups candidates, ranks the groups and records what the shortlist is:
  - one group per **identity**, scored by its **best** similarity (an identity with many representations is not favoured by their number: no history-count feature before representation-count bias is measured, ML spec 12.2); a candidate **without an identity** (an accepted `ABSTAIN` representation, a pending one the run left unresolved) is its own group and is never a match target (Persistence 6.2);
  - `margin` (best minus next group), `requested_k`, `returned`, `dropped`, and `complete` (nothing stale was dropped; a dropped candidate may have hidden one beyond the cut);
  - `interpretation = COSINE_UNCALIBRATED`: no calibration profile exists for the reference models, so nothing claims a calibrated probability; a later calibration is a new interpretation value.
- `backend/app/recognition/reasoner.py`: `IdentityReasoner(policy).decide(assessment) -> RecognitionDecision`, three outcomes (`MATCH_EXISTING`, `CREATE_NEW`, `ABSTAIN`) with a reason. The rules, in order:
  1. below the quality gate: `ABSTAIN` `LOW_QUALITY` (it must neither match nor create);
  2. a shortlist that lost candidates: `ABSTAIN` `RETRIEVAL_INCOMPLETE` (no automatic match or new identity on a possibly missing neighbour);
  3. nothing retrieved: `CREATE_NEW` `NO_CANDIDATE` (a valid unknown);
  4. best group at or above `match_threshold`: without the `margin` over the next group `ABSTAIN` `AMBIGUOUS_CANDIDATES`; with no identity `ABSTAIN` `UNRESOLVED_NEIGHBOUR`; otherwise `MATCH_EXISTING` its identity (a run's own PENDING identity matches like any, which is how the same new person is recognised again within the run);
  5. below `new_identity_ceiling`: `CREATE_NEW` `NOT_SIMILAR`;
  6. in between: `ABSTAIN` `UNCERTAIN_SIMILARITY`: an abstention is never a low-confidence `CREATE_NEW` (Roadmap phase 6).
- `DecisionPolicy` (version, `min_detection_score`, `match_threshold`, `margin`, `new_identity_ceiling`) has **no defaults** and ships none, and is validated (`-1 <= ceiling <= match <= 1`, margin 0 to 2, gate 0 to 1, NaN refused).
- `RecognitionDecision.evidence_payload()`: the JSON payload an Evidence row keeps (schema version, outcome, reason, identity, assessment version and interpretation, space, quality, retrieval counts, every candidate group with rank, identity, representation ids, pools and similarity, the margin, the policy version and thresholds), per the owner's decision that the candidate evidence (top candidates, scores, decision-engine version, thresholds) is kept.

## Decisions (the agent's, for the owner to confirm)
- **Thresholds are configuration with no default.** Policy thresholds "must be supported by recorded evaluation evidence" (Decision Engine Plan 3) and the reference models are not benchmarked in M3 (TST-044 is after it), so inventing numbers here would be inventing a claim. A run supplies the values it was configured with (the processing snapshot, step 10), and the decision records them. The first-slice end-to-end test passes explicit values chosen for the generated models. **A real default needs TST-044's evaluation**; until then a run with no configured policy must refuse to start rather than guess.
- Retrieval is "complete" only when nothing was dropped (conservative: it abstains more, never matches on a possibly short list).
- The quality gate is the detector's score only for now (`ObservationQuality`); other measurements are additive later.
- Similarity is the cosine similarity as returned; the margin is a difference of similarities.

## Verification
- `tests/unit/test_recognition_reasoner.py` (37) and `tests/integration/test_recognition_service.py` (6, real indexes and SQLite), 100% coverage of `assessment.py` and `reasoner.py`: grouping (identity, best similarity, unresolved candidates alone, equal-similarity order), the counts, the margin; every rule above with its boundary (exact binary similarities: at the threshold, exactly the margin, at the ceiling); the quality gate before the retrieval check; coherent policies only; the evidence payload (plain JSON, candidates, thresholds, dropped); property tests with Hypothesis: no input produces a match to anything but the top group's identity at or above the threshold with the margin, no `CREATE_NEW` unless the best group is below the ceiling, no automatic outcome on an incomplete shortlist or a poor face, and assessing is deterministic with groups best first; end to end: an empty memory is a valid unknown, a known face matches, the same new person twice in a run is matched through the run-local pool, a stale neighbour makes the assessment incomplete and the reasoner abstain, the service never mixes spaces and is read-only.
- Mutation pass: 42 mutations (every rule, boundary, the grouping and ranking, the counts, the payload fields, the policy validation); the first run had four survivors (the margin and ceiling boundaries, the dropped count in the payload, one no-match), which led to the exact-binary boundary tests; none survive.
- Full gate: see the PR.

## Open issues / follow-ups
- Step 10 applies the proposal: the Identity Manager revalidates it, creates the PENDING identity for `CREATE_NEW`, links `MATCH_EXISTING` to its identity, leaves `ABSTAIN` unresolved, and writes the Evidence with `evidence_payload()`.
- The configured `DecisionPolicy` and `k` come from the processing configuration snapshot (step 10).
