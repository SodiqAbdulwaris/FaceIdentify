# M5 R4: the conservative operating point and its result

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, R4; TST-044 (first baseline; the policy built from it is in R4's next entry)
- **Status:** measured; the result is that automatic acceptance is disabled on this set
- **Commits:** PR to be recorded when merged

## What changed

- `evaluation/measure_operating_point.py` gains `--conservative`, `--conservative-minimum-accepted`
  and `--write-policy`. The rule: only thresholds strictly above a floor, a margin always required, zero false accepts on the selection half, then highest
  recall; the floor is the owner's 0.326 or the selection half's own tail if higher; the final half
  must show zero false accepts and recall of at least 0.25 or automatic acceptance is disabled. The report gains a `conservative` block (floor, point, final-half precision
  with Wilson interval, recall, false accepts split into unknown and known people, their scores,
  abstention rate, verdict, reason, and the `decision_policy` object). `--write-policy` writes that
  object to a file; the real host (next entry) reads it from `<local state root>/policies/`.
- `tests/unit/test_conservative_policy.py`: twelve tests of the rule's guards. Mutation-tested: the
  floor, the zero-false-accept condition, the always-required margin, the false-accept verdict and the
  useful-recall verdict were each removed in turn and a test failed each time (the first attempt at
  the margin mutation did not apply, because the formatter had re-wrapped the line; it was redone).
- `docs/research/measured-operating-point.md` (first run, the rule, the result and its limits).
- `match_threshold` may now be up to 2.0 (`DecisionPolicy`, `ProcessingRequestV1`): above 1.0 nothing
  can be matched, which is how the disabled policy is expressed (the first review found that 1.0
  still matched an exact copy). Tests: a policy with matching off abstains on an exact copy with no
  runner-up and with the widest lead, still creates an identity when nobody is retrievable, the request
  parser accepts 2.0 and refuses 2.01.
- Owner decision recorded in `M5_PLAN.md`.

## Review (Codex, read-only) and answers

- Disabled policy not ABSTAIN-only: fixed as above. The reviewer also asked that no-candidate abstain;
  it stands as `CREATE_NEW`, recorded as an agent design for the owner to confirm.
- Floor leaked the final half: fixed (`tail_floor` reads only the selection half; the owner's figure
  is a fixed input). The numbers did not change.
- Wording said the policy was in force: it is an evaluated artifact until the real host reads it.

## Why

The first run showed the 99% rule fits the selection half and not the held-out half (78.4%). The
owner chose a conservative provisional policy with a disable switch.

## Result

Threshold 0.3544, margin 0.02 was chosen on the selection half (40 of 40 correct). On the held-out
half it accepted 40 and got 5 wrong (3 queries of people never enrolled, 2 known people matched to the
wrong person, scores 0.409 to 0.615). The owner's rule therefore disables automatic acceptance: the
evaluated policy is `buffalo-l-abstain-only-v1` (threshold 2.0). Whether the false accepts are label errors or look-alikes
cannot be told from this set.

## Open issues / follow-ups

- The real host builds its request from this policy file (separate PR). The UI notice wording and
  TST-044's tracker row follow with it.
- A larger, verified evaluation set is the way to a policy that accepts anything automatically.
