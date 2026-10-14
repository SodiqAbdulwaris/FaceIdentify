# The Commons portrait collector (from the owner's `facescrape.py`)

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R (evaluation data); no tracker row changes
- **Status:** built and dry-run; the collected pictures are unverified and local
- **Commits:** PR to be recorded when merged

## What changed

`evaluation/collect_commons_portraits.py`, a Commons-only collector based on the owner's
`facescrape.py` (reviewed 2026-10-14). It replaces PR 191's `--follow-years` builder options (closed,
not merged). Changes from the owner's script, each from the review:

- **Whole-word title filter.** The old filter matched substrings and rejected "Silicon Valley",
  "Discovery Channel", "addresses", "Shoemaker" and "Iconic".
- **Only the person's own subcategories**: the name (with or without a disambiguation like `(actor)`)
  followed by exactly `by year`, `by decade`, `by event`, `by location`, `in <year>` or `at <event>`, or
  `Portraits of` / `Photographs of` the name. A longer name (`Jennifer Lopez Smith`, `Chris Evans
  (presenter)`), a pair or list (`and`, `with`, `&`, a comma, `family`, `fans`) is not followed.
  `Display Name = Category Name` is accepted in the people file.
- **Licence read from the short name and the URL together.** A Creative Commons licence must come from
  `creativecommons.org`, the family (BY or BY-SA) and the version (2.0 to 4.0, `.5` included) must agree,
  and a name or URL that mentions NC or ND is refused; public domain and CC0 keep their own check.
- **The project's SCRFD detector with the gate's dominant-subject rule** (largest face at least 2.5
  times the next, and at least `--min-face` pixels on its short side) instead of OpenCV's Haar cascade:
  no new dependency, and profile and tilted faces are not filtered out before the model sees them.
- **De-duplication against every person's pictures**, not just their own.
- **Data safety.** One collection per folder at a time (a lock file). A picture is published into a free
  number with a hard link, which refuses an existing name, so an existing picture is never replaced
  (a fallback uses a rename that refuses on Windows). The picture's full provenance is written to
  `collect-journal.jsonl` *before* the picture is published and recovered into the manifest on the next
  run (the picture is only trusted if its hash matches). The manifest and `PROVENANCE.json` are replaced
  atomically (`PROVENANCE.json` carries the manifest's digest). A person folder that is a symlink or a
  junction is refused. A set made with `--licence free` cannot be resumed with `--licence pd`.
- `--dry-run` (metadata only), a User-Agent with the project URL instead of a personal e-mail address,
  an ASCII folder name (`Beyonce`, `Zoe_Saldana`), and a name with no Latin letters is refused.

## What this set can and cannot show

A picture is kept only if SCRFD finds one dominant face of at least 75 pixels. Every detector miss, every
crowded picture and every tiny face is therefore absent by construction. The set **cannot** measure
detector recall or unfiltered end-to-end performance, and a high identity-matching score on it describes
pictures where a subject was found. The filter configuration and the rejection counts of the last run
(licence, not a JPEG, size, no dominant face, duplicate, error) are recorded in `PROVENANCE.json`.

## How to run it (not run yet)

```bash
# 1. look first (metadata only, downloads no picture):
PYTHONPATH=. uv run python evaluation/collect_commons_portraits.py --out evaluation/datasets/celebs-commons --licence free --dry-run
# 2. the real collection (about 38 people x up to 15 pictures; an hour or two at Commons' polite rate):
PYTHONPATH=. uv run python evaluation/collect_commons_portraits.py --out evaluation/datasets/celebs-commons --licence free --per-person 15
# 3. review the labels and the rights before any use:
PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/celebs-commons --reviewer <you>
```

It can be stopped and re-run: pictures are kept and an interrupted one is recovered. To use another
people list: `--people-file names.txt` (one name per line, `Display = Category` when they differ).

## Why

The first automatic Commons download (PR 191) returned unusable pictures: clothing, objects, signatures
and groups. The owner's script already had the right shape; its flaws would have (a) thrown away good
photographs, (b) labelled a photograph of someone else, and (c) kept only easy frontal faces, which
would flatter any recognition result.

## Verification

- `uv run pytest tests/unit/test_collect_commons_portraits.py -q`: 31 passed, offline (the filter on
  whole words; which categories are followed, including longer names, ampersand pairs and a
  disambiguated name; licences, including a name and URL that disagree, NC and ND, a foreign host;
  the dominant-subject rule; a picture saved once across people; a re-run adds without repeating or
  renumbering; a free name that never replaces; recovery from the journal; a policy conflict; the lock;
  a linked person folder refused; rejection counts; a dry run downloads nothing; output outside the
  datasets folder refused). ruff and mypy (both platforms) clean.
- **The collector itself was not run** at the owner's request (the owner will run it later), so the
  numbers of pictures per person are not known; an earlier dry run of the previous version of the
  crawl (metadata only) found 23 to 150 allowed candidates for six people.
- **Not verified:** live Commons behaviour of the final version, real SCRFD inference inside it, that
  every followed category holds only the named person, and the licence metadata itself (taken as given).

## Open issues / follow-ups

- Review the collected labels before using the set for any claim.
- `--licence free` includes CC BY and BY-SA: attribution is in the manifest; never redistribute.
