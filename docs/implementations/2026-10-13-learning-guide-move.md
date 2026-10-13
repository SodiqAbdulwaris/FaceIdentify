# The learning guide moved to `docs/guides/learning/`

- **Date:** 2026-10-13
- **Milestone / tracker IDs:** documentation only; no tracker row changes
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- `docs/learning/` became `docs/guides/learning/` (a `git mv`, so history follows; 130 files renamed).
- Every relative link in the moved lessons was recomputed from each file's old and new location (107 of the
  130 files needed link or path edits), and the references to the folder in `.agents/CONTEXT.md`,
  `docs/plans/PROJECT_STATUS.md`, `docs/research/codebase-learning-guide.md` and
  `docs/implementations/README.md` were updated. The older implementation entries keep their original
  paths; the 2026-10-12 entry has a dated decision note.

## Why

`.agents/rules/documentation.md` places how-tos in `docs/guides/` and says not to create new top-level
documents where an existing folder fits. The reviewing agent recommended `docs/guides/learning/` and the
owner agreed (2026-10-13), which also avoids amending the rule.

## Verification

- A script resolved every relative link and heading anchor in the moved lessons and the four updated
  files: 1,278 links, 0 broken. The guide's own link check
  (`docs/guides/learning/07-walkthrough-and-glossary/05-further-reading-and-keeping-true.md`) points at the
  new folder.
- Only paths and links changed: no lesson wording, code or data. A first version also rewrote the branch
  name `docs/learning-guide-restructure` inside git examples (the review caught it); it is restored.
- **Not verified:** external links; renderers other than GitHub's.

## Open issues / follow-ups

- Any external bookmark of `docs/learning/...` breaks (there are none in the repository).
