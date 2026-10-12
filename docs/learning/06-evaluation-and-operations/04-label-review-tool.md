# Evaluation 04 The label-review tool

## 1. What this is and why it exists

The evaluation set's identity labels are Wikimedia Commons *categories*: a human-curated hint, not proof that the photograph shows that
person. Every number computed on them carries that doubt. `label_review.py` is a small local tool that lets a **person look at each photograph
and say whether its label is right**, and exports a **verified manifest** that the gate script can use instead. It never approves anything by
itself and never looks at embeddings.

## 2. Where it lives

| Thing | Where |
|---|---|
| The tool (`serve`, `status`, `export`; `Review` class; a small web page served locally) | `evaluation/label_review.py` (572 lines) |
| Its tests (no real photographs) | `tests/unit/test_label_review.py` (18) |
| The log it appends to | `<dataset>/review/decisions.jsonl` |
| Exports | `<dataset>/review/exports/verified-<UTC time>.json` |
| Plan | [`docs/plans/M5_REMAINING_WORK.md`](../../plans/M5_REMAINING_WORK.md) (R5) |

## 3. How it works

- **Nothing is overwritten.** The original `manifest.json` and the photographs are never touched. Each decision is one **appended** line:
  reviewer, UTC time, photograph, its SHA-256, the label it was reviewed under, the manifest's SHA-256, the decision, any correction, flags and a
  note. The latest line for a photograph is current; older ones stay as the audit trail; a half-written last line from a crash is ignored.
- **A decision belongs to what was looked at.** If the photograph's bytes or its proposed label change, the decision is `stale` and needs a new review.
- **Decisions**: `VERIFIED`, `INCORRECT` (give the right name if you know it, which then counts as human-confirmed), `UNCERTAIN`, `EXCLUDED`
  (the last two never count). **Flags** `AMBIGUOUS`, `LOW_QUALITY`, `MULTI_PERSON` keep a photograph out even if marked verified (conservative on purpose).
  `same_picture_as` groups copies so they count once and never cross a split.
- **The export** lists only photographs that are verified, unflagged, unchanged and used once, with provenance, and reports a *shortfall*
  against the TST-057B targets (initial targets: 40 verified identities, 80 verified queries) rather than padding. Each export is a new file.
- **The server** listens on 127.0.0.1 only; every request carries a per-run token; it serves only files the manifest lists; the page draws names as text, never markup.
  `serve` takes `--reviewer` and `--port`.

**The first real use** is recorded in `docs/implementations/2026-10-12-m5-first-verified-label-run.md`: the owner reviewed 292 of 662 photographs; the verified export was then used for the first run on
human-verified labels. Reviewing is slow and has a selection effect (the photographs a person can confidently identify are the easy ones), which is why the export reports its shortfall honestly.

## 4. Try it

**Works with no real data (a synthetic set). Verified 2026-10-12.** Make a tiny set of invented pictures under the git-ignored folder (the tool
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
`review/exports/verified-<time>.json`. Clean up: `rm -rf evaluation/datasets/practice`.

The interactive page: `PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/practice --reviewer <your name>`
prints the address to open (*the browser page was not driven in this session*). Tests: `uv run pytest tests/unit/test_label_review.py -q`
(`56 passed` together with the other two evaluation unit files).

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

**Answers**

1. So the audit trail shows every change of mind.
2. A flag signals doubt (ambiguous, low quality, several people); the safe choice is to leave it out.
3. A padded set would let a number look better than the evidence supports.

## 8. Related files

- Previous: [03](03-assisted-gate-and-open-set.md) · Next: [05 A real-model run](05-real-model-run.md)
- [`evaluation/label_review.py`](../../../evaluation/label_review.py), [`docs/plans/M5_REMAINING_WORK.md`](../../plans/M5_REMAINING_WORK.md)
