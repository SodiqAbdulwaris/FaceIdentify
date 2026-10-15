# The operating point and the hard-negative gate re-measured on DirectML

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 track R; TST-044 (operating point), TST-057B (evidence), TST-074
  (DirectML validation, this machine)
- **Status:** done; measurement only (no code changed)
- **Commits:** PR (number recorded when merged): `docs: record the DirectML re-measure`

## What changed

Nothing in the code. Two runs on the default Windows provider (`onnxruntime-windowsml` 1.30.0,
`DmlExecutionProvider` then the CPU, PR 202), compared with the CPU reports of 2026-10-15, are
recorded here. The JSON reports stay in the Git-ignored `evaluation/datasets/reports/`
(`operating-point-celebs-commons-48-conservative-dml.json`, `gate-celebs-commons-hard-wide-dml.json`,
`dml-remeasure.log`).

## Why

The automatic-acceptance point (0.45 / margin 0.10) and the conservative operating point were
measured on the CPU; the shipped default is now DirectML. The DirectML entry of 2026-10-15 asked for
a re-measure "before relying on it".

## How it was run

- The package in `local-models/state` predates the DirectML variants (it keeps running on the CPU)
  and must not be written to, so a fresh state root was made in the Git-ignored
  `evaluation/datasets/dml-state` from the same weight files (`install_reference_models.py`; same
  SHA-256s), with the **abstain-only** policy, the one the CPU gate ran under. The live
  `local-models/state` was not touched.
- `measure_operating_point.py` caches embeddings beside the dataset by weights and pictures, not by
  provider: the first DirectML attempt reused the CPU cache and measured nothing (its report is kept
  as `operating-point-dml-cached-invalid.json`). The CPU cache was moved aside (not deleted), the
  embeddings recomputed on DirectML, the DirectML cache kept as
  `celebs-commons/cpu-cache-backup/dml-embeddings-…npz`, and the CPU cache put back.
- Both runs used the main checkout's code at `a4ae18a` (before PR 205's gate-report change, which
  only adds an exclusions listing) with the DirectML worktree's environment, because the gate refuses a dataset outside
  its own checkout. One heavy run at a time; nothing else was using the GPU.

```bash
FACEIDENTIFY_PROVIDERS=DmlExecutionProvider,CPUExecutionProvider PYTHONPATH=. python \
  evaluation/measure_operating_point.py --dataset evaluation/datasets/celebs-commons \
  --manifest evaluation/datasets/celebs-commons/review/exports/verified-20261015T073439095195Z.json \
  --local-state-root evaluation/datasets/dml-state --provider DmlExecutionProvider \
  --report evaluation/datasets/reports/operating-point-celebs-commons-48-conservative-dml.json --conservative
FACEIDENTIFY_PROVIDERS=DmlExecutionProvider,CPUExecutionProvider PYTHONPATH=. python \
  evaluation/assisted_recognition_gate.py --dataset evaluation/datasets/celebs-commons \
  --manifest evaluation/datasets/celebs-commons/review/exports/verified-20261015T073439095195Z.json \
  --local-state-root evaluation/datasets/dml-state --workdir evaluation/datasets/gate-dml-hard-wide \
  --report evaluation/datasets/reports/gate-celebs-commons-hard-wide-dml.json --people 40 --unknown 8 \
  --hard-negatives 15 --hard-negative-pool evaluation/datasets/lfw-pool --minimum-photographs 5 --run-timeout 3600
```

## Results

**Operating point (48 verified identities, 686 photographs):** the report is identical to the CPU
report in every field except `configuration.provider`: the same conservative point (threshold
0.3314, margin 0.02 chosen on the selection half), the same final-half result (156 of 156 correct,
0 false accepts, recall 0.994), the same exclusions. Embedding drift, DirectML against CPU, over all
686 vectors: largest 1 − cosine **1.25e-6**, mean 3.7e-8. Time: 71 s for the whole run (embedding
included) on DirectML.

**Hard-negative gate (40 enrolled, 8 strangers, 15 hard negatives from the LFW pool):**

| | CPU (2026-10-15) | DirectML (2026-10-16) |
|---|---|---|
| Recall@1 / Recall@5 / MRR (118 queries) | 0.983 / 0.992 / 0.986 | identical |
| Workflow checks | 10 of 10 | identical |
| Stranger queries accepted (115 random, 31 hard negatives) | 0 and 0 | identical |
| Hard negatives chosen | 15 people | the same 15 |
| Top-1 person and status, all 267 queries | | identical |
| Rankings after the restart, per identity, counts | | identical |
| Enrolment | 612.5 s | 496.9 s |
| Hard-negative selection | 4,573.6 s | 1,072.5 s |
| Queries / after workflow / restart and queries | 888.3 / 836.8 / 785.0 s | 184.4 / 186.3 / 192.5 s |
| Total | about 2 h 8 min | about 36 min |
| Provider that ran (readiness after enrolment) | not recorded (the CPU run predates the field) | `DmlExecutionProvider`, fallback `NONE` |

The only differences are in the tail of the candidate lists: near-ties among low similarities (around
0.1, deltas about 1e-4) swap places, and in two queries the approximate index shortlist surfaced a
different face for a low-ranked person (largest difference 0.026, on a candidate at 0.106). No
decision, top-1 answer or metric changed.

## Decisions

- **The CPU-measured operating point and the owner-approved 0.45 / 0.10 point stand on DirectML:**
  the decisions are identical and the embeddings agree to 1.25e-6. No change is proposed.

## Verification

The gate report's `readiness_after_enrolment` shows DirectML ran with no fallback (`execution_provider`
`DmlExecutionProvider`, `provider_fallback` `NONE`); the operating-point script records only the
provider it was asked for, so for that run the DirectML timings (71 s) are the evidence. The
comparisons above were made field by field on the two pairs of JSON reports and on the two
embedding caches (scripts kept outside the repository; the reports are Git-ignored data). The
enrolment time is dominated by import and the database, which is why it barely moves.

## Open issues / follow-ups

- `measure_operating_point.py`'s embedding cache is keyed by weights and pictures but not by
  provider, so a run on another provider silently reuses the first provider's vectors (harmless here,
  since the vectors agree, but the report then names a provider that did not run). Keying the cache by
  provider, or recording which provider made it, is a small fix.
- AMD GPUs and machines without DirectX 12 remain unverified (TST-074 stays partial).
