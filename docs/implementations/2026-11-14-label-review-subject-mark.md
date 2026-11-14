# Label review: the reviewer marks which face carries the label (issue #181)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M5 backlog (evaluation tooling); GitHub issue #181; no tracker row changes
- **Status:** the tool and the gate are built and tested; no photograph has been re-reviewed with it
  (the review of labels is the owner's), so no published number changes
- **Commits:** PR (number recorded when merged): `feat(eval): mark which face carries a label in review`

## What changed

- `evaluation/label_review.py`:
  - The page: clicking a photograph marks a point on it (a red dot; "Clear mark" removes it). The
    mark is sent with the next decision. The text under the picture says whether a face is marked.
  - `Review.decide(..., subject_point=[x, y])`: x and y from 0 to 1 across the upright picture;
    anything else is refused. The decision record carries `subject_point` (null without a mark).
  - Export: a photograph flagged `MULTI_PERSON` and nothing else, with a mark, may enter the
    verified set, and its entry carries `subject_point`. Without a mark, or with any other flag,
    it stays out as before. The manifest stays schema 1 (one optional key).
- `evaluation/assisted_recognition_gate.py`:
  - `choose_people` reads each entry's `subject_point` into `MARKS` (by photograph).
  - `subject(faces, box, mark)`: with a mark, the subject is the one face whose box holds the
    mark; no face or several faces there is "no subject". Without a mark the rule is unchanged
    (the only face, or one 2.5 times larger). Used for enrolment, queries and the workflow checks.
  - The report's configuration records `photographs_with_a_marked_subject`.
- Tests: `tests/unit/test_label_review.py` (the mark is validated, saved, served over HTTP and
  exported; a marked several-people photograph enters, an unmarked or otherwise flagged one does
  not) and `tests/unit/test_assisted_gate.py` (the marked face wins whatever its size; no face or
  two faces at the mark is no subject; a manifest's mark reaches the query's subject choice).
- `docs/guides/learning/06-evaluation-and-operations/04-label-review-tool.md`: the flags line.

## Why

The gate leaves out a photograph with several faces and none clearly largest (89 of 1,244 LFW
photographs, `2026-10-13-m5-lfw-exclusion-analysis.md`): it cannot know which face the label is
about. A reviewer can. Issue #181 asks for exactly that, and rules out "most central face" (a
dataset artefact).

## Decisions

- **The mark is a point, chosen by a person.** The tool has no detector (standard library only),
  so the reviewer clicks the face and the gate, which has the detected boxes, finds the face under
  the point. Nothing is chosen by size or position.
- **Conservative at the gate:** exactly one box must hold the mark. A mark on no face (the detector
  missed it) or inside two overlapping boxes leaves the photograph out, as "no subject".
- **A mark overrides the dominance rule**, also for a photograph with one detected face: if the
  reviewer's mark is not on it, the detected face is not the labelled person.
- **`MULTI_PERSON` alone is no longer a doubt once marked;** `AMBIGUOUS` and `LOW_QUALITY` still
  keep a photograph out.
- The picture is marked as the browser shows it (upright, EXIF applied); the application's boxes
  are in the same upright frame (`ImageOps.exif_transpose` in `backend/infrastructure/media/image.py`).

## Verification

- `uv run ruff format --check`, `uv run ruff check`, `uv run mypy`: clean.
  `tests/unit/test_label_review.py` and `tests/unit/test_assisted_gate.py`: 56 passed.
- By hand in a browser, on a generated picture of two shapes in a scratch dataset (deleted
  afterwards): a click on the second shape drew the dot there and showed "face marked at 0.75,
  0.50"; `VERIFIED` with `MULTI_PERSON` saved `subject_point` in the decision log; `export` listed
  the photograph as verified with none flagged.
- Not verified: a gate run on real photographs with marks. None exists until the owner reviews
  some; the gate's use of the mark is covered by the unit tests only.

## Open issues / follow-ups

- Re-reviewing the excluded LFW or Commons photographs with marks, and a gate run on the result,
  are the owner's.
