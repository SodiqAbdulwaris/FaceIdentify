# Measured operating point for `buffalo_l` (TST-044, first baseline)

**Date:** 2026-10-07. **Status:** measured twice; automatic acceptance is **disabled** (ABSTAIN-only) under the
owner's rule of 2026-10-07 until a larger verified set exists. Numbers only: no photograph is recorded or committed.

## Run

`evaluation/measure_operating_point.py` (protocol in its docstring) on `evaluation/datasets/commons-pd`
(673 public-domain Commons photographs of 44 people), CPU, ONNX Runtime 1.30.0, weights digest
`6c8808d2fac7336cff42c053846dc5aa60ce9ba39537013137dd9eb4b3a480c1`, dataset manifest SHA-256
`9e1118443ff7c9062e248e4475954013174bda125846f7d757d1d6df6091c555`. Rule: highest recall with at least
99% precision, at least 30 accepted queries and recall at least 0.5 (the agent's predeclared minimum;
the owner has not set one). The report is local (`evaluation/datasets/reports/final.json`).

## Data after exclusions

- 94 photographs had no face and 340 had no usable subject (several faces of similar size), none failed.
  221 photographs of 36 people remain; seven people had one usable photograph and are out.
- Selection half: 17 people (12 known), 100 queries. Final half: 19 people (11 known), 121 queries, 55
  of known people. The halves share nobody.

## Scores

- Same-person pairs (n = 882), cosine at percentiles 1, 5, 25, 50, 75: -0.083, -0.030, 0.129, 0.492, 0.684.
- Different-person pairs (n = 23,428), at percentiles 50, 95, 99, 99.9: 0.008, 0.110, 0.164, 0.326.

A quarter of the same-person pairs score below 0.129, and one in twenty is negative. Formal portraits
of one person span decades, and the labels are unverified Commons categories, so some of this is label
error and some is real age and pose variation; the two cannot be separated here.

## Choice and result

- Chosen on the selection half: margin 0.0, threshold 0.2586, 42 accepted, 42 correct (precision 1.0,
  recall 0.667). The new-identity ceiling had no point meeting its rule (`null`).
- Reported on the final half, which took no part in the choice: 51 accepted, 40 correct, precision
  0.784 (Wilson 95% interval 0.654 to 0.875), recall 0.727.

## What the numbers say

The 99% rule is satisfied on the half it was chosen on and **not** on the held-out half: the point is
overfit to 100 queries, and 0.2586 sits far below the different-person 99.9th percentile (0.326).
With this set the 99% precision target cannot be certified at any useful recall; the interval's upper
end is 0.875. Calling this threshold "calibrated to 99%" would be false. The owner's decision
(2026-10-07) was to choose the threshold above the different-person tail, to put false accepts before
recall, to re-evaluate on the held-out half, and to disable automatic acceptance if the higher
threshold still produced false accepts.

## The conservative rule and its result

Rule (`--conservative`, predeclared before the run): thresholds only strictly above the
floor, the owner's figure 0.326 (the different-person tail of the first run) or the 99.9th percentile of different-person pairs among the *selection* half's photographs if that is higher (it was not); the final half is never read for the floor (a review found the first version had read it); a margin is always required (0.02, 0.05,
0.1); zero false accepts and at least 20 accepted queries on the selection half; then the highest
recall; judged on the final half, which must show zero false accepts and a recall of at least 0.25
(predeclared "useful" minimum), otherwise automatic acceptance is disabled. No new-identity ceiling:
a face below the threshold abstains.

- Chosen on the selection half: threshold 0.3544, margin 0.02, 40 accepted, 40 correct, recall 0.635.
- Final half (121 queries, 55 of known people): 40 accepted, 35 correct, **5 false accepts**
  (precision 0.875, Wilson 95% interval 0.739 to 0.945), recall 0.636, abstention rate 0.669.
  Three false accepts were queries of people never enrolled and two were known people matched to the
  wrong person; their scores were 0.409, 0.409, 0.567, 0.598 and 0.615.
- Verdict: **auto-accept-disabled** (5 false accepts on the held-out half). The policy that results
  is `buffalo-l-abstain-only-v1`: match threshold 2.0 (above any cosine, so no face is ever matched
  automatically; the validators now allow a threshold up to 2.0 for this), margin 2.0, ceiling -1.0
  (no automatic new identity), minimum detection score 0.5 (the detector's own floor, which the
  measurement ran under). Every face that has candidates abstains and waits for manual resolution; a
  face with nobody to compare with still starts a new identity (the reasoner's `NO_CANDIDATE`: no
  existing identity is asserted, and it is bookkeeping the first face of a library cannot avoid).
  The policy is an evaluated artifact: it takes effect only when the real host reads it (the next
  change); until then the application runs on the development profile.

False accepts at cosine 0.57 to 0.62 are far above the different-person 99.9th percentile. Either
the labels are wrong for those pairs (the labels are unverified Commons categories) or the model
confuses look-alikes; this set cannot say which, so neither is claimed. The result stands as
"separation is not stable on this set", which is the owner's trigger for ABSTAIN-only operation.
It is a statement about this set, not about the model in general.

Provenance of the numbers: local report `evaluation/datasets/reports/conservative.json` (never
committed), produced by `uv run python evaluation/measure_operating_point.py --dataset
evaluation/datasets/commons-pd --local-state-root local-models/state --report <path> --conservative
--write-policy local-models/state/policies/insightface-buffalo-l.json`; weights digest and dataset
manifest hash as in "Run". Re-run it when the set grows or is verified; a policy that passes the
rule is written by the same command.

## Limits

Small set of formal adult portraits of public figures; unverified labels; leave-one-out open set;
CPU run (CUDA agreement is checked separately); the dataset can be rebuilt with
`evaluation/build_commons_dataset.py`. The numbers describe this set and nothing wider.
