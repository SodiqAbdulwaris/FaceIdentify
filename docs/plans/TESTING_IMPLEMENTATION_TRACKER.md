# FaceIdentify — Testing Implementation Tracker

**Version:** 1.0  
**Status:** M0 complete (TST-008 factories, PR #5); M1 complete (TST-011 through TST-020, PR #10)  
**Related document:** `TESTING_STRATEGY.md`

## 1. Tracking conventions

Every task has a stable identifier, responsible component, priority and completion criterion.

Priorities:

- **P0:** Required for critical correctness or the relevant integration milestone.
- **P1:** Required before the affected functionality is considered release-ready.
- **P2:** Extended validation, optimisation or later functionality.

Statuses:

- `PLANNED`
- `IN_PROGRESS`
- `BLOCKED`
- `PASSING`
- `COMPLETE`

`PASSING` means the implemented test currently passes.

`COMPLETE` means the test, relevant documentation, required CI integration and review are finished.

All tasks below begin as `PLANNED`. This document does not claim that their implementation already exists.

---

## M0 — Testing foundation

**Goal:** Establish reproducible, isolated test execution.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-001 | P0 | Configure pytest | Unit and integration tests execute |
| TST-002 | P0 | Configure async testing | Async backend tests execute reliably |
| TST-003 | P0 | Configure coverage | Coverage reports are generated |
| TST-004 | P0 | Implement test markers | Suites can be selected independently |
| TST-005 | P0 | Create isolated SQLite fixtures | Tests cannot modify real libraries |
| TST-006 | P0 | Create isolated filesystem fixtures | Temporary storage is controlled |
| TST-007 | P0 | Create USearch fixtures | Real temporary indexes can be tested |
| TST-008 | P0 | Create deterministic factories | Reproducible domain data |
| TST-009 | P1 | Configure Vitest | Frontend tests execute |
| TST-010 | P0 | Create initial CI | Static and fast tests run automatically |

**Dependencies:** Repository structure and development environment.

**Milestone gate:** A fresh development environment can execute the initial test suite without using real application data.

### M0 status (2026-09-23)

Verified locally on Windows 11 (Python 3.12.14) and on GitHub Actions (PR #1, run `35902624488`: all five jobs green, 19 backend and 1 frontend tests passed). PR #1 was reviewed and merged by the owner on 2026-09-23, which completes the review criterion for `COMPLETE`.

| ID | Status | Evidence / remaining work |
|---|---|---|
| TST-001 | `COMPLETE` | `pyproject.toml` pytest config; unit, integration and security suites execute |
| TST-002 | `COMPLETE` | pytest-asyncio `auto` mode; async + HTTPX tests in `tests/unit/test_test_infrastructure.py` |
| TST-003 | `COMPLETE` | pytest-cov with branch coverage; term/XML/HTML reports generated. No threshold (per strategy §19) |
| TST-004 | `COMPLETE` | 11 strict markers; directory-based auto-marking (`tests/contracts/` → `contract`); expensive suites excluded by default; `-m` selection verified |
| TST-005 | `COMPLETE` | `sqlite_engine`/`db_session` use the production engine factory (Persistence §24/§25); pragmas, FK enforcement and per-test isolation tested; leak detection verified by mutation. Schema initialisation was `Base.metadata.create_all` until M2; it is now a per-test copy of a database migrated to Alembic `head` (`migrated_template_db`) |
| TST-006 | `COMPLETE` | `app_dirs` + `_require_inside` guard; session-wide user-data env sandbox |
| TST-007 | `COMPLETE` | `make_usearch_index` with real USearch 2.26: add/search/save/restore/remove tested |
| TST-008 | `COMPLETE` | Deterministic clock/UUID/RNG utilities (M0) plus `tests/factories/models.py` (M1 PR #5, merged): builders for sources, runs, jobs, observations, representations, identities, evidence, lineage, index operations, occurrences, people and associations. Link and catalog rows are built inline (see TESTING_GUIDE.md) |
| TST-009 | `COMPLETE` | Vitest 5 + React Testing Library + jsdom in `frontend/`; `src/app/App.test.tsx` passes; typecheck, lint and build pass |
| TST-010 | `COMPLETE` | `.github/workflows/ci.yml`: branch name, commit messages, static (ruff, mypy), backend tests + coverage artifact (Windows), frontend. Observed green on GitHub (run `35902624488`) |
| SEC-001 | `COMPLETE` | `tests/security/test_test_data_isolation.py` |

---

## M1 — Domain integrity

**Goal:** Verify identity and observation behaviour independently of actual ML inference.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-011 | P0 | Identity creation tests | Stable, valid identity creation |
| TST-012 | P0 | Assignment tests | Authoritative assignment consistency |
| TST-013 | P0 | Correction tests | Historical evidence is preserved |
| TST-014 | P0 | Rename tests | Identifier and history remain stable |
| TST-015 | P0 | Merge tests | Documented merge invariants hold |
| TST-016 | P0 | Split tests | Documented split invariants hold |
| TST-017 | P0 | Observation tests | Source provenance is preserved |
| TST-018 | P0 | Historical-event tests | Committed changes are represented correctly |
| TST-019 | P0 | Query-only recognition tests | Search does not silently create memory |
| TST-020 | P1 | Property-based tests | Generated operation sequences preserve invariants |

**Dependencies:** M0, authoritative identity and observation contracts.

**Milestone gate:** Applicable identity and observation invariants pass.

### M1 status (2026-09-23)

Verified locally on Windows 11 (Python 3.12.14): `uv run pytest` gives 238 passed, 0 skipped, 0
warnings, `backend/` coverage 100%. Remote CI observed green on PR #4 through PR #9. M1 is
complete: TST-011 through TST-020 all `PASSING`.

| ID | Status | Evidence / remaining work |
|---|---|---|
| TST-011 | `PASSING` | `backend/app/identities/use_cases.py`: `create_pending_identity` and `activate_identity`. Stable UUID identifier verified across the PENDING→ACTIVE transition; optimistic-locking (stale `revision`) and invalid-transition rejection tested and mutation-checked |
| TST-012 | `PASSING` | `assign_representation_to_identity`: a PENDING representation can only be assigned once; many representations may authoritatively point to one ACTIVE identity; an inactive identity cannot receive a new assignment. All four rejection paths are tested for leaving no partial state (no leaked `ann_key`, `Evidence` or `IndexOperation`) |
| TST-017 | `PASSING` | `test_assigning_an_identity_never_touches_observation_provenance` and `test_each_observation_keeps_its_own_run_and_source` in `tests/integration/test_identity_manager.py` |
| TST-018 | `PASSING` | `test_evidence_is_append_only_across_later_operations` (an Evidence row is byte-identical after a later, unrelated operation) and `test_evidence_kind_records_whether_the_identity_was_new_or_matched` (IDENTITY_CREATED vs IDENTITY_MATCHED) |
| TST-013 | `PASSING` | `backend/app/people/use_cases.py`: `assign_identity_to_person` calling itself again with a different person is the correction — the old association becomes `SUPERSEDED` (never deleted) and its `Evidence` is untouched; a new `Evidence` row explains the change. `test_reassigning_to_a_different_person_corrects_the_link_and_preserves_history` |
| TST-014 | `PASSING` | `rename_person`: changes only `display_name`/`normalized_name`; the Person's own id, and any linked Identity's id/state/Evidence, are unaffected. Optimistic-locked (stale `revision` rejected), mutation-checked |
| TST-015 | `PASSING` | `backend/app/identities/use_cases.py`: `merge_identities`. Identity-level merge (§18): the losing identity keeps its row (`MERGED`, `merged_into_identity_id` set), never deleted; its ACTIVE representations move to the survivor with `ann_key` untouched; the Person link is reconciled (survivor's own link always wins, the loser's is carried over only if the survivor has none); one `Evidence(IDENTITY_MERGED)` and one `identity_lineage` `MERGED_INTO` edge are recorded. Self-merge, a non-ACTIVE survivor or loser, and a stale revision are all rejected; rejection leaves no partial state |
| TST-016 | `PASSING` | `split_identity`: creates a new, directly-`ACTIVE` identity (§19.2) and moves the caller-selected representations to it, `ann_key` untouched; the source keeps everything else and stays `ACTIVE`. One `Evidence(IDENTITY_SPLIT)` and one `identity_lineage` `SPLIT_FROM` edge are recorded. An empty selection, an unknown/foreign/non-ACTIVE representation, and a non-ACTIVE or unknown source are all rejected; rejection creates no identity and moves nothing |
| TST-019 | `PASSING` | `backend/app/identities/use_cases.py`: `resolve_recognition_candidates` (`API and Contracts.md` §12.2: "ANN candidate retrieval -> authoritative SQLite revalidation"). Read-only: a candidate is resolved through any merge chain to its current identity, dropped if missing or not ACTIVE, and de-duplicated; the function never creates or updates any row, proven for a mix of known/unknown/merged/forgotten/deleted/duplicated candidates in the same call. `resolve_ann_candidates` (`tests/integration/test_ann_candidate_revalidation.py`, 21) revalidates the `ann_key`s an index returns at *representation* level, 500 keys per SELECT, returning plain values: kept only if the row is in the space, `ACTIVE`, with an `ACTIVE` identity (every other representation and identity state, and another space's key, is dropped; a merged-away identity's key resolves to the survivor); a stale index that still holds an `ERASING` vector does not return it for an active identity (the retrieval half of INDEX-03); input order kept, repeats removed before the query, reads only and touches no ORM object (a caller's unflushed change survives); 9 mutations, one equivalent |
| TST-020 | `PASSING` | `tests/property/test_identity_lifecycle_invariants.py`: a Hypothesis `RuleBasedStateMachine` generates sequences of create/activate/assign/assign-person/remove-person/rename/merge/split calls against a real SQLite database, checking after every step that each identifier's revision matches an independently predicted count of bumps, Evidence only grows, every ACTIVE representation stays ANN-eligible, and a query never writes anything |

---

## M2 — Persistence

**Goal:** Verify durable authoritative state and recoverable derived state.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-021 | P0 | SQLite configuration tests | WAL and required constraints verified |
| TST-022 | P0 | Repository contract tests | Real SQLite behaviour verified |
| TST-023 | P0 | Transaction rollback tests | Partial authoritative writes cannot commit |
| TST-024 | P0 | Optimistic concurrency tests | Stale semantic updates are handled |
| TST-025 | P0 | Storage Manager tests | Managed and referenced storage contracts pass |
| TST-026 | P0 | Artifact-finalization tests | Pending and available states are correct |
| TST-027 | P0 | USearch integration tests | Index operations work with real USearch |
| TST-028 | P0 | IndexOperation replay tests | Index synchronization is idempotent |
| TST-029 | P0 | Cross-storage failure tests | Partial failures are recoverable |
| TST-030 | P0 | Startup recovery tests | Interrupted state is reconciled |
| TST-031 | P0 | Deletion tests | Cleanup and isolation rules hold; no residue in SQLite after an erasure (PER-08); erasure is two-step (`ERASING`), queued erasures are excluded from retrieval at once, through representation-level revalidation (INDEX-03), superseded and quarantined index generations are verifiably retired (INDEX-04), erasure and the coordinator do not race (INDEX-05), and every erasure step recovers idempotently (PER-07) |
| TST-032 | P1 | Migration tests | Supported populated schemas migrate correctly |

**Dependencies:** M0, applicable M1 domain contracts, Persistence Implementation.

**Milestone gate:** Representative identity and observation records can be committed, retrieved and recovered without violating authoritative-state invariants.

### M2 status (2026-10-01)

Verified locally on Windows 11 (Python 3.12.14): `uv run pytest` gives 921 passed, 0 skipped, 0
warnings, `backend/` coverage 100%. Remote CI observed green on PR #11. Only part of M2 has been
started.

| ID | Status | Evidence / remaining work |
|---|---|---|
| TST-032 | `IN_PROGRESS` | `backend/alembic/` with revision `0001_initial_schema`; `tests/integration/test_migrations.py`: a fresh upgrade produces exactly the models' tables, indexes (including partial-index `WHERE` clauses), columns and named CHECK/FK/UNIQUE constraints; `alembic check` reports no drift; head is a single linear chain; upgrade is idempotent; downgrade removes every table and round-trips; a failed migration leaves an existing database untouched (no partial schema, data intact); offline `--sql` works. Every other persistence test also runs on the migrated schema. Revision `0002_representation_erasing_state` (the `ERASING` state) is the first to migrate *from* a populated schema: `tests/integration/test_migration_0002.py` (11) upgrades a database holding rows that reference `representations` with every row kept and no dangling reference, accepts `ERASING` while the other CHECKs still hold, shows foreign key enforcement is off while the revision runs (a plain recreation failed with enforcement on), and shows a Python error after the recreation, a reference left dangling and an already inconsistent database are each rolled back to `0001` untouched, and that in one `upgrade head` a failing `0002` leaves `0001` applied (each revision commits on its own); downgrade round-trips, and is refused atomically while a representation is `ERASING` (Q19 stays open); offline `--sql` prints the recreation; 16 mutations, all caught. **Remaining:** none for the downgrade policy: it is built (`backend/infrastructure/db/downgrade_guard.py`, `tests/integration/test_downgrade_guard.py`, 27: a library without data downgrades freely, internal metadata does not count as data, a populated library is refused at every revision before anything changes and left byte-identical, only the exact override `=1` lets it through, an unknown table counts as data, an AST test fails the build for a revision whose `downgrade()` does not start with the guard; 19 mutations, all caught). Revision `0003_ann_key_per_space_and_snapshot_triggers` (decided 2026-10-01; PER-09, PER-10; issues 48 and 51): `UNIQUE(representation_space_id, ann_key)` on `representations` instead of a table-wide `UNIQUE(ann_key)`, and two triggers making snapshots immutable (`UPDATE` always aborts; `DELETE` aborts while a run uses the snapshot; one snapshot per run was already `uq_processing_runs_configuration_snapshot_id`). `tests/integration/test_migration_0003.py` (13) migrates a database that holds rows at `0002` with every row and key kept; the same key in two spaces is allowed and twice in one refused; a snapshot cannot be updated by SQL or the ORM (even to the same values) or deleted while a run uses it, and one no run uses can be; a Python error after the recreation and triggers, a dangling reference and a failing third revision in one upgrade each roll back to `0002` untouched; foreign key enforcement is off while it runs; downgrade restores the old constraint and drops the triggers, and is refused atomically while two spaces share a key; offline `--sql` prints it; `test_migrations.py` compares the trigger text with `create_all`; 16 mutations, all caught. The helpers shared with the `0002` tests are in `tests/fixtures/migrations.py`. Revision `0004_app_state` (issue 52): `tests/integration/test_migration_0004.py` (7) migrates a populated `0003` database with every row kept, a failing revision leaves it at `0003` without the table, downgrade drops the table, the key must not be empty, `AppStateRepository` upserts, deletes, and compare-and-deletes |
| TST-021 | `PASSING` | Pragmas (`foreign_keys`, WAL, `synchronous`, `busy_timeout`, `temp_store`) and per-connection FK enforcement: `test_persistence_fixtures.py`; required constraints: `test_schema_contract.py`, `test_core_models.py`; WAL *behaviour*: `test_sqlite_wal_behaviour.py` (WAL persisted in the file itself, a reader is not blocked by an open write transaction, a second writer is refused while the lock is held, and a reader-turned-writer fails immediately once another writer has committed — see CONTEXT open question 20) |
| TST-023 | `PASSING` | `tests/integration/test_transaction_rollback.py`: for 8 use-case paths (assign a representation as CREATED and as MATCHED, activate, merge, split, correct/remove a Person link, rename), a fault is injected at *every* SQL statement each sends (59 points, 32 of them writes; a final unfaulted run must send exactly the same statements); after the caller's rollback the same session commits, and every row of every table is unchanged. Also: closing the session without committing discards a successful use case's writes, and a merge that flushed before its stale-revision check commits nothing. Mutation-checked: a use case committing mid-way is caught in all four places it was injected. See CONTEXT open question 21 on `ann_key` reuse after rollback |
| TST-024 | `PASSING` | `tests/concurrency/test_optimistic_concurrency.py`: with separate sessions, a stale rename, activation and merge are each rejected and change nothing; with simultaneous threads (5 rounds each) exactly one rename lands (revision bumped once, never per writer), exactly one activation, and exactly one merge of a shared loser (with its Person link carried over once). Mutation-checked, and stable over 25 repeated runs. Only Person and Identity have revision-guarded use cases so far |
| TST-025 | `PASSING` | Managed storage: `tests/integration/test_storage_files.py` (layout on both roots; only exactly-generated keys accepted, refusing Windows aliases, device names, `..`, absolute/drive/UNC forms and junction escapes; staged write → sha256 → fsync → atomic no-overwrite rename, no partial final file on any failure, including a file racing in before the rename) and `tests/integration/test_artifact_storage.py` (ID-oriented keys, deletion intent → bytes → finalize, referenced originals never deleted, `verify_artifact`, report-only `scan_storage`). Referenced originals: `tests/integration/test_referenced_artifacts.py` (50; inspection refuses relative, missing, directory, unreadable and in-application-root paths, including through links; an import records `REFERENCED`/`AVAILABLE` with the fingerprint; a missing or changed original becomes `MISSING` with its own code and a matching file makes it `AVAILABLE` again; the Source and the external file are never touched; an unchanged re-check writes nothing; 23 mutations, all caught). Relinking: a `MISSING` original is relinked only to a file whose size and SHA-256 equal the recorded ones (a different file, even of the same size, is refused and changes nothing; the candidate is inspected like an import; the write is state-guarded; the resolved path is recorded; 9 mutations: 8 caught, 1 equivalent). Temporary workspaces: `tests/integration/test_workspaces.py` (22; allocated under machine-local `temp/jobs/<id>/` with the standard subdirectories, idempotent, released completely, orphans removed and live jobs kept, only directories the manager named are ever deleted, links are never followed in or out, one locked workspace does not stop the rest; an ownership marker, reparse points and read-only files handled; mutations checked, two unobservable guards documented). Recycle/restore: `tests/integration/test_source_recycle.py` (25; `ACTIVE` ⇄ `RECYCLED` is revision-guarded and touches only the `sources` row, proven by comparing every other table and the managed bytes before and after; only the right states move; a stale revision is reported first; a restore is refused once the original's bytes are gone but allowed while a referenced original is merely `MISSING`, evaluated by the database so a cached original cannot defeat it; 21 mutations, all caught). Conservative cleanup: `tests/integration/test_storage_cleanup.py` (33; only `AVAILABLE` managed artifacts that nothing references, past a caller-supplied cutoff, are deleted, through the crash-safe protocol; the references are read from the schema and pinned by a test that needs a case per referencing column; the "unreferenced" check is part of the deletion-intent `UPDATE` so an artifact referenced after it was chosen is skipped; referenced originals, other states, recycled Sources' files and stray files on disk are never touched; one failure does not stop the rest; 18 mutations, all caught). Storage usage: `tests/integration/test_storage_usage.py` (16; AVAILABLE managed artifacts by kind, the Recycle Bin's share as an upper bound with each artifact counted once and only for recycled Sources, referenced originals reported apart with unknown sizes counted as unknown, sizes matching real files, only workspaces the manager made measured, iteratively, without entering a junction and reporting directories that vanish or cannot be listed, the volume's figures; mutation-checked). All TST-025 items are covered |
| TST-026 | `PASSING` | `test_artifact_storage.py`: the three-step PENDING → AVAILABLE protocol, and every crash window settled by startup recovery (crash before any byte, mid-write with a torn staging file, after the rename but before the AVAILABLE commit, after the deletion intent, after the bytes are gone), recovery idempotent and tolerant of an unreadable file, an unusable key or an undeletable staging file; it deletes only staging files whose artifact is settled. 21 mutations across two review rounds, all caught |
| TST-027 | `PASSING` | `tests/integration/test_representation_index.py` (76, real USearch and real files) and `test_plain_paths.py` (3): idempotent add and remove, nearest-first candidate search, key and vector validation, generations flushed and persisted behind an atomically replaced manifest (a crash before the replace leaves the old generation live; a read-only `open`; the writer cleans leftovers), every way an index can be unusable is detected and reported (no or unreadable manifest, unsupported format, another space, another dimension or metric read from the file header because `Index.load` adopts the file's own, a name that is not the generation's own, a missing, resized, wrong-hash, garbage or wrong-count index file, and links), quarantine that never overwrites, never follows a link and tolerates a locked file, and `open_or_rebuild` from streamed entries; two rounds of mutation checks, all caught or shown unobservable. The coordinator that replays `IndexOperation`s into it is TST-028 |
| TST-028 | `PASSING` | `tests/integration/test_index_coordinator.py` (27, real SQLite and real USearch files): an `ADD` or `REMOVE` is applied as a desired state after re-reading the representation, replaying one changes nothing (not even the index generation), an ineligible `ADD` adds nothing, operations run oldest first and only when due, a limit is honoured, the index is persisted before operations are marked `APPLIED` (a crash between the two, and a failure to persist, are both reproduced and recover), a bad operation does not stop the rest of its batch, retries back off and end in `FAILED`, each space has its own index, an unusable index is rebuilt from every `ACTIVE` representation in SQLite (a corrupt vector is skipped and reported), and an operation settled elsewhere is not double-counted, an erased representation's vector is gone from every file of the index (rebuild, old file verified removed), eligibility includes an active identity, passes are serialized; 37 mutations, all caught, removed or equivalent. Whether erasure should be ordered to avoid that rebuild is open question 25 |
| TST-030 | `IN_PROGRESS` | The library root and lock (CONTEXT questions 17 and 23): `tests/integration/test_library_root.py` (20: explicit, environment, persisted order; blank means unset; no invented default; relative, file and typo-deep roots refused; the local state root), `tests/integration/test_library_lock.py` (12: a second holder is refused promptly in this process and in a real second process, released by an orderly exit and by `taskkill /T` of a killed holder, never reentrant, idempotent release, two libraries independent) and `tests/integration/test_alembic_database_path.py` (11: explicit path, library root, deprecated variable, nothing guessed); 33 mutations, all caught. **Remaining:** wiring them before migrations and recovery in the lifecycle (issue 33). Earlier: `tests/recovery/test_startup_recovery.py` (72): each interrupted state from architecture §25.13 that has defined semantics is constructed and reconciled in one test (a dead worker's `RUNNING` job loses its lease and becomes `INTERRUPTED`, `RUNNING` runs and segments become `INTERRUPTED`, a `PENDING` artifact whose file was renamed is finalized, a deleted referenced original becomes `MISSING` by existence alone, workspaces of finished jobs are removed and those of jobs that may resume are kept, a corrupt index is rebuilt from SQLite and a pending `IndexOperation` applied); other states (a job that was already paused, queued work, `FINALIZING` runs, finished work) are left exactly as found, while `PAUSING` and `CANCELLING` work is now moved (see the end of this row); a second run changes no row and no file; a crash after each of the five steps, and inside the workspace removal, is repaired by running recovery again; a fault part-way through interrupting work rolls all of it back; stale leases are cleared from any job, failed index operations get one fresh set of attempts, a workspace is kept while its linked run is live, contradictory job/run combinations are each judged by their own state, and `unresolved`/`clean` distinguish a repair from unfinished work; catch-up is bounded and a failing operation cannot keep startup spinning; 45 mutations, all caught or equivalent. **Remaining:** what to do with `FINALIZING` runs, acceptance of a final-checkpoint run, runtime installation recovery (open question 26, issue 34), the application lifespan that calls it, and the process-level tests that kill a real subprocess (issue 33). Decided 2026-10-01 (open question 26) and implemented: a job or run found `PAUSING` becomes `PAUSED`, `CANCELLING` becomes `CANCELLED` (a cancelled job ends, its lease is cleared, its partial output stays private, a paused job's workspace is kept, and a cancelled one's is removable once no linked run that is still live needs it; the last sign of life, `heartbeat_at`, is kept as evidence, as for `RUNNING`); a second run changes nothing (the world fixture now holds both states), a crash after any step reaches the same end state, a failure at any of the three run updates rolls back the whole interruption, and the reported ids are sorted (PER-06); 21 mutations, all caught. Still open for M3: `FINALIZING`, pending output without a final checkpoint, runtime installs (issue 34) |
| TST-029 | `PASSING` | `tests/recovery/test_cross_storage_failures.py` (28) and `test_missing_managed_files.py` (15): 16 durable states that a failure at one seam leaves across SQLite, the managed files and the USearch indexes (a reservation whose bytes never arrived, bytes never made available, an accepted image with an untouched, deleted, corrupt, ahead, behind or different-keyed index, an index persisted but not settled, a deleted managed file, a staging leftover, an orphan file, a deletion intent, a full disk while persisting) are each proven inconsistent by `tests/fixtures/consistency.py`, recovered by startup recovery to a consistent library, and recovered again with nothing left to repair; orphan files are kept; recovery gained two spec-backed steps the matrix exposed (a managed artifact whose file is gone becomes `MISSING`; a stale index is rebuilt); 19 mutations, all caught or equivalent. Process-level kill tests remain for when a backend process exists |
| TST-022 | `PASSING` | `SettingsRepository` and `RuntimeCatalogRepository` (`backend/app/settings/repository.py`, `backend/app/runtime/repository.py`, `tests/integration/test_catalog_settings_repositories.py`, 23): settings bootstrapped once whatever races, revision-guarded updates with one winner, names that are not settings refused; catalog rows added whole (a persistent one is refused), read in a stable order with id tie-breaks, only installation records change state (guarded, one winner under contention); 27 mutations, all caught. **With these every repository listed in persistence §26 has its mechanics** (the Artifact mechanics are in `artifact_storage.py`; Person changes are in the Person use cases); the `state` of components, variants, compatibility mappings and packages has no write path until a use case needs one Earlier: `IdentityRepository`, `OccurrenceRepository` and `EvidenceRepository` (`backend/app/identities/repository.py`, `tests/integration/test_identity_repositories.py`, 20): `lock` holds the write lock and changes nothing, revision- and state-guarded identity transitions with one winner under contention, a `MERGED` identity must name its target, observations kept in order, keyset pages that neither skip nor repeat when rows change between requests, evidence appended whole and marked superseded once; 19 mutations, the two that survived are equivalent (documented). Earlier (before the identity repositories): `ObservationRepository` and `RepresentationRepository` (`backend/app/memory/repository.py`, `tests/integration/test_memory_repositories.py`, 24): batch add, keyset pages (representations as a projection without the vector), a per-space key lookup, guarded transitions with one winner under contention (erasure refused as a plain state change), and ann-key allocation (never the same key twice under four writers); 14 mutations, all caught. Remaining repositories: none. Earlier: `tests/integration/test_job_repository.py` (23): `JobRepository` joins the caller's transaction and never commits; a claim is one guarded `UPDATE ... RETURNING` chosen by priority, age and id and never hands a job to two workers (4 threads held together at their first claim, 24 jobs); transitions, progress and the transient list are decided by the database, not by cached rows; `RUNNING` is entered only by a claim; a caller that has already read still meets `SQLITE_BUSY_SNAPSHOT` (open question 20); 18 mutations, all caught. `tests/integration/test_processing_repositories.py` (19) does the same for `SegmentRepository` and `CheckpointRepository`: ordinals are allocated inside the INSERT (16 writes from 4 threads held together at their first insert, none repeated or skipped), the partial unique indexes refuse a second running segment or valid final checkpoint, segments are never reopened, recovery can move backward through valid checkpoints; 18 mutations, one equivalent. `tests/integration/test_index_operation_repository.py` (23) covers `IndexOperationRepository`, which the IndexCoordinator now uses for all its statements (its 141 tests unchanged): `append_batch` skips an already-pending operation via the partial unique index instead of failing, supersedes (deletes) an opposite pending one so ADD, REMOVE, ADD ends as a single ADD (open question 27), and commits nothing; due, failed, requeue and settle are guarded by the database; 25 mutations, all caught. `tests/integration/test_source_repository.py` (29) covers `SourceRepository`: the library page is keyset-paginated (a source imported while paging cannot shift or repeat a page), a missing original is derived from the artifact and the source stays `ACTIVE` (open question 24), `set_current_run` accepts only a `FINALIZING` or `COMPLETED` run of the same source (the acceptance sequence sets the pointer before marking the run `COMPLETED`) at the expected revision, decided by the database (two racing writers: one wins, one revision bump); 19 mutations, all caught. `tests/integration/test_processing_run_repository.py` (37) covers `ProcessingRunRepository` and `SnapshotRepository`: `lock` takes SQLite's write lock before it reads (a second `lock` told not to wait is refused while it is held and then returns the committed row), changes nothing, and works for a missing run; the transient list is exactly `TRANSIENT_RUN_STATES` for all eleven states, least recently updated first; a snapshot's fingerprint is the SHA-256 of a canonical form (key order does not matter, content does), settings JSON cannot represent exactly are refused, runs with identical settings each keep their own snapshot and a second run cannot reuse one (`uq_processing_runs_configuration_snapshot_id`); snapshot immutability is not yet database-enforced (triggers decided for revision `0003`: issue #51); 23 mutations, all caught. The other repositories in persistence §26 are added as use cases need them |
| TST-031 | `IN_PROGRESS` | Representation erasure is built and passing (`docs/implementations/2026-10-01-m2-representation-erasure.md`): `backend/app/memory/erasure.py` (`erase(ids)` single and bulk, `resume()`), the coordinator's rebuild-based `REMOVE` for an `ERASING` representation and its refusal to mark a `REMOVE` applied while a superseded generation remains, `superseded_files`/`retire_quarantine`, the `app_state` marker and startup recovery. `tests/integration/test_representation_erasure.py` (37): INDEX-03 (a queued erasure is rejected by `resolve_ann_candidates` while the stale index still holds the vector, and a rebuild leaves it out), INDEX-04 (a locked superseded generation or quarantined copy keeps the `REMOVE` pending / the representation `ERASING`, is reported, and completes once released; the vector's bytes are in no file under the index directory, searched recursively), INDEX-05 (an `ADD` claimed before the erasure commits re-reads `ERASING` and does nothing, an `ADD` applied before is removed, a repeated erasure queues nothing, a bulk forget overlapping a coordinator pass converges, reactivation / split / merge cannot move an `ERASING` row), PER-07 (a crash at five points: queued, before the new generation, persisted but unsettled, removal applied but not cleared, cleared but not truncated; a restart completes it exactly once and a second recovery changes nothing), PER-08 (byte search of the database file and its log; a checkpoint blocked by a reader is reported owed with the marker set and completes on retry). Startup recovery: 3 tests in `test_startup_recovery.py`. Mutations all caught. **Remaining:** Source deletion, Recycle Bin cleanup and identity-level forget (use cases that call this one) |

---

## M3 — Single-image ML integration

**Goal:** Implement the first inference pipeline using one imported image.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-033 | P0 | ML IPC contract tests | Request and response schemas pass |
| TST-034 | P0 | Shared-memory tests | Ownership and cleanup are correct |
| TST-035 | P0 | Worker-supervision tests | Worker failure does not corrupt backend state |
| TST-036 | P0 | Image-import tests | Source and artifact creation succeed |
| TST-037 | P0 | Image-decoding tests | Supported image inputs are handled |
| TST-038 | P0 | Detection integration | Observations can be generated |
| TST-039 | P0 | Representation integration | Valid representations are produced |
| TST-040 | P0 | Candidate-retrieval tests | Retrieval respects representation compatibility |
| TST-041 | P0 | Recognition contract tests | Assessments satisfy documented contracts |
| TST-042 | P0 | Identity-reasoning integration | Decisions pass through backend authority |
| TST-043 | P0 | Persistence integration | Results survive restart |
| TST-044 | P1 | Initial ML evaluation | Reproducible component baselines exist |

**Dependencies:** M1, M2, available inference components.

**Milestone gate:** A single image can be imported, processed, represented, recognised and persisted.

---

## M4 — API and desktop vertical slice

**Goal:** Expose the single-image workflow through the actual application.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-045 | P0 | FastAPI contract tests | Required endpoints satisfy documented schemas |
| TST-046 | P0 | OpenAPI synchronization | Generated frontend contracts match backend |
| TST-047 | P0 | Tauri startup tests | Backend launches successfully |
| TST-048 | P0 | Readiness tests | Startup capabilities are reported correctly |
| TST-049 | P0 | Frontend import tests | User can initiate image import |
| TST-050 | P0 | Frontend results tests | Authoritative results are displayed |
| TST-051 | P1 | WebSocket tests | Notifications and reconnection work |
| TST-052 | P0 | Initial E2E test | Complete image workflow passes |
| TST-053 | P0 | Restart E2E test | Previously committed results remain available |

**Dependencies:** M3, frontend and desktop implementation.

**Milestone gate:** The first complete desktop workflow passes.

---

## M5 — Corrections, search and memory

**Goal:** Extend the initial application with meaningful identity-management workflows.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-054 | P0 | Correction E2E | User corrections persist correctly |
| TST-055 | P0 | Historical-search integration | Search reflects authoritative relationships |
| TST-056 | P0 | Face-search integration | Query-only recognition remains ephemeral |
| TST-057 | P0 | Cross-source recognition | Repeat appearances can be evaluated |
| TST-058 | P0 | Merge/split integration | Domain and persistence invariants hold |
| TST-059 | P0 | Deletion/recovery integration | Deleted data cannot be unintentionally resurrected |

**Dependencies:** M4 and the corresponding application features.

**Milestone gate:** Identity-management workflows preserve current state and historical evidence.

---

## M6 — Movies and scheduling

**Goal:** Introduce reliable long-running processing.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-060 | P0 | Job-transition tests | Documented state machine enforced |
| TST-061 | P0 | ProcessingRun tests | Durable processing history maintained |
| TST-062 | P0 | ExecutionSegment tests | Runtime provenance preserved |
| TST-063 | P0 | Chunking tests | Timestamp and segment correctness |
| TST-064 | P0 | Retry tests | No unintended duplicate committed work |
| TST-065 | P0 | Cancellation tests | Safe checkpoint cancellation |
| TST-066 | P0 | Pause/resume tests | Supported checkpoint transitions |
| TST-067 | P0 | Crash-recovery tests | Interrupted runs recover correctly |
| TST-068 | P0 | Concurrency tests | One heavy movie pipeline enforced |
| TST-069 | P1 | Resource-policy tests | Bounded queues and backpressure |
| TST-070 | P1 | Movie-processing E2E | Complete movie workflow succeeds |

**Dependencies:** M5 and the processing implementation.

**Milestone gate:** Movie processing can be interrupted and recovered without corrupting identity memory.

---

## M7 — Camera and advanced runtime behaviour

**Goal:** Validate sustained processing and hardware-specific behaviour.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-071 | P1 | Camera lifecycle tests | Start, stop and reconnection work |
| TST-072 | P1 | Camera backpressure tests | Stale-frame accumulation is bounded |
| TST-073 | P1 | CUDA validation | Supported NVIDIA runtime verified |
| TST-074 | P1 | DirectML validation | Supported Windows GPU runtime verified |
| TST-075 | P0 | CPU fallback tests | Required fallback remains functional |
| TST-076 | P1 | Runtime compatibility tests | Validated representation/calibration compatibility |
| TST-077 | P1 | Resource benchmarks | Reproducible hardware baselines |

**Dependencies:** M6 and available supported hardware.

**Milestone gate:** Included camera and runtime functionality satisfies its correctness and compatibility requirements.

---

## M8 — Packaging and release

**Goal:** Validate the distributable Windows application.

| ID | Priority | Task | Completion criterion |
|---|---|---|---|
| TST-078 | P0 | Clean-install tests | Application starts on supported clean Windows |
| TST-079 | P0 | Bootstrap validation | Required runtime packages install correctly |
| TST-080 | P0 | Artifact-integrity tests | Invalid packages are rejected |
| TST-081 | P0 | Application-update tests | Supported migrations and compatibility verified |
| TST-082 | P0 | Runtime rollback tests | Failed activation preserves usable configuration |
| TST-083 | P0 | ML-component promotion tests | Required evaluation and compatibility gates pass |
| TST-084 | P0 | Packaged E2E tests | Critical user workflows pass |
| TST-085 | P0 | Uninstall tests | User-library retention contract is preserved |
| TST-086 | P0 | Full release regression | No unresolved release-blocking failures |

**Dependencies:** All functionality included in the release candidate.

**Milestone gate:** The exact packaged release candidate passes its applicable release gates.

---

## Cross-cutting security work

Security testing begins when the relevant component is implemented.

| ID | Priority | Task | First applicable milestone |
|---|---|---|---|
| SEC-001 | P0 | Test-data isolation | M0 |
| SEC-002 | P0 | Filesystem boundary validation | M2 |
| SEC-003 | P0 | Local API protection | M4 |
| SEC-004 | P0 | Sensitive-data logging checks | M3 |
| SEC-005 | P0 | Offline-processing verification | M3 |
| SEC-006 | P0 | Deletion privacy regression | M5 |
| SEC-007 | P0 | Model-artifact integrity | M3 |
| SEC-008 | P0 | Packaged security validation | M8 |

Security requirements must not be deferred merely because their extended adversarial tests run later.

---

## CI implementation tracker

| ID | Priority | Workflow | Trigger |
|---|---|---|---|
| CI-001 | P0 | Static validation | Pull requests |
| CI-002 | P0 | Backend unit tests | Pull requests |
| CI-003 | P0 | Contract tests | Pull requests |
| CI-004 | P0 | Frontend tests | Pull requests |
| CI-005 | P0 | Integration tests | Pull requests and merges |
| CI-006 | P1 | Extended recovery | Scheduled and relevant changes |
| CI-007 | P1 | ML evaluation | Relevant component changes |
| CI-008 | P1 | GPU validation | Trusted hardware execution |
| CI-009 | P1 | Performance benchmarks | Scheduled and release candidates |
| CI-010 | P0 | Windows release validation | Release candidates |

GitHub Actions is the proposed initial CI platform.

---

## Immediate implementation checklist

Start with the following tasks:

- [x] Configure pytest and test markers.
- [x] Establish isolated SQLite and filesystem fixtures.
- [ ] Implement deterministic identity and observation factories. (Deterministic utilities done; factories blocked on models.)
- [ ] Create the first Identity Manager invariant tests.
- [x] Add the initial CI workflow. (Green on GitHub Actions, run `35902624488`.)
- [ ] Implement real persistence integration fixtures.
- [ ] Prepare the single-image pipeline integration test.

Do not begin by implementing the entire movie-processing, GPU-benchmark or packaged-release infrastructure.

Build those testing capabilities when their corresponding functionality becomes relevant.

---

**End of Testing Implementation Tracker v1.0**