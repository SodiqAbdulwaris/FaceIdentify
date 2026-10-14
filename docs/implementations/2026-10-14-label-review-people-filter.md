# Label review: serve only named people (`--people`)

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R5 (label review); supports TST-057B, no tracker row changes
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

`evaluation/label_review.py serve --people "Name One,Name Two"` lists only those people in the review
page. `Review.focus(names)` sets the list; the page's `/api/state` honours it.

- Names must be ones the manifest has (case ignored; labels that differ only in case are all chosen). A
  name that is not there stops the tool with the closest matches, so a typo cannot silently show an
  empty page; an empty, blank or comma-only `--people` is refused. A name containing a comma is quoted
  (`--people '"Doe, Jane",Ada Lovelace'`).
- It is a view filter only: decisions, `status`, the export and the verified set still use the whole
  dataset, and a photograph outside the filter is neither hidden from the log nor made undecidable.
- The page still lists every photograph of a chosen person, including ones already reviewed (the page,
  not the filter, shows their state).

## Why

The owner has to verify about 20 of the Commons set's 44 people to reach a usable verified set
(the decision entry `2026-10-14-m5-celeba-gate-and-acceptance-decision.md`); scrolling past the
people already done was wasted effort.

## Verification

- `uv run pytest tests/unit/test_label_review.py -q`: 21 passed (three runs), including three new tests:
  the page lists only the named person while decisions, status and export are unchanged and an
  out-of-filter decision is still accepted; case variants are chosen together and commas are quotable
  through `main()`, with empty values refused; a misspelt name stops the tool with a hint. ruff and
  mypy clean. One run of an older test failed once with a socket abort and passed on three re-runs;
  not diagnosed.
- The 20 names of the owner's current list resolved against the real Commons manifest (321 photographs).
- **Not verified:** the interactive page itself (no browser was driven).

## Open issues / follow-ups

- Order the photographs so the unreviewed come first (the page does not do this).
