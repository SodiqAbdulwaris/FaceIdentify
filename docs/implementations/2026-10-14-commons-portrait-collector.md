# The Commons portrait collector (from the owner's `facescrape.py`)

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R (evaluation data); no tracker row changes
- **Status:** built and dry-run; the collected pictures are unverified and local
- **Commits:** PR to be recorded when merged

## What changed

`evaluation/collect_commons_portraits.py`, a Commons-only collector based on the owner's
`facescrape.py` (reviewed 2026-10-14). It replaces PR 191's `--follow-years` builder options (not
merged). Changes from the owner's script, each from the review:

- **Whole-word title filter.** The old filter matched substrings and rejected "Silicon Valley",
  "Discovery Channel", "addresses", "Shoemaker" and "Iconic".
- **Only the person's own subcategories** (by year, in a year, at an event, Portraits or Photographs of),
  never a pair or group ("X and Y", "with", "family"); the disambiguation of a category such as
  `Chris Evans (actor)` is handled, and `Display Name = Category Name` is accepted in the people file.
- **The project's SCRFD detector with the gate's dominant-subject rule** (largest face at least 2.5
  times the next, and at least `--min-face` pixels on its short side) instead of OpenCV's Haar cascade:
  no new dependency, and profile and tilted faces are not filtered out before the model sees them.
- **De-duplication against every person's pictures**, not just their own (so one photograph cannot
  carry two labels).
- **CC 2.5 accepted** (`[234].[05]`), the licence still read per file and never NC or ND.
- Atomic writes that never overwrite, an uncaught decompression-bomb case handled, an ASCII folder
  name (`Beyonce`, `Zoe_Saldana`), `--dry-run` (metadata only), and no personal e-mail address in the
  User-Agent (the project URL instead).

## Why

The first automatic Commons download (PR 191) returned unusable pictures: clothing, objects, signatures
and groups. The owner's script already had the right shape; its flaws would have (a) thrown away good
photographs, (b) labelled a photograph of someone else, and (c) kept only easy frontal faces, which
would flatter any recognition result.

## Verification

- `uv run pytest tests/unit/test_collect_commons_portraits.py -q`: 22 passed (the filter on whole
  words; which categories are followed; each category read once; licences; the dominant-subject rule;
  a picture saved once across people; a re-run adds without repeating or renumbering; a dry run
  downloads nothing; output outside the datasets folder refused). ruff and mypy (both platforms) clean.
- A real dry run on six people (metadata only): accepted candidates Jason Statham 23, Zendaya 43,
  Jennifer Lawrence 150, Jenna Ortega 44, Jennifer Lopez 130, Chris Evans (actor) 141 (the old top
  category found 0 usable pictures for Zendaya, Jennifer Lawrence and Jenna Ortega).
- **Not verified:** that every followed category holds only the named person, and the licence
  metadata itself (taken as given); the labels stay unverified and need `label_review.py`.

## Open issues / follow-ups

- Review the collected labels before using the set for any claim.
- `--licence free` includes CC BY and BY-SA: attribution is in the manifest; never redistribute.
