# Hand-collected celebrity photographs: folders, guide and numbering script

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R (evaluation data); no tracker row changes
- **Status:** done; the pictures themselves are the owner's to collect
- **Commits:** PR to be recorded when merged

## What changed

- `evaluation/prepare_manual_dataset.py` with two commands: `init` makes one folder per person from
  `people.txt` (38 people by default, editable) under `evaluation/datasets/celebs-manual/`;
  `number` (a dry run until `--apply`) gives each new picture the next number (`001.jpg`, ...), keeps
  JPEGs byte for byte and converts PNG, WebP and BMP, sets unreadable files, AVIFs and duplicates aside
  in `_skipped/` (never deleted), keeps a picture saved for two people once, appends the original name
  and hashes to `rename-log.json`, and writes `manifest.json` and `PROVENANCE.json` in the shape the
  review and evaluation scripts read.
- `docs/guides/COLLECTING_CELEBRITY_PHOTOS.md`: what to collect, where to go (Wikimedia Commons first,
  with a category link per person and what the dry run saw), what to avoid, and the commands.

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

- `uv run pytest tests/unit/test_prepare_manual_dataset.py -q`: 6 passed (the folders and the listing,
  dry run versus apply, stability and continuing numbers, a duplicate across two people, small pictures
  flagged, a folder outside the datasets folder refused, duplicate folder names refused). ruff and mypy
  clean.
- `init` was run for real: 38 folders. `number` on the empty tree reports nothing to do.
- **Not verified:** real photographs (the tests use generated ones); AVIF cannot be read on this
  machine, which is why it is set aside with a hint.

## Open issues / follow-ups

- The 251 pictures already downloaded into `evaluation/datasets/celebrities-cc/` (11 people) can be
  copied into the new folders by hand where usable.
