# 06 Evaluation and operations

Two kinds of knowledge that keep a recognition product honest: **how the numbers that judge a face are measured** (evaluation), and
**how the project is run** (rules, branches, reviews, milestones, trackers, decisions).

| Lesson | Teaches |
|---|---|
| [01 Evaluation overview](01-evaluation-overview.md) | what is measured, why it needs local data, and the safety rules |
| [02 Measure the operating point](02-measure-operating-point.md) | `measure_operating_point.py`: the protocol and its flags |
| [03 The assisted gate and the open set](03-assisted-gate-and-open-set.md) | `assisted_recognition_gate.py` end to end |
| [04 The label-review tool](04-label-review-tool.md) | turning unverified labels into evidence |
| [05 A real-model run](05-real-model-run.md) | install the models, smoke test, run the real profile |
| [06 Rules, branches and reviews](06-rules-branches-reviews.md) | the branch / commit / PR workflow, step by step |
| [07 Milestones, the tracker and decisions](07-milestones-tracker-decisions.md) | how to read the plans, the status page and the decisions |

**Everything that needs photographs or model weights is local only** (`evaluation/datasets/` and `local-models/` are git-ignored and are never
committed; the photographs are biometric data). This folder therefore **describes** those scripts and shows their `--help`; it does not
reproduce their results. What *can* be run anywhere without data is marked **works with no models**.

Back to the [guide index](../README.md).
