# M5 R5: the label-review utility, the TST-057A decision and the index cleanup

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** M5 track R5; TST-057A, TST-057B (still blocked)
- **Status:** the tool is built and tested; **the review of the labels is the owner's** and has not started
- **Commits:** PR to be recorded when merged

## Owner decisions applied (2026-10-12)

1. **TST-057A: PASS the functional/integration gate, recognition quality explicitly unverified.** The real
   `buffalo_l` pipeline works end to end (40 people, 475 photographs, 46 eligible queries; Recall@1 0.739, Recall@5
   0.826, MRR 0.775; same rankings after a restart; 10 of 10 workflow checks; queries wrote nothing). These
   numbers do **not** meet the TST-057B quality bar below and, because the labels are unverified, are not proof
   that the model is inadequate. No tuning against noisy labels. The independent smoke test (below) is still owed.
2. **TST-057B provisional minimum thresholds**, on a manually verified dataset: Recall@1 >= 0.85, Recall@5 >=
   0.95, MRR >= 0.90, ranking stability after restart 100%, workflow checks 100% passing, zero unintended
   mutations by a query. Project-defined engineering targets, not industry guarantees.
3. **R5 approved** and to be done before TST-057B can pass.
4. **The stale index directory may be cleaned up after verification** (below).

## What was built

`evaluation/label_review.py` (standard library only, no new dependency), run with
`uv run python evaluation/label_review.py serve --dataset evaluation/datasets/commons-pd --reviewer <name>`:

- A local page (127.0.0.1, a per-run token on every request, serves only photographs the manifest lists) showing
  the photographs of one proposed person side by side, with VERIFIED / INCORRECT / UNCERTAIN / EXCLUDED buttons,
  the flags AMBIGUOUS, LOW_QUALITY and MULTI_PERSON, a note, and a prompt for the right name on INCORRECT.
- Every decision is a line appended to `<dataset>/review/decisions.jsonl` (reviewer, UTC time, photograph and its
  SHA-256, the manifest's SHA-256, decision, correction, flags, note). The latest line is current; older lines
  stay as the audit trail; restarting resumes. The original manifest and photographs are never touched.
- `export` writes `review/exports/verified-<UTC>.json` (schema 1): only photographs that are VERIFIED (or
  INCORRECT with a human-typed correction), unflagged, unchanged since review and used once. It records the source
  manifest and decision-log digests, the reviewers, counts, what was left out and why, and the shortfall against
  the targets (40 identities, 5+ images each, 2+ held-out queries each, 80+ queries): a shortfall is reported,
  never padded.
- Nothing is ever approved from a Commons category or from embedding similarity; UNCERTAIN, EXCLUDED and flagged
  photographs never count.
- `evaluation/assisted_recognition_gate.py` takes `--manifest <verified manifest>`, so the same script produces the
  TST-057B numbers from verified labels. Unknown-identity (open-set) reporting separate from closed-set retrieval
  is **not built yet** (see "Next").
- Tests: `tests/unit/test_label_review.py` (18) and the gate's integrity checks in `test_assisted_gate.py`.
- Smoke-checked on the real set: 44 candidate identities, 662 photographs listed, images served.

## Changes after the independent review

- A decision counts only while the photograph still has the bytes and the proposed label it was reviewed under
  (checked when serving, deciding and exporting, with a size-and-time cache); otherwise it is listed as
  `stale_needs_review`. A relabelled or replaced photograph needs a new review.
- The page draws names, titles and labels as text (DOM properties, no `innerHTML`), so a manifest title cannot run
  script and forge decisions; saving a decision keeps keyboard focus on the same button, and each card is a
  labelled group.
- A half-written last line from a crash is moved to `decisions.torn.jsonl` (kept) and the log resumes; damage
  before the end of the log stops the tool. Reads come from one snapshot under the lock; an export's digest and
  counts describe the same snapshot.
- `review/` and image reads are confined by real path (links and junctions followed); an export is a new file
  every time (microsecond name, exclusive create).
- `same_picture_as`: the reviewer declares copies or re-encodings; a group counts once (byte-identical files are
  caught automatically).
- The gate checks a verified manifest's schema and every file's digest (a changed or missing file stops the run)
  and its report says the labels were human-verified, with provenance.

## The review is the owner's

I cannot verify identities by eye on your behalf and must not guess. To do it:
`uv run python evaluation/label_review.py serve --dataset evaluation/datasets/commons-pd --reviewer <your name>`,
open the printed address, go person by person, then `... export --dataset evaluation/datasets/commons-pd`.
Then tell me, and I will run the gate on the verified manifest, add the open-set evaluation, and report against
the thresholds. If the shortfall is large, I will propose a justified expansion (not fabricate labels).

## Independent smoke test for TST-057A (owed by the owner)

With people and images that are **not** in the public dataset, in the desktop app:
1. Import several photographs of two or three known people; name each person (place their faces).
2. Search with held-out photographs of them: are they found, and ranked sensibly?
3. Do several photographs of one person resolve consistently?
4. Search with a photograph of someone unfamiliar: is nobody assigned without adequate evidence?
5. Correct an identity (move a face, merge two people), restart the app: do the corrections persist?
6. Confirm searching changed nothing (the library lists and counts are unchanged).

## The stale index directory (verified 2026-10-12, not yet deleted)

`local-models/state/indexes/f0fd4e92c8c8492097e2307e82000af9` holds one derived USearch index (3 vectors, built
under a test clock on 2026-01-01). Checked: it is a rebuildable index, not authoritative data; none of the 115
library databases found on this machine (the application's, the gate runs', the test temp folders) has a
representation space with this id; no application or Python process was running. To delete exactly that
directory (not its parent), in PowerShell from the project folder:

```powershell
$d = Join-Path (Get-Location) 'local-models\state\indexes\f0fd4e92c8c8492097e2307e82000af9'
if ((Split-Path $d -Leaf) -eq 'f0fd4e92c8c8492097e2307e82000af9' -and (Test-Path $d)) { Remove-Item -LiteralPath $d -Recurse -Force }
```

It is recorded as pending until you run it; the evaluation gates use their own state folders and are untouched.

## Next

TST-057B needs the verified manifest first, then: the gate on verified labels, an open-set evaluation (unknown
people: false matches and abstentions, reported apart from closed-set retrieval), per-identity retrieval,
the manual smoke test, and the comparison with the baseline kept in
`evaluation/datasets/reports/gate.json` (unverified labels, 2026-10-10).
