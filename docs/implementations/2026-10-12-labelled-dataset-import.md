# Evaluation on ready-labelled datasets (LFW and CelebA); the Commons set is parked

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** M5 track R (TST-057B evidence); owner decision of 2026-10-12
- **Status:** the importer is built and tested; **no dataset has been downloaded or run yet**
- **Commits:** PR to be recorded when merged

## Owner decision

The owner parks the Wikimedia Commons set (`evaluation/datasets/commons-pd`, with its review log, kept as it
is) and evaluates on **LFW** and **CelebA**, which come with identity labels made by their creators. The owner
will label the own set later.

## What was built

- `evaluation/import_labelled_dataset.py lfw|celeba --source <extracted folder>`: reads the folder the owner
  downloaded (nothing is downloaded by the project), selects people deterministically (at least `--minimum`
  distinct pictures, at most `--people`, `--maximum` pictures each, a byte-identical picture once) and writes
  `evaluation/datasets/<name>/` (Git-ignored): the pictures, `manifest.json` in the shape the gate and the review
  tool read (with a SHA-256 per picture, which the gate checks), and `PROVENANCE.json` stating that the labels
  were supplied by the dataset creators and are **not verified by this project**.
- `assisted_recognition_gate.py` reads `PROVENANCE.json` when it sits beside the manifest and says in its report
  who supplied the labels.
- Tests: `tests/unit/test_import_labelled_dataset.py` (4).

## How to use it

1. Download LFW (the extracted `lfw/` folder of `Person_Name/Person_Name_0001.jpg`) and/or CelebA (the aligned
   images and `identity_CelebA.txt`) yourself, reading each dataset's terms.
2. `uv run python evaluation/import_labelled_dataset.py lfw --source <folder> --people 150 --minimum 5`
3. Run the gate on it, with strangers held out:
   `PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py --dataset evaluation/datasets/lfw
   --local-state-root local-models/state --workdir evaluation/datasets/gate-lfw
   --report evaluation/datasets/reports/gate-lfw.json --people 100 --minimum-photographs 5 --unknown 50`

## Cautions

- **Training overlap.** LFW and CelebA are famous people, and web-scale training sets (the recogniser was
  trained on WebFace600K) can include the same people or pictures. A model that has seen the test people looks
  better than it is. Report it as a limit; prefer people unlikely to be in training sets for any claim.
- **CelebA's aligned images are tight crops** with little context: face detection may behave differently from
  real photographs; the "in the wild" originals are better if detection fails often.
- **Labels are the creators', with some errors** (LFW is known to have a few). They are not verified here.
- **Terms not verified.** Both are research datasets; CelebA states non-commercial use. Recorded in the
  licensing file (section 10.2); never committed or redistributed.
- CelebA is large (about 200,000 pictures); the importer copies only the selection.
