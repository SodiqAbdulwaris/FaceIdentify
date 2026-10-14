# M5: the operating point on a verified manifest (issue 178)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`); issue 178
- **Status:** done (measurement only); **automatic acceptance stays off**, no policy written
- **Commits:** PR to be recorded when merged (`feat(evaluation): read verified manifests in the operating point`)

## What changed

- `evaluation/measure_operating_point.py` gains `--manifest`: a `label_review.py` export
  (`kind: verified-manifest`, schema 1). Every verified photograph must lie inside the dataset
  folder, exist and match its reviewed SHA-256 **before** any cached embedding is used (the same
  checks as the gate's `choose_people`). A verified run caches embeddings under a name that also
  carries the manifest digest, so a different selection never reuses another's vectors. The report
  records `verified_labels` and the manifest digest, and its `limits` text names the label source.
  Without `--manifest` the script reads `manifest.json` as before.
- `tests/unit/test_measure_operating_point_manifest.py`: a valid export, a photograph changed after
  review, a missing photograph, a missing digest, a path escaping the dataset, a wrong schema and the
  legacy manifest.
- The code was first written in PR 187, whose CI failed (an 80-character commit header and
  formatting). It is carried over here, reformatted, with a mypy fix in the test; PR 187 can be
  closed in favour of this one (the owner's call).

## Why

The 2026-10-14 decision on automatic acceptance lists, as its third condition, the conservative
rule re-run on a verified manifest (`.agents/CONTEXT.md`, *Decision 2026-10-14*). The script could
only read unverified Commons categories.

## The run (2026-10-15)

```bash
PYTHONPATH=. uv run python evaluation/measure_operating_point.py \
  --dataset evaluation/datasets/celebs-commons \
  --manifest evaluation/datasets/celebs-commons/review/exports/verified-20261014T223246658800Z.json \
  --local-state-root local-models/state \
  --report evaluation/datasets/reports/operating-point-celebs-commons-conservative.json --conservative
```

No `--write-policy`: the installed policy is untouched. Report Git-ignored.

| Measure | Value |
|---|---|
| People / photographs used | 36 / 516 (none excluded: every photograph had a subject) |
| Halves (people, known, queries) | selection 25, 20, 357; final 11, 6, 159 (86 of known people, 73 of strangers) |
| Genuine / impostor pairs | 3,458 / 129,412 |
| Conservative point chosen on the selection half | threshold 0.3314, margin 0.02: 279 accepted, 279 correct, recall 0.982 |
| Reported on the final half | 85 accepted, 85 correct, **0 false accepts** (0 of strangers, 0 of known people), recall 0.988, precision 95% interval 0.957 to 1.000, abstention rate 0.465 |
| Verdict | `provisional-conservative` ("no false accept on the final half") |
| Non-conservative point (for comparison) | threshold 0.2622, margin 0.10: precision 0.993 on the selection half (2 wrong of 282); 86 of 86 on the final half |

## What this does and does not show

- The conservative rule meets its own requirement on human-verified labels: zero false accepts on a
  half that took no part in the choice.
- **It does not re-open automatic acceptance.** The final half is small (11 people; the 73 stranger
  queries come from 5 people, so they are not independent trials), the strangers are random
  celebrities rather than look-alikes (issue 177 is not done), the set is 36 of the required 40
  identities, and the photographs are filtered to one dominant face and likely overlap the
  recogniser's training data (a possibility, not measured). The decision of 2026-10-14 stands; any
  change needs the remaining conditions and an explicit owner-approved code change.
- The non-conservative point made 2 false accepts on the selection half, which is why the owner's
  conservative rule exists.

## Verification

- `uv run pytest -q tests/unit/test_measure_operating_point_manifest.py`: 4 passed.
- Full backend gate before the PR: see the PR description for the exact results.
- The run above finished with exit code 0 and `verified_labels: true`; the installed policy files
  were not written.

## Follow-ups

- Repeat this run when the set reaches 40 identities and with hard negatives (issue 177).
