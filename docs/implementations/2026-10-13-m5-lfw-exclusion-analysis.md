# M5: where LFW and CelebA photographs drop out before recognition (diagnostic; nothing changed)

- **Date:** 2026-10-13
- **Milestone / tracker IDs:** M5 track R; supports TST-057B (stays `BLOCKED`); no tracker row changes
- **Status:** analysis done on LFW and CelebA; no threshold, policy or model was changed
- **Commits:** PR to be recorded when merged

## What was asked

The owner asked (2026-10-13) to separate real pipeline weaknesses from intentional safety exclusions
for the photographs the first LFW run lost: 5 of 652 enrolment photographs with no face, 46 with no
clear subject, and 33 of 408 stranger photographs with no clear subject. The constraints: change no
threshold or policy, do not optimise for LFW, keep the baseline, and keep this apart from
identity-matching accuracy.

## What was built

- `evaluation/analyse_exclusions.py`: runs the installed SCRFD export in this process on exactly the
  photographs the assisted gate used (the gate's own `choose_people` and `partition_people`), keeps
  every candidate the detector sees down to a score of 0.05, and splits them the way the production
  contract does (kept at 0.5, below the floor, dropped by the border rule). It cross-checks that its
  production-equivalent output equals `detection.decode` on every image (an assertion, so a future
  divergence stops the run). It embeds and matches nothing. It writes
  `evaluation/datasets/reports/exclusions-lfw.json` (names photographs: Git-ignored) and, with
  `--sheets`, contact sheets with the boxes drawn.
- `tests/unit/test_exclusion_analysis.py`: the classification rules on synthetic faces, including
  that the diagnostic verdict equals the gate's own `subject` rule on the same faces.

Run: `PYTHONPATH=. uv run python evaluation/analyse_exclusions.py --dataset evaluation/datasets/lfw
--local-state-root local-models/state --people 100 --unknown 50 --report
evaluation/datasets/reports/exclusions-lfw.json [--sheets evaluation/datasets/reports/exclusion-sheets]`.

## Where the rules live (found while doing this)

| Rule | Where | What it does |
|---|---|---|
| Detector score floor 0.5 | `DetectorContract.score_threshold` in `backend/ml/perception/detection.py` | Candidates below it never leave the worker |
| Border rule | same file, `usable` in `decode` | A box is clipped, but a detection with a landmark outside the image is dropped (alignment would be a guess) |
| Policy floor `min_detection_score` | the policy file (`load_policy` in `backend/api/real.py`; `buffalo-l-abstain-only-v1` sets 0.5), applied by `IdentityReasoner.decide` in `backend/app/recognition/reasoner.py` | A separate decision-time quality gate. In the measured configuration it equals the detector floor, so it removes nothing the detector kept; nothing enforces that equality |
| Subject rule (largest face at least 2.5 times the next) | **the evaluation gate only**, `DOMINANCE` in `evaluation/assisted_recognition_gate.py` | Chooses which one face stands for a photograph that has one label. The application does not apply it: it recognises every face |
| Two enrolled faces | the gate, `eligible` | A person with fewer than 2 enrolled faces has their queries marked ineligible (a cascade from enrolment exclusions) |

**So, in detector output and gate coverage, 79 of the 84 "lost" photographs are lost to the
measurement, not to the detector.** Only the 5 no-face photographs are a detector loss. (Whether
embedding or matching would also fail on the others was not measured here: this is not an accuracy
result.)

## Result (the baseline reproduced exactly)

| Group | Photographs | ok | no subject | no face |
|---|---|---|---|---|
| Enrolment | 652 | 601 | 46 | 5 |
| Held-out known queries | 184 | 174 | 10 | 0 |
| Strangers | 408 | 375 | 33 | 0 |

The gate's 173 evaluated queries are the 174 above minus one: a person left with a single usable
enrolment photograph (3 of that person's 4 photographs were crowd scenes) has their query marked
ineligible. 35 of the 100 enrolled people lost at least one enrolment photograph; none lost all.

### The 5 with no face: a detector weakness on close-ups, not the floor

All five contain one real, frontal-enough face that fills 34% to 40% of the frame (the dataset's
median largest face is 19%), scored 0.30 to 0.499 and so fell just under the floor. Padding each
picture with a black margin of half its size on every side, nothing else changed, gave a confident
detection (0.75 to 0.86) for **all five**, and each padded detection, mapped back, lies on the
largest face the original run saw below the floor, the subject candidate (checked, not assumed; a
small background face would not count). That supports a scale hypothesis: the detector scores very
large faces low on this canvas. It does not show that 0.5 is the right operating point (that needs
false-positive and downstream measurements), and five photographs is a small sample.

Across all 1,244 photographs the median score of the largest face falls as it grows (0.85 for the
smallest fifth, 0.82 for the 0.22 to 0.35 band, and 0.62 for the four photographs above 0.35). One
of the five (best score 0.4988) also has a confident face dropped by the border rule: a different
person at the image edge, not the subject, so the border rule did not cause that loss.

### Each rule on its own (counterfactuals; measurements, not proposals)

| Alone | Enrolment | Known queries | Strangers |
|---|---|---|---|
| Baseline: ok / no subject / no face | 601 / 46 / 5 | 174 / 10 / 0 | 375 / 33 / 0 |
| Floor 0.3 | 599 / 53 / 0 (+5 recovered, 7 ok become no subject) | 170 / 14 (4 become no subject) | 370 / 38 (5 become no subject) |
| Floor 0.1 | 569 / 83 / 0 | 157 / 27 | 350 / 58 |
| Ratio 2.0 | 609 / 38 / 5 | 175 / 9 | 379 / 29 |
| Ratio 1.5 | 626 / 21 / 5 | 179 / 5 | 393 / 15 |
| Largest face wins (no ratio test) | 647 / 0 / 5 | 184 / 0 | 408 / 0 |

Lowering the floor looks like the wrong remedy (provisional: this measures the gate's coverage, not
harm to the application, which processes faces one by one): it recovers the 5 but turns 16 other
photographs into "no subject" (the sub-0.5 detections are mostly real background faces, and below about 0.15 they are
clusters of junk boxes on clothing and texture, visible on the contact sheets). The border rule
removes one confident face in the whole set; it cannot be rescued by a threshold.

### The 89 "no subject" photographs (46 + 10 + 33): why

The second face (the one that stops the ratio test), counted so that each photograph falls in one row:

| Second face is | Enrolment | Known queries | Strangers |
|---|---|---|---|
| Complete and confident (score at least 0.7, inside the frame) | 12 | 3 | 8 |
| Confident but cut by the image edge | 12 | 5 | 10 |
| Inside the frame but weak (below 0.7) | 7 | 2 | 9 |
| Weak and cut by the edge | 15 | 0 | 6 |

(Per-photograph flags are in the report.) The largest face is also the most central one in 44 of 46 enrolment photographs
and in all 10 and 32 of 33 of the others: that is how LFW was built (each picture is centred on the
labelled face), a property of the dataset that real photographs do not have, so it is **not** a rule
to adopt.

### Categories (the agent's reading of the contact sheets, not owner-verified)

| Category | Meaning | Count (46 + 10 + 33 + 5) |
|---|---|---|
| Legitimate rejection | Two or more complete, confident, comparable faces: no single subject exists | about 23 (12 + 3 + 8) |
| Rejected by the evaluation rule, subject plain to a person | The companion is cut by the edge or low confidence, the labelled face is central and whole | about 66 |
| Detection failure | A real, large face the detector scored under the floor | 5 |
| Ambiguous | Crowds (for example three photographs of one person, all crowd scenes) | included above |

I looked at the contact sheets of all 94 excluded photographs (51 enrolment, 10 query, 33 stranger);
they agreed with these proxies. Treat the counts as approximate: they depend on my reading and on the 0.7 and 1% cut-offs
chosen for the proxies.

## CelebA (same method, same 100 enrolled and 50 stranger people, 2026-10-13)

`evaluation/import_labelled_dataset.py celeba --people 150 --maximum 12 --minimum 5` selected 150
identities, 1,736 photographs (all 178 by 218 aligned crops; labels are the dataset creators', not
verified). The importer needed a fix first: the standard download nests the pictures once more
(`Img/img_align_celeba/img_align_celeba`) and keeps the table in `Anno/`, so it found none.

| Group | Photographs | ok | no subject | no face |
|---|---|---|---|---|
| Enrolment | 872 | 872 | 0 | 0 |
| Held-out known queries | 283 | 283 | 0 | 0 |
| Strangers | 581 | 580 | 0 | 1 |

- **No subject: 0.** CelebA crops hold one face (17 of 1,736 photographs show a second kept face and
  all have a dominant subject). The subject rule that excluded 89 LFW photographs excludes none:
  those exclusions come from the interaction of LFW's news photographs (several people per picture)
  with the dominance rule; a different rule would exclude fewer of them, as the counterfactuals
  show.
- **The one no-face photograph** (a stranger) is a mostly-hair corner crop with the face cut off by
  the crop (largest candidate 0.469, 21% of the frame). Padding gives a 0.62 detection on that
  face. I would call it an ambiguous crop, not a detector failure.
- **Large faces:** the median largest face fills 27% of the frame (LFW 19%) and 27 photographs fill
  35% or more. None was lost; 7 of those 27 scored under 0.7. The median score is unchanged by size
  (0.83 for every size band), so what the data shows is a low-score *tail* among the largest faces
  (4.3% under 0.7 at 30% of the frame or more, against under 1% below that), not a steady decline.
  The tail stays above the floor.
- **Why LFW differs is not established.** The LFW copy is the deep-funnelled set (rotated and
  re-centred, black corners) at 250 by 250, CelebA is a 178 by 218 alignment. A size effect alone
  does not explain it, since CelebA has more large faces and loses none. Candidate causes (the
  funnelling's rotation and black fill, the square canvas, the tight framing) are untested.

## The owner's own photographs (`MyFaces/`, 11 pictures, 2026-10-13)

A first look, with the same detector and the same assertions (nothing saved, aggregate only; the
pictures are the owner's and Git-ignored):

- All 11 pictures give exactly one confident face (scores 0.66 to 0.90); none is excluded. They are
  small (183 by 275 to 738 by 414), faces fill 0.6% to 43% of the frame.
- One picture has a face at 43% of the frame (larger than any CelebA face): it scores 0.66, and 0.82
  once padded. That is the same large-face score drop as in LFW and CelebA, and it still passes the
  floor. One picture of eleven: it supports the scale effect, it does not size it.
- Faces at 0.6% and 1.3% of the frame (two pictures) are still found at 0.82 and 0.88, so small
  faces are not a problem at this size.

## Root-cause findings

1. **On LFW, very large faces fall under the 0.5 floor; CelebA does not reproduce it.** All five LFW
   losses are faces at 34% to 40% of the frame, and padding fixes them. On CelebA (see below) the
   same measurement lost one photograph in 1,736, and that one was a cut-off crop, not a close-up. I
   had predicted CelebA would show *more* losses; **that prediction was wrong.** The weakness is
   real in LFW's tail, but its size in the product is unknown: neither measured selection establishes
   performance on a representative sample of the pictures the worry is about (selfies, ID
   photographs, tight phone crops).
2. **The subject rule is a labelling device of the evaluation, not a product rule.** It trades
   coverage for certainty about whose face carries the label. It correctly excludes the genuinely
   ambiguous photographs, and excludes about two thirds more where a person would pick the subject.
3. **The two 0.5 floors are two rules with equal values.** The detector decides which candidates
   leave perception; the policy floor independently gates a decision. Lowering only the policy floor
   cannot recover a candidate the detector discarded; lowering only the detector floor exposes more
   faces that the policy would still treat by its own gate. Equality is the measured configuration,
   not an enforced invariant; review them together.
4. **Stranger exclusions are biased towards crowds.** The 33 excluded stranger photographs are the
   ones with several prominent faces, which is where a stranger standing next to an enrolled person
   would be hardest. The open-set claim ("0 of 375 accepted") says nothing about them. (It is
   vacuous under the abstain-only policy anyway: nothing is accepted.)
5. **Enrolment exclusions cascade**, one query here; with fewer photographs per person it would be
   more.

## Recommendations (each needs a dated owner decision; none is built)

1. **Close-up detection: do not change the detector on this evidence.** LFW lost 5 of 1,244
   photographs (0.4%) and CelebA 1 of 1,736 (0.06%, an ambiguous crop). A second pass on a padded
   canvas (a new `scrfd-letterbox-v2` contract with its own provenance) would fix the five, but neither
   selection represents the owner's intended photographs. The next measurement is a
   larger set of the owner's own close-up photographs (selfies, ID photographs, tight phone crops;
   the first 11 are above, with one large face that still passed); decide after that, and check that
   padding adds no false faces.
2. **Keep the floor at 0.5** and the border rule as they are.
3. **Keep the subject rule for evaluation**, but stop treating its exclusions as pipeline loss in
   reports: say "not evaluated (ambiguous subject)". A better measurement is face-level labels for
   the ambiguous photographs in the label-review tool, so the labelled face is identified rather
   than the photograph excluded. Do not use "most central face" (a dataset artefact).
4. **Report exclusions by rule in every gate report** (done here for LFW; the gate itself still
   reports totals).

## Verification

- `PYTHONPATH=. uv run python evaluation/analyse_exclusions.py ...` ran on all 1,244 photographs; its
  production-equivalent output matched `detection.decode` on every image (assertion), and its counts
  match the gate's: 5 and 46 enrolment, 33 stranger exclusions, 11 held-out queries (10 + 1 cascade).
  It decodes pictures with the application's own decoder (EXIF orientation applied) and keeps scores
  and boxes at full precision.
- `PYTHONPATH=. uv run python evaluation/analyse_exclusions.py --dataset evaluation/datasets/celeba ...`
  ran on 1,736 CelebA photographs with the same assertions (report `exclusions-celeba.json`,
  Git-ignored). `uv run pytest tests/unit/test_import_labelled_dataset.py -q`: 11 passed.
- `uv run pytest tests/unit/test_exclusion_analysis.py tests/unit/test_assisted_gate.py -q`: 26 passed
  (boundary regressions with a fake detector session: a 0.49996 score stays below the floor, a
  batched output is read like production reads it, a landmark outside the image is a border drop and
  an empty box is not; padding must recover the subject candidate, not a background face; areas keep
  full precision; a contact sheet will not follow a symlink out of the datasets folder).
  `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform linux`
  pass (302 files formatted, 294 source files).
- **Not verified:** the padding result is five photographs; the category counts are the agent's
  reading; CPU only (CUDA agrees with CPU on the gate, not re-run here); the full test suite was not
  re-run for this docs and evaluation-only change.

## Open issues / follow-ups

Gaps found or confirmed here are tracked as GitHub issues #173 to #183 (listed in `docs/plans/PROJECT_STATUS.md`); #184 (evaluate on CelebA) was completed in this entry and closed.

- Measure the owner's own close-up photographs before deciding recommendation 1 (see issue #173).
- Look-alike strangers (best similarity 0.402), margin and aggregation policy, and the hard-negatives
  selection mode remain deferred, as the owner decided.
- The label-review tool could mark which face carries a label (recommendation 3).
