# Evaluation 01 Overview

## 1. What this is and why it exists

The decision policy ([recognition](../03-backend/recognition/03-decision-policy.md)) turns similarity numbers into decisions. Those
numbers must come from **measurement**, not from guessing, because a wrong automatic match merges two people's memories. The
evaluation scripts measure, on a labelled set of photographs, how well the installed models separate *the same* person from
*different* people, and what happens when the application is driven the way a person would drive it. The result so far is sobering and
it is why automatic matching is switched off (a later run on owner-verified labels looks much better but is too small and too easy to change that) ([measured operating point](../../research/measured-operating-point.md)).

## 2. Where it lives

| Script | What it does | Size |
|---|---|---|
| `evaluation/build_commons_dataset.py` | builds a small public-domain, identity-labelled set from Wikimedia Commons into `evaluation/datasets/` | 174 lines |
| `evaluation/import_labelled_dataset.py` | imports a ready-labelled public dataset (LFW or CelebA) that you downloaded yourself into `evaluation/datasets/<name>/`, with a `PROVENANCE.json` saying the labels are the creators', not verified here | 197 lines |
| `evaluation/label_review.py` | a local tool to review labels by eye and export a **verified** manifest | 572 |
| `evaluation/measure_operating_point.py` | measures separation and picks a decision threshold (TST-044) | 478 |
| `evaluation/assisted_recognition_gate.py` | drives the real application through its HTTP API (TST-057A) | 748 |
| `scripts/install_reference_models.py`, `scripts/smoke_real_models.py` | install the model package; run it on pictures | 63 and 101 |
| Reports | local JSON under `evaluation/datasets/reports/` (not committed); numbers summarised in `docs/research/measured-operating-point.md` |
| Real-model tests | `tests/e2e/test_real_models.py`, `test_real_host.py` (marker `-m e2e`, local only) |

## 3. How it works

- **Open-set, leave-one-out, subject-disjoint.** *Open set*: some people are never enrolled, and a correct system must not "recognise"
  them. *Leave-one-out*: each photograph is a query against the others with itself removed. *Subject-disjoint*: people are split by a hash of
  their name into a **selection half** (the threshold is chosen here) and a **final half** (the threshold is *reported* here, having taken no
  part in the choice). Choosing and reporting on different people is what stops a threshold from merely memorising its own data.
- **Honest uncertainty**: results carry a Wilson 95% interval; the identity labels are Commons categories (human-curated, **not verified** unless reviewed with the label-review tool), so
  a mislabelled photograph can make the numbers look better or worse with no direction.
- **Recorded, not claimed**: each report stores the configuration, environment, exclusions and the SHA-256 of the dataset manifest.
- **Safety rules**: never commit photographs, embeddings, reports or model files; never put real personal data in docs; `build_commons_dataset.py`
  *refuses* an output folder outside `evaluation/datasets/`; do not reference the dataset's contents in documentation. The local servers
  (label review) listen on 127.0.0.1 with a per-run token.

**Which dataset?** The Commons set was the first one. On 2026-10-12 the owner **parked** it (kept as is, with its review log) and chose LFW and CelebA, which come with labels made
by their creators ([entry](../../implementations/2026-10-12-labelled-dataset-import.md); no dataset had been downloaded or run when it was written). The importer takes
`lfw` or `celeba`, `--source <extracted folder>` (required), and `--out`, `--minimum`, `--people`, `--maximum` (verified from `--help`, 2026-10-12); its selection is
deterministic (people ordered by a hash of their name), a byte-identical picture is used once, nothing is downloaded by the project, and the gate's report repeats who
supplied the labels. Its tests (`tests/unit/test_import_labelled_dataset.py`) use invented data. The dataset terms are not verified here
(`docs/research/licensing-and-commercialization.md`, section 10).

## 4. Try it

**Works with no models. Verified 2026-10-12.** See that the scripts exist and describe themselves, without any data:

```bash
PYTHONPATH=. uv run python evaluation/measure_operating_point.py --help
PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py --help
```

Observed: argument lists exactly as in the next lessons. Then read the first 40 lines of each script: each docstring is the protocol. The
unit tests for the evaluation logic that need no photographs are run with the rest of the suite (`uv run pytest tests/unit -q`).
Anything that reads photographs (`--dataset ...`) is **not runnable here**: it needs a local dataset and, for the gate, the installed
models.

## 5. Change it

Never "improve a number" by changing the protocol after seeing a result; the project rule is that rules are declared *before* a run (the
conservative rule's floor was written down first, and a review found a version that had read the final half, which was then corrected). A
protocol change is a decision recorded in `docs/research/measured-operating-point.md` and `CONTEXT.md`, with the owner.

## 6. Break it on purpose

Ask for an output folder outside the ignored area: `PYTHONPATH=. uv run python evaluation/build_commons_dataset.py --out /tmp/x` is refused by design
(*reasoned from its docstring; it also needs network access, so it was not run here*).

## 7. Exercises

1. Why is the threshold chosen on one half of the people and reported on the other?
2. Why are the labels a limit on what the numbers mean?
3. Why must no report or photograph be committed?

**Answers**

1. So the reported figure was not tuned to the data it is judged on.
2. A wrong label turns a correct match into a "false accept" or hides a real one, and nobody knows which way.
3. Photographs and their vectors are biometric data; the repository must stay free of them.

## 8. Related files

- Next: [02 Measure the operating point](02-measure-operating-point.md)
- [`docs/research/measured-operating-point.md`](../../research/measured-operating-point.md), [`docs/specs/ML_COMPONENTS_AND_EVALUATION.md`](../../specs/ML_COMPONENTS_AND_EVALUATION.md)
