# M8: what remains and what depends on M6 and M7

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M8 (planning record, no tracker row moves)
- **Status:** done
- **Commits:** PR (number added when opened): `docs(m8): list what remains and what depends on M6 and M7`

## Why

The M8 brief asks for a written list of what depends on M6 and M7 (for example bundling FFmpeg) and what is left, so the
orchestrating session and the next agent do not have to rebuild that picture from the entries.

## What changed

- `docs/plans/M8_PLAN.md` section 1a: what is built, what is left in M8, that nothing waits for M6 any more (FFmpeg ships), that M7's
  only packaging follow-up is a rebuild (re-freeze, notices, installer) plus two checks on an installed build, and what needs the owner.
- The owner's requirement of 2026-11-12 (use a supported GPU, else the CPU, no manual step): what already provides it (the manifest's DirectML, CUDA and CPU
  variants, the DirectML runtime in the frozen backend, `FACEIDENTIFY_PROVIDERS`), how step 7's installed-build check is planned to prove both paths, and that
  the adapter-selection change in `backend/ml/worker/onnx_session.py` (another session's) needs only a re-freeze when it merges.

## Verification

Docs only. Every statement was checked against the merged entries (steps 1 to 4, the pre-migration copy). The installed-build check is described as planned: it is not part of this PR.

## Open issues / follow-ups

- Section 1 of the plan still describes 2026-11-10; section 1a supersedes it where they differ.
- Once `check_installed.py` merges, section 1a says it proves the provider selection; until then it says it is planned.
