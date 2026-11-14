# Dataset licensing evidence record and artifact audit (issue 183)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** licensing record, issue #183 (M8 release blocker; issue stays open)
- **Status:** partial (CelebA verified; LFW permission-unverified by evidence, as decided)
- **Commits:** PR for #183: `docs(licensing): separate verified dataset terms from unknowns`

## What changed

- `docs/research/licensing-and-commercialization.md` section 10.3 rewritten as an evidence record in
  three explicit classes (directly verified, reported by secondary sources, unknown), with every
  attempt to reach LFW's terms (URL, date, result), the required and requested citations (LFW and
  deep-funneled LFW keep both papers) and the conservative release gate. New section 10.4: the
  dataset artifact exclusion audit (commands and counts).
- Documentation only: no product code, spec or test changed. This record covers the datasets only;
  the InsightFace model-weight and dependency records (sections 2 to 9) are untouched and stay separate.

## Why

Owner decision 2026-11-14: separate verified permissions from assumptions, keep a conservative gate,
and do not treat a documented decision as a finished implementation.

## Decisions

- **CelebA** re-read at its official page on 2026-11-14: non-commercial research only, no
  redistribution (single-site internal copies excepted), images not MMLAB's property, citation required.
- **LFW's official page was read for the first time** through the Internet Archive snapshot of
  2025-01-05 (reachable with `curl`; the fetch tool refuses archive.org and the live host does not
  resolve). It, and its `README.txt`, state **no licence or terms**; the only relevant text is a
  disclaimer against using LFW results to judge commercial suitability. Absence of a licence is not a
  grant, so LFW stays permission-unverified: no redistribution, no commercial use, local evaluation only.
- No authoritative positive evidence was found, so none is claimed. A Kaggle licence field, an open
  download URL or public availability grants nothing.
- The owner's personal-development and release restrictions are preserved as documented.

## Verification

- Commands and counts are in section 10.4: 0 tracked files under the dataset directories, 14 tracked
  PNGs all application icons, 0 JPEGs or embedding/index/database/weight/archive files, history clean
  of dataset paths and image binaries, all five dataset directories matched by `.gitignore`.
- Installer: no build output exists locally, so contents were reasoned from `tauri*.conf.json`,
  `faceidentify-backend.spec` and `build_installer.py`, not listed. To be repeated on the first real
  installer build.
- Online reads dated 2026-11-14 (CelebA page, LFW archive snapshot, Kaggle metadata) are in section 10.3.

## Open issues / follow-ups

- LFW's live page and the maintainers' written position remain unread; a written answer from the
  University of Massachusetts Amherst maintainers is the only thing that would change LFW's status.
- Re-run the artifact listing against a real installer before any release.
- Issue #183 is not closed by this PR (owner instruction).
