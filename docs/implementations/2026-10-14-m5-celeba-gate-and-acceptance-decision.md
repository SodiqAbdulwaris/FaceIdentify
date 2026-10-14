# M5: the CelebA run, and the decision on automatic acceptance

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R; TST-057A (owner's smoke test reported), TST-057B (stays `BLOCKED`)
- **Status:** evidence recorded; **automatic acceptance stays off** (decision below); TST-057B not claimed
- **Commits:** PR to be recorded when merged

## What was run

`evaluation/assisted_recognition_gate.py --people 100 --minimum-photographs 5 --unknown 50 --run-timeout 3600`
on the CelebA selection imported on 2026-10-13 (150 identities, 1,736 photographs, 178 by 218 aligned crops;
labels are the dataset creators', **not verified by this project**), with the real application: `buffalo_l`
SCRFD and ArcFace on CPU under the abstain-only policy. Report: `evaluation/datasets/reports/gate-celeba.json`
(Git-ignored). Its workflow and restart phases were still running when this entry was written, so the report
was **partial**: the retrieval and open-set figures below are complete and final; the workflow checks and the
restart comparison for CelebA are **not recorded here** (see Open items).

The first two attempts stopped at the gate's fixed 900 s wait for the processing runs (CPU: 215 of 872
unfinished; a run that asked for CUDA with a CPU fallback: 451 unfinished, and the GPU showed no use, not
investigated). That is a harness limit, not a result. The gate gained `--run-timeout` (default unchanged).

## Result

| Measure | CelebA | LFW (2026-10-13) |
|---|---|---|
| Enrolled people / photographs placed | 100 / 872 (none lost) | 100 / 601 of 652 |
| Closed-set queries evaluated | 283 | 173 |
| Recall@1 (Wilson 95%) | 0.979 (0.955 to 0.990) | 1.000 (0.978 to 1.000) |
| Recall@5, MRR | 0.979, 0.980 | 1.000, 1.000 |
| Stranger queries evaluated | 580 | 375 |
| Strangers accepted by the real policy | 0 (all offered as possible people) | 0 |
| Strangers' best similarity: median / max | 0.198 / 0.383 | 0.193 / 0.402 |
| Correct match similarity: minimum / 5th percentile | 0.284 / 0.535 | 0.430 / 0.633 |
| Queries changed the library | no (872 / 100 / 872 before and after) | no |

The six CelebA misses are not near-misses: the correct person scored 0.11 to 0.15 (two were not offered at
all) against a wrong person at 0.17 to 0.31. They look like mislabelled or very different photographs;
unverified. None would have been accepted at any cut-off at or above 0.35.

### What a cut-off would have done (a read-out, not a policy)

| Cut-off | CelebA strangers accepted (of 580) | CelebA known accepted correct (of 283) | LFW strangers accepted (of 375) | LFW known accepted correct (of 173) |
|---|---|---|---|---|
| 0.30 | 26 (4.5%) | 276 | 14 (3.7%) | 173 |
| 0.35 | 4 (0.7%) | 276 | 4 (1.1%) | 173 |
| 0.40 | 0 | 274 | 1 (0.3%) | 173 |
| 0.45 | 0 | 273 (0.965) | 0 | 172 (0.994) |
| 0.50 | 0 | 270 (0.954) | 0 | not tabulated here |

At 0.45, none of 955 strangers was accepted on either set (95% upper bound about 0.3% by the rule of three),
no known person was accepted wrongly (0 of 445), and 96.5% to 99.4% of known queries were accepted correctly.
That is far better than the Commons set's earlier "5 false accepts of 40", and it is the first evidence that a
safe operating point may exist. It is **not** enough on its own (below).

## Decision (owner, delegated 2026-10-14: "I'll go with whatever you recommend")

> **Decision 2026-10-14:** automatic acceptance stays **off** (abstain-only; `require_abstain_first` in
> `backend/api/real.py` is unchanged and no policy file may enable matching). The agent's recommendation was
> delegated by the owner and so counts as approved.

Why, in order of weight:

1. **The owner's own condition is not met.** The owner required a *verified* set (40 identities with 5 or
   more images, 80 or more queries). LFW and CelebA labels are the creators' and unverified here; the only
   verified set has 9 identities and 18 queries.
2. **The strangers were not hard.** They are random other people. Look-alikes are untested (the best stranger
   is 0.402 on LFW and 0.383 on CelebA, and a look-alike or a relative would sit higher). The hard-negatives
   mode is issue 177.
3. **Both sets are friendly.** Press and celebrity photographs, many of whom are probably in the recogniser's
   training data (recorded in the licensing file), so the numbers are optimistic. Neither contains the
   owner's snapshots, cameras, lighting or ages. The first look at the owner's own photographs
   (`MyFaces/`, 29 pictures) found one face each, but it is a detector check, not recognition.
4. **The cost is asymmetric.** A wrong automatic acceptance silently puts a face into the wrong person's
   memory; an abstention costs one click. Nothing is lost by waiting.

Nothing about the model or thresholds changed.

### What re-opens it (all of these, in order)

1. A verified set at the owner's targets: review a selection of LFW or CelebA photographs and the owner's
   own with `evaluation/label_review.py` (owner time; the face-level labelling of issue 181 helps).
2. Hard negatives in the stranger set (issue 177).
3. `measure_operating_point.py` reading a verified manifest (issue 178).
4. The conservative precision rule re-run on that set meets the owner's thresholds (Recall@1 0.85,
   Recall@5 0.95, MRR 0.90, stability 100%, zero unintended mutations) with zero false accepts.
5. An explicit, owner-approved code change enabling it (not a policy-file edit).

A candidate operating point to test at step 4, **evidence only, not a policy**: a cut-off of about 0.45 on the
similarity, with a margin over the runner-up still to be measured. A softer intermediate (showing a "likely"
badge above the cut-off while still requiring one click) is possible without any of this and is not built.

## Also recorded

- **The owner's smoke test (TST-057A, manual confirmation):** the owner reported on 2026-10-14 that the
  independent smoke test was done and that images were imported and processed in the app (the CORS fix was
  confirmed the day before). The checklist's individual outcomes were not itemised to the agent; TST-057A stays
  `PASSING` as a functional gate with recognition quality still explicitly unverified.
- **`MyFaces/` again (29 decodable of 30):** every picture gives exactly one confident face (0.66 to 0.93).
  The face at 43% of the frame is still the lowest score (0.66; 0.82 padded); the next largest, at 31% to
  32%, score 0.86 to 0.87. `18.avif` is **refused by the application** (its decoder accepts JPEG, PNG,
  BMP and WebP only): issue 188.
- **Where the datasets came from (owner, 2026-10-13):** LFW from the Kaggle mirror `jessicali9530/lfw-dataset`,
  CelebA from the creators' page (licensing file).

## Verification

- `PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py ... --run-timeout 3600` produced the
  figures above (CPU; report partial as stated). `uv run pytest tests/unit/test_assisted_gate.py -q`: 15
  passed; ruff and mypy clean. The new option is covered by the parser help only.
- **Not verified:** the CelebA workflow checks and restart comparison (the run was unfinished); any of the
  labels; behaviour on the GPU path (not investigated).

## Open issues / follow-ups

- Finish or repeat the CelebA run to record its workflow checks and restart comparison.
- Issues 177, 178 and 181 are on the path above; issue 188 (AVIF) is new.
