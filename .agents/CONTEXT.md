# Agent context

Read after [`AGENTS.md`](../AGENTS.md). **Keep this file true:** update it at the end of every
task (see [`rules/documentation.md`](rules/documentation.md)).

_Last updated: 2026-09-23_

## Current state

- **Milestone:** M0 (testing foundation) is complete and merged, except the domain-factory part
  of TST-008. That part is blocked until domain models exist and is carried into M1. Next is M1
  (domain integrity). Status per task: [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../docs/plans/TESTING_IMPLEMENTATION_TRACKER.md).
- **Git:** public repository <https://github.com/SodiqAbdulwaris/FaceIdentify>. `main` contains the
  bootstrap commit and the project foundation (PR #1, merged 2026-09-23). It is protected by
  ruleset `23894323` (PR required, rebase merge only, five required CI checks, no bypass).
- **Backend:** only `backend/infrastructure/db/engine.py` has code (SQLite engine and session
  factory per Persistence §24/§25, plus an empty `Base` registry). All other backend packages are
  empty scaffolds from IMPLEMENTATION_ARCHITECTURE.md §8. There are no domain models, no FastAPI
  app and no ML worker yet.
- **Frontend:** Vite + React 19 + TS + Tailwind v4 + shadcn/ui (Nova preset, radix base) +
  Vitest. It is a placeholder `App` shell only; no features.
- **Desktop:** Tauri v2 in `desktop/src-tauri`, default shell. It loads the frontend at
  `http://localhost:5173` in dev and `frontend/dist` in builds. It does not spawn the backend yet
  (M4).

## Repository map

| Path | Contents |
|---|---|
| `docs/specs/` | **Authoritative** architecture and contracts (architecture, API, persistence, ERD, identity model, processing, search, product, ML components) |
| `docs/plans/` | Roadmap, testing tracker, identity decision engine plan |
| `docs/strategy/` | Testing strategy, ML benchmark and evaluation protocol |
| `docs/guides/` | How-tos, e.g. `TESTING_GUIDE.md` |
| `docs/research/` | Stack research and `tech-stack.md` (the locked stack decisions) |
| `docs/archive/` | Superseded documents; do not treat as current |
| `docs/implementations/` | Log of every implemented change (one entry per task) |
| `backend/` | Python backend (`app/`, `infrastructure/`, `ml/`) |
| `frontend/` | React app (`src/app`, `features`, `components`, `api`, `native`, `stores`, `hooks`, `lib`) |
| `desktop/src-tauri/` | Tauri shell (Rust) |
| `tests/` | Python tests. Directory decides the marker (`unit/`, `contracts/`, `integration/`, …) |
| `runtime/`, `benchmarks/`, `evaluation/`, `scripts/`, `packaging/` | Empty scaffolds from architecture §24 (`evaluation/` = ML quality evaluation; `evaluation/datasets/` is Git-ignored) |
| `.githooks/` | `commit-msg` (Conventional Commits), `pre-commit` (no commits on `main`), `pre-push` (no pushes to `main`, branch naming) and `check-branch-name`. CI runs the same scripts |
| `.github/rulesets/main.json` | Source of GitHub ruleset `23894323` protecting `main`; after editing, re-apply with `gh api -X PUT …/rulesets/23894323` |

## Commands

```bash
uv sync && npm install                 # install everything
git config core.hooksPath .githooks   # enable commit-msg + pre-push hooks (once per clone)
git switch -c feat/short-description  # every change starts on a branch (rules/branches.md)
codex exec -s read-only -C "$dir" -o review.md - < prompt.txt  # PR review in a disposable worktree (rules/branches.md)
uv run pytest                          # fast backend tests
uv run ruff format --check . && uv run ruff check . && uv run mypy
npm test && npm run typecheck && npm run lint && npm run build
npm run tauri dev                      # desktop app with frontend dev server
npx tauri build --debug --no-bundle    # desktop build check (~3 min cold)
```

## Known conflicts and open questions

Unresolved items need the user's decision. Do not settle them silently.

1. ~~Migrations directory~~ **Resolved 2026-09-23:** `backend/alembic/` with revisions in
   `backend/alembic/versions/`, as PERSISTENCE_IMPLEMENTATION.md specifies. The architecture spec
   was aligned. The folder is created by `alembic init` in M2.
2. ~~ML evaluation location~~ **Resolved 2026-09-23:** top-level `evaluation/`, separate from
   `tests/` (correctness) and `benchmarks/` (performance). Datasets go in the Git-ignored
   `evaluation/datasets/`, never committed.
3. ~~Tauri identifier~~ **Resolved 2026-09-23:** `io.github.sodiqabdulwaris.faceidentify`
   (the owner's GitHub account namespace; the project owns no domain). **Never change it after
   the first release:**
   Windows app-data paths derive from it.
4. ~~Product name~~ **Resolved 2026-09-23:** "FaceIdentify". Read `<App>` in the specs as
   FaceIdentify.
5. `docs/archive/opendecisions.md` is superseded (it predates the SQLite/USearch/SQLAlchemy
   decisions).
6. `docs/research/tech-stack.md` holds **locked** decisions despite living under `research/`.

## Next steps (M1)

1. Add Alembic at `backend/alembic/` and the models for `0001_initial_schema` per PERSISTENCE_IMPLEMENTATION.md.
   Switch the `sqlite_engine` fixture from `create_all` to migrations.
2. Add `tests/factories/` for the new models (completes TST-008, carried over from M0).
3. Write the Identity Manager invariant tests (TST-011 to TST-020).
