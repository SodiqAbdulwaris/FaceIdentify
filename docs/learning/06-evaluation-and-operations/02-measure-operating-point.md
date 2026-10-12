# Evaluation 02 Measure the operating point

## 1. What this is and why it exists

`measure_operating_point.py` answers one question: **at what similarity (and margin) can we accept a match automatically and still
almost never be wrong?** It measures how the installed models separate people on a labelled set and chooses a threshold by a
predeclared rule. The honest outcome so far: the threshold chosen on one half of the people did **not** hold on the other half, so
automatic acceptance stays disabled ([the result](../../research/measured-operating-point.md)).

## 2. Where it lives

| Thing | Where |
|---|---|
| The script | `evaluation/measure_operating_point.py` (478 lines) |
| Its tests (invented numbers) | `tests/unit/test_conservative_policy.py` (13) |
| The recorded result | `docs/research/measured-operating-point.md` |
| The policy it writes | `<local state>/policies/<package key>.json` (read by the real profile on every request, [profiles](../03-backend/architecture/04-profiles.md)) |

## 3. How it works

The protocol (from its docstring):

1. A photograph is *usable* if it has a subject (its only face, or a face at least 2.5 times larger than any other). A person needs at least two usable photographs.
2. People are split **by a hash of the name** into a *selection* half and a *final* half that share nobody; inside each half into *known* (the gallery) and *unknown* (never enrolled).
3. Every usable photograph queries the known people of its own half, itself left out; an identity scores as its best-matching photograph; a query needs at least two competing known identities.
4. A query is *accepted* if its best score and its margin to the runner-up reach the policy. It is correct if the accepted identity is the person; an unknown person's accepted query is wrong.
5. **Standard rule**: choose, on the selection half only, the point with the highest recall among those with precision at least 0.99, at least `--minimum-accepted` accepted queries and recall at least `--minimum-recall`; none means ABSTAIN. Report that point on the final half with a Wilson 95% interval.
6. **`--conservative`** (owner decision 2026-10-07): only thresholds strictly above a floor, zero false accepts on the selection half, then the highest recall; the final half must show zero false accepts and recall at least `--minimum-recall` (default 0.5), else automatic acceptance is disabled; no new-identity ceiling.

Flags (from `--help`, verified 2026-10-12): `--dataset`, `--local-state-root`, `--provider` (default `CPUExecutionProvider`), `--report`,
`--minimum-accepted` (30), `--minimum-recall` (0.5), `--minimum-below` (20), `--conservative`, `--conservative-minimum-accepted` (20),
`--tail-floor`, `--write-policy`. `--dataset`, `--local-state-root` and `--report` are required.

## 4. Try it

**Needs local-only data and models: describe only, not run here.** The shape of the command (from the docstring):

```bash
uv run python evaluation/measure_operating_point.py --dataset evaluation/datasets/commons-pd \
    --local-state-root local-models/state --report evaluation/datasets/reports/commons-pd.json
```

*Unverified here, with the reason:* it reads photographs from `evaluation/datasets/` and runs the installed models; neither exists in a fresh
clone (they are never committed). **What you can run:** the help text and the rule's unit tests, which use invented numbers:

```bash
PYTHONPATH=. uv run python evaluation/measure_operating_point.py --help
uv run pytest tests/unit/test_conservative_policy.py -q
```

Read the test names as the rule in sentences: `test_only_scores_above_the_floor_can_be_the_threshold`,
`test_a_false_accept_on_the_selection_half_rules_a_threshold_out`, `test_a_margin_is_always_required`,
`test_the_floor_reads_only_the_photographs_it_is_given`, `test_a_disabled_policy_accepts_nothing_and_never_creates_an_identity`.

## 5. Change it

Never touch a threshold to make a number better. A change to the protocol: write the rule down first, change the tests first
(`test_conservative_policy.py`), re-run on the local set, record the result in `docs/research/measured-operating-point.md`, and get the
owner's decision. A policy file is *written by this script* (`--write-policy`); the real profile refuses any file that can match until a verified
evaluation exists (`require_abstain_first`), so a hand-edited file cannot switch matching on.

## 6. Break it on purpose

In `tests/unit/test_conservative_policy.py` the case `test_the_floor_reads_only_the_photographs_it_is_given` exists because an earlier version
of the floor had read the held-out half. If you edit the floor function to take every photograph, that test fails: the protection against
peeking is tested. (*Not run here as a mutation.*)

## 7. Exercises

1. Why is the final half never used to choose?
2. What does "ABSTAIN-only policy" mean in numbers?
3. What is the Wilson interval for?

**Answers**

1. A figure reported on the data that chose it is optimistic.
2. `match_threshold` 2.0 (unreachable), `margin` 2.0, `new_identity_ceiling` -1.0, so every face with candidates abstains.
3. It says how uncertain a proportion is when there are few queries (for example 40 correct of 51 accepted).

## 8. Related files

- Previous: [01](01-evaluation-overview.md) · Next: [03 The assisted gate and the open set](03-assisted-gate-and-open-set.md)
- [`evaluation/measure_operating_point.py`](../../../evaluation/measure_operating_point.py), [thresholds and errors](../01-basics/recognition-ideas/05-thresholds-and-errors.md)
