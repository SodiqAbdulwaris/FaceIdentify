# Evaluation 04 The label-review tool

## 1. What this is and why it exists

The evaluation set's identity labels are Wikimedia Commons *categories*: a human-curated hint, not proof that the photograph shows that
person. Every number computed on them carries that doubt. `label_review.py` is a small local tool that lets a **person look at each photograph
and say whether its label is right**, and exports a **verified manifest** that the gate script can use instead. It never approves anything by
itself and never looks at embeddings.

## 2. Where it lives

| Thing | Where |
|---|---|
| The tool (`serve`, `status`, `export`; `Review` class; a small web page served locally) | `evaluation/label_review.py` |
| The step before it: find the faces and suggest one (issue #181) | `evaluation/review_detections.py` |
| The box rule shared by the tool and the evaluation scripts | `evaluation/face_boxes.py` |
| Their tests (no real photographs) | `tests/unit/test_label_review.py`, `tests/unit/test_label_review_faces.py` |
| The faces the detector found, with provenance | `<dataset>/review/detections.jsonl` |
| The log it appends to | `<dataset>/review/decisions.jsonl` |
| Exports | `<dataset>/review/exports/verified-<UTC time>.json` |
| Plan | [`docs/plans/M5_REMAINING_WORK.md`](../../../plans/M5_REMAINING_WORK.md) (R5) |

## 3. How it works

- **Nothing is overwritten.** The original `manifest.json` and the photographs are never touched. Each decision is one **appended** line:
  reviewer, UTC time, photograph, its SHA-256, the label it was reviewed under, the manifest's SHA-256, the decision, any correction, flags and a
  note. The latest line for a photograph is current; older ones stay as the audit trail; a half-written last line from a crash is ignored.
- **A decision belongs to what was looked at.** If the photograph's bytes or its proposed label change, the decision is `stale` and needs a new review.
- **Decisions**: `VERIFIED`, `INCORRECT` (give the right name if you know it, which then counts as human-confirmed), `UNCERTAIN`, `EXCLUDED`
  (the last two never count). **Flags** `AMBIGUOUS`, `LOW_QUALITY`, `MULTI_PERSON` keep a photograph out even if marked verified (conservative on purpose). One exception: a photograph flagged only `MULTI_PERSON` may enter once a face is selected (section 3a).
  `same_picture_as` groups copies so they count once and never cross a split.
- **The export** lists only photographs that are verified, unflagged, unchanged and used once, with provenance, and reports a *shortfall*
  against the TST-057B targets (initial targets: 40 verified identities, 80 verified queries) rather than padding. Each export is a new file.
- **The server** listens on 127.0.0.1 only; every request carries a per-run token; it serves only files the manifest lists; the page draws names as text, never markup.
  `serve` takes `--reviewer` and `--port`.

## 3a. Which face? (issue #181)

A photograph can show several people while its label names one. The gate used to leave such a photograph out (no face clearly the
largest). Now a person says which face it is, and the evaluation uses *that* face. Three rules keep this honest:

1. **The model only suggests.** `review_detections.py` runs the installed detector the way the application does (its decoder, EXIF
   orientation applied, so the boxes are in the same upright frame the gate sees) and stores every face it found, with its provenance
   (package key and version, model file digests, detector settings), in `review/detections.jsonl`. For a photograph of several faces it
   suggests the face that looks most like faces in the *other photographs of the same label*; a photograph with one face suggests that face.
   It never suggests by size or by being central: those are accidents of a dataset, not evidence of who someone is. The page draws the
   suggestion dashed and labelled "Suggestion - not verified", and selects nothing for you.
2. **You confirm explicitly.** Click the face (or press `Draw a box` and drag, when the detector missed it or boxed it badly), then press
   `VERIFIED`. Choosing another face overrides the suggestion; `None / cannot determine` rejects it. A confirming decision with no face is
   refused when the photograph has detections. The decision stores the box (`[x1, y1, x2, y2]`, fractions of the upright picture), the
   suggestion that was offered and what became of it (`CONFIRMED`, `OVERRIDDEN`, `REJECTED`, `NOT_ADDRESSED`, `NONE_OFFERED`), and the detection run.
3. **The approval binds to the photograph and the box, never to "face number 2".** The record carries the photograph's SHA-256 and the
   geometry. Changed bytes, a changed label, a different picture size, or (for a detected box) a new detection run that has no face
   corresponding to it make the decision `stale` with the reason, so it is reviewed again. The gate and the operating-point script find the
   detected face that corresponds to the box (intersection over union of at least 0.5, and only one face that close); if none does, the
   photograph is left out as an "annotation mismatch" and no other face is taken instead.

Records are schema 2; schema 1 lines in an old log stay readable and count as before. The export is schema 2; a script that only knows
schema 1 refuses it rather than ignoring the boxes.

**The first real use** is recorded in `docs/implementations/2026-10-12-m5-first-verified-label-run.md`: the owner reviewed 292 of 662 photographs; the verified export was then used for the first run on
human-verified labels. Reviewing is slow and has a selection effect (the photographs a person can confidently identify are the easy ones), which is why the export reports its shortfall honestly.

## 4. Try it

**Works with no real data (a synthetic set). Verified 2026-10-12; the face commands below verified 2026-11-14.** Make a tiny set of invented pictures under the git-ignored folder (the tool
refuses datasets elsewhere), review it, export, and delete it:

```bash
uv run python - <<'EOF'
import json, pathlib, random
from PIL import Image
root = pathlib.Path("evaluation/datasets/practice")
manifest = {}
for person, base in (("Person One", (200, 60, 60)), ("Person Two", (60, 60, 200))):
    (root / person).mkdir(parents=True, exist_ok=True)
    manifest[person] = []
    for i in range(3):
        file = f"{person}/{i:02}.png"
        image = Image.new("RGB", (64, 64), base)
        pixels = image.load()
        rnd = random.Random(i)
        for _ in range(200):
            pixels[rnd.randrange(64), rnd.randrange(64)] = (rnd.randrange(256),) * 3
        image.save(root / file)
        manifest[person].append({"file": file, "title": f"File:{person}-{i}.png"})
(root / "manifest.json").write_text(json.dumps(manifest))
EOF
PYTHONPATH=. uv run python evaluation/label_review.py status --dataset evaluation/datasets/practice
```

Observed: `photographs 6, reviewed 0, unreviewed 6`, and zero in every decision. Record some decisions the way the web page does, through the
`Review` class the page uses, then look again and export:

```bash
PYTHONPATH=. uv run python - <<'EOF'
from pathlib import Path
from evaluation.label_review import Review
review = Review(Path("evaluation/datasets/practice"), "practice-reviewer")
review.decide("Person One/00.png", "VERIFIED")
review.decide("Person One/01.png", "VERIFIED")
review.decide("Person One/02.png", "VERIFIED", flags=("LOW_QUALITY",))
review.decide("Person Two/00.png", "INCORRECT", corrected_identity="Person One")
review.decide("Person Two/01.png", "UNCERTAIN", note="cannot tell")
EOF
PYTHONPATH=. uv run python evaluation/label_review.py status --dataset evaluation/datasets/practice
PYTHONPATH=. uv run python evaluation/label_review.py export --dataset evaluation/datasets/practice
```

Observed: status `reviewed 5, unreviewed 1, VERIFIED 3, INCORRECT 1, UNCERTAIN 1`; the export reports `verified_photographs 3`, `identities 1`,
`identities_with_enough_images 0`, `left_out` `{not_verified: 2, flagged: 1}` and a **shortfall** of `verified_identities 40`, `verified_queries 80`:
a tiny set honestly says it is nowhere near the targets. Two files appeared: `review/decisions.jsonl` (one line per decision) and
`review/exports/verified-<time>.json`.

The interactive page: `PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/practice --reviewer <your name>`
prints the address to open (*the browser page was not driven in this session*). Tests: `uv run pytest tests/unit/test_label_review.py tests/unit/test_label_review_faces.py -q`.

To review only some people, add `--people "Name One,Name Two"` (names exactly as the manifest has them, case aside; a misspelt name stops the tool with a hint). It filters the page only: counts and the export still cover the whole dataset.

Faces, with an invented detection run (no model needed; with the real models,
`PYTHONPATH=. uv run python evaluation/review_detections.py --dataset evaluation/datasets/practice --local-state-root local-models/state`
writes the run instead):

```bash
PYTHONPATH=. uv run python - <<'EOF'
from pathlib import Path
from evaluation.label_review import Review, ReviewError
review = Review(Path("evaluation/datasets/practice"), "practice-reviewer")
file = "Person One/00.png"
review.append_detection({
    "file": file, "sha256": review.digest(file), "image_size": [64, 64],
    "faces": [{"box": [0.05, 0.1, 0.45, 0.8], "score": 0.9}, {"box": [0.55, 0.1, 0.95, 0.8], "score": 0.9}],
    "suggestion": {"box": [0.05, 0.1, 0.45, 0.8], "basis": "label_recurrence", "score": 0.5, "rationale": "practice"},
    "provenance": {"package_key": "practice", "package_version": "0", "detector": {}},
})
try:
    review.decide(file, "VERIFIED")
except ReviewError as error:
    print("refused:", error)
record = review.decide(file, "VERIFIED", face=[0.55, 0.1, 0.95, 0.8])
print(record["suggestion"]["outcome"], record["face"]["source"])
print(review.export()["people"]["Person One"][0]["face"]["box"])
EOF
```

Observed: the plain `VERIFIED` is refused ("choose the face this label belongs to..."), then `OVERRIDDEN DETECTED` (the reviewer chose the
second face, not the suggested first one) and `[0.55, 0.1, 0.95, 0.8]`, the box that the export carries and the gate will look for.

Clean up when you are done with the interactive page: `rm -rf evaluation/datasets/practice` (the `serve` command above needs the folder).

## 5. Change it

A new decision value or flag means: the constant in `label_review.py`, the rule for what counts, the export, the page, and a test in
`test_label_review.py` first. Never make an export include something not verified to "reach the target"; the shortfall must stay visible.

## 6. Break it on purpose

Edit a practice photograph's bytes after reviewing it and run `status`: `stale_needs_review` counts it, because the decision recorded the old
SHA-256. A review is bound to what was seen.

## 7. Exercises

1. Why are decisions appended rather than edited?
2. Why does a flagged photograph stay out even if verified?
3. Why report a shortfall instead of lowering the target?
4. Why does a decision store the face's box instead of "the second face the detector found"?
5. Why is the model's suggestion never selected for you?

**Answers**

1. So the audit trail shows every change of mind.
2. A flag signals doubt (ambiguous, low quality, several people); the safe choice is to leave it out.
3. A padded set would let a number look better than the evidence supports.
4. A detector's order or version can change; a box tied to the photograph's digest still says which face was meant, and a change that loses it is caught.
5. A suggestion is a guess by a model that can be wrong in exactly the hard cases; if a click could confirm it by default, the model would be grading itself.

## 8. Related files

- Previous: [03](03-assisted-gate-and-open-set.md) · Next: [05 A real-model run](05-real-model-run.md)
- [`evaluation/label_review.py`](../../../../evaluation/label_review.py), [`docs/plans/M5_REMAINING_WORK.md`](../../../plans/M5_REMAINING_WORK.md)
