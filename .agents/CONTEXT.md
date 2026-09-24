# Agent context

Read after [`AGENTS.md`](../AGENTS.md). **Keep this file true:** update it at the end of every
task (see [`rules/documentation.md`](rules/documentation.md)).

_Last updated: 2026-09-24_

## Current state

- **Milestone:** M0 (testing foundation) is complete and merged, except the domain-factory part
  of TST-008. That part is blocked until domain models exist and is carried into M1. Next is M1
  (domain integrity). Status per task: [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../docs/plans/TESTING_IMPLEMENTATION_TRACKER.md).
- **Git:** public repository <https://github.com/SodiqAbdulwaris/FaceIdentify>. `main` contains the
  bootstrap commit and the project foundation (PR #1, merged 2026-09-23). It is protected by
  ruleset `23894323` (PR required, rebase merge only, five required CI checks, no bypass).
- **Backend:** the SQLite engine/session factory, models for all 33 `0001_initial_schema`
  tables (registry `backend/app/models.py`), the Identity Manager core use cases
  (`backend/app/identities/use_cases.py`: create/activate an identity, assign a representation
  with Evidence and an index intent, merge one identity into another, split selected
  representations into a new identity), and Person/association use cases
  (`backend/app/people/use_cases.py`: assign/reassign/remove an Identity's Person link, rename a
  Person). `backend/infrastructure/db/optimistic.py` holds the one shared optimistic-locked
  `UPDATE` helper both feature modules use. Tests build rows with the shared `build` factory and
  assert constraints with `tests/fixtures/constraints.py`. The remaining backend
  packages are empty scaffolds from IMPLEMENTATION_ARCHITECTURE.md §8. There are no use cases, no
  FastAPI app and no ML worker yet.
- **Frontend:** Vite + React 19 + TS + Tailwind v4 + shadcn/ui (Nova preset, radix base) +
  Vitest. It is a placeholder `App` shell only; no features.
- **Desktop:** Tauri v2 in `desktop/src-tauri`, default shell. It loads the frontend at
  `http://localhost:5173` in dev and `frontend/dist` in builds. It does not spawn the backend yet
  (M4).

## Repository map

| Path | Contents |
|---|---|
| `docs/specs/` | **Authoritative** architecture and contracts (architecture, API, persistence, identity model, processing, search, product, ML components). The **schema** comes from `PERSISTENCE_IMPLEMENTATION.md`; `ERD.md` is conceptual only |
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
# PR review: follow the procedure in .agents/rules/branches.md (Review section)
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
7. ~~ERD vs persistence schema~~ **Resolved 2026-09-23:** `PERSISTENCE_IMPLEMENTATION.md` is the
   implementation schema; `ERD.md` is conceptual (status note added).
8. ~~UUIDv7 (roadmap) vs uuid4 (persistence)~~ **Resolved 2026-09-23:** uuid4 in `Uuid` / CHAR(32).
   Roadmap updated.
9. ~~Person-level vs Identity-level merge~~ **Resolved 2026-09-23:** Identity-level (persistence
   §7, API §8.1/§114). Identity model §18 annotated.
10. ~~Merge/split in M1 (tracker) vs after the first milestone (roadmap)~~ **Resolved 2026-09-23:**
    domain-level merge/split and TST-015/016 are in M1; roadmap Phases D/E keep the API/UI/ML
    integration.
11. **Open: unconstrained model columns.** No spec gives the complete value sets for
    `Component.kind` (the API lists examples only), every runtime-catalog `state`,
    `ModelExport.format`/`precision`, `RuntimeVariant.provider`/`device_kind` or
    `RepresentationSpace.normalization`, `EvidenceCandidate.decision`, and the contents of
    `Observation.landmarks_json`/`quality_json`. They are plain strings or free JSON until decided
    (before the M2 migration). The transient run-state list for the partial index is inferred from recovery
    (§28).
12. **Open: no `EvidenceKind` for a pure Person rename.** `identity-and-memory-model-v1.md`
    §38 says renaming "produces a historical semantic event", but the locked `EvidenceKind`
    enum (persistence §10, PR #4/#5) has no matching value (e.g. `PERSON_RENAMED`). `rename_person`
    (PR #7) therefore records no Evidence; the Person's own `revision`/`updated_at` are the only
    audit trail. Decide whether to add a kind, or whether this is intentional (a name change
    isn't identity/visual evidence, only an Identity's link to a Person is).
13. **Open: `representations.ann_key` global uniqueness vs per-space sequences.**
    PERSISTENCE_IMPLEMENTATION.md §21 says "unique `ann_key`" as a plain table-wide index, but
    §6.3's `ann_key_sequences` allocates independently per `representation_space_id`, each
    starting at 1. Two different ACTIVE spaces can therefore legitimately both allocate key 1,
    which the current global `UNIQUE(ann_key)` (PR #4) would reject. **Nothing in the current
    backend can construct two simultaneously-ACTIVE spaces**, so this cannot happen through any
    code path today (only directly in tests) — but if it ever did,
    `assign_representation_to_identity` would surface a raw, unguarded `sqlite3.IntegrityError`,
    not a domain error (PR #6 reviewed this and deliberately left it unguarded rather than invent
    RepresentationSpace lifecycle policy the specs don't define). A future multi-space scenario
    (e.g. a model upgrade with two ACTIVE spaces briefly overlapping) would need either
    `UNIQUE(representation_space_id, ann_key)` or a single global sequence. Decide before M3
    introduces a second concurrently-active space.
14. **Open (M6): job claim order.** `jobs.priority` is a string, so `ORDER BY priority` is
    alphabetical and the `(state, priority, created_at)` index cannot serve INTERACTIVE-first
    claiming (§15). Decide with the scheduler: an integer rank column or one equality probe per
    priority.
15. **Open: `IdentityState.SPLIT` is never assigned.** The enum (persistence §7) lists a `SPLIT`
    state, but no spec text says which of a split's two resulting identities (if either) should
    receive it. `split_identity` (PR #8) reads `identity-and-memory-model-v1.md` §19.2's
    conceptual example — the source keeps some of its own evidence — as meaning neither identity
    is retired by a split, so it leaves the source `ACTIVE` and creates the new identity directly
    `ACTIVE`, using `SPLIT` nowhere. Decide whether `SPLIT` should mark the source, the new
    identity, or is dead enum space.
16. **Open: merge/split do not move `Occurrence` rows.** Only test factories create `Occurrence`
    rows today (no production pathway does), so `merge_identities`/`split_identity` (PR #8)
    reassign `Representation.identity_id` only. Decide, before a production path creates
    `Occurrence` rows, whether merge/split must also move `Occurrence.identity_id`.

## Next steps (M1)

M1 is delivered as a series of small PRs, each reviewed and green before the next (agreed
2026-09-23):

1. ~~Provenance and runtime-catalog models~~ Done (PR #4).
2. ~~Memory, identity and people models~~ Done, with the shared `build` factory
   (`tests/factories/models.py`), which also covers step 3 and completes TST-008.
3. ~~Factories~~ Folded into step 2.
4. ~~Identity Manager core~~ Done (PR #6): create/activate, assign representation with Evidence
   and an index intent, observation provenance preserved (TST-011, 012, 017, 018).
5. ~~Corrections and rename via Person association~~ Done (PR #7): `assign_identity_to_person`
   (reassignment is the correction), `remove_identity_from_person`, `rename_person`
   (TST-013, 014).
6. ~~Merge, then split, at the domain level~~ Done (PR #8): `merge_identities`,
   `split_identity` (TST-015, 016), done ahead of step 7 per the user's explicit sequencing.
7. Query-only recognition guard (TST-019).
8. Hypothesis property tests over operation sequences (TST-020).

Model rules: CHECK constraints only where a spec defines the complete value set; otherwise a
plain string, listed as an open question. Test fixtures keep using `create_all` until M2.

Deferred to M2: Alembic at `backend/alembic/` (revision `0001_initial_schema`), switching the
`sqlite_engine` fixture from `create_all` to migrations, and migration tests (TST-032).
