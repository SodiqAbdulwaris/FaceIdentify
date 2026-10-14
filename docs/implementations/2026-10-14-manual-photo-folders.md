# Hand-collected celebrity photographs: folders, guide and numbering script

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R (evaluation data); no tracker row changes
- **Status:** done; the pictures themselves are the owner's to collect
- **Commits:** PR to be recorded when merged

## What changed

- `evaluation/prepare_manual_dataset.py` with two commands: `init` makes one folder per person from
  `people.txt` (38 people by default, editable) under `evaluation/datasets/celebs-manual/`;
  `number` (a dry run until `--apply`) gives each new picture the next number (`001.jpg`, ...).
- **Nothing is deleted or overwritten.** The numbered copy is written to a temporary file, checked and
  moved into place; only then is the original moved into `_originals/` (rejects go to `_skipped/`),
  under a unique name. A crash leaves every picture somewhere; a re-run recognises a picture it already
  numbered by its hash.
- JPEGs keep their bytes; PNG, WebP and BMP are converted; unreadable files, AVIFs and duplicates are set
  aside; a picture saved for two people is kept once (all existing numbered files are read first, so
  the order of people does not matter).
- Numbered names (case aside, so `001.JPG` too) are never renamed; a damaged numbered file, or one
  that is not a JPEG, stops the run before anything changes.
- Every path is confined: a linked person folder, `_originals`, `_skipped` or metadata file is refused.
- `rename-log.jsonl` (one line per picture, flushed before the original moves; a torn last line is
  ignored), and `manifest.json` and `PROVENANCE.json` replaced atomically, in the shape the review and
  evaluation scripts read.
- `docs/guides/COLLECTING_CELEBRITY_PHOTOS.md`: what to collect, where to go (Wikimedia Commons first,
  with a category link per person and what the dry run saw), what to avoid, and the commands. Its folder
  column is checked against the folders `init` made.

## Why

The automatic download from Commons (PR 191, `build_commons_dataset.py --follow-years`) returned
pictures the owner could not use: clothing, objects, signatures and groups, because a year category is
a bag of everything tagged with the person. The owner chose to collect by hand and asked for the
folders, directions and a script that numbers everything.

## Decisions

- **Numbered files never move.** A review decision is keyed by the file path, so renaming an already
  numbered file would make its decision stale. New files continue the numbering.
- **Nothing is deleted.** Unreadable, duplicate and original (converted) files go to `_skipped/`.
- **Labels are the owner's.** `PROVENANCE.json` says so and that they are not verified; the label review
  is the next step.

## Verification

- `uv run pytest tests/unit/test_prepare_manual_dataset.py -q`: 13 passed, including the regressions the
  independent review named: an uppercase numbered name is never deleted, two originals with one name in
  separate runs are both kept, a crash after numbering does not double a picture, a damaged numbered file
  stops the run, a duplicate under a later-listed person, case-only person names refused, and a linked
  person folder or metadata file refused (real symlinks, which this machine permits). ruff and mypy
  clean.
- `init` was run for real: 38 folders; every folder in the guide exists.
- **Not verified:** real photographs (the tests use generated ones); junctions (only symlinks were
  exercised; both resolve through `Path.resolve`); AVIF cannot be read on this machine, so it is set
  aside with a hint.

## Open issues / follow-ups

- The 251 pictures already downloaded into `evaluation/datasets/celebrities-cc/` (11 people) can be
  copied into the new folders by hand where usable.
