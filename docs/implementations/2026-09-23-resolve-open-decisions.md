# Resolve open repository decisions

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** prerequisites for M2 (migrations), M3 (TST-044 ML evaluation) and M8 (packaging)
- **Status:** done
- **Commits:** `4170c75` migrations location, `fe6937e` evaluation location, `f1f455f` bundle identifier (branch `docs/resolve-open-decisions`)

## What changed

1. **Migrations location → `backend/alembic/`** (revisions in `backend/alembic/versions/`).
   Two tree entries in `docs/specs/IMPLEMENTATION_ARCHITECTURE.md` (§8 and §24) changed from
   `migrations/` to `alembic/`. The folder itself is created by `alembic init` in M2.
2. **ML evaluation location → top-level `evaluation/`.** Added to the §24 tree,
   `evaluation/.gitkeep`, and `evaluation/datasets/` in `.gitignore`. Documented in
   `docs/guides/TESTING_GUIDE.md`.
3. **Product name "FaceIdentify"; Tauri identifier `io.github.sodiqabdulwaris.faceidentify`**
   (was the placeholder `com.faceidentify.desktop`), in `desktop/src-tauri/tauri.conf.json`.
4. `.agents/CONTEXT.md`: open questions 1–4 marked resolved; the repository map and next steps
   are updated.

## Why

The user delegated these decisions on 2026-09-23 ("do what you think is best; I'll go with your
recommendation"). That also authorised the spec edit, which `rules/documentation.md` otherwise
forbids without approval.

## Decisions

- **Alembic path:** PERSISTENCE_IMPLEMENTATION.md is the detailed implementation contract. It
  names the exact path and the first revision `0001_initial_schema`. The architecture tree's
  `migrations/` was a generic label, so the spec with less detail was aligned to the one with more.
- **`evaluation/`:** TESTING_STRATEGY.md §3.4 separates model quality from software correctness
  and §4 lists ML evaluation and benchmarks as distinct suites. The ML protocol requires frozen
  experiment manifests and dataset versions. Keeping it outside `tests/` stops it running in
  ordinary test runs, and outside `benchmarks/` keeps quality apart from performance. Datasets
  are biometric data (§12), so Git ignores them.
- **Identifier:** a reverse-DNS identifier should belong to a domain the owner controls;
  `com.faceidentify.desktop` implied `faceidentify.com`. GitHub Pages
  (`sodiqabdulwaris.github.io`) is controlled by the owner. Windows app-data paths derive from
  the identifier, so it must be fixed before the first release and never changed after.
- **Not changed:** `docs/research/tech-stack.md` stays in `research/`, the layout the user
  chose, even though it holds locked decisions (CONTEXT open question 6).

## Verification

- `git check-ignore -v evaluation/datasets/x.jpg` matches `.gitignore:23`.
- `tauri.conf.json` parses; `npx tauri build --debug --no-bundle` succeeded with the new
  identifier (18.6 s incremental).
- The build rewrote `Cargo.toml` with identical bytes, which showed as modified only because of
  `core.autocrlf=true`. Re-adding it produced an empty diff and a clean tree.

## Open issues / follow-ups

- This branch is stacked on PR #1 (`chore/project-foundation`). Once #1 is rebase-merged, rebase
  this branch onto `main` because the SHAs change, then retarget or re-run its PR.
