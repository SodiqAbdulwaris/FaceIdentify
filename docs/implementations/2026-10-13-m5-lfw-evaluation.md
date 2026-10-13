# M5: the first run on LFW (TST-057B evidence, not a pass)

- **Date:** 2026-10-13
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`), TST-057A evidence
- **Status:** evidence recorded; **TST-057B is not claimed**
- **Commits:** PR to be recorded when merged

## What was run

The owner downloaded Labeled Faces in the Wild (`lfw-deepfunneled`). `evaluation/import_labelled_dataset.py lfw`
selected 150 people with at least 5 distinct pictures (at most 12 each: 1,244 photographs) into the Git-ignored
`evaluation/datasets/lfw`. `evaluation/assisted_recognition_gate.py --people 100 --minimum-photographs 5
--unknown 50` ran the real application (`buffalo_l` SCRFD and ArcFace, CPU, the abstain-only policy) on it:
100 people enrolled, 50 never enrolled. Report: `evaluation/datasets/reports/gate-lfw.json`
(photograph digest `a904805202687b33...`, manifest digest `801c5d14096dacb0...`).

**The labels are the dataset creators' (names from photograph captions). This project has not verified them.**

## Result

| Measure | Value |
|---|---|
| Enrolled people / photographs imported / subject faces placed | 100 / 652 / 601 (5 with no face, 46 with no clear subject) |
| Closed-set queries | 173 (11 held-out photographs had no clear subject) |
| Recall@1, Recall@5, MRR | 1.000 / 1.000 / 1.000 (Wilson 95% for the recalls: 0.978 to 1.000) |
| Strangers: people / photographs attempted / evaluated | 50 / 408 / 375 (33 without a clear subject face) |
| Strangers accepted by the real policy | 0 of 375 (all offered only as possible people) |
| Strangers' best-candidate similarity | 0.135 to 0.402 (median 0.193) |
| Workflow checks, same rankings after restart, queries wrote nothing | 10 of 10, yes, yes (652, 100, 652) |

Cut-off table (a candidate at or above the cut-off would be accepted), 375 strangers and 173 known queries:

| Cut-off | Strangers accepted | Known rightly top-ranked | Known wrongly accepted |
|---|---|---|---|
| 0.30 | 14 | 173 | 0 |
| 0.35 | 4 | 173 | 0 |
| 0.40 | 1 | 173 | 0 |
| 0.45 | 0 | 172 | 0 |
| 0.50 | 0 | 172 | 0 |
| 0.60 | 0 | 167 | 0 |
| 0.70 | 0 | 132 | 0 |
| 0.80 | 0 | 36 | 0 |

After the destructive workflow steps (a person forgotten, an image deleted) the same queries gave Recall@1 0.988:
expected, since those steps removed enrolled people.

## Reading it, and its limits

- LFW is the easy end of face recognition. A model like this one is expected to be near-perfect on it, so the
  closed-set result mostly shows that the pipeline, the index and the API work end to end on a larger set
  (652 images, 100 people) and not that recognition is solved.
- **One stranger scored 0.402**, above a 0.40 cut-off, and 14 of 375 reached 0.30: look-alike strangers exist,
  and the region between about 0.30 and 0.45 is where a cut-off would be decided. That is what automatic
  acceptance would have to be safe in; this run does not choose a point and the abstain-only policy is unchanged.
- **Leakage.** LFW people are famous and the recogniser's training data (WebFace600K) may contain them or their
  pictures, so the numbers are optimistic by an unknown amount.
- **Easy photographs.** Frontal, well-lit press photographs; family photographs are harder.
- **Not independent trials.** The 375 stranger queries are repeated photographs of 50 people. The interval
  (0 to 0.010 from a cut-off of 0.45) is nominal per query, not a population bound.
- **Unverified labels.** A mislabelled photograph moves the numbers either way.

## What it changes, and what it does not

- It is the first run with a stranger pool large enough to show false-match behaviour at all (the earlier
  owner-verified run had 25 stranger queries). It makes the open-set protocol credible.
- TST-057B still needs: a verified or trusted set at the dataset targets, hard negatives (strangers chosen to
  resemble enrolled people), photographs of ordinary quality (CelebA, the owner's own set), and the owner's
  decision on automatic acceptance with the conservative rule re-run (`measure_operating_point.py` does not yet
  read an imported manifest).
- CelebA has not been downloaded yet.
