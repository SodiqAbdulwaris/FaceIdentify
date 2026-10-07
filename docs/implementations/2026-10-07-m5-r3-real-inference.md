# M5 R3: the real models through the production client, and the evaluation tools

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, R3 and the tools for R4; TST-038, TST-039 (real path, CPU), TST-044 (tools only)
- **Status:** partial: CPU inference runs; CUDA and the measured policy are not done
- **Commits:** PR to be recorded when merged

## What changed

- `tests/e2e/test_real_models.py` (marker `e2e`, never in the default run or CI, because the weights
  are local files). It is a **real-worker integration smoke test**, not an application workflow: it
  bypasses the catalog, the host, the scheduler, persistence, retrieval and the decision policy. It
  runs the production `PerceptionClient` over the supervised real worker and checks that faces are
  found, vectors are finite unit 512-d vectors, detection and embedding both ran on the requested
  provider (no silent fallback), and the same person scores above different people.
  `FACEIDENTIFY_PROVIDER` selects the provider.
- `evaluation/build_commons_dataset.py`: builds an identity-labelled set from Wikimedia Commons
  photographs. It keeps only an allow-listed public-domain status (`Public domain`, `PD-USGov*`) read
  from each file's own metadata, and records per photograph the exact licence name and URL, usage
  terms, author, credit, source page, acquisition time and the SHA-256 of the bytes. It refuses an
  `--out` outside `evaluation/datasets/` (Git-ignored: the photographs are biometric data) and waits
  and retries on "too many requests".
- `evaluation/measure_operating_point.py`: a subject-disjoint, open-set, leave-one-out measurement
  (the protocol is in its docstring). People are split by hash into a **selection** half and a
  **final** half that share nobody; the operating point is chosen on the selection half only, from
  the scores actually observed, under the owner's rule (precision at least 0.99) with predeclared
  minimums (`--minimum-accepted` 30, `--minimum-recall` 0.5, `--minimum-below` 20); the chosen point
  is then reported on the final half with Wilson 95% intervals. A person needs two usable photographs;
  queries without two competing known identities are set aside and counted. The report records the
  configuration, the environment (weights digest, library versions), the exclusions and the hash of
  the dataset manifest.
- Tracker: TST-038/039 `IN_PROGRESS`. The testing guide lists the new local commands.

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

- "Minimum useful recall" had no number from the owner: the agent predeclared 0.5 (`--minimum-recall`)
  and flags it for the owner to change.
- Identity labels are Commons categories, not verified. A mislabelled photograph can push the result
  either way, so the residual label uncertainty is non-directional; it is reported as a limit, not
  claimed away.
- The Wilson interval is reported on the final half; the 99% target is a rule for choosing a point,
  not a claim that the interval's lower end reaches 99%. With a set this small it will not.

## Verification

- `uv run pytest -m e2e tests/e2e/test_real_models.py`: 1 passed on CPU on this machine (real
  weights, four public-domain photographs).
- `uv run ruff format --check . && uv run ruff check .`: clean; `uv run mypy`: clean; unit and
  contract tests pass.
- The measurement ran end to end on the first small set during development; its numbers are not
  used. The measured result is recorded with R4.

## Open issues / follow-ups

- CUDA on the RTX 4070 (the GPU runtime libraries are still downloading) and CPU/CUDA agreement.
- The measured policy, its reworded notice and the real host wiring come after the full set is
  measured (R4).
