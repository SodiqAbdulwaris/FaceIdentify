# LFW and CelebA terms read at source

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** licensing record, issue #183
- **Status:** partial (CelebA and the Kaggle mirror read; LFW's own page could not be reached)
- **Commits:** PR for #183: `docs(licensing): record the LFW and CelebA terms read at source`,
  `fix(evaluation): say what was read in the dataset provenance`; follow-up PR:
  `docs(licensing): record the LFW Kaggle mirror's licence field`

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

## Follow-up, 2026-10-15 (cloud session)

- **Tried LFW's page again, from a cloud session:** the egress proxy refused the connection to
  `vis-www.cs.umass.edu:443` (502, recorded by the proxy as a refused CONNECT), plain http did not
  resolve, the fetch tool failed with `ENOTFOUND`, and `web.archive.org` was refused (the
  availability API names a 2025-01-05 snapshot, which could not be opened). Still unread.
- **Read the Kaggle mirror** (`jessicali9530/lfw-dataset`) through Kaggle's public dataset metadata
  (`/api/v1/datasets/view/...`, HTTP 200): licence "Other (specified in description)", and the
  description names no licence or conditions; it credits the UMass page and asks for two citations.
  Recorded in section 10.3: the mirror grants nothing of its own, so every terms question falls back
  to the official page and the photographs' rights holders. Sections 10.2, `PROJECT_STATUS.md` and
  `CONTEXT.md` now say the mirror was read.
- **`evaluation/import_labelled_dataset.py` and its test are unchanged:** the LFW `terms` text
  ("the LFW page could not be read by this project (2026-10-15)") is still accurate.
- Verification: the backend checks, see the PR description. Documentation only.

## Open issues / follow-ups

- Read the LFW page from a machine that can reach it, then replace the LFW paragraph of section 10.3
  and the LFW `terms` text. Issue #183 stays open for this.
