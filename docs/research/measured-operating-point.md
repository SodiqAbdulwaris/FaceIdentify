# Measured operating point for `buffalo_l` (TST-044, first baseline)

**Date:** 2026-10-07. **Status:** measured; the policy built from it waits on an owner decision
(see "What the numbers say"). Numbers only: no photograph is recorded or committed.

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
end is 0.875. Calling this threshold "calibrated to 99%" would be false. Options (owner's call, not
taken by the agent): ship the measured point under an honest notice (held-out precision about 78%);
choose the threshold from the different-person tail (for example above 0.326) and accept lower recall;
or auto-accept nothing (ABSTAIN) until a larger, verified set exists. No new identity ceiling is
available either.

## Limits

Small set of formal adult portraits of public figures; unverified labels; leave-one-out open set;
CPU run (CUDA agreement is checked separately); the dataset can be rebuilt with
`evaluation/build_commons_dataset.py`. The numbers describe this set and nothing wider.
