# LFW and CelebA terms read at source

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** licensing record, issue #183
- **Status:** partial (CelebA read; LFW's own page could not be reached)
- **Commits:** PR for #183: `docs(licensing): record the LFW and CelebA terms read at source`,
  `fix(evaluation): say what was read in the dataset provenance`

## What changed

- `docs/research/licensing-and-commercialization.md` section 10.3: what CelebA's agreement says
  (non-commercial research only, no redistribution, images not MMLAB's property), what could and
  could not be read for LFW, and what both mean for this project. States that it is a reading of
  published terms, not legal advice.
- `evaluation/import_labelled_dataset.py`: the `terms` text written to each import's
  `PROVENANCE.json` now says what was read instead of "not verified". One test assertion followed; it now also pins that the LFW caveat ("could not be read") survives.

## Why

Issue #183: the records said both datasets' terms were unverified.

## Decisions

- **LFW is recorded as unread, not as permissive.** `vis-www.cs.umass.edu` did not resolve from this
  machine or the fetch tool (http, https, README path); the Wayback copy was blocked. The official
  technical report (`people.cs.umass.edu/~elm/papers/lfw.pdf`) was read: it states no licence and
  says the images are pre-existing news photographs. Treat LFW as research-only, not redistributable,
  not usable commercially, until its page is read.
- Nothing from either dataset is in the repository: `evaluation/datasets/` is ignored and
  `git ls-files` shows no file under it (2026-10-15).

## Verification

- CelebA page fetched 2026-10-15 and its Agreement section summarised; LFW report text extracted
  with `pdftotext` and searched for licence, copyright, redistribution, terms: no hit.
- `git check-ignore -v evaluation/datasets/lfw/x.jpg` matches `.gitignore`; `git ls-files` finds none.
- Backend gate run: see the PR description.

## Open issues / follow-ups

- Read the LFW page (and the Kaggle mirror's licence field) from a machine that can reach it, then
  replace the LFW paragraph of section 10.3 and the LFW `terms` text. Issue #183 stays open for this.
