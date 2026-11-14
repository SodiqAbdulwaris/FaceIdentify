# Label review: the model suggests the face, a reviewer confirms it (issue #181)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M5 backlog (evaluation tooling); GitHub issue #181 (**stays open**); no tracker row changes
- **Status:** the workflow is built and tested; **no photograph has been confirmed by a reviewer with it**, so no
  evaluation number has changed and the re-measurement with a newly verified set is the owner's step (below)
- **Commits:** PR (number recorded when merged): `feat(eval): review confirms which face carries a label`.
  It supersedes the earlier, simpler attempt (draft PR 288, a click-to-mark point), which did not meet the owner's
  decision of 2026-11-14 and whose documents called the issue built and closed; those claims are removed here.

## The decision this follows

The owner's architecture decision for #181 (locked 2026-10-14, confirmed 2026-11-14): a model **suggests** the face for
the supplied label, a human **confirms**; nothing the model offers is ground truth until a reviewer acts. No central-face,
largest-face or detector-index heuristic is proof. The feature is evaluation annotation, not enrolment. The issue stays
open until verified, and the owner said not to call an issue complete because its decision is documented.

## Audit: what existed, what was missing

Existing before this change (`main`):

- `evaluation/label_review.py`: an append-only decision log (`decisions.jsonl`, schema 1) with reviewer, time,
  photograph digest, manifest digest, label, decision, flags, note, `same_picture_as`; staleness when bytes or label change;
  an export (`verified-<time>.json`) that includes only verified, unflagged, unchanged, once-used photographs; a
  127.0.0.1-only server with a per-run token, text-only page, confinement to the dataset folder. **No detector, no
  boxes, no geometry.** `MULTI_PERSON` simply kept a photograph out.
- `evaluation/assisted_recognition_gate.py`: `subject()` = the only face or one 2.5 times larger than the next
  (`DOMINANCE`), otherwise the photograph is left out as `no_subject`. No way to say which face.
- `evaluation/measure_operating_point.py`: the same dominance rule (`dominant`) on a PIL-decoded picture (EXIF
  orientation **not** applied), so a reviewer's box on the upright picture would not even be in its frame.
- `evaluation/analyse_exclusions.py`: runs the installed detector in process and shows that 89 of 1,244 LFW photographs
  are left out only because several faces have no clear subject (46 enrolment, 10 known-person queries, 33 stranger
  queries); 5 more have no face.
- Draft PR 288 (the starting point): a click point `subject_point`, matched in the gate through a module-level `MARKS`
  dict. It showed no detected boxes, offered no suggestion, stored no geometry or provenance, and the dict could go stale
  between calls.

Missing against the decision (all built here): detected faces shown with selectable boxes; a model suggestion marked
unverified; confirm / override / reject / none; correcting a box; versioned records with geometry, provenance and the
suggestion outcome; binding to the photograph digest and the box, not an index; invalidation when correspondence
changes; an export that carries the geometry; the gate and operating-point script consuming it with a stated matching
rule and a named exclusion when it does not match.

## What changed

- **`evaluation/face_boxes.py` (new).** The shared box rule. Boxes are `[x1, y1, x2, y2]`, fractions of the upright
  picture (EXIF orientation applied, the application's own decoding). `checked` validates a box (four finite numbers,
  inside 0..1, with width and height). `match_face(selected, faces)`: a detected face corresponds to the selection when the
  intersection over union is **at least 0.5** and it is the **only** one that close; otherwise no correspondence.
  Why 0.5: the detector's own suppression keeps two of its faces below 0.4 overlap, so for a face it sees at all 0.5
  tolerates the small shifts of another run or detector version and cannot mix up two neighbours; two faces both at or
  above 0.5 are ambiguous and count as no match. The position it returns is never stored.
- **`evaluation/review_detections.py` (new): detection is a precomputed step**, not on demand. Reasons: the review
  server stays standard-library and needs no model; boxes are reproducible and auditable; detection provenance belongs to a
  run, not to a click. It runs the installed detector and embedder through the production worker on pictures decoded
  by `decode_image` (EXIF applied) and appends one record per photograph to `<dataset>/review/detections.jsonl`:
  faces (box, score), the suggestion (or none), the upright image size, and provenance (package key and version, detector
  and embedder model file names and SHA-256, provider, detector settings, decoder, suggestion method). A record equal to the
  newest one of the same bytes is not appended again. Embeddings are used in memory and never written.
- **`evaluation/label_review.py`.**
  - Decision records are **schema 2** (schema 1 lines stay readable and count as before; a newer schema is refused):
    an immutable `id`, `supersedes` (the previous decision of that photograph), `face_choice` (`SELECTED`,
    `NONE_OR_CANNOT_DETERMINE`, null), `face` (`box`, `image_size`, `source` `DETECTED` or `CORRECTED`, `frame`),
    `suggestion` (`outcome` `CONFIRMED`, `OVERRIDDEN`, `REJECTED`, `NOT_ADDRESSED`, `NONE_OFFERED`, and what was offered), `detection`
    (the run's id and provenance). The old `subject_point` of PR 288 is gone (it never reached `main`).
  - `decide(..., face=<box>, none_or_cannot_determine=...)`. **A confirming decision (`VERIFIED`, or `INCORRECT` with a
    correction) on a photograph that has a detection run is refused without a selected face**; the suggestion is never filled
    in for the reviewer. `none / cannot determine` goes with `UNCERTAIN` or `EXCLUDED` and records `REJECTED` when something
    was offered (a decision made without answering the suggestion records `NOT_ADDRESSED`). The outcome is computed on the server from the boxes (the offered box and the chosen one at IoU 0.95 or
    more is `CONFIRMED`), not trusted from the page.
  - Validity (`_why`): changed bytes, changed label, an invalid box, a different picture size than the newest detection run
    of the same bytes, or, for a `DETECTED` box, a newer run with no face corresponding to it make the decision **stale**;
    the export lists each stale photograph under its reason (`stale_reasons`). A confirming decision made without a face before the faces were known (no
    detection run then) turns stale as `face_not_reviewed` once a run exists, so such a photograph is never exported without
    geometry once detections exist. A box the reviewer drew (`CORRECTED`) is theirs
    and is not tied to a detector. A suggestion made for another label is not shown.
  - Export **schema 2**: each verified photograph that has a face carries `face` and `review` (decision id, reviewer,
    time, suggestion outcome, detection run); top-level `geometry_frame`, `detection_provenance`,
    `counts.verified_with_a_selected_face`, `stale_reasons`. `MULTI_PERSON` alone no longer keeps a photograph out once a
    face is selected; `AMBIGUOUS` and `LOW_QUALITY` still do. A verified photograph without a face (legacy workflow, or no
    detection run) exports as it always did.
  - The page: every detected face is a numbered, keyboard-focusable box; the suggestion is dashed orange and labelled
    "Suggestion - not verified"; nothing is selected for you; click a box to select it, `Draw a box` for a missed or
    mis-boxed face, `Clear selection`, `Enlarge` (zoom), and a separate `None / cannot determine` button. All text goes in as
    text (no `innerHTML`).
- **`evaluation/assisted_recognition_gate.py`.** `MARKS` is gone. `choose_people` validates each entry's `face` and puts the
  boxes in the person's own `selected` map (copied to people used as strangers); `subject(faces, box, selected)` returns the
  one detected face that corresponds (`match_face`), else `None`: **never** the only or the largest face. A new exclusion
  rule `annotation_mismatch` ("the detector found no one face that corresponds to the reviewer's selected face") is listed in
  `log.exclusions` for enrolment photographs and for known and stranger queries, with its count. A schema 1 or 2 verified
  manifest is accepted. A photograph without a selected face uses the dominance rule exactly as before.
- **`evaluation/measure_operating_point.py`.** `pick_subject(photo, detections)`: with a selected face, the corresponding
  detection or `annotation_mismatch` (counted in `photographs_without_a_usable_subject`); without, the dominant face as before.
  A photograph with a selected face is decoded with the application's decoder (the frame the box is in); every other
  photograph is read as before, so existing results are unchanged. The embedding cache key includes the box.
- `docs/guides/learning/06-evaluation-and-operations/04-label-review-tool.md`: a new section 3a, the files table, a worked
  example and two exercises.

## What the suggestion is based on

Not on size or position. A photograph with **one** detected face suggests it (`sole_face`: nothing else to choose from,
and still not verified). A photograph with several faces suggests the face that looks most like faces in the **other
photographs of the same label** (`label_recurrence`): each face is scored by the mean, over the other photographs, of its
best cosine similarity to any face there; the person the label names recurs, the people beside them mostly do not. It is
offered only when at least two other photographs of the label have faces, the best face scores at least 0.326 (the owner's
measured different-person tail from 2026-10-07, used only as "worth offering", not as a verdict) and strictly more than the
next. The stored `score` is the raw cosine consensus and the rationale says it is **not a probability or a confidence**: the
model has no calibrated score for this and none is invented. Weakness to know about: it needs the label's other photographs
to show the person, so a label whose photographs are mostly wrong or mostly group shots gets a poor or no suggestion; the
reviewer sees that it is unverified and can override it. Whether a suggestion is right is judged only by a reviewer, and none has been.

## Decisions (no spec changed)

- Detection is a precomputed step stored under the dataset's `review/` folder (above).
- A face selected from a detection and a drawn one are both stored as geometry; the gate matches either to the detector
  by IoU, so a box the detector could not reproduce is left out (`annotation_mismatch`), never replaced.
- The export schema is bumped to 2 so that a consumer that does not know geometry **refuses** the file instead of silently
  using the dominant face. `measure_operating_point.py` and the gate accept 1 and 2. `import_labelled_dataset.py` and the
  other scripts do not read verified manifests (checked with a search for `verified-manifest`).
- A relabelled photograph, new bytes or a lost correspondence need a new review; an older decision is never edited.
- `measure_operating_point.py` still decodes unreviewed pictures without applying EXIF orientation. That is existing
  behaviour (left alone so results do not change) and is noted as a follow-up.

## Verification

All commands from the repository root of this change.

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`: clean.
- New and changed tests: `tests/unit/test_label_review_faces.py` (25), changed `test_label_review.py`,
  `test_assisted_gate.py`, `test_measure_operating_point_manifest.py`. They cover the acceptance list on synthetic
  pictures only: an unconfirmed suggestion never becomes ground truth (and a verdict without a face is refused); an
  override exports the reviewer's box, not the suggestion; `none / cannot determine` and no detection never produce a
  face; permuting the detected faces (in the store, in the gate's `subject`, and in `pick_subject`) changes nothing; changed
  bytes, a changed label, a different picture size, an invalid box and a geometry that no longer corresponds are excluded
  and listed with the reason; a selected face with no corresponding detection is left out and **not** replaced by the only or
  largest face (gate and operating-point script); the history stays auditable across a schema-1 line, restarts, a torn last
  line and a newer-schema refusal; a schema-1 or face-less manifest still gives the same cache key and the same dominance
  results. The existing single-face tests pass unchanged apart from the three that name the schema number or list the
  exclusion rules (a new key).
- **By hand, in the browser** (the built-in browser on `127.0.0.1`, a generated dataset of three pictures with two drawn
  ellipses as "faces" and a synthetic detection run, in a scratch folder under `evaluation/datasets`, kept out of Git): the
  boxes were numbered and the suggested one was dashed orange with "Suggestion - not verified" and not selected; pressing
  `VERIFIED` with nothing selected showed the refusal; clicking face 2 and `VERIFIED` saved `OVERRIDDEN` with the box of face
  2; on the picture where the detector found no face, `Draw a box` and a mouse drag drew a box and `VERIFIED` saved it as
  `CORRECTED`; `None / cannot determine` saved `UNCERTAIN` with `face_choice NONE_OR_CANNOT_DETERMINE`; `export` carried the
  two selected boxes. Not checked by hand: a touch screen, a real photograph in the page, other browsers.
- **What is and is not covered for the page.** Nothing automated executes the page's JavaScript: the tests cover the
  server (state with faces and suggestion, the decision route, refusals), the stored records and the page source (no
  `innerHTML`, the suggestion wording), but not the click and drag arithmetic for a letterboxed picture (`object-fit:
  contain`), the keyboard selection or the zoom. Those were exercised only by the manual check above, with a picture
  whose shape differs from its frame. An independent review of the earlier draft confirmed the coordinate transform, the
  text-only DOM building, the token check and that EXIF orientation is applied before detection; a browser test of the
  page is a follow-up (the repository has no browser harness for these local tools).
- **Independent review** (read-only subagent, because Codex was at its usage limit; posted on the PR): no blocker. Fixed from it:
  a face-less verdict made before detections existed is now stale (`face_not_reviewed`) once a run exists, so nothing is
  exported without geometry then; the page no longer pre-selects a saved box (it is shown dotted, and a decision needs a
  fresh selection; re-checked in the browser); `REJECTED` is recorded only for "none / cannot determine", otherwise
  `NOT_ADDRESSED`; a complete last record that only lost its newline is kept; `tests/unit/test_face_boxes.py` tests the
  matching boundaries. Not changed: the gate accepts a `face` in a schema 1 manifest (the exporter writes it only in schema 2).
- A flaky test was found and fixed on the way: the unauthorised-POST check failed about one run in ten on Windows
  (`ConnectionAbortedError`) because the server answered 403 before reading the request body. The handler now reads the
  bounded body first; 60 consecutive runs of that test passed.
- Geometry is accepted only as an explicit list or tuple of four real, non-boolean, finite numbers (a string such as
  "01", booleans or other iterables are refused), with a regression test; two manifests used one after the other never
  share a selected face (a test; there is no module-level state).
- **The full backend suite** (`uv run pytest`, this machine, 18 min): 3,695 passed, 74 failed, 30 errors. Every failure and
  error is in `tests/integration` and is `MediaToolsMissingError` (the pinned ffmpeg is not installed in the test
  profile here; CI installs it), in the video, camera and import tests; none touches `evaluation/`. They were not
  re-run with ffmpeg here; CI's result for the exact head is the evidence.
- **Real models, counts only** (the installed `insightface-buffalo-l` 1.0.0, CPU): `review_detections.py` on a scratch set
  of 22 LFW photographs of three people: 22 appended, none undecodable or refused; 15 with one face, 7 with several, none
  without; a suggestion for every photograph (15 sole face, 7 label recurrence). No photograph was looked at to judge it,
  and nothing was confirmed. The scratch copy is deleted.
- **Baseline re-measured** (`analyse_exclusions.py` on LFW, 100 known and 50 unknown people, unchanged code of `main`):
  enrolment 652 = 601 usable + 46 no subject + 5 no face; known queries 184 = 174 + 10 no subject; strangers 408 =
  375 + 33 no subject. This reproduces the recorded baseline of 2026-10-13 exactly. The original baseline reports are kept
  untouched.

## The honest limit, and what the owner does next

Verifying a label is a human reviewer's act, and the agent that built this is not that reviewer. It confirmed nothing,
so it produced no new coverage or performance number. What it can say is how many photographs the workflow makes
reviewable: **89 of the 1,244 LFW photographs (46 enrolment, 10 known-person queries, 33 stranger queries), spread over 56
people, are excluded only because several faces have no clear subject**; each can now be reviewed and, if confirmed, evaluated.
The 5 no-face photographs can be reviewed only by drawing a box.

The owner's steps (the folder names below are the dataset's; run from the repository root; the first line writes nothing
into the dataset except `review/detections.jsonl`):

```bash
# 1. the faces and the suggestions, for the people who have a multi-face photograph
PYTHONPATH=. uv run python evaluation/review_detections.py --dataset evaluation/datasets/lfw --local-state-root local-models/state --people "$(python -c "import json; r=json.load(open('evaluation/datasets/reports/exclusions-lfw-181-baseline.json')); print(','.join(sorted({x['file'].split('/')[0].replace('_',' ') for g in r['groups'].values() for x in g['records'] if x['describe']['status']=='no_subject'})))")"
# 2. look and decide, in the page (a name that is not in the manifest stops the tool with a hint)
PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/lfw --reviewer "<your name>"
# 3. export (a new file every time) and read the stale and left-out reasons
PYTHONPATH=. uv run python evaluation/label_review.py export --dataset evaluation/datasets/lfw
# 4. the gate on the verified set (the original reports stay as the baseline)
PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py --dataset evaluation/datasets/lfw --manifest <the export> --local-state-root local-models/state --workdir evaluation/datasets/gate-lfw-181 --report evaluation/datasets/reports/gate-lfw-181.json --people 100 --unknown 50
# 5. the operating point on the same export
PYTHONPATH=. uv run python evaluation/measure_operating_point.py --dataset evaluation/datasets/lfw --manifest <the export> --local-state-root local-models/state --report evaluation/datasets/reports/operating-point-lfw-181.json --conservative
```

Note that the verified export contains only photographs a reviewer confirmed, so the new run is on the verified set (as the
2026-10-12 and 2026-10-15 verified runs were), not on all of LFW; compare it with those, and with the unverified baseline
only knowing that difference. The 89 photographs add to whatever else has been verified.

## Privacy

Everything biometric stays in the Git-ignored folders: detections, decisions and exports under
`<dataset>/review/`, the scratch sets, the baseline report (it names photographs). No photograph, vector or name from a
dataset is in a test, this entry, the PR or CI; tests build pictures from solid colours. Embeddings are held in memory
while the detection step runs and are never written. The review server is unchanged in its exposure (127.0.0.1 only, a
per-run token, listed files only). No weights were written; the installed models were read from `local-models/state`
only.

## Open issues / follow-ups

- **Issue #181 stays open** until a reviewer has used the workflow on real photographs and the evaluation has been re-run on the
  confirmed set. This entry does not close it.
- `measure_operating_point.py` applies no EXIF orientation to a picture without a selected face (existing behaviour; the
  gate sees the oriented picture). Aligning them would change published numbers, so it is the owner's call.
- The label-recurrence suggestion needs at least two other photographs of the label with faces, so a person with few
  photographs gets none (or a sole-face suggestion); lowering that is a judgement for after real use.
