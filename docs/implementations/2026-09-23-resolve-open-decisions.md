# Resolve open repository decisions

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** prerequisites for M2 (migrations), M3 (TST-044 ML evaluation) and M8 (packaging)
- **Status:** done
- **Commits:** PR #2 (`docs/resolve-open-decisions`): `docs(specs): place the alembic environment at backend/alembic`, `docs: set evaluation/ as the ml evaluation location`, `build(desktop): use an owner-scoped bundle identifier`, `docs: record resolution of open repository decisions`

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
- **Identifier:** a reverse-DNS identifier should come from a namespace the project can claim.
  `com.faceidentify.desktop` implied ownership of `faceidentify.com`, which the owner does not
  hold. `io.github.sodiqabdulwaris` is the owner's GitHub account namespace
  (`sodiqabdulwaris.github.io`). GitHub owns the domain, but that subdomain is tied to this
  account, the common convention for projects without their own domain. If the project later
  acquires its own domain, the identifier may switch to it only **before** the first release.
  Windows app-data paths derive from the identifier, so it must never change after release.
  (Corrected wording after the Codex review of PR #2, which rightly noted that `github.io` is
  not an owned domain.)
- **Not changed:** `docs/research/tech-stack.md` stays in `research/`, the layout the user
  chose, even though it holds locked decisions (CONTEXT open question 6).

## Verification

- `git check-ignore -v evaluation/datasets/x.jpg` matches `.gitignore:23`.
- `tauri.conf.json` parses; `npx tauri build --debug --no-bundle` succeeded with the new
  identifier (18.6 s incremental).
- The build rewrote `Cargo.toml` with identical bytes, which showed as modified only because of
  `core.autocrlf=true`. Re-adding it produced an empty diff and a clean tree.

## Open issues / follow-ups

- ~~Stacked on PR #1~~ PR #1 merged 2026-09-23. This branch was rebased onto `main` and the PR
  retargeted.
- Commit SHAs cited in implementation entries went stale after PR #1's rebase merge. They are now
  cited by PR and subject, and `rules/documentation.md` requires this from now on.
