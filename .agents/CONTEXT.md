# Agent context

Read after [`AGENTS.md`](../AGENTS.md). **Keep this file true:** update it at the end of every
task (see [`rules/documentation.md`](rules/documentation.md)).

_Last updated: 2026-10-01 (Q25/Q26 decided)_

## Current state

- **Milestone:** M0 and M1 (domain integrity) are complete and merged. M2 (persistence) has
  started: Alembic and the initial migration (TST-032, in progress), SQLite WAL behaviour
  (TST-021), use-case transaction rollback (TST-023), optimistic concurrency (TST-024), managed
  artifact finalization (TST-026) and the Storage Manager (TST-025: managed core, referenced
  artifacts, relinking, temporary workspaces, Source recycle/restore, conservative cleanup and
  storage usage), the per-space USearch index (TST-027) and the IndexCoordinator that replays
  `IndexOperation`s into it (TST-028) and the cross-storage failure matrix (TST-029) are done;
  startup recovery (TST-030) is partly done (see open question 26); TST-022 (repository contract) has its
  `JobRepository`, `SegmentRepository`, `CheckpointRepository` and `IndexOperationRepository`; TST-031 is next.
  Status per task: [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../docs/plans/TESTING_IMPLEMENTATION_TRACKER.md).
- **Pending work is tracked as GitHub issues** (<https://github.com/SodiqAbdulwaris/FaceIdentify/issues>):
  #29 to #41 and #44 hold every decided-but-unbuilt item and every provisional decision to validate (the table is in
  `docs/implementations/2026-10-01-decide-q25-q26-erasure-and-recovery.md`). When something becomes pending,
  open an issue for it.
- **Git:** public repository <https://github.com/SodiqAbdulwaris/FaceIdentify>. `main` contains the
  bootstrap commit and the project foundation (PR #1, merged 2026-09-23). It is protected by
  ruleset `23894323` (PR required, rebase merge only, five required CI checks, no bypass).
  Reviewers for agent-opened PRs (`rules/branches.md`): Codex CLI and a read-only subagent are
  approved. Probed 2026-09-30 and **not** approved: `agy`, OpenCode (see the implementation entry
  for why); the Cursor `agent` CLI is not installed.
- **Backend:** the SQLite engine/session factory, models for all 33 `0001_initial_schema`
  tables (registry `backend/app/models.py`), the Identity Manager core use cases
  (`backend/app/identities/use_cases.py`: create/activate an identity, assign a representation
  with Evidence and an index intent, merge one identity into another, split selected
  representations into a new identity, resolve stale ANN candidates for a query-only face
  search), and Person/association use cases
  (`backend/app/people/use_cases.py`: assign/reassign/remove an Identity's Person link, rename a
  Person). `backend/infrastructure/db/optimistic.py` holds the one shared optimistic-locked
  `UPDATE` helper both feature modules use. The schema is created only by Alembic
  (`backend/alembic/`, revision `0001_initial_schema`); every persistence test runs on the migrated
  schema. The Storage Manager's managed core: `backend/infrastructure/storage/` (the two roots
  and layout from tech-stack §15, safe key → path resolution, crash-safe staged writes, reads,
  hashing, deletion) and `backend/app/sources/artifact_storage.py` (the three-step
  PENDING → AVAILABLE protocol, symmetric deletion, startup recovery, a report-only consistency
  scan), and `backend/app/sources/referenced_artifacts.py` with
  `backend/infrastructure/storage/referenced.py` (external originals: inspect and fingerprint
  before the transaction, record `REFERENCED`/`AVAILABLE`, and re-verify against the file so a
  missing or changed original becomes `MISSING`, never touching the Source or the file;
  `relink_referenced_artifact` points a `MISSING` one at a user-selected file only if its size and
  SHA-256 equal the recorded ones), and `backend/infrastructure/storage/workspaces.py` (job
  workspaces under machine-local `temp/jobs/<job id>/`: allocate, release, and remove orphans given
  the live job ids; deletes only marked directories it made, never follows a link), and `backend/app/sources/lifecycle.py` (`recycle_source` /
  `restore_source`: revision-guarded `ACTIVE` ⇄ `RECYCLED` changes that touch only the `sources`
  row; neither move is made once permanent deletion of the original has begun), and
  `backend/app/sources/storage_cleanup.py` (deletes only `AVAILABLE` managed artifacts that no row
  references, past a caller-supplied cutoff; the references are read from the schema in
  `artifact_references.py`, and the check is part of the deletion-intent `UPDATE`; stray files are
  reported, never deleted; a reference that keeps bytes alive must be a foreign key, and whatever
  creates one, such as the future import use case, must first check in its own transaction that the
  artifact is still `AVAILABLE`), and `backend/app/sources/storage_usage.py` (what the library
  holds by kind, the Recycle Bin's share, referenced originals apart, workspace bytes and volume
  free space; it reports, the scheduler decides). Tests
  build rows with the shared `build` factory and
  assert constraints with `tests/fixtures/constraints.py`. `backend/infrastructure/indexing/
  representation_index.py` is the per-space USearch index: idempotent add/remove, candidate search,
  generations flushed and hashed behind an atomically replaced manifest, a read-only `open`, and
  quarantine plus rebuild of a missing, corrupt, mismatched or unsupported index
  (`open_or_rebuild`; one process, one writer; note `Index.load` adopts the file's dimension *and*
  metric, so the file header is checked; it takes keys and vectors and knows nothing about SQLite
  or `ann_key` allocation, open questions 13 and 21). `backend/app/memory/index_coordinator.py` is
  the IndexCoordinator: `apply_pending` re-reads each representation, applies `ADD`/`REMOVE` as a
  desired state, persists one index generation and only then marks the operations `APPLIED`; the
  retry limit and backoff are caller-supplied, a rebuild skips and reports a corrupt vector,
  eligibility needs an ACTIVE identity, and an erased representation's vector is guaranteed gone
  by a rebuild (open question 25). `backend/app/recovery/startup.py` is startup recovery:
  `recover_on_startup` settles artifacts and missing referenced originals (existence only), marks
  `RUNNING` jobs, runs and segments `INTERRUPTED` and clears stale leases from any job, removes
  workspaces of finished jobs whose run is over too, marks a managed artifact whose file is gone
  `MISSING` (and refuses to run at all if the library root is not there; `reverify_managed_artifact`
  brings one back, but nothing calls it yet), validates every active space's index (a stale one is rebuilt from SQLite, not just a
  missing or corrupt one), gives
  `FAILED` `IndexOperation`s one fresh set of attempts and catches up pending ones in bounded
  passes; idempotent, survives a crash after any step, and reports what is `unresolved`. It relies
  on the single-process precondition (open questions 20 and 23) and nothing calls it yet (no
  application lifespan). The remaining backend
  packages are empty scaffolds from IMPLEMENTATION_ARCHITECTURE.md §8. There is no FastAPI app, no
  source-import use case and no ML worker yet.
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
uv run alembic upgrade head           # migrate the DB at $env:FACEIDENTIFY_DATABASE_PATH (backend/alembic/README)
uv run ruff format --check . && uv run ruff check . && uv run mypy
uv run mypy --platform linux          # CI's static job runs on Linux; Windows-only APIs need sys.platform guards
npm test && npm run typecheck && npm run lint && npm run build
npm run tauri dev                      # desktop app with frontend dev server
npx tauri build --debug --no-bundle    # desktop build check (~3 min cold)
```

## Known conflicts and open questions

Unresolved items need the user's decision. Do not settle them silently.

1. ~~Migrations directory~~ **Resolved 2026-09-23:** `backend/alembic/` with revisions in
   `backend/alembic/versions/`, as PERSISTENCE_IMPLEMENTATION.md specifies. The architecture spec
   was aligned. Created in M2 (PR #11).
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
17. **Open (narrowed 2026-09-25): where the library root comes from.** The database path is now
    defined by the layout: `StorageRoots.database_path` = `<Library Root>/database/library.db`
    (PR #14). What is still undecided is how the application learns the library root itself
    (first-run selection, persisted setting, default location), so `backend/alembic/env.py` still
    reads `FACEIDENTIFY_DATABASE_PATH` explicitly. Decide with the first-run/settings work.
    **2026-10-01 (owner):** deferred to the first-run/settings milestone.
18. **Open: batch-mode migrations and multi-revision failure atomicity are unproven.** `env.py`
    enables `render_as_batch` from the first revision because SQLite needs table recreation for
    most constraint changes, but revision `0001` only creates tables, so batch mode is exercised
    by no test yet. The second revision must add a populated-database upgrade test (and check
    that recreating a table with `PRAGMA foreign_keys = ON` behaves), a test that a failing
    *second* revision leaves `0001` applied as intended, and one for a Python error raised
    inside `upgrade()`; today only one failure shape is tested.
    **2026-10-01 (owner):** deferred to the second Alembic revision (TST-032), which the `ERASING` state of question 25 will provide.
19. **Open: what `alembic downgrade` should do to a populated library.** It destroys data, and
    whether foreign keys stop it is data-dependent (a richly populated database fails
    atomically; a simple one is dropped without complaint). Production never downgrades, and
    the README marks it development-only. Decide whether to leave it, or refuse to downgrade a
    non-empty database unless explicitly forced.
    **2026-10-01 (owner):** deferred to the second Alembic revision (TST-032).
20. **Open: `SQLITE_BUSY` handling does not exist yet.** Persistence §25 requires the application
    to "retry a small bounded number of times for known transient write conflicts, and return a
    diagnostic/retryable error rather than spin forever". Nothing does. What
    `test_sqlite_wal_behaviour.py` and `test_optimistic_concurrency.py` show: a second writer waits
    up to `busy_timeout` and then fails with `database is locked`; and a transaction that has
    **read before writing** (merge, split, assignment all do) fails *immediately*, ignoring the
    timeout, if another writer committed in between (`BUSY_SNAPSHOT`), which no retry of the
    single statement can fix. The engine begins deferred transactions (`BEGIN`), so the loser of a
    simultaneous merge *can* get a raw `OperationalError` instead of a domain error (or a domain
    error, if it happened to start after the winner committed). **Recommendation:** write
    use-case transactions start with `BEGIN IMMEDIATE` (writers queue for `busy_timeout` instead of
    failing at once), plus a bounded whole-transaction retry in the future unit-of-work, mapping
    a final failure to a retryable API error. Note `engine.py`'s `_begin` hook hard-codes plain
    `BEGIN` for every transaction, so this needs an execution option (set on the session's
    connection before its first statement) or a second engine for writers. Decide when the
    unit-of-work / API layer is designed; until then callers of use cases must treat an
    `OperationalError` whose message says the database is locked or busy as retryable (other
    `OperationalError`s, such as I/O errors, are not).
    **2026-10-01 (owner): agreed provisional direction** (the recommendation above), to be validated when the unit-of-work / API layer is designed.
21. **Open: when `ann_key` is allocated, and whether a rolled-back key may be reused.** Two spec
    passages pull apart. Persistence §6.3 allocates "in the same short transaction that creates
    representations... keys are never reused", and the run-local pending index (§23, "Recognition
    searches global active vectors plus a run-local pending index... ANN output is only candidate
    `ann_key` values") implies PENDING representations carry keys. But the §6.2 column table says
    `ann_key` is "required while ANN-eligible", and the code (PR #6) allocates only when a
    representation is assigned and becomes ACTIVE; PENDING representations have none. Separately,
    because allocation is inside the transaction, a rolled-back allocation is handed out again
    (TST-023 pins that). That is harmless while only committed keys are ever indexed (INDEX-01),
    but a run-local index holding a key from a transaction that then rolled back could later return
    that key for a *different* representation, and revalidation (space, state, identity,
    eligibility) would not notice. **Recommendation:** keep allocation at ANN-eligibility time as
    now, change §6.3 to say so, and give the run-local pending index its own ephemeral labels
    (e.g. a per-run integer mapped to `representation_id`) so it never depends on `ann_key`.
    Decide before the processing pipeline (M3) builds the run-local index.
    **2026-10-01 (owner): agreed provisional direction** (the recommendation above), to be validated before M3 builds the run-local index.
22. ~~Storage layout: three specs disagreed~~ **Resolved 2026-09-25 (owner):** tech-stack §15's
    two roots are authoritative (library root with `database/library.db` and managed bytes;
    `%LOCALAPPDATA%` for derived data). Managed writes stage in `<Library Root>/staging/` so the
    final rename stays on one volume. Persistence §1 and architecture §16.3 (and its `recycle/`
    directory, which contradicted "recycling never moves bytes") were aligned.
23. **Open: a library opened by two processes at once.** `recover_artifacts` (PR #14) assumes no
    other process uses the library: single-instance per machine is specified for the desktop shell
    (tech-stack §2, not built yet), but a library on a shared or removable drive could be opened from
    two machines. Recovery now deletes only staging files it owns, but it would still mark another
    live writer's PENDING artifact MISSING. **Recommendation:** the backend takes an exclusive lock
    on a file in the library (e.g. `<Library>/database/.lock`) for its whole lifetime and refuses to
    start without it, before migrations and recovery. Decide with the startup/lifespan work.
    **2026-10-01 (owner): agreed provisional direction** (the recommendation above), to be validated with the startup/lifespan work.
24. **Open: when does a `Source` become `UNAVAILABLE`?** Persistence §4.2 lists the state, but
    no spec says what sets it. The likeliest trigger is a missing referenced original, but
    IMPLEMENTATION_ARCHITECTURE §23.5 says to keep the Source and mark the *artifact's*
    availability `MISSING`, and API §57 says this "is handled by availability state rather than
    corrupting Source history". `reverify_referenced_artifact` therefore leaves the Source
    `ACTIVE`. **Recommendation:** keep `UNAVAILABLE` unassigned until a use case needs it, and
    derive "the original is missing" from the artifact, so there is one source of truth.
    Decide with the Source use cases.
    **Decided 2026-10-01 (owner):** keep `Source.UNAVAILABLE` unassigned until a use case needs it, and
    derive "the original is missing" from the associated artifact's state.
25. ~~Open (mitigated): erasure clears the key a `REMOVE` would need.~~ **Decided 2026-10-01 (owner):**
    erasure is two-step. Step one, one transaction: the representation moves `ACTIVE` -> `ERASING` and a
    `REMOVE` is queued; `ERASING` keeps its vector and key but is excluded from recognition, candidate
    revalidation and every rebuild at once. Step two, only after the `REMOVE` is `APPLIED`, the new
    generation is persisted and every superseded and quarantined generation file is verifiably gone:
    `ERASING` -> `ERASED`, clearing vector and key. Bulk forget does step one for all, **one** rebuild,
    then step two for all. A `REMOVE` is never applied while an old generation remains; quarantined
    generations have no time-based retention and are deleted when an erasure in their space finishes.
    "Securely retired" means verified file deletion, not physical erasure from SSD storage. Specs
    updated (persistence 6.2, 23, 28; architecture 23; testing strategy INDEX-03, INDEX-04, INDEX-05, PER-07). Candidate revalidation must resolve each
    `ann_key` to its representation row; today it revalidates identities only.
    **Still to build (TST-031):** the `ERASING` state (an Alembic revision, which is also the populated
    batch-mode migration question 18 needs), the erasure use case, coordinator retirement of old
    generations before a `REMOVE` is applied, recovery of `ERASING`, and the tests. The keyless-`REMOVE`
    rebuild in the coordinator stays as a safety net. **Not decided here:** whether SQLite itself should
    run with `secure_delete` / checkpoint after an erasure so the cleared vector does not linger in WAL or
    free pages (see the tracking issue).
26. **Decided 2026-10-01 (owner), partly built:** startup recovery marks a job or run found `PAUSING`
    `PAUSED` (nothing runs; the worker is gone) and one found `CANCELLING` `CANCELLED` (the user's intent;
    partial output stays private and is never activated). A `RUNNING` job is `INTERRUPTED`, never
    requeued. Recovery is idempotent by construction (guarded transitions), tested by a stop after each
    step and a rerun. **Not built yet:** the `PAUSING`/`CANCELLING` transitions in
    `backend/app/recovery/startup.py`. **Still open, for the M3 run lifecycle and the runtime installer:**
    `FINALIZING` runs (revalidate and accept without redoing ML, needing `AcceptProcessingRunUseCase`), a
    run with pending output and no final checkpoint, and interrupted runtime installations.
27. **Agreed provisional direction (owner, 2026-10-01), to be validated when the erasure and import use
    cases that append operations begin: how an obsolete `IndexOperation` is superseded.** Persistence
    §17 says that creating an opposite operation "must supersede/coalesce the obsolete desired state
    in the use case", and names no mechanism. It matters: `REMOVE` means absent whatever SQLite
    says, so a `REMOVE` left pending would run after, and undo, a later `ADD` that was skipped as a
    duplicate of an earlier one (ADD, REMOVE, ADD ends with the representation missing from the
    index). `IndexOperationRepository.append_batch` now **deletes** a pending operation of the
    opposite kind for the same representation before inserting the new one. Deleting was chosen
    because there is no `SUPERSEDED` state, `APPLIED` would claim something that never happened, and
    `FAILED` is requeued at startup, which would resurrect it; the row was never applied, so nothing
    that happened is lost. **Alternative:** add a `SUPERSEDED` state (a schema change and an Alembic
    revision) to keep the history of what was asked. Recommendation: keep deleting unless you want
    that audit trail.

## M1 delivery (complete)

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
7. ~~Query-only recognition guard~~ Done (PR #9): `resolve_recognition_candidates` (TST-019).
8. ~~Hypothesis property tests over operation sequences~~ Done (PR #10):
   `tests/property/test_identity_lifecycle_invariants.py` (TST-020).

**M1 (domain integrity) is complete: TST-011 through TST-020 all `PASSING`.**

## Next steps (M2)

1. ~~Alembic and `0001_initial_schema`~~ Done (PR #11): `backend/alembic/`, the `sqlite_engine`
   fixture copies a database migrated to `head` (no more `create_all` in fixtures), migration tests
   (TST-032, `IN_PROGRESS`: the populated-schema criterion needs a second revision).
2. ~~SQLite WAL behaviour and optimistic concurrency~~ Done (PR #12): TST-021
   (`tests/integration/test_sqlite_wal_behaviour.py`) and TST-024
   (`tests/concurrency/test_optimistic_concurrency.py`).
3. ~~Use-case transaction rollback~~ Done (PR #13): TST-023
   (`tests/integration/test_transaction_rollback.py`).
4. ~~Storage Manager, managed core~~ Done (PR #14): TST-026 passing, TST-025 in progress.
5. ~~Storage Manager follow-ups for TST-025~~ Done: referenced imports, missing-file detection,
   relinking, temporary workspaces, recycle/restore, conservative cleanup and storage usage (see
   above).
6. The rest of M2: TST-022 (repository contract; `JobRepository`, `SegmentRepository`, `CheckpointRepository`, `IndexOperationRepository` done, others as use cases need them), ~~TST-027 (USearch integration)~~ done, ~~TST-028
   (IndexOperation replay)~~ done, ~~TST-029 (cross-storage failure)~~ done, ~~TST-030 (startup recovery beyond
   artifacts)~~ partly done (open question 26 and the lifespan wiring remain), TST-031 (deletion).

Model rules: CHECK constraints only where a spec defines the complete value set; otherwise a
plain string, listed as an open question. Every schema change is now a reviewed Alembic revision
(see `backend/alembic/README`).
