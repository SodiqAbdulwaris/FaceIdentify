# M5: tracker rows TST-044, TST-038 and TST-039

- **Date:** 2026-10-20
- **Milestone / tracker IDs:** M5 close-out step 4; TST-044, TST-038, TST-039
- **Status:** done; documentation only (no code, threshold, policy, model or spec changed)
- **Commits:** PR (number recorded when merged): `docs: close the M5 evidence rows`

## What changed

`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`: TST-038 / TST-039 (writer row and real-path row) and
TST-044 go from `IN_PROGRESS` to `PASSING`; the superseded "until then it was blocked" and "still
open: the owner's decision" wording is removed from the active rows, and the 2026-10-06 "M3 status"
snapshot gets a dated note after it. `.agents/CONTEXT.md` and `docs/plans/PROJECT_STATUS.md` get
their dates and one line each.

## TST-038 / TST-039

> **Decision 2026-10-20:** (owner: "TST-038/039 closed on local evidence") the rows close on local
> real-weight evidence. The `buffalo_l` weights are research-licensed and cannot go into CI. The
> evidence is `tests/e2e/test_real_models.py` and `tests/e2e/test_real_host.py` (`-m e2e`, local), which
> passed on CPU and CUDA as recorded in the rows, and the provenance re-hash: the exact weight files
> matched the recorded SHA-256s (issue #69, closed;
> [entry](2026-10-16-m5-weights-provenance-and-install-guide.md)). CI keeps the fixture-model halves.

## TST-044 review

Criterion (tracker M3 table): "Reproducible component baselines exist". Verdict: **met, `PASSING`**.

- **Commands recorded:** `evaluation/measure_operating_point.py` with the verified manifest
  `verified-20261015T073439095195Z.json` ([entry](2026-10-15-m5-verified-operating-point.md)) and the
  same command plus the hard-negative `evaluation/assisted_recognition_gate.py` run, both with exact
  flags, on DirectML ([entry](2026-10-16-directml-remeasure.md)).
- **Reports named:** `operating-point-celebs-commons-48-conservative.json`,
  `operating-point-celebs-commons-48-conservative-dml.json`, `gate-celebs-commons-hard-wide-dml.json`
  and the CPU gate report, in the Git-ignored `evaluation/datasets/reports/`. The operating-point script
  records the manifest digest and `verified_labels` in its report, the gate records the pool manifest's SHA-256
  and the provider that ran; the weights digest is recorded in the 2026-10-07 baseline
  ([research note](../research/measured-operating-point.md)).
- **Numbers recorded:** 48 identities / 686 photographs; point 0.3314 / 0.02 chosen on the selection half;
  final half 156 of 156 correct, 0 false accepts, recall 0.994; the gate's Recall@1/5/MRR
  0.983 / 0.992 / 0.986 with 0 strangers accepted among 15 hard negatives; DirectML identical, embedding
  drift 1.25e-6. The first baseline (2026-10-07) records the weights digest and dataset manifest SHA-256.
- **Why not `COMPLETE`:** the data and reports are licensed or local and cannot be in CI, so the baseline
  is reproducible by the owner's machine rather than by a CI job. Gaps, for honesty: the verified
  export's manifest SHA-256 and the 48-identity weights digest are in the Git-ignored reports, not in
  these entries; the operating-point script records only the provider it was asked for.

## Verification

Documentation review against the entries cited above; no tests were run for this change. Step 4 is marked done in
[`M5_CLOSEOUT_PLAN.md`](../plans/M5_CLOSEOUT_PLAN.md).
