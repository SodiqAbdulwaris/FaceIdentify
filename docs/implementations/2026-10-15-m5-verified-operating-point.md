# M5: the operating point on a verified manifest (issue 178)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`); issue 178
- **Status:** done (measurement only); **automatic acceptance stays off**, no policy written
- **Commits:** PR to be recorded when merged (`feat(evaluation): read verified manifests in the operating point`)

## What changed

- `evaluation/measure_operating_point.py` gains `--manifest`: a `label_review.py` export
  (`kind: verified-manifest`, schema 1). Every verified photograph must lie inside the dataset
  folder, exist and match its reviewed SHA-256 **before** any cached embedding is used (the same
  checks as the gate's `choose_people`). Every used picture is hashed once: a byte-identical copy
  under a second name is left out and counted (`byte_identical_copies_left_out`), since
  leave-one-out removes a query by name and a copy would match itself; and the embedding cache is
  named by a key over every used file name with its digest, so an edited picture or a different
  selection never reuses cached vectors (the old weights-only cache name could, for any manifest). The report
  records `verified_labels` and the manifest digest, and its `limits` text names the label source.
  Without `--manifest` the script reads `manifest.json` as before.
- `tests/unit/test_measure_operating_point_manifest.py`: a valid export, a photograph changed after
  review, a missing photograph, a missing digest, a path escaping the dataset, a wrong schema, the
  legacy manifest, byte-identical copies, and the cache key changing with a picture's bytes and
  with the selection (symlink escapes are covered by `resolve()` but not tested: creating symlinks
  needs extra rights on Windows).
- The independent review of this PR found the duplicate-copy and stale-cache gaps; both were fixed
  and the run below repeated with identical results (0 copies in this set).
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

## Repeated on the 48-identity verified export (2026-10-15)

After the owner reviewed 12 more people, the same command on
`verified-20261015T073439095195Z.json` (report `operating-point-celebs-commons-48-conservative.json`):

| Measure | Value |
|---|---|
| People / photographs used | 48 / 686 (none excluded, no byte-identical copies) |
| Halves (people, known, queries) | selection 30, 24, 428; final 18, 11, 258 (157 of known people, 101 of strangers from 7 people) |
| Genuine / impostor pairs | 4,582 / 230,373 |
| Conservative point chosen on the selection half | threshold 0.3314, margin 0.02 (the same point): 336 of 336 correct, recall 0.985 |
| Reported on the final half | 156 accepted, 156 correct, **0 false accepts**, recall 0.994, precision 95% interval 0.976 to 1.000, abstention rate 0.395 |
| Non-conservative point (comparison) | threshold 0.257, margin 0.10: 3 wrong of 340 on the selection half |

The same point was chosen from a larger set, which is mildly reassuring about its stability. The
limits below still apply (random strangers, the final half's strangers are 7 people), and hard
negatives (issue 177) are not measured yet.

## What this does and does not show

- The conservative rule meets its own requirement on human-verified labels: zero false accepts on a
  half that took no part in the choice.
- **It does not re-open automatic acceptance.** The final half is small (11 people; the 73 stranger
  queries come from 5 people, so they are not independent trials; in the 48-identity repeat, 18
  people and 101 stranger queries from 7), the strangers are random celebrities rather than
  look-alikes (issue 177 is not done), the first set was 36 of the required 40 identities (the repeat
  has 48), and the photographs are filtered to one dominant face and likely overlap the
  recogniser's training data (a possibility, not measured). The decision of 2026-10-14 stands; any
  change needs the remaining conditions and an explicit owner-approved code change.
- The non-conservative point made 2 false accepts on the selection half, which is why the owner's
  conservative rule exists.

## Verification

- `uv run pytest -q tests/unit/test_measure_operating_point_manifest.py`: 6 passed (and fail to
  import without the change).
- After the review fix the run was repeated (`operating-point-celebs-commons-conservative-v2.json`):
  halves, pair distributions, both chosen points and the final-half results equal the first run.
- Full backend gate before the PR: see the PR description for the exact results.
- The run above finished with exit code 0 and `verified_labels: true`; the installed policy files
  were not written.

## Follow-ups

- Repeat this run when the set reaches 40 identities and with hard negatives (issue 177).
