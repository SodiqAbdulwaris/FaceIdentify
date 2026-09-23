# Repository structure, agent files and scaffolding

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M0 · TST-009, TST-010 (plus repository conventions)
- **Status:** done locally; remote CI not yet observed
- **Commits:** not yet committed

## What changed

**Documentation layout.** All root `.md` docs moved into `docs/`, grouped by document type:
`specs/` (authoritative), `plans/`, `strategy/`, `guides/`, `research/`, `archive/`
(`opendecisions.md`, `docs.md`) and `implementations/` (this log). Spec content is unchanged;
their cross-references are bare filenames, which are still unique.

**Commit convention.** `.githooks/commit-msg` is a dependency-free `sh` script enforcing
Conventional Commits (types `feat fix docs chore refactor test ci build perf style revert`,
optional lowercase scope, optional `!`, header ≤ 72 characters; git-generated `Merge`/`Revert`/
`fixup!`/`squash!`/`amend!` are allowed). It was enabled here with
`git config core.hooksPath .githooks`. `.gitattributes` keeps it LF. The CI `commit-messages`
job runs the same script on every new commit.

**Agent files.** `AGENTS.md` (entry point), `CLAUDE.md` (`@AGENTS.md` import),
`.agents/CONTEXT.md` (current state, read second), and `.agents/rules/` with `commits.md` (small,
scoped commits), `documentation.md` (document everything), `scope.md` and `testing.md`.

**Type checking.** mypy in strict mode over `backend/` and `tests/`, with
`untyped_calls_exclude = ["usearch"]` because usearch is only partially annotated. Fixed the 14
findings, including real ones: an unchecked `Optional` from `Index.restore` and from
`engine.url.database`.

**Backend scaffold.** Empty packages per IMPLEMENTATION_ARCHITECTURE.md §8: `backend/app/{api,
core, sources, processing, identities, people, memory, search, jobs, runtime, settings, cameras}`,
`backend/infrastructure/{storage, media, indexing, events, resources, diagnostics}` and
`backend/ml/{contracts, client, supervisor, worker}`. The repo-level `runtime/{manifests,schemas}`,
`benchmarks/`, `scripts/` and `packaging/` come from §24, as do the test folders
`tests/{contracts, property, recovery, concurrency, e2e, factories}`. `tests/contracts/` maps to
the `contract` marker.

**Frontend.** `frontend/` from `create-vite` (react-ts): React 19, TypeScript 6 (strict), Vite 8,
Tailwind v4 (`@tailwindcss/vite`), shadcn/ui (`radix` base, default Nova preset), the `@/` alias,
oxlint (from the template), and Vitest 5 + React Testing Library + jest-dom + jsdom. The demo was
replaced with a placeholder `App` shell and one test. The `src/` folders follow architecture §24.
There is a root `package.json` with npm workspaces, and `.nvmrc` pins Node 24.

**Desktop.** `desktop/src-tauri` from `tauri init` (Tauri v2): product name `FaceIdentify`,
identifier `com.faceidentify.desktop`, 1280×800 window, and a CSP limited to self plus the
`127.0.0.1` loopback backend. Cargo placeholders were replaced (`faceidentify` /
`faceidentify_lib`).

**CI.** Added the `commit-messages` job and the `frontend` job (typecheck, lint with
`--deny-warnings`, Vitest, build), and added mypy to `static`.

## Why

User request (2026-09-23): organise the docs, enforce commit conventions, add agent guidance
(small commits, document everything, implementation log, context entry point), and unblock the
blocked M0 items by scaffolding the frontend, the type checker, and the rest of the documented
structure.

## Decisions

- **User decisions:** docs grouped by type; hook + CI enforcement; mypy; implementation log in
  `docs/implementations/`; full scaffold including Tauri.
- `AGENTS.md` stays short and stable. Changing state lives in `.agents/CONTEXT.md` so the entry
  point does not grow without bound.
- The shadcn preset (Nova) is the CLI default, not a design decision. Change it with
  `npx shadcn@latest init -f`.
- shadcn installed the `cn` package (repository `github.com/shadcn-ui/cn`, a drop-in for
  `clsx` + `tailwind-merge`). It was verified as legitimate before keeping it.
- The oxlint `only-export-components` rule is off for `src/components/ui/**` only, because that
  code is shadcn-generated.
- No `backend/app/main.py`/`bootstrap.py`: they need FastAPI, which arrives with M4.
- No migrations folder, because the specs conflict (see open issues).
- Tauri/Rust is not built in CI yet: slow cold build and nothing to test until M4.

## Verification

- `.githooks/commit-msg`: 17 cases (8 valid incl. merge/fixup/revert, 8 invalid incl. bad type,
  capital type, empty or uppercase scope, missing space, 73-character header, plus a
  comment-first message). All behaved as expected.
- `uv sync --locked`, `ruff format --check`, `ruff check`: pass. `mypy`: no issues in 36 files.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov`: 19 passed, coverage 100% of `backend/` code.
- `npm ci`; `npm run typecheck` ok; `npm run lint -- --deny-warnings` 0 warnings; `npm test`
  1 passed; `npm run build` ok.
- `npx tauri build --debug --no-bundle` (from the repo root): built `faceidentify.exe` in
  2m 46s. This also exercised `beforeBuildCommand`.
- `ci.yml` parses (4 jobs). The JSON configs parse.
- **Not verified:** `npm run tauri dev` (needs an interactive desktop session), the CI
  `commit-messages` range logic (needs real commits and a push), and any remote CI run.

- **Remote CI (2026-09-23):** PR #1, run `35902624488`: all five jobs passed on GitHub Actions
  (backend on `windows-latest`: 19 passed; frontend: 1 passed; coverage artifact uploaded).

## Open issues / follow-ups

1. Migrations folder: `backend/migrations/` (architecture) vs `backend/alembic/`
   (persistence). Needs a user decision before M2.
2. The ML evaluation code location is unspecified.
3. The Tauri identifier and product name need confirmation before release (the identifier
   determines Windows app-data paths).
4. After the first commit, mark `.githooks/commit-msg` executable in the index
   (`git update-index --chmod=+x .githooks/commit-msg`) so it works on macOS/Linux clones.
   `core.fileMode` is off on Windows.
