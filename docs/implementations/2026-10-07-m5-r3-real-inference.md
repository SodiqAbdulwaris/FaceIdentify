# M5 R3: the real models through the production client, and the evaluation tools

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, R3 and the tools for R4; TST-038, TST-039 (real path, CPU), TST-044 (tools only)
- **Status:** partial: CPU inference is proven; CUDA and the measured policy are not yet
- **Commits:** PR to be recorded when merged

## What changed

- `tests/e2e/test_real_models.py` (marker `e2e`, never in the default run or CI, because the weights are
  local files): installs nothing itself; it expects the package installed by
  `scripts/install_reference_models.py` and pictures in `local-models/images`, runs the production
  `PerceptionClient` over the supervised real worker, and checks that faces are found, vectors are
  finite unit 512-d vectors, the provider used is the requested one (no silent fallback), and the same
  person scores above different people. `FACEIDENTIFY_PROVIDER` selects the provider.
- `evaluation/build_commons_dataset.py`: builds an identity-labelled evaluation set from Wikimedia
  Commons photographs, checking each file's licence in Commons' metadata and keeping only public
  domain ones (US government works and similar); the label is the person's Commons category. It
  waits and retries on "too many requests". The photographs are biometric data: `evaluation/datasets/`
  is Git-ignored and nothing is committed.
- `evaluation/measure_operating_point.py`: an open-set, leave-one-out measurement. People are split
  70/30 (by hash of the name) into known and unknown; each photograph's subject is its only face or a
  face 2.5 times larger than any other (group photographs have no subject and are skipped); an
  identity scores as its best-matching photograph. It sweeps the match threshold and the margin,
  reports precision and recall with a Wilson lower bound, picks the highest-recall point that reaches
  99% precision (the owner's rule, 2026-10-07), and finds the new-identity ceiling. It caches
  embeddings next to the dataset, keyed by the weights digest.
- Tracker: TST-038/039 `IN_PROGRESS` with the evidence above.

## Why

M5 plan R3 and R4. The owner's rule: choose the measured operating point that reaches at least 99%
precision for automatic identity acceptance on the evaluation set, subject to a minimum useful recall,
and prefer ABSTAIN when that confidence cannot be achieved.

## Decisions

> **Decision 2026-10-07:** Owner (answering the R-item questions): the evaluation data may be a public
> benchmark and "free to use" faces; the agent chose public-domain Commons photographs because their
> licence is verifiable per file (the LFW host was unreachable and its terms could not be checked).

> **Decision 2026-10-07:** Owner: a calibrated policy means thresholds measured at the 99% rule and
> frozen in the snapshot as before; the mode stays `UNCALIBRATED` (scores are raw cosine, never
> probabilities) and the UI notice is reworded to say what was measured and its limits. No new
> `CALIBRATED` mode is built.

- Label noise: a Commons category holds photographs that show the person among others, so some
  "same person" pairs are not (the genuine pairs' low percentiles near zero show it). Noise makes
  recall look worse; it cannot make precision look better, because a wrongly labelled correct match
  is counted as an error. The limit is recorded with the result.

## Verification

- The e2e test passes on CPU on this machine (real weights, four public-domain photographs).
- The measurement runs end to end; its numbers on the small first set are not used for a policy.
- Full gate: see the PR.

## Open issues / follow-ups

- CUDA on the RTX 4070 (the GPU runtime libraries are still downloading) and CPU/CUDA agreement.
- The measured policy, its reworded notice, and the real host wiring come after the bigger
  evaluation set is measured (R4).
