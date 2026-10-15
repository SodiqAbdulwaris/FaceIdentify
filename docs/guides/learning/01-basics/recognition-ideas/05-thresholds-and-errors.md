# Recognition 05 Thresholds, errors and how a policy is measured

## 1. What this is and why it exists

For one face and its best candidate, the system has one number, the **similarity** `s`. A high `s`
probably means the same person, a low `s` a different person, and in between nobody knows. A
**threshold** is the cut-off you compare `s` with. Choosing it is the most consequential decision in the
product, because the two possible mistakes cost very different amounts, and "choosing by feel" is how such
systems fail. So this project **measures** its numbers, and where the measurement is not good enough yet,
it refuses to act automatically.

## 2. Where it lives

| Thing | Where |
|---|---|
| The knobs | `DecisionPolicy` in `backend/app/recognition/reasoner.py` |
| The policy a real run uses | a file `<local state>/policies/<package>.json`, read by `load_policy` in `backend/api/real.py` |
| The measurement | `evaluation/measure_operating_point.py` (see [that lesson](../../06-evaluation-and-operations/02-measure-operating-point.md)) |
| The recorded result | `docs/research/measured-operating-point.md` |
| The tests | `tests/unit/test_conservative_policy.py`, `tests/unit/test_recognition_reasoner.py` |

## 3. How it works

### Two kinds of wrong

- A **false accept**: the system says "same person" but it was not. The worst case for FaceIdentify: a
  stranger's face goes into someone's memory.
- A **false reject**: the system fails to recognise someone it knows. Cheaper: you fix it by hand.

### The knobs

| Field of `DecisionPolicy` | Meaning |
|---|---|
| `min_detection_score` | below this detector confidence the face is not decided at all |
| `match_threshold` | the best candidate must score at least this to be considered a match (a value above 1.0 can never be reached by a cosine, so it **switches automatic matching off**) |
| `margin` | and must beat the runner-up (a different person) by at least this much |
| `new_identity_ceiling` | below this the face is clearly nobody known: a new identity (`-1.0` means never, from a weak score) |
| (between the two) | abstain |

Why a **margin**? If two different known people both score 0.60 the system cannot tell which; a match needs
a clear lead.

### Measuring a policy (the vocabulary of `evaluation/`)

- **Precision**: of the faces the system accepted, the share that was correct. **Recall**: of the faces it
  could have accepted correctly, the share it did. Raising the threshold raises precision and lowers recall.
- **Selection half and final half**: split the *people* (not the photos) into two groups that share nobody.
  Choose the threshold on one; judge it on the other, which took no part in the choice. Otherwise you "mark
  your own homework" (overfitting). This is the most important methodological rule in the evaluation code.
- **Leave-one-out**: when a photo is a query, it is removed from the gallery it is compared with.
- **Wilson interval**: a 95% range for a proportion measured on few samples. "40 of 51 correct" is not exactly
  78.4%; the honest statement is "between about 65% and 88%".
- **Label noise**: if the labels (which person is in which photo) are unverified, a wrong label looks like a
  false accept or false reject. The owner reviews labels with a local tool (see
  [the label-review tool](../../06-evaluation-and-operations/04-label-review-tool.md)).
- **Calibrated versus uncalibrated.** A *calibrated* score would be a true probability ("0.9 means right nine
  times out of ten"). These scores are raw cosines, never probabilities; "calibrated" in this project only
  means "the thresholds were measured". The mode stays `UNCALIBRATED`, and the screen says so.

### The result so far

The first rule (highest recall at 99% precision) **overfitted**: 100% precision on the selection half, 78.4%
(Wilson 95% interval 0.654 to 0.875) on the held-out half. The owner's conservative rule still left 5 false
accepts of 40 on the held-out half. So **automatic acceptance is disabled** (the `buffalo-l-abstain-only-v1`
policy: match threshold 2.0, margin 2.0, ceiling -1.0) until a larger *verified* evaluation set exists. A face
with candidates abstains and waits for you; only a face with nothing to compare with starts an identity. These
numbers describe one small set of public-domain portraits and nothing wider
(`docs/research/measured-operating-point.md`).

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The owner confirmed option A on 2026-10-15:** "A: threshold 0.45, margin 0.10, no automatic new identity." (`buffalo-l-verified-match-v1`; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.** The evaluation script's own arithmetic runs on made-up numbers,
so you can see precision, recall and the Wilson interval without any data. In `uv run python`:

```python
>>> import importlib.util
>>> spec = importlib.util.spec_from_file_location("mop", "evaluation/measure_operating_point.py")
>>> m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
>>> [round(x, 3) for x in m.wilson(40, 51)]      # 40 correct of 51: about 78%, but how sure?
[0.654, 0.875]
>>> [round(x, 3) for x in m.wilson(42, 42)]      # 42 of 42: still not "100% certain"
[0.916, 1.0]
>>> queries = [("ann","ann",0.50,0.10,True), ("bob","ann",0.40,0.39,True),
...            ("cy","cy",0.20,0.00,True),  ("dee","ann",0.45,0.20,False)]
>>> m.accepted_at(queries, 0.3544, 0.02)          # (accepted, correct)
(2, 1)
>>> m.accepted_at(queries, 0.3544, 0.30)          # a much bigger margin accepts fewer
(1, 1)
```

Each query is `(person, best person found, best score, runner-up score, is this person known)`. With a
threshold of 0.3544 and a margin of 0.02:

- `ann`: score 0.50 is above the threshold and her lead (0.50 - 0.10) is above the margin: **accepted, correct**.
- `bob`: score 0.40 is above the threshold but his lead is only 0.01 (0.40 - 0.39), below 0.02: **not accepted**
  (the system abstains; this is the margin doing its job, because the best match, `ann`, would have been wrong).
- `cy`: 0.20 is below the threshold: not accepted.
- `dee`: a stranger who was never enrolled, scores 0.45 against `ann` with a big lead: **accepted, wrong**, a
  false accept.

So `(2, 1)`: two accepted, one correct. Raise the margin to 0.30 and `dee` (lead 0.25) drops out while `ann`
stays: `(1, 1)`.

The real host refuses a policy that could match automatically until a verified evaluation exists:
`require_approved_policy` (formerly `require_abstain_first`) in `backend/api/real.py` rejects a measured policy file whose `match_threshold` is 1.0
or less (unless it equals an owner-approved operating point in `APPROVED_MATCHING`) or whose `new_identity_ceiling` is not `-1.0`. Try the policy classes, in `uv run python`:

```python
>>> from backend.app.recognition.reasoner import DecisionPolicy
>>> DecisionPolicy("v", 0.5, 2.0, 2.0, -1.0).automatic_matching       # the abstain-only policy
False
```

and run the tests of the *measuring rule*: `uv run pytest tests/unit/test_conservative_policy.py -q` (they
include `test_a_false_accept_on_the_selection_half_rules_a_threshold_out` and
`test_a_disabled_policy_accepts_nothing_and_never_creates_an_identity`).

## 5. Change it

Change the *inputs* of the made-up example until you can predict `accepted_at` before running it: lower
bob's runner-up score to 0.30 and bob joins the accepted, as a **false accept** (his best match is `ann`);
make dee's best score 0.2 and her false accept disappears. This is exactly the trade-off the real script automates over thousands of queries. To
**measure real data** you need the local evaluation set; that is described, not run, in
[measure the operating point](../../06-evaluation-and-operations/02-measure-operating-point.md).

## 6. Break it on purpose

Build a policy whose ceiling is above its threshold: `DecisionPolicy("bad", 0.5, 0.2, 0.1, 0.3)`. Expected:
`ValueError: the thresholds must satisfy -1 <= new_identity_ceiling <= match_threshold <= 2`. A margin of 0:
`ValueError: the margin is a difference of cosine similarities, above 0 (a match needs a lead) and at most 2`.
The policy refuses to exist in an inconsistent state.

## 7. Exercises

1. Which mistake is worse for FaceIdentify and why?
2. Why is it wrong to pick the threshold and report its precision on the *same* people?
3. What does a `match_threshold` of 2.0 do?
4. "40 of 51 correct" with a Wilson interval of 0.654 to 0.875: can you claim 99% precision?
5. Why does the screen say "Similarity score" and not "% alike"?

**Answers**

1. A false accept: it puts a stranger in someone's memory; a false reject costs only a manual correction.
2. The threshold was tuned to those people, so the result flatters it (overfitting); judge on people who took no
   part in the choice.
3. No cosine reaches 2.0, so nothing is matched automatically; faces with candidates abstain.
4. No; the whole interval is below 0.99.
5. Because the score is a raw cosine similarity, not a probability.

## 8. Related files

- Previous: [04 Kinds of recognition](04-kinds-of-recognition.md) · Next: [06 Nearest-neighbour search and video vocabulary](06-nearest-neighbour-and-video-vocabulary.md)
- [`docs/research/measured-operating-point.md`](../../../../research/measured-operating-point.md)
- [Decision policy](../../03-backend/recognition/03-decision-policy.md), [measure the operating point](../../06-evaluation-and-operations/02-measure-operating-point.md)
