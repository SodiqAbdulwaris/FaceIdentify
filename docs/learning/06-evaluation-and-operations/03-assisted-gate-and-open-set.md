# Evaluation 03 The assisted gate and the open set

## 1. What this is and why it exists

Thresholds are only part of the story; the product is a *workflow*. `assisted_recognition_gate.py` starts the **real application** in
the same process (real models, the abstain-only policy, a fresh library) and drives it **only through its HTTP API**, the way the desktop
app does: enrol people, search by face, correct, recycle and restore, merge and split, delete, forget, restart and ask again. It
measures the result of *assisted* recognition: how highly the right person is ranked when a human will choose among suggestions.

## 2. Where it lives

| Thing | Where |
|---|---|
| The script | `evaluation/assisted_recognition_gate.py` (748 lines) |
| Its tests (no photographs) | `tests/unit/test_assisted_gate.py` (14) |
| Recorded runs | `docs/implementations/2026-10-10-m5-assisted-recognition-gate.md` (first run on unverified labels: Recall@1 0.739, Recall@5 0.826, MRR 0.775), `2026-10-12-m5-first-verified-label-run.md` (human-verified labels) and `2026-10-12-m5-open-set-evaluation.md` (adds strangers) |

## 3. How it works

1. **Enrol**: for each chosen person, import all but the held-out photographs (each its own source), process them, and *place* each subject face
   into that person's identity (standing in for a human confirmation) and name the person. Automatic matching is off, so the application
   places nothing by similarity.
2. **Query (TST-057A)**: each held-out photograph is searched by face (`POST /search/face`). Metrics: Recall@1, Recall@5 and mean reciprocal rank
   over people who have at least two enrolled photographs. A query writes nothing: library counts are compared before and after.
3. **Workflow**: name search; recycle and restore; merge and split; permanent delete; forget.
4. **Restart**: stop and start again on the same library; rankings and name search must be unchanged.
5. **Open set** (`--unknown`): people never enrolled; their photographs must not be confidently attributed to anyone.

Flags (from `--help`, verified 2026-10-12): `--dataset`, `--local-state-root`, `--workdir`, `--report` (required: dataset, local state root,
report); `--manifest` (a verified manifest from `label_review.py export`), `--people`, `--unknown`, `--minimum-photographs`.

The labels are still Commons categories unless you pass a **verified manifest** ([next lesson](04-label-review-tool.md)); the report says which.

**What the recorded runs say, and do not say.** On the unverified labels the first run scored Recall@1 0.739; the owner then verified a subset of labels by eye and a
second run on that subset scored 1.000 on 18 queries, which suggests much of the earlier gap was label noise and group photographs rather than the model. The entry
is explicit that this **does not pass TST-057B** (automatic recognition): the verified set is far below the targets (9 of 40 identities with five or more photographs, 18 of 80
queries), the owner verified only photographs they could confidently identify (a selection bias that leaves the hard cases out), and 18 queries support no claim beyond "no
failures were seen". The open-set run added strangers: none of 25 was accepted as a known person. TST-057B stays `BLOCKED`.

## 4. Try it

**Needs local-only data and models: describe only, not run here.** Shape (from its docstring):

```bash
PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py \
    --dataset evaluation/datasets/commons-pd --local-state-root local-models/state \
    --workdir evaluation/datasets/gate-run --report evaluation/datasets/reports/gate.json
```

What you can run anywhere: the help, and the unit tests of its scoring helpers:

```bash
PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py --help
uv run pytest tests/unit/test_assisted_gate.py -q
```

The same *workflow* with the **development profile** (fake perception) is exercised by `npm run test:e2e` and by the API walk-throughs in
[call the API](../03-backend/api/01-call-the-api.md), which are the closest runnable cousins.

## 5. Change it

Adding a workflow step means adding it to the script *and* a unit test of its bookkeeping; the real gate stays a local run recorded in
the tracker with its evidence. Keep the step API-only: if the script reaches into the database, it stops testing what the app does.

## 6. Break it on purpose

(Conceptual.) Let a query path write a row: the "library counts before and after" check in step 2 would catch it, the same check the
backend's `test_a_search_writes_nothing_and_repeating_it_changes_nothing` makes in the other direction.

## 7. Exercises

1. Why does the gate talk to the application only over HTTP?
2. What does the open-set run test that Recall@k does not?
3. Why is automatic matching off during the gate?

**Answers**

1. It then tests exactly what the desktop app uses.
2. That people never enrolled are not confidently attributed to someone.
3. The policy is abstain-only; the gate measures ranked suggestions for a human, not automatic decisions.

## 8. Related files

- Previous: [02](02-measure-operating-point.md) · Next: [04 The label-review tool](04-label-review-tool.md)
- [`evaluation/assisted_recognition_gate.py`](../../../evaluation/assisted_recognition_gate.py), [face query](../03-backend/recognition/05-face-query.md)
