# Agent context

Read after [`AGENTS.md`](../AGENTS.md). **Keep this file true:** update it at the end of every
task (see [`rules/documentation.md`](rules/documentation.md)).

_Last updated: 2026-10-07 (M4 W7.2: the library screen (cards, import through the native picker, process) and the uncalibrated-policy notice in the layout; M4 W7.1: the web view connects through the shell (gate, typed client, event client with gap detection and reconnection, query invalidation, hash routes with placeholder screens); M4 W6: the Tauri shell starts the backend sidecar (token in the environment, validated handshake, clean stop through the stdin lifeline), owns the library root and offers a folder picker, and CI checks it on Windows; M4 W6 host side: `--stdin-lifeline` lets the shell stop the host cleanly by closing its standard input; M4 development profile: the host flag `--development-profile` registers a fake catalog and perception under an uncalibrated policy and the host now always passes the media limits; M4 W5: the OpenAPI document and TypeScript types are generated and kept in sync by a backend test and a CI step (`npm run generate:api`); every operation declares the one error shape; M4 W4: the event connection publishes `source.created`, `processing_run.created` and `processing_run.updated` with sequence numbers and a hello greeting, best effort; M4 W3.6: runs report their frozen policy's calibration status; no separate system-status route (`/readiness` is it); M4 W3 complete; M4 W3.5: read-only identity and occurrence routes that show only authoritative (ACTIVE) data; M4 W3.4: `CancelProcessingUseCase` writes the cancellation request (queued: cancelled now; running: `CANCELLING`, settled by the executor), with `POST /processing-runs/{id}/cancel` and the jobs routes; M4 W3.3: `POST /sources/{id}/process`, processing-run reads and `POST /processing-runs/{id}/retry`, with `ProcessingSettings.request_for` supplying the development policy profile; M4 W3.2: the source routes (import, list, detail, original media with ETag) under `/api/v1`; M4 W3.1: the REST conventions (one error shape, cursor pagination, library gating) every route inherits; M4 W2.3: the scheduler loop starts after the library opens, `/readiness` reports it, and recognition opens its index fail-closed; M4 W2.2: `ProcessingRunner.run_once` claims, executes and accepts one queued job with every outcome decided; M4 W2.1: revision 0007 gives jobs an integer priority rank and claiming orders by it; M4 W1 complete: the loopback sidecar host `python -m backend.api.host` (uvicorn, websockets; stdout handshake; token from the environment; parent-process watch); M4 W1.1: the API lifespan opens the library and `/readiness` reports the lifecycle and capabilities; the M3 exit gate is met: tracker rows TST-040 to TST-043 are PASSING, TST-038 and TST-039 are BLOCKED on real weights (issue #69); M3.2: the pipeline killed at each stage in a real child process, then recovered and retried (TST-043); M3.1: the eraser and recovery writes moved onto the UnitOfWork (issue #66); rules added: implementation plans go in `docs/plans/` and `docs/plans/PROJECT_STATUS.md` is the glanceable status page; the M3 and M4 completion plan, `docs/plans/M3_M4_COMPLETION_PLAN.md`, approved with six owner decisions; M3 step 13, the end-to-end recognition, restart and rebuilt-index test, added with planted perception; Step 12 recovery of FINALIZING and pre-FINAL runs built, with `RetryProcessingUseCase` (issue #34); stale M3 documentation corrected by the cross-check; M3 identity-less candidate readers merged in PR #95; PR #101 merged the approved provider-fallback execution segments; PR #106 merged the step-11 acceptance remediation, which validates every FINAL decision from SQLite-authoritative candidate evidence and the versioned run snapshot before all lifecycle branches; its focused coverage, guard mutation proofs, 2,328-test full gate, independent review, and exact-head CI passed, and it closed issue #104; M4's authenticated FastAPI bootstrap merged in PR #103, with loopback hosting/lifespan still pending)_

> **Decision 2026-10-03:** the owner approved the version-1 payload contracts for new ML output: `landmarks_json` has `schema_version` and normalised `points`; observation `quality_json` has `schema_version` and `detection_score`; representation `quality_json` has `schema_version` and `l2_norm`.

> **Decision 2026-10-05:** #102 is approved and merged in PR #101: only an actual backend-approved provider fallback closes one execution segment and starts another; ordinary detector-to-embedder progression does not. #104 is approved: the acceptance branch adds immutable `RECOGNITION_ABSTAINED` evidence for an accepted abstention, and later resolution adds evidence rather than rewriting it.

## Current state

- **Milestone:** M0 and M1 (domain integrity) are complete and merged. **M3 (single-image ML integration) started 2026-10-02 (item 7 below).** M2 (persistence) is complete except issue 34; it had
  started: Alembic and the initial migration (TST-032, in progress), SQLite WAL behaviour
  (TST-021), use-case transaction rollback (TST-023), optimistic concurrency (TST-024), managed
  artifact finalization (TST-026) and the Storage Manager (TST-025: managed core, referenced
  artifacts, relinking, temporary workspaces, Source recycle/restore, conservative cleanup and
  storage usage), the per-space USearch index (TST-027) and the IndexCoordinator that replays
  `IndexOperation`s into it (TST-028) and the cross-storage failure matrix (TST-029) are done;
  startup recovery (TST-030) is done (open question 26 is built, M3 step 12); TST-022 (repository contract) has its
  `JobRepository`, `SegmentRepository`, `CheckpointRepository`, `IndexOperationRepository`, `SourceRepository`, `ProcessingRunRepository`, `SnapshotRepository`, `ObservationRepository`, `RepresentationRepository`, `IdentityRepository`, `OccurrenceRepository`, `EvidenceRepository`, `SettingsRepository` and `RuntimeCatalogRepository` (TST-022 has its mechanics for every listed repository; Artifact is `artifact_storage.py`); the library root and lock (`library_root.py`, `library_lock.py`; not yet called by a lifecycle) and the downgrade guard are built; TST-031's representation erasure is built (Source deletion and identity-level forget are not).
  Status per task: [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../docs/plans/TESTING_IMPLEMENTATION_TRACKER.md).
- **Pending work is tracked as GitHub issues** (<https://github.com/SodiqAbdulwaris/FaceIdentify/issues>):
  #29 to #41, #48, #51, #57, #66, #69, #71, #79, #80 and the SQLite erasure policy hold every decided-but-unbuilt item and every provisional decision to validate (the table is in
  `docs/implementations/2026-10-01-decide-q25-q26-erasure-and-recovery.md`). When something becomes pending,
  open an issue for it.
- **Git:** public repository <https://github.com/SodiqAbdulwaris/FaceIdentify>. `main` contains the
  bootstrap commit and the project foundation (PR #1, merged 2026-09-23). It is protected by
  ruleset `23894323` (PR required, rebase merge only, five required CI checks, no bypass).
  Reviewers for agent-opened PRs (`rules/branches.md`): Codex CLI and a read-only subagent are
  approved. Probed 2026-09-30 and **not** approved: `agy`, OpenCode (see the implementation entry
  for why); the Cursor `agent` CLI is not installed.
- **Backend:** FastAPI is now a locked dependency and `backend/api/app.py` provides the first
  in-memory authenticated application factory: canonical 256-bit per-launch Bearer capability for
  all HTTP routes and a WebSocket credential offered through `Sec-WebSocket-Protocol` but never
  echoed as the selected protocol. It has no production server binding, lifespan, library, worker,
  scheduler, or domain routes yet. The SQLite engine/session factory, models for all 33 `0001_initial_schema`
  tables (registry `backend/app/models.py`), the Identity Manager core use cases
  (`backend/app/identities/use_cases.py`: create/activate an identity, assign a representation
  with Evidence and an index intent, merge one identity into another, split selected
  representations into a new identity, resolve stale ANN candidates for a query-only face
  search), and Person/association use cases
  (`backend/app/people/use_cases.py`: assign/reassign/remove an Identity's Person link, rename a
  Person). `backend/infrastructure/db/optimistic.py` holds the one shared optimistic-locked
  `UPDATE` helper both feature modules use. The schema is created only by Alembic
  (`backend/alembic/`, revisions `0001_initial_schema`, `0002_representation_erasing_state` (the `ERASING`
  state), `0003_ann_key_per_space_and_snapshot_triggers` (`ann_key` unique per space; immutable snapshots) and
  `0004_app_state` (a key/value table for the durable `wal_truncation_owed` marker), `0005` (output provenance columns, snapshot-replace trigger), `0006` (the `RECOGNITION_ABSTAINED` evidence kind) and `0007` (the integer `jobs.priority_rank`)); every persistence test runs on the migrated
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
  retry limit and backoff are caller-supplied, settling skips an operation that was deleted (superseded
  by `IndexOperationRepository.append_batch`) while it was in flight, a rebuild skips and reports a
  corrupt vector,
  eligibility admits an ACTIVE representation with either an ACTIVE identity or no identity (accepted
  abstention); identity-less candidates are never MATCH_EXISTING targets, and an erased representation's vector is guaranteed gone
  by a rebuild (open question 25); the `REMOVE` of an `ERASING` representation is applied by rebuilding the space (a saved USearch
  generation keeps a removed key's bytes), and no `REMOVE` is `APPLIED` while a superseded generation file remains.
  `backend/app/memory/erasure.py` is the erasure use case (`RepresentationEraser.erase(ids)` / `resume()`: queue and
  exclude, rebuild once per space, retire old and quarantined generations under the coordinator's lock, clear vector and
  key with the `wal_truncation_owed` marker, `truncate_wal`, verify; a blocked step is reported, never complete).
  `backend/app/recovery/startup.py` is startup recovery:
  `recover_on_startup` (it takes the eraser and finishes interrupted erasures and an owed log truncation, and `AcceptProcessingRunUseCase`) settles artifacts and missing referenced originals (existence only), accepts every `FINALIZING` run from its FINAL checkpoint without ML (its job stays `RUNNING` until then; a refused FINAL makes the run `NOT_RESUMABLE`; a failing post-commit index wake is caught), marks
  `RUNNING` jobs, runs and segments `INTERRUPTED`, moves a job or run found `PAUSING` to `PAUSED` and
  one found `CANCELLING` to `CANCELLED` (a cancelled job ends, its partial output stays private), clears
  stale leases from any job, removes
  workspaces of finished jobs whose run is over too, marks a managed artifact whose file is gone
  `MISSING` (and refuses to run at all if the library root is not there; `reverify_managed_artifact`
  brings one back, but nothing calls it yet; `open_library` calls recovery at startup), validates every active space's index (a stale one is rebuilt from SQLite, not just a
  missing or corrupt one), gives
  `FAILED` `IndexOperation`s one fresh set of attempts and catches up pending ones in bounded
  passes; idempotent, survives a crash after any step, and reports what is `unresolved`. It relies
  on the single-process precondition (open questions 20 and 23), which `open_library` (`backend/app/lifecycle.py`) now
  provides: it validates the roots, takes the library lock, lays out the folders, migrates (a database stamped with a revision
  this version does not know is refused untouched: `DatabaseNewerThanApplicationError`), builds the engine, Storage Manager,
  IndexCoordinator and eraser, runs `recover_on_startup`, and releases the lock and the engine on exit or on any failed step.
  The FastAPI lifespan that wraps it does not exist yet. The remaining backend
  packages are empty scaffolds from IMPLEMENTATION_ARCHITECTURE.md §8. There is an authenticated in-memory FastAPI application factory but no production loopback host or lifespan yet. Image source import (PR #82) and the ML worker and supervisor (PRs #76, #77) are built.
- **Frontend:** Vite + React 19 + TS + Tailwind v4 + shadcn/ui (Nova preset, radix base) +
  Vitest. It is a placeholder `App` shell only; no features.
- **Desktop:** Tauri v2 in `desktop/src-tauri`, default shell. It loads the frontend at
  `http://localhost:5173` in dev and `frontend/dist` in builds. It does not spawn the backend yet
  (M4).

## Repository map

| Path | Contents |
|---|---|
| `docs/specs/` | **Authoritative** architecture and contracts (architecture, API, persistence, identity model, processing, search, product, ML components). The **schema** comes from `PERSISTENCE_IMPLEMENTATION.md`; `ERD.md` is conceptual only |
| `docs/plans/` | Implementation plans (agents put theirs here), roadmap, testing tracker, identity decision engine plan, and **`PROJECT_STATUS.md`**, the one-page overview of what is built and where we are |
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
uv run alembic upgrade head           # migrate the DB under $env:FACEIDENTIFY_LIBRARY_ROOT (backend/alembic/README)
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
13. ~~Open: `representations.ann_key` global uniqueness vs per-space sequences.~~ **Decided 2026-10-01 (owner,
    issue 48; the same conflict as question 28, which re-found it):** `UNIQUE(representation_space_id, ann_key)`,
    revision `0003`, **built**: two spaces can now hold the same key.
14. **Open (M6): job claim order.** `jobs.priority` is a string, so `ORDER BY priority` is
    alphabetical and the `(state, priority, created_at)` index cannot serve INTERACTIVE-first
    claiming (§15). Decide with the scheduler: an integer rank column or one equality probe per
    priority.
    **Decided 2026-10-06 (owner):** an integer priority rank column in revision `0007`, added before the scheduler loop; the string is never scheduling semantics (Persistence §15 note; plan W2). **Built 2026-10-07:** revision `0007` and `JobRepository.claim_next` ordering by `priority_rank`.
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
    **Decided 2026-10-01 (owner); the backend side is built (`library_root.py`, `library_lock.py`, `alembic/env.py`; the shell's persisted setting and the lifecycle wiring, issue 33, are not):** the desktop shell owns
    library selection and persists the selected absolute library root in application-level settings *outside* the library;
    the backend receives exactly one resolved root at startup, immutable for the process lifetime, and every database,
    artifact, index, runtime, quarantine and lock path derives from it (repositories and Alembic never read
    `FACEIDENTIFY_DATABASE_PATH` themselves; it is deprecated in favour of a `FACEIDENTIFY_LIBRARY_ROOT` development/test
    override, whose priority is: explicit override, then the persisted setting, then first-run selection). The library
    lock (question 23) is taken right after the root is resolved and minimally validated, before migrations, recovery,
    workers or any mutation; a held lock fails startup for that library and never falls back to another. Changing library
    means restarting the backend lifecycle.
18. **Open: batch-mode migrations and multi-revision failure atomicity are unproven.** `env.py`
    enables `render_as_batch` from the first revision because SQLite needs table recreation for
    most constraint changes, but revision `0001` only creates tables, so batch mode is exercised
    by no test yet. The second revision must add a populated-database upgrade test (and check
    that recreating a table with `PRAGMA foreign_keys = ON` behaves), a test that a failing
    *second* revision leaves `0001` applied as intended, and one for a Python error raised
    inside `upgrade()`; today only one failure shape is tested.
    **2026-10-01 (owner):** deferred to the second Alembic revision (TST-032), which the `ERASING` state of question 25 will provide.
    **Resolved with revision `0002` (same day):** a plain recreation of `representations` *failed* on a
    populated database (foreign keys on); `env.py` now follows SQLite's procedure (enforcement off
    outside the transaction, `foreign_key_check` before each revision commits). Tested: a populated
    upgrade, a Python error after the recreation, a dangling reference, an already inconsistent
    database, and downgrade; each revision is its own transaction, so a failing second revision leaves
    `0001` applied. Persistence section 27 has the decision note.
19. **Open: what `alembic downgrade` should do to a populated library.** It destroys data, and
    whether foreign keys stop it is data-dependent (a richly populated database fails
    atomically; a simple one is dropped without complaint). Production never downgrades, and
    the README marks it development-only. Decide whether to leave it, or refuse to downgrade a
    non-empty database unless explicitly forced.
    **2026-10-01 (owner):** deferred to the second Alembic revision (TST-032).
    **Decided 2026-10-01 (owner) and built (issue 35):** a downgrade that could destroy information
    is refused on a *populated* library by default (populated = user/domain data, not merely a row in `app_state` or
    migration bookkeeping), with an explicit development-only override (`FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1`) that
    the application never sets; an empty library downgrades normally; a refused downgrade leaves the database unchanged;
    production recovery moves forward with corrective migrations, never by schema rollback. Built as `backend/infrastructure/db/downgrade_guard.py`: every revision's `downgrade()` starts with the guard (a test enforces it), 'populated' excludes the internal and re-creatable metadata tables listed there (the agent's reading of the owner's definition; a table not listed counts as data; an `artifacts` row is internal only if a catalog row references it and no source or observation does; `ann_key_sequences` is data), an offline `--sql` run is let through, and the override is exactly `=1`.
20. **Final; the unit of work is built, the services are not yet moved onto it (issue 37, 66; `backend/infrastructure/db/unit_of_work.py`): `BEGIN IMMEDIATE` write units of work, whole-transaction bounded retry, `DatabaseBusyError` on exhaustion.** Original question follows. Persistence §25 requires the application
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
    **2026-10-01 (owner): pre-approved for finalisation with item 3 of the build order, without coming back:** write units of
    work use `BEGIN IMMEDIATE`; retry is bounded and at the whole-transaction boundary, never per statement and never for
    non-idempotent work outside the transaction; exhaustion becomes a retryable application/API error. If implementation
    contradicts an existing spec, isolate that part and open an issue.
    **Built 2026-10-02:** `UnitOfWork.write` begins with `BEGIN IMMEDIATE` (engine execution option `sqlite_begin_immediate`), retries the whole transaction on SQLITE_BUSY/LOCKED (decided by result code, not text) with the caller's attempts and back-off (no defaults), and raises `DatabaseBusyError`. `work` must be a function of the session only. `open_library` exposes it as `OpenLibrary.unit_of_work`. **Built 2026-10-05:** the IndexCoordinator's requeue and settlement writes use that shared UnitOfWork so acceptance can contend through the same writer boundary. **Built 2026-10-06 (M3.1, issue 66):** the `RepresentationEraser`'s three writes (queueing, clearing, the WAL marker) and recovery's own writes in `startup.py` (interrupting in-flight work, marking a refused FINAL `NOT_RESUMABLE`) now go through the same UnitOfWork, each a retry-safe function of its session. Still on plain sessions by design: the artifact settlement and missing-original functions in `backend/app/sources/` (`recover_artifacts`, `mark_missing_*`), which interleave file effects with short transactions and run before any other writer exists (issue 66 records this remainder).
21. **Final (issue 38; spec §6.3 amended 2026-10-02): allocation at ANN-eligibility, run-local index uses ephemeral labels.** Original question follows. Two spec
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
    **2026-10-01 (owner): pre-approved for finalisation with item 3:** `ann_key` is allocated when a representation becomes
    ANN-eligible, unique within its space; run-local indexes use their own ephemeral labels and never depend on permanent
    keys of transactions that might roll back.
    **Finalised 2026-10-02:** Persistence §6.3 amended (issue 38).
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
    **2026-10-01 (owner): finalised and built as `backend/infrastructure/storage/library_lock.py` (an OS-level non-blocking lock, released by a crash or kill; tested with real subprocesses) and wired first in `open_library`, before the layout, the migrations and recovery, with a killed real backend freeing it (issue 33):** an exclusive library-lifetime lock at
    `<LibraryRoot>/database/.lock`, taken after question 17's resolution and validation and before migrations, recovery,
    workers or any mutation; another live owner fails startup for that library; released on orderly shutdown; an OS-level
    lock so a crash never leaves the library locked.
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
    updated (persistence 6.2, 23, 28; architecture 23; testing strategy INDEX-03, INDEX-04, INDEX-05, PER-07). Candidate revalidation resolves each
    `ann_key` to its representation row (`resolve_ann_candidates`, built; returns plain values and reads 500 keys per query; issue 44 closed).
    **Built:** the `ERASING` state (revision `0002`, which is also the populated batch-mode migration
    question 18 needed). **Built (2026-10-01, PR for issues 29 and 52):** the erasure use case
    (`backend/app/memory/erasure.py`), coordinator retirement of old generations before a `REMOVE` is applied, recovery of
    `ERASING` and the tests. Owner answers: `ACTIVE`, `PENDING` and `SUPERSEDED` may be erased (a keyless one skips the
    index work); representation-level erasure writes no Evidence (section 7's Evidence is for the identity-level forget).
    **Agent finding, decided by the owner 2026-10-02 (issue 57):** persistence 6.2 item 2 said a single erasure "needs no rebuild",
    but a USearch generation saved after `remove()` still holds the vector's bytes (probed), so the `REMOVE` of an `ERASING`
    representation rebuilds the space (one rebuild per space for a bulk). The keyless-`REMOVE` rebuild stays as a safety net.
    SQLite's own residue is question 30.
26. **Decided 2026-10-01 (owner), built for `PAUSING`/`CANCELLING`:** startup recovery marks a job or run found `PAUSING`
    `PAUSED` (nothing runs; the worker is gone) and one found `CANCELLING` `CANCELLED` (the user's intent;
    partial output stays private and is never activated). A `RUNNING` job is `INTERRUPTED`, never
    requeued. Recovery is idempotent by construction (guarded transitions), tested by a stop after each
    step and a rerun. **Built** (PR for issue 30): the `PAUSING`/`CANCELLING` transitions in
    `backend/app/recovery/startup.py`. **Still open, for the M3 run lifecycle
    (issue 34):**
    `FINALIZING` runs (revalidate and accept without redoing ML, `AcceptProcessingRunUseCase` is built, PR #106) and a
    run with pending output and no final checkpoint. **Built 2026-10-06 (issue 34; clarification decided by the owner the same day, Persistence 15 and 28):** a `FINALIZING` run is accepted by startup recovery without ML, its job kept `RUNNING` until then; a refused FINAL leaves the run `NOT_RESUMABLE` and its output private; a pre-FINAL crash is `INTERRUPTED` with the PENDING output kept private, never discarded or requeued; a retry is a new Job (`previous_job_id`) and Run (`parent_run_id`) on a copy of the frozen snapshot (`RetryProcessingUseCase`), never made by recovery. (Interrupted runtime installations are built: `RuntimePackageStore.recover`.)
28. ~~Open: `ann_key` is globally unique but allocated per space (the same conflict as question 13).~~ **Decided 2026-10-01 (owner, issue 48):**
    an `ann_key` is unique within its space, `UNIQUE(representation_space_id, ann_key)`, as revision `0003`
    (specs: persistence 6.2, 6.3), **built** in revision `0003`. Every index lookup and removal carries the
    space and the key (already true: an index belongs to one space, and `resolve_ann_candidates` looks keys
    up by the pair); allocation
    stays at ANN-eligibility time (question 21, final) and run-local indexes keep ephemeral labels.
29. **Decided 2026-10-01 (owner, issue 51): snapshots are immutable and one per run, in the database.** One
    snapshot per run is already enforced (`uq_processing_runs_configuration_snapshot_id`; I had wrongly said it
    was not, in PR 50, and corrected it). Immutability is two triggers (revision `0003`, **built**): `UPDATE` always aborts,
    `DELETE` aborts while a run references the snapshot. **Known limit (closed by revision `0005`, a third trigger, issue 55):** `INSERT OR REPLACE` on a snapshot no run
    references was not stopped (SQLite fires no delete trigger for it). **Decided (final) 2026-10-01 (owner), to be built with
    the run and Source deletion use cases:** deleting a run
    retains its snapshot as historical evidence; permanent deletion of a Source deletes its runs and then their
    now-unreferenced snapshots (the database allows any caller to delete an unreferenced snapshot, so "only
    the lifecycle does" is the application's rule, not a database guarantee). Snapshots carry every value needed to reproduce a
    run, never references to mutable rows (persistence 13).
30. **Decided 2026-10-01 (owner, issue 31): `PRAGMA secure_delete = ON` on every connection, and a
    `wal_checkpoint(TRUNCATE)` after each erasure batch commits**, retried later if readers prevent it, with the
    erasure reported as having outstanding cleanup until it succeeds. Not a guarantee of physical erasure.
    The owner's sequence is merged with question 25's: queue and exclude (`ERASING`); apply the index removal or
    publish a replacement generation; retire old and quarantined generations; clear the vector and key and
    commit; checkpoint; verify (persistence 6.2 item 9, 25). A durable "WAL truncation owed" marker is needed
    (set with the clearing transaction, cleared after a successful truncation) so a crash between them is
    recoverable; its mechanism is for the owner to confirm (issue 52). **Built (2026-10-01):** `secure_delete = ON` in
    `SQLITE_PRAGMAS` and `truncate_wal(engine)` in `backend/infrastructure/db/engine.py` (False when a reader blocks it),
    with the byte-search tests in `test_sqlite_erasure_policy.py`. **Decided and built (owner, 2026-10-01):** the owed
    marker is a key/value table `app_state` (revision `0004`, only that), key `wal_truncation_owed`, set in the clearing
    transaction and cleared (compare-and-delete) after a successful truncation; startup recovery runs the checkpoint while
    it is set; the erasure use case calls the checkpoint and never reports complete without it.
27. **Decided (final) 2026-10-01 (owner): how an obsolete `IndexOperation` is superseded. Keep deleting; no `SUPERSEDED`
    state and no revision for an audit trail. Only a `PENDING` operation may be deleted this way: an `APPLIED` or
    otherwise historical one is never rewritten or deleted because a later opposite operation exists.** (Was provisional;
    the erasure use case, which appends operations, is built.) Persistence
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

31. **Decided 2026-10-02 (owner), all three parts (found building registration, M3 step 7c).** (1) **Decided:** a persisted `RepresentationSpace` is `ACTIVE` or `DEPRECATED` only (Persistence 6.1, the schema); ML 9.2's `REGISTERED`/`VALIDATED`/`ACTIVE`/`RETIRED` mix a registration process (discover, validate, register) with the durable lifecycle, so `REGISTERED` and `VALIDATED` are not persisted states and `RETIRED` is `DEPRECATED`; a newly registered valid space is `ACTIVE` (what registration does); whether a variant is validated for a space lives on its compatibility row (`DECLARED`, later `VALIDATED`). Dated notes are in Persistence 6.1 and ML 9.2. (3) **Decided:** `RepresentationSpace.component_version_id` is origin provenance (the component version that established the space), not every version that produced vectors in it; a later component version with identical space-defining semantics shares the space and does not overwrite it; a new model with other weights is a new space. The invariant: space identity describes compatibility, execution provenance describes what produced the data (per run and segment, and per observation through `detector_component_version_id`; the plan for recording the embedder's actual component and variant is the PENDING-output writer's, M3 step 7 last part). Notes in Persistence 6.1 and at the paragraph on new embedding models. (2) **Decided:** the manifest component `contract` keys registration requires (a `FACE_DETECTOR`: `preprocessing_contract`; a `FACE_REPRESENTATION`: `family`, `dimension`, `preprocessing_contract`, `normalization`, `normalization_contract_version`, `compatibility_version`) are approved, **with `family` removed from the space identity**: a space is identified by the weights digest, dimension, preprocessing contract, normalization, normalization contract version and compatibility version; `family` stays a required descriptive field (a human-controlled label must not split a space); the provider, variant, device and requirements are excluded; `compatibility_version` stays separate and is bumped only deliberately, with a documented reason, when representations must become incompatible. Notes in Architecture 12.2 and ML 18.1. Built (PR for this change). **Follow-up, GitHub issue 88 (Q6):** there is no unambiguous durable path from a Representation to the embedder's actual component version, export and runtime variant (a segment names one variant and a run executes two components; the snapshot is intent), so the PENDING-output writer is held until the owner chooses a persistence shape. **Decided 2026-10-03 (owner), option C:** a nullable `runtime_variant_id` FK on `representations` (the embedder variant that actually executed) and on `observations` (the detector variant that actually executed); the chain variant, export, component version is the provenance path and no export or component id is duplicated; the catalog rows stay durable (`RESTRICT`); the application requires the value for newly produced ML output; `observations.detector_component_version_id` stays and must agree with the variant's component version; `execution_segment_id` stays lifecycle context and segments are not split per stage; `RepresentationSpace` gains nothing; no provenance table (Persistence 5, 6.2, 14). The columns are delivered by migration 0005 (**built 2026-10-03**), so the PENDING-output writer is built right after that revision.

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
6. The rest of M2: TST-022 (repository contract; `JobRepository`, `SegmentRepository`, `CheckpointRepository`, `IndexOperationRepository`, `SourceRepository`, `ProcessingRunRepository`, `SnapshotRepository`, `ObservationRepository`, `RepresentationRepository`, `IdentityRepository`, `OccurrenceRepository`, `EvidenceRepository`, `SettingsRepository`, `RuntimeCatalogRepository` done; TST-022 passing), ~~TST-027 (USearch integration)~~ done, ~~TST-028
   (IndexOperation replay)~~ done, ~~TST-029 (cross-storage failure)~~ done, ~~TST-030 (startup recovery beyond
   artifacts)~~ done (M3 step 12; only the FastAPI lifespan remains), TST-031 (deletion: representation erasure
   done; Source deletion, Recycle Bin cleanup and identity-level forget remain).
7. **M3 (single-image ML integration) is in progress (2026-10-02 onward).** The 14-step plan is authoritative. Steps 1 through 6 are complete: decisions, the ML IPC contract (TST-033), machine-local runtime packages and recovery, shared-memory worker/supervisor, and image decode/import (TST-036/037). Step 7's versioned SCRFD/ArcFace contracts, ONNX worker handlers, runtime catalog registration, machine-specific planning, perception client, and PENDING-output writer are complete. The writer persists each detector result first as a PENDING observation, then attaches its settled embedding as a PENDING representation; an embedding failure leaves the observation PENDING and writes no representation. Each output records the runtime variant that actually executed (issue 88), while the representation space remains compatibility metadata. Steps 8 and 9 are complete: run-local/global retrieval (TST-040) and the recognition assessment/reasoner (TST-041/042). Step 10 now has its request, claim/start, and private execution boundaries: `ExecuteProcessingJob` performs decode → detect → private observation → embed → private representation → retrieve/reason → private decision, keeps ML outside write transactions, writes INTERMEDIATE then valid FINAL checkpoints, and moves the run to FINALIZING without making output authoritative. It checks cancellation only between safe boundaries. The runtime planner accepts the snapshot's exact detector and embedder exports and refuses a substitute. There are no M3 mutable defaults (decision 2026-10-04, issue 98); M4 defaults will produce the same request. M3 permits only the implemented uncalibrated interpretation and refuses a profile request or a runtime policy without usable matching detector/embedder variants. Identity-less ACTIVE representations remain readable candidate evidence but are never offered as MATCH_EXISTING targets. **Known conflict:** Persistence §14 says any provider/export/variant change starts a new execution segment, while the owner decision dated 2026-10-03 says segments must not be split per detector/embedder stage. The PerceptionClient supplies actual successful output variants but not fallback-history events; output provenance is correct, but fallback segment history is not yet claimed complete. Step 11 now accepts an identity-less ACTIVE candidate through migration 0006 and records `RECOGNITION_ABSTAINED` Evidence for accepted ABSTAIN output (PR #106, closing issue #104). Runtime packages remain machine-local and are never substituted; `ABSTAIN` creates no Occurrence and is resolved later without an `ann_key` change; a representation-space key excludes provider and descriptive family. TST-044 remains post-M3, Q16 remains deferred unless M3 makes it unavoidable, and issue 80's remaining installation-MISSING sweep waits for real weights and issue 69.

   > **Decision 2026-10-06 (owner):** M4 runs the vertical slice on a clearly named development/evaluation decision-policy profile, marked uncalibrated and non-release in the frozen snapshot and shown as such in the UI; its numbers are not shipped defaults, and TST-044 gates any calibrated release policy. The real SCRFD/ArcFace path stays blocked on issue #69 (source, exact artifact and version, hash, licence, redistribution status, verifier); M4 uses fakes. Startup recovery must complete before the scheduler claims work. See `docs/plans/M3_M4_COMPLETION_PLAN.md`.

   > **Decision 2026-10-05 (owner):** The apparent §14 conflict is resolved by #102 and PR #101: only a real provider fallback starts a successor execution segment; detector-to-embedder movement does not. The step-11 acceptance branch now validates a current FINAL checkpoint and atomically activates outputs, writes occurrences/evidence plus durable ADD operations, moves the source pointer and completes run/job before a post-commit index wake. `ABSTAIN` creates `RECOGNITION_ABSTAINED` evidence, an identity-less ACTIVE representation and no Occurrence. **Remediation 2026-10-06:** FINAL's v1 decision evidence now fails closed for unknown/missing versions and fields, contradictory decision facts, incoherent semantic/candidate snapshots, and a CREATE_NEW FINAL records the resolved Identity in both outer and evidence forms. Repeated acceptance revalidates exact durable Evidence/link/candidates, Occurrence membership or its absence, and one ADD operation. The focused acceptance/execution suite passed 151 tests at 100% line/branch coverage with thirteen guard mutations caught; the final full gate passed 2,328 tests at 100% coverage. The independent review and exact-head CI passed before PR #106 merged and closed issue #104. Step 12 wires recovery to this boundary.
8. Owner's build order (2026-10-01): ~~the remaining repositories (issue 32)~~ done, ~~the downgrade policy (35)~~ done, ~~the library root and lock (36, 39)~~ built and wired into `open_library`, ~~lifespan wiring and process-kill tests (33)~~ done except the FastAPI lifespan itself (no web app exists yet),
   the rest of Q26 (34), the downgrade policy (35, question 19), the library root (36, question 17), and the
   validations Q20, Q21, Q23, Q27 (37 to 41, all final now; the M3 run-local index of Q21 is built, step 8), deriving a missing original's availability from its artifact (Q24).
   Issue 55 (block `INSERT OR REPLACE` on snapshots) was built in revision `0005` (2026-10-03).

Model rules: CHECK constraints only where a spec defines the complete value set; otherwise a
plain string, listed as an open question. Every schema change is now a reviewed Alembic revision
(see `backend/alembic/README`).
