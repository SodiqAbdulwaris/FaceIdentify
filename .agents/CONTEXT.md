# Agent context

Read after [`AGENTS.md`](../AGENTS.md). **Keep this file true:** update it at the end of every
task (see [`rules/documentation.md`](rules/documentation.md)).

_Last updated: 2026-10-16 (a how-to for turning automatic acceptance on and off, `docs/guides/AUTOMATIC_ACCEPTANCE.md`, `docs/implementations/2026-10-16-automatic-acceptance-howto.md`; issue #174, first part: face search by path refuses a path that leads off the computer (a UNC or device form, a mapped or subst network drive, a device name, an unfollowed reparse type, or a link or junction to a share; the opened handle is verified to be the resolved local file), resolved without contacting anything (`backend/infrastructure/storage/local_path.py`, `400 QUERY_PATH_NOT_LOCAL`); approved network roots and bounded network reads not built, `docs/implementations/2026-10-16-face-search-network-paths.md`; the overnight run of 2026-10-16 reported: PRs 204 to 211 and 214 merged, 212 and 213 open with review findings, the automatic-acceptance check not started, `docs/plans/OVERNIGHT_RUN_2026-10-16.md`; the M5 tracker caught up with re-run evidence: TST-058, SEC-006 and TST-059 4a/4b `PASSING`, TST-054 `IN_PROGRESS` (no end-to-end correction test yet), the TST-038/039 writer row unblocked (#69 closed), `docs/implementations/2026-10-16-m5-tracker-catch-up.md`; issue #69: the exact `buffalo_l` files in use re-hashed and matching the recorded SHA-256s, licence unchanged (research-only, owner-accepted risk, release blocker); a Windows install guide for the weights, the runtime package, the policy file and the GPU runtime, `docs/guides/INSTALLING_MODELS_WINDOWS.md`, `docs/implementations/2026-10-16-m5-weights-provenance-and-install-guide.md`; earlier, 2026-10-16: test fix: `finished()` drains the index pass before returning (a `database is locked` flake in PR 210's retry test), `docs/implementations/2026-10-16-break-run-index-race.md`; the M5 tracker caught up with re-run evidence: TST-058, SEC-006 and TST-059 4a/4b `PASSING`, TST-054 `IN_PROGRESS` (no end-to-end correction test yet), the TST-038/039 writer row unblocked (#69 closed), `docs/implementations/2026-10-16-m5-tracker-catch-up.md`; issue #69: the exact `buffalo_l` files in use re-hashed and matching the recorded SHA-256s, licence unchanged (research-only, owner-accepted risk, release blocker); a Windows install guide for the weights, the runtime package, the policy file and the GPU runtime, `docs/guides/INSTALLING_MODELS_WINDOWS.md`, `docs/implementations/2026-10-16-m5-weights-provenance-and-install-guide.md`; earlier, 2026-10-16: issue #179: a missing original is verified again when its source is opened or processed, and on request; a referenced one can be located; only the recorded file is accepted (`POST /sources/{id}/recheck`, `POST /sources/{id}/relink`, `availability_reason`, Recheck file / Locate original on the source screen), `docs/implementations/2026-10-16-missing-originals-recheck-and-relink.md`; earlier, 2026-10-16: the operating point and the hard-negative gate re-measured on DirectML: identical decisions and metrics to the CPU runs (embeddings within 1.25e-6), the gate in about 36 min against 2 h 8 min, `docs/implementations/2026-10-16-directml-remeasure.md`; earlier, 2026-10-16: the M5 definition of done audited: backend coverage 100% (3,081 tests), M5 not done: the tracker lags for TST-054, TST-058, TST-059 4a/4b and SEC-006, and the owner's TST-038/039 decision and a real-model check of automatic acceptance remain, `docs/plans/M5_DOD_AUDIT.md`, `docs/implementations/2026-10-16-m5-coverage-and-dod-audit.md`; earlier, 2026-10-16: an M6 movies and scheduling plan drafted, not approved: reprocessing (#180) first, then worker arbitration (#175), then video; ten open owner decisions, `docs/plans/M6_PLAN.md`, `docs/implementations/2026-10-16-m6-plan-draft.md`; earlier, 2026-10-16: issue #69: the exact `buffalo_l` files in use re-hashed and matching the recorded SHA-256s, licence unchanged (research-only, owner-accepted risk, release blocker); a Windows install guide for the weights, the runtime package, the policy file and the GPU runtime, `docs/guides/INSTALLING_MODELS_WINDOWS.md`, `docs/implementations/2026-10-16-m5-weights-provenance-and-install-guide.md`; earlier, 2026-10-15: the assisted-recognition gate report lists exclusions by rule in `log.exclusions` (no face, ambiguous subject, a failed processing run, and the enrolment cascade of people left with fewer than 2 enrolled faces), #182, unit-tested only, `docs/implementations/2026-10-15-m5-gate-exclusions-by-rule.md`; earlier the same day: the Kaggle mirror of LFW read from a cloud session: "Other (specified in description)" with no licence in the description, so it grants nothing; LFW's own page still unreachable (proxy 502, DNS failure, Wayback refused), #183 stays open, `docs/implementations/2026-10-15-lfw-celeba-terms-read.md`; earlier the same day: automatic acceptance: `require_approved_policy` admits a matching policy only at an operating point in `APPROVED_MATCHING` (`backend/api/real.py`); the owner confirmed option A (0.45 / margin 0.10), verified with real weights in a private state; the owner installs the live policy file, `docs/implementations/2026-10-15-enable-automatic-acceptance.md`; the shipped ONNX Runtime build decided and built: `onnxruntime-windowsml` on Windows, DirectML then the CPU by default, a DirectML start failure falls back to the CPU visibly, CUDA developer-only, Known conflicts 32, `docs/implementations/2026-10-15-ship-onnxruntime-windowsml.md`; earlier the same day: CelebA terms read at source and recorded, LFW page unreachable so #183 stays open, `docs/implementations/2026-10-15-lfw-celeba-terms-read.md`; GPU: readiness now reports `execution_provider` and `provider_fallback` and a provider fallback is logged; CUDA verified again on the RTX 4070 (about 0.03 s per picture against about 0.7 s on the CPU) and DirectML measured; which ONNX Runtime build to ship is asked as Known conflicts 32, `docs/research/onnx-runtime-gpu-packaging.md`, `docs/implementations/2026-10-15-gpu-provider-visibility.md`; earlier the same day: the Commons celebrity gate result recorded, `docs/implementations/2026-10-14-celebs-commons-verified-set.md`; earlier, 2026-10-12: the learning guide was restructured into the small lessons of `docs/guides/learning/`, with `docs/research/codebase-learning-guide.md` kept as a short pointer, `docs/implementations/2026-10-12-learning-guide-restructure.md`; documentation only, no code, test or configuration changed. The rest of this line is the project state as last revised on 2026-10-07; for the current overview see `docs/plans/PROJECT_STATUS.md`) and, as of 2026-10-07 (the scheduler-degrade test no longer races its own retry: it waits on a long idle interval and an explicit wake, `docs/implementations/2026-10-07-scheduler-degrade-test-race.md`; owner decisions on the M4 agent notes and the M5 plan, `docs/plans/M5_PLAN.md`, drafted; M4 end to end: the complete desktop image workflow, with a restart, passes against the real backend (`npm run test:e2e`, CI `desktop` job); the M4 definition of done is met on the development profile (real models: issue #69); M4 W7.4: the people and processing screens (W7 complete: every route in the plan is a real screen); M4 W7.3: the source screen (image with face boxes, process/cancel/retry, people and processing history); M4 W7.2: the library screen (cards, import through the native picker, process) and the uncalibrated-policy notice in the layout; M4 W7.1: the web view connects through the shell (gate, typed client, event client with gap detection and reconnection, query invalidation, hash routes with placeholder screens); M4 W6: the Tauri shell starts the backend sidecar (token in the environment, validated handshake, clean stop through the stdin lifeline), owns the library root and offers a folder picker, and CI checks it on Windows; M4 W6 host side: `--stdin-lifeline` lets the shell stop the host cleanly by closing its standard input; M4 development profile: the host flag `--development-profile` registers a fake catalog and perception under an uncalibrated policy and the host now always passes the media limits; M4 W5: the OpenAPI document and TypeScript types are generated and kept in sync by a backend test and a CI step (`npm run generate:api`); every operation declares the one error shape; M4 W4: the event connection publishes `source.created`, `processing_run.created` and `processing_run.updated` with sequence numbers and a hello greeting, best effort; M4 W3.6: runs report their frozen policy's calibration status; no separate system-status route (`/readiness` is it); M4 W3 complete; M4 W3.5: read-only identity and occurrence routes that show only authoritative (ACTIVE) data; M4 W3.4: `CancelProcessingUseCase` writes the cancellation request (queued: cancelled now; running: `CANCELLING`, settled by the executor), with `POST /processing-runs/{id}/cancel` and the jobs routes; M4 W3.3: `POST /sources/{id}/process`, processing-run reads and `POST /processing-runs/{id}/retry`, with `ProcessingSettings.request_for` supplying the development policy profile; M4 W3.2: the source routes (import, list, detail, original media with ETag) under `/api/v1`; M4 W3.1: the REST conventions (one error shape, cursor pagination, library gating) every route inherits; M4 W2.3: the scheduler loop starts after the library opens, `/readiness` reports it, and recognition opens its index fail-closed; M4 W2.2: `ProcessingRunner.run_once` claims, executes and accepts one queued job with every outcome decided; M4 W2.1: revision 0007 gives jobs an integer priority rank and claiming orders by it; M4 W1 complete: the loopback sidecar host `python -m backend.api.host` (uvicorn, websockets; stdout handshake; token from the environment; parent-process watch); M4 W1.1: the API lifespan opens the library and `/readiness` reports the lifecycle and capabilities; the M3 exit gate is met: tracker rows TST-040 to TST-043 are PASSING, TST-038 and TST-039 are BLOCKED on real weights (issue #69); M3.2: the pipeline killed at each stage in a real child process, then recovered and retried (TST-043); M3.1: the eraser and recovery writes moved onto the UnitOfWork (issue #66); rules added: implementation plans go in `docs/plans/` and `docs/plans/PROJECT_STATUS.md` is the glanceable status page; the M3 and M4 completion plan, `docs/plans/M3_M4_COMPLETION_PLAN.md`, approved with six owner decisions; M3 step 13, the end-to-end recognition, restart and rebuilt-index test, added with planted perception; Step 12 recovery of FINALIZING and pre-FINAL runs built, with `RetryProcessingUseCase` (issue #34); stale M3 documentation corrected by the cross-check; M3 identity-less candidate readers merged in PR #95; PR #101 merged the approved provider-fallback execution segments; PR #106 merged the step-11 acceptance remediation, which validates every FINAL decision from SQLite-authoritative candidate evidence and the versioned run snapshot before all lifecycle branches; its focused coverage, guard mutation proofs, 2,328-test full gate, independent review, and exact-head CI passed, and it closed issue #104; M4's authenticated FastAPI bootstrap merged in PR #103, with loopback hosting/lifespan still pending)_

> **Decision 2026-10-14:** (owner, delegated: "I'll go with whatever you recommend") automatic acceptance stays **off** (abstain-only; `require_abstain_first` unchanged). LFW and CelebA (955 strangers, 0 accepted at a cut-off of 0.45; known people accepted correctly 96.5% to 99.4%) make a safe operating point plausible but do not meet the owner's own condition (a *verified* set of 40 identities with 5 or more images and 80 or more queries), say nothing about look-alikes, and are narrow samples (news photographs and aligned celebrity crops). Re-opening needs, in order: a verified set, hard negatives (issue 177), `measure_operating_point.py` reading a verified manifest (issue 178), the conservative rule re-run meeting the owner's thresholds with zero false accepts, then an explicit owner-approved code change. Evidence and numbers: [`docs/implementations/2026-10-14-m5-celeba-gate-and-acceptance-decision.md`](../docs/implementations/2026-10-14-m5-celeba-gate-and-acceptance-decision.md).

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The owner confirmed option A on 2026-10-15:** "A: threshold 0.45, margin 0.10, no automatic new identity." (`buffalo-l-verified-match-v1`; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../docs/implementations/2026-10-15-enable-automatic-acceptance.md)).

> **Decision 2026-10-09 (owner):** confirmed the recycle API design (step 4a) and the permanent-delete design (step 4b): delete only from the Recycle bin; the audit log is kept but detached (decision types, ids, timestamps and scores stay; every reference to deleted representations, crops, runs and biometric artifacts goes; the tombstone holds no file name, path or sensitive metadata); `204` complete, `202` durably scheduled or partly done (guaranteed to resume after a restart, never presented as fully deleted, and meanwhile unreachable through every route, idempotent on retry and visible), `409` refused. Revision `0010` approved and built (clear a deleted referenced original's path, also for originals an earlier revision had deleted; add a `SOURCE_PERMANENTLY_DELETED` history entry). Real-world gate photographs: the public-domain set. R5 starts after the M5 gate.

> **Decision 2026-10-08:** the owner confirmed the abstain-only agent designs (full text in [`docs/plans/M5_PLAN.md`](../docs/plans/M5_PLAN.md)): the first face still creates an unnamed identity while matching to existing identities is disabled; `match_threshold` above 1.0 stays the disabled-matching representation (similarities bounded to the cosine range, enforced centrally, the interface shows "Automatic matching disabled"); rename events carry ids and revisions, not names; `--minimum-recall 0.5` is a usefulness target that never relaxes safety; similarity is called a "Similarity score", never "% alike" and never a probability. Built 2026-10-08 with regression tests.

> **Decision 2026-10-08 (owner): assisted and automatic recognition are separate.** Cross-source recognition is now *assisted* (ranked possible matches plus manual confirmation; TST-057A, validated by Recall@1, Recall@5, MRR and persistence after restart); *automatic* recognition (TST-057B) is `BLOCKED pending calibration` and is never claimed while automatic matching is disabled. A local label-review utility (R5) will earn it with verified evidence (reviewed examples never reused as the untouched final set). Permanent deletion must leave no retained Evidence that exposes deleted biometric material; face search is independent of matching thresholds and persists nothing. The assisted workflow may pass its own M5 gate. Plan: [`docs/plans/M5_REMAINING_WORK.md`](../docs/plans/M5_REMAINING_WORK.md).

> **Decision 2026-10-08 (owner, final):** **ABSTAIN does not mean NEW IDENTITY.** Only the first face in an empty library (nothing to compare with) creates an identity automatically; once identities exist an unmatched face abstains, never creates another, and waits for manual resolution (confirm an existing identity, or "This is someone new", which associates the face, creates its occurrence and writes `USER_CORRECTION` Evidence citing the abstention). Raw cosine similarity is bounded to [-1, 1], so a `match_threshold` above 1.0 disables automatic matching and the interface says "Automatic matching disabled". All eleven listed routes (corrections, unresolved faces, merge, split, people) are approved as they are. Written into `identity-and-memory-model-v1.md` section 2.5 and `ML_COMPONENTS_AND_EVALUATION.md` section 2.3.

> **Decision 2026-10-07:** the owner confirmed the six M4 agent decisions (dated notes in the M4 implementation entries): `/readiness` and `/health` are the status read model (no status route); the development catalog stays in the library database **with a guard that refuses a kept library opened with `--development-profile` and the reverse, recording development provenance (GitHub issue #137, **built 2026-10-07**: `backend/api/library_profile.py`, a `library_profile` marker in `app_state`)**; React Router hash routing; `legacy-peer-deps` stays as a documented temporary exception (remove when openapi-typescript supports TypeScript 6); an unnamed identity is shown as `Person {SHORT_ID}` (uppercase first 6 hex characters of the identity UUID, presentation only, never persisted); recycled sources keep their Occurrences in identity views and counts, marked as recycled (built with the recycle command). The M5 order is naming, corrections, merge and split, lifecycle, retrieval: [`docs/plans/M5_PLAN.md`](../docs/plans/M5_PLAN.md) (scope and order approved 2026-10-07 with seven changes made the same day: a mixed-support Occurrence is a split conflict, naming creates and attaches the Person atomically, merge and split are atomic across entities, Forget's meaning is decided before it is built, recycled-source Occurrences stay in historical views and search, TST-057 workflow and quality gate are separate lines, and reprocessing stays outside M5; later the same day the owner made M5 the first real recognition milestone: the real-model track (issue #69 selection by the owner before any download, runtime installation and provenance, real-inference tests, issue #80's sweep, TST-038/039 on the real path, TST-044 initial calibrated policy) and issue #137 move into M5 and run in parallel with the identity-management steps, converging before face search, cross-source recognition and the M5 gate; M6, M7 and M8 work is not absorbed).

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
  `JobRepository`, `SegmentRepository`, `CheckpointRepository`, `IndexOperationRepository`, `SourceRepository`, `ProcessingRunRepository`, `SnapshotRepository`, `ObservationRepository`, `RepresentationRepository`, `IdentityRepository`, `OccurrenceRepository`, `EvidenceRepository`, `SettingsRepository` and `RuntimeCatalogRepository` (TST-022 has its mechanics for every listed repository; Artifact is `artifact_storage.py`); the library root and lock (`library_root.py`, `library_lock.py`; called by `open_library`) and the downgrade guard are built; TST-031's erasure is built at every level (representation erasure, M5 step 4b permanent Source deletion and step 4c forgetting an identity or a person).
  Status per task: [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../docs/plans/TESTING_IMPLEMENTATION_TRACKER.md).
- **Pending work is tracked as GitHub issues** (<https://github.com/SodiqAbdulwaris/FaceIdentify/issues>):
  #29 to #41, #48, #51, #57, #66, #69, #71, #80 and the SQLite erasure policy hold every decided-but-unbuilt item and every provisional decision to validate (the table is in
  `docs/implementations/2026-10-01-decide-q25-q26-erasure-and-recovery.md`). When something becomes pending,
  open an issue for it.
- **Git:** public repository <https://github.com/SodiqAbdulwaris/FaceIdentify>. `main` contains the
  bootstrap commit and the project foundation (PR #1, merged 2026-09-23). It is protected by
  ruleset `23894323` (PR required, rebase merge only, five required CI checks, no bypass).
  Reviewers for agent-opened PRs (`rules/branches.md`): Codex CLI and a read-only subagent are
  approved. Probed 2026-09-30 and **not** approved: `agy`, OpenCode (see the implementation entry
  for why); the Cursor `agent` CLI is not installed.
- **Licences:** the application is personal-use only (owner, 2026-10-07). [`docs/research/licensing-and-commercialization.md`](../docs/research/licensing-and-commercialization.md) records every third-party model, dataset and direct dependency with its terms and what is not yet verified (the Rust crates, NVIDIA's runtime terms, the weights' training-data terms, transitive packages); the face weights are research-only and the repository has no `LICENSE` file. The next verification steps are in its section 11.
- **Backend:** FastAPI is now a locked dependency and `backend/api/app.py` provides the first
  in-memory authenticated application factory: canonical 256-bit per-launch Bearer capability for
  all HTTP routes and a WebSocket credential offered through `Sec-WebSocket-Protocol` but never
  echoed as the selected protocol. (M4 has since added the sidecar host, the lifespan that opens
  the library, the scheduler, the REST routes, the event connection and the generated contract:
  see `docs/plans/PROJECT_STATUS.md` and the M4 entries in `docs/implementations/`.) The SQLite engine/session factory, models for all 33 `0001_initial_schema`
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
  `0004_app_state` (a key/value table for the durable `wal_truncation_owed` marker), `0005` (output provenance columns, snapshot-replace trigger), `0006` (the `RECOGNITION_ABSTAINED` evidence kind) `0007` (the integer `jobs.priority_rank`) `0008` (the `PERSON_RENAMED` Evidence kind), `0009` (the `SPLIT` identity state removed) and `0010` (a `DELETED` artifact may have no location; the `SOURCE_PERMANENTLY_DELETED` Evidence kind)); every persistence test runs on the migrated
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
  `backend/app/sources/permanent_delete.py` (`PermanentSourceDeletion`, M5 step 4b: a `RECYCLED` Source becomes `DELETING` with the
  deletion intent of its managed artifacts, their bytes go, its face vectors go through `RepresentationEraser`, then one transaction
  deletes its occurrences, observations, runs and their snapshots while Evidence is kept but detached from the deleted
  representations and run, an unnamed identity left with nothing becomes `DELETED`, and the Source stays as a `DELETED`
  tombstone; `resume()` at startup finishes a deletion a crash cut short), and
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
  brings one back, called since 2026-10-16 when the source is opened, processed or retried and by
  Recheck file, #179; `open_library` calls recovery at startup), validates every active space's index (a stale one is rebuilt from SQLite, not just a
  missing or corrupt one), gives
  `FAILED` `IndexOperation`s one fresh set of attempts and catches up pending ones in bounded
  passes; idempotent, survives a crash after any step, and reports what is `unresolved`. It relies
  on the single-process precondition (open questions 20 and 23), which `open_library` (`backend/app/lifecycle.py`) now
  provides: it validates the roots, takes the library lock, lays out the folders, migrates (a database stamped with a revision
  this version does not know is refused untouched: `DatabaseNewerThanApplicationError`), builds the engine, Storage Manager,
  IndexCoordinator and eraser, runs `recover_on_startup`, and releases the lock and the engine on exit or on any failed step.
  (The FastAPI lifespan that wraps it, the loopback host and the routes were built in M4.) The remaining backend
  packages are empty scaffolds from IMPLEMENTATION_ARCHITECTURE.md §8. Image source import (PR #82) and the ML worker and supervisor (PRs #76, #77) are built.
- **Frontend:** Vite + React 19 + TS + Tailwind v4 + shadcn/ui (Nova preset, radix base) + Vitest,
  with React Router hash routes, TanStack Query and generated API types. Library, source, people and
  processing screens are built (M4), and so are the M5 naming, correction, merge/split and
  unplaced-face controls and the recycle bin (step 4a, built 2026-10-08: `DELETE /sources/{id}` and `POST /sources/{id}/restore`,
  idempotent, `409 SOURCE_BUSY` while a run is in flight, `OccurrenceSummary.source_recycled`, a Library / Recycle bin switch and a
  "from an image in the recycle bin" marker); permanent delete is built (step 4b: Delete permanently in the bin, with a confirmation); forgetting an identity or a person is built (step 4c); name and history search is built (step 5a: `GET /search`, a Search screen; recycled images are left out unless "Include recycled images" is ticked; a forgotten person stays findable by name, labelled "Biometric memory forgotten", owner decisions 2026-10-09); face search is built (step 5b: `POST /search/face`, a picture chosen, dropped or pasted; an answer per face; nothing saved; PDF queries deferred; "Choose a picture" opens the native dialog in the desktop app (path form of the same route); the step 8 gate ran on 2026-10-10 (`evaluation/assisted_recognition_gate.py`; Recall@1 0.739, Recall@5 0.826, MRR 0.775 against unverified labels; the first run on owner-verified labels (2026-10-12, `evaluation/datasets/reports/gate-verified.json`: 9 identities, 18 queries, all 1.000; not a TST-057B pass: far below the dataset targets, selection bias; the open-set evaluation was not built when that run was made) is in `docs/implementations/2026-10-12-m5-first-verified-label-run.md`, and the open-set evaluation is built (`--unknown`; first run: 12 strangers, 25 queries, none accepted, top similarity 0.046 to 0.237; tiny sample; no operating point chosen) in `docs/implementations/2026-10-12-m5-open-set-evaluation.md`; TST-057A functional gate PASSING with quality unverified, owner 2026-10-12; the R5 label-review utility `evaluation/label_review.py` is built and the review of labels is the owner's; the web view could not read any answer from the backend until 2026-10-12 (no CORS: the app sat on "Opening your library"); fixed with `--allow-origin` and tested, `docs/implementations/2026-10-12-webview-cors.md`, confirmed in the real desktop window by the owner on 2026-10-13 (images were imported and processed; recognition stays abstain-only); the first LFW run is recorded (2026-10-13, `docs/implementations/2026-10-13-m5-lfw-evaluation.md`: 100 enrolled, 173 queries all rank 1, 375 stranger queries none accepted, best stranger similarity 0.402; easy set, labels unverified, TST-057B not claimed; LFW and CelebA downloaded and evaluated 2026-10-13; CelebA exclusions in `docs/implementations/2026-10-13-m5-lfw-exclusion-analysis.md`); the owner parked the Commons set and will evaluate on LFW and CelebA (`evaluation/import_labelled_dataset.py`, `docs/implementations/2026-10-12-labelled-dataset-import.md`; LFW imported, CelebA imported on 2026-10-13 and evaluated on 2026-10-14); the licensing record now states that nothing is trained here and lists the datasets behind the weights and the evaluation sets (CelebA terms read 2026-10-15; LFW's page still unread, issue #183); the stale index `local-models/state/indexes/f0fd4e92c8c8492097e2307e82000af9` was verified safe to delete on 2026-10-12; deletion remains pending the owner's action with the command in the R5 entry).
- **Desktop:** Tauri v2 in `desktop/src-tauri` starts the Python backend sidecar (token in the
  environment, validated handshake, clean stop) and owns the library root and its folder picker (M4).

## Repository map

| Path | Contents |
|---|---|
| `docs/specs/` | **Authoritative** architecture and contracts (architecture, API, persistence, identity model, processing, search, product, ML components). The **schema** comes from `PERSISTENCE_IMPLEMENTATION.md`; `ERD.md` is conceptual only |
| `docs/plans/` | Implementation plans (agents put theirs here), roadmap, testing tracker, identity decision engine plan, and **`PROJECT_STATUS.md`**, the one-page overview of what is built and where we are |
| `docs/strategy/` | Testing strategy, ML benchmark and evaluation protocol |
| `docs/guides/` | How-tos, e.g. `TESTING_GUIDE.md` |
| `docs/research/` | Stack research, `tech-stack.md` (the locked stack decisions), model selection, licensing, the measured operating point, and **`codebase-learning-guide.md`** (now only a short pointer to `docs/guides/learning/`) |
| `docs/guides/learning/` | The learning guide: small practical lessons from Python basics to this codebase, each with commands that were run, exercises and answers; start at `docs/guides/learning/README.md` to understand the project |
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
12. **Decided 2026-10-07 (owner): add `PERSON_RENAMED` in M5 (revision `0008`, plan step 1); built 2026-10-07 (the rename event records revisions, not names).** Original question follows. No `EvidenceKind` for a pure Person rename. `identity-and-memory-model-v1.md`
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
15. **Decided 2026-10-07 (owner): do not assign it; remove it in the M5 schema cleanup (plan step 3) unless a compatibility constraint needs it; a split is recorded by `IDENTITY_SPLIT` Evidence and lineage. Built 2026-10-07: revision `0009` removes it.** Original question follows. `IdentityState.SPLIT` is never assigned. The enum (persistence §7) lists a `SPLIT`
    state, but no spec text says which of a split's two resulting identities (if either) should
    receive it. `split_identity` (PR #8) reads `identity-and-memory-model-v1.md` §19.2's
    conceptual example — the source keeps some of its own evidence — as meaning neither identity
    is retired by a split, so it leaves the source `ACTIVE` and creates the new identity directly
    `ACTIVE`, using `SPLIT` nowhere. Decide whether `SPLIT` should mark the source, the new
    identity, or is dead enum space.
16. **Decided 2026-10-07 (owner): merge and split also move `Occurrence.identity_id` (M5 plan step 3; a mixed-support Occurrence is an explicit split conflict, never kept automatically by the source). Built 2026-10-07.** Original question follows. Merge/split do not move `Occurrence` rows. Only test factories create `Occurrence`
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
32. **Resolved 2026-10-15 (owner; asked the same day): which ONNX Runtime build the application ships.** The project depends on the CPU `onnxruntime` 1.30.0; CUDA is a developer-only, machine-local `onnxruntime-gpu` plus 2.5 GB of NVIDIA libraries (`FACEIDENTIFY_ORT_GPU_DIR`). Measured on this machine (`docs/research/onnx-runtime-gpu-packaging.md`): `onnxruntime-windowsml` 1.30.0 (74 MB, MIT; `DirectML.dll`'s terms not verified) runs DirectML on the RTX as fast as CUDA (0.019 s detect, 0.007 s embed per picture) and agrees with the CPU (1 − cos ≤ 2.4e-7); DirectML also ran on the Intel UHD, tested with `onnxruntime-directml` 1.23.0 only (model only, explicit adapter; Windows ML on Intel not verified); the CPU provider is inside for every other machine, but the fallback when DirectML cannot start is not yet guaranteed (a start exception is reported as `COMPONENT_LOAD_FAILED`, which does not fall back) and AMD and no-DX12 machines are untested. **Recommendation:** on Windows, replace `onnxruntime` with `onnxruntime-windowsml` (environment marker; Linux CI keeps `onnxruntime`), declare DirectML then CPU variants, classify a DirectML start failure as a provider failure so it falls back, keep CUDA developer-only and never ship it. This changes a locked dependency, what end users install, and `tech-stack.md` sections 7 and 12 for NVIDIA (they say NVIDIA gets CUDA), so it waits for the owner. Options and consequences: A keep the CPU build (no GPU for users); B ship `onnxruntime-gpu` (2.9 GB, NVIDIA only, NVIDIA terms); C CPU plus an optional NVIDIA pack (two installs); D the recommendation.

> **Decision 2026-10-15:** (owner) "Ship onnxruntime-windowsml 1.30.0 on Windows (DirectML for NVIDIA, AMD and Intel, then CPU), keep onnxruntime on Linux CI through a marker, keep CUDA developer-only, and make a DirectML start failure fall back to CPU." Option D, CUDA developer-only. Built in `docs/implementations/2026-10-15-ship-onnxruntime-windowsml.md`: the marker dependency, DirectML then CPU as the Windows default, the start failure classified as `RUNTIME_INITIALIZATION_FAILED`, DirectML session options; decision notes added to `tech-stack.md` (tree, 7, 12, 20), `IMPLEMENTATION_ARCHITECTURE.md` (tree, 13, final stack), ML 13 and 18.1, the benchmark protocol 13, the roadmap, the licensing record. Unverified: AMD, no-DirectX 12 machines.

32. ~~The spec's accepted image formats~~ **Resolved 2026-10-15 (owner; issue 188):** `docs/specs/API and Contracts.md` says "JPEG, PNG, BMP or WebP" in the import decision note (2026-10-02) and "only JPEG, PNG, BMP and WebP are accepted" in the face-search note (2026-10-10); the code now also accepts AVIF. The owner approved adding AVIF ("Pillow's built-in AVIF support, no new dependency"); a dated `Decision 2026-10-15` note now follows each passage, the original text kept.

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

## Next steps

**M5 close-out plan (2026-10-17):** the owner approved [`docs/plans/M5_CLOSEOUT_PLAN.md`](../docs/plans/M5_CLOSEOUT_PLAN.md): resolve PRs #213 and #219 one at a time through exact-head review, CI and owner-authorized rebase merge; record the installed-policy real-host check and automatic-placement correction path (TST-057B); add Correction E2E (TST-054); resolve TST-044 and the owner decision on TST-038/039; then reconcile the active status documents. **#213 is currently blocked:** its independent review at `02921ee` found shutdown can stop a worker after inference but before its shared-memory result is attached; it needs an active-operation drain plus a deterministic regression before re-review. M6 follow-ups #180 and #221 remain out of scope.

**Overnight decisions confirmed (2026-10-16):** the owner confirmed all four delegated decisions in `docs/plans/OVERNIGHT_RUN_2026-10-16.md` ("Okay, I confirm on all 4"): #174 refuses every network target by default (no approved roots yet); #179 rechecks a missing original only when a source is opened, processed or retried (never a library scan); #175 serves at most 3 face searches in a row before waiting background work; TST-058, SEC-006 and TST-059 4a/4b stay `PASSING` (TST-054 `IN_PROGRESS`).

**Switching agents (2026-10-16):** when Claude Code is out of usage, continue with Codex from the repository root; `docs/guides/AGENT_HANDOFF.md` has the state pointers, the traps and the review rule for Codex-authored PRs (a fresh read-only Codex run is the independent reviewer). Keep that page current when you learn a new trap.

**Shipped ONNX Runtime build (2026-10-15, Known conflicts 32, decided and built):** Windows installs `onnxruntime-windowsml` (DirectML + CPU); `FACEIDENTIFY_PROVIDERS` unset means `DmlExecutionProvider,CPUExecutionProvider` on Windows, the CPU elsewhere; CUDA only when named with `FACEIDENTIFY_ORT_GPU_DIR`. **To use DirectML with the real models, reinstall the runtime package** (a package installed before this declares no DirectML variant and runs on the CPU): when no gate is using `local-models/state`, remove `local-models/state/runtime/packages/insightface-buffalo-l` and re-run `scripts/install_reference_models.py`. A library that registered the old manifest refuses the new one (gate libraries are fresh, so they are not affected). Open: AMD and no-DirectX 12 machines, uncontended timings, ONNX Runtime telemetry (`disable_telemetry_events`), re-measuring the operating point on DirectML (`docs/implementations/2026-10-15-ship-onnxruntime-windowsml.md`).

**Automatic acceptance (2026-10-15, owner decision):** the code admits a matching policy only when it equals an entry of `APPROVED_MATCHING` in `backend/api/real.py` (0.45 / margin 0.10, `buffalo-l-verified-match-v1`; no automatic new identity). The owner confirmed option A on 2026-10-15: "A: threshold 0.45, margin 0.10, no automatic new identity." Remaining: the owner installs the live policy with the command in the entry (the abstain-only file is kept beside it to restore; read on every request, no restart), then TST-057B can be marked `PASSING`. Faces processed before it stay abstained. `docs/implementations/2026-10-15-enable-automatic-acceptance.md`. **Installed (2026-10-16 check):** the owner installed the live policy file on 2026-10-15 at 23:58 (`insightface-buffalo-l.json` = `buffalo-l-verified-match-v1`, 0.45 / margin 0.10; `insightface-buffalo-l.abstain-only-v1.json` beside it restores ask-every-time, its content checked to load as a policy); the real-host check on the live install is still to record.

**AVIF accepted (2026-10-15, issue 188):** `backend/infrastructure/media/image.py` accepts AVIF (`image/avif`) through the same decoder, limits and error mapping as the other four formats, so import, processing and face search all take it; the native picker and the face-search screen offer it. No new dependency (Pillow 12.3.0's wheel bundles libavif and dav1d). The owner approved the spec change; `API and Contracts.md` has a `Decision 2026-10-15` note after each format list (Known conflicts, item 32). `docs/implementations/2026-10-15-avif-images.md`.

**Test race fixed (2026-10-15):** a run reads `COMPLETED` before acceptance wakes the index coordinator, which then saves the index on the scheduler thread; API tests that process an image (`processed()` in `tests/integration/test_api_memory.py`) now run one serialized coordinator pass before returning and assert every index operation is `APPLIED`, so nothing is still being written. `docs/implementations/2026-10-15-face-search-snapshot-index-race.md`.
**Next steps (2026-10-15), in order** (written at the end of the 2026-10-14 session; the owner was asleep, so nothing here
needs an answer to start):

1. **Done 2026-10-15:** the gate finished (2026-10-14 23:50): Recall@1 / Recall@5 / MRR 0.988 on 84 queries, 10 of 10
   workflow checks, same rankings after a restart, source/identity/run counts unchanged by the queries (counts only), 0 of 109 strangers accepted (best 0.309); not
   a TST-057B pass (36 of 40 identities). Recorded in the entry, tracker, status page. Original instruction kept below.
   **Collect the gate result.** `evaluation/datasets/reports/gate-celebs-commons.json` (command in
   `docs/implementations/2026-10-14-celebs-commons-verified-set.md`). If it is missing or still marked `"partial": true` and no
   gate process is running, the run died with its session: delete `evaluation/datasets/gate-celebs-commons` and re-run the same
   command in the background. Read: Recall@1, Recall@5, MRR against the owner's thresholds (0.85, 0.95, 0.90), the
   same-rankings-after-restart check (stability 100%), `queries_wrote_nothing`, the workflow checks, and the open-set table
   (strangers accepted at each cut-off, best stranger similarity). Record it (entry, tracker TST-057B row, status page,
   this file). **It cannot pass TST-057B: 36 identities are below 40.** State both facts.
2. **Done 2026-10-15:** 12 more people collected and reviewed by the owner (unmarked ones bulk-recorded VERIFIED from the owner's statement); export `verified-20261015T073439095195Z.json` has 48 identities and 142 queries; the gate with 40 enrolled met every measured provisional threshold (Recall@1 0.983, Recall@5 0.992, MRR 0.986, 10 of 10 workflow, same rankings, 0 of 115 strangers). TST-057B stays blocked: automatic acceptance is off until hard negatives (issue 177; PR 196 open, not mergeable as is) and an owner-approved change. Original instruction kept: **Close the identity gap automatically.** Make a people file of about 10 more well-known people not in the set (one
   per line; `Display = Category` when the Commons category differs) and run
   `collect_commons_portraits.py --out evaluation/datasets/celebs-commons --licence free --people-file <file>`
   (it resumes: existing pictures are kept). Then the owner reviews only the new people
   (`label_review.py serve ... --people "A,B,..."`). Do not mark anything verified on the owner's behalf without a statement.
3. **Issue 178** (small): let `measure_operating_point.py` read a verified manifest (`--manifest`, the gate's digest
   checks), then run the conservative precision rule on the verified set. Record the result; **do not enable automatic
   acceptance** (decision 2026-10-14: it needs the verified set at the targets, hard negatives and an explicit
   owner-approved code change).
4. **Issue 177** (medium): a hard-negatives selection mode (strangers chosen by similarity to enrolled people), then
   repeat the open-set evaluation with it.
5. **Smaller, any time:** #173 (measured on `MyFaces/` 2026-10-15: 0 of 29 lost; open for a categorised close-up set
   and the padded-fallback comparison, owner's call), #183 (LFW's own page; CelebA and the Kaggle mirror read 2026-10-15), #188 (AVIF), the remaining Commons
   public-domain review (14 people short, `label_review.py --people`).

Working rules that cost time before: work from the repository root and do not `cd` elsewhere in a command (the shell
keeps the directory); write scripts with the Write tool, not heredocs with apostrophes; commit headers at most 72
characters; many files are CRLF; `PYTHONPATH=.` for evaluation scripts; a background process dies when the session ends;
a merge needs the owner's own message, and every PR needs an independent read-only review (`.agents/rules/branches.md`).
**Operating point on verified labels (2026-10-15, issue 178):** `measure_operating_point.py --manifest <label_review export>` digest-checks every verified photograph; the conservative rule on the 36-identity celebrity set chose 0.3314 / margin 0.02 and made 0 false accepts on the final half (recall 0.988; 11 people, small); repeated on the 48-identity export: the same point, 0 false accepts on 156 accepted (recall 0.994, 18 people). Measurement only: **automatic acceptance stays off** (decision 2026-10-14); `docs/implementations/2026-10-15-m5-verified-operating-point.md`.
**Hard negatives (2026-10-15, issue 177):** `assisted_recognition_gate.py --hard-negatives N --hard-negative-pool <dataset>` ranks a second dataset's people by one selection photograph against the enrolled library and scores the closest N on their other photographs (own open-set table; pool people sharing a name or a picture with the main dataset are left out). On the 48-identity verified set with all of LFW as the pool (`evaluation/datasets/lfw-pool`, 1,680 people): 15 look-alikes (Emma Thompson for Cate Blanchett, Keira Knightley for Natalie Portman, ...), 0 of 31 queries accepted, best 0.320, none at 0.35. PR 196 (another agent's importer-based attempt) is kept open for reference, not mergeable. A wide-pool gate run takes about 2 hours plugged in (2.5+ on battery, where Windows throttles the CPU; it is CPU-only until the ONNX Runtime build decision in PR 200). Start long runs fully detached: background processes and Terminal tabs die when the app restarts, and a WMI-started process still received a console Ctrl+C; `evaluation/datasets/reports/launch_detached.py` (Git-ignored, DETACHED_PROCESS plus a new process group) ran one to completion; its stdout did not reach the log, but the JSON report is complete. `docs/implementations/2026-10-15-m5-gate-hard-negatives.md`.

**Commons collector (2026-10-14):** `evaluation/collect_commons_portraits.py` (from the owner's `facescrape.py`, fixed) collects free-licence portraits by person from Wikimedia Commons into `evaluation/datasets/celebs-commons/`; `--dry-run` reads metadata only; `docs/implementations/2026-10-14-commons-portrait-collector.md`.

**Review tool (2026-10-14):** `evaluation/label_review.py serve ... --people "Name,Name"` limits the review page to the named people (a view filter; counts and export stay whole-dataset), `docs/implementations/2026-10-14-label-review-people-filter.md`.

**Close-ups and CelebA finished (2026-10-15):** `analyse_exclusions.py`'s own functions on the 29 `MyFaces/` pictures (no manifest, so a throwaway driver): 0 lost to the floor or the subject rule, largest face 43.5% at 0.66 (0.82 padded); issue 173 stays open (one person, uncategorised, no negatives). The CelebA gate re-run to completion (2 h 40 min CPU, detached): 10 of 10 workflow checks, same rankings after a restart, figures identical to 2026-10-14; report `evaluation/datasets/reports/gate-celeba-rerun.json`. `docs/implementations/2026-10-15-m5-myfaces-closeups-and-celeba-rerun.md`.

**Latest (2026-10-13):** the LFW and CelebA exclusion analysis (`evaluation/analyse_exclusions.py`, `docs/implementations/2026-10-13-m5-lfw-exclusion-analysis.md`) found no pipeline weakness that justifies a change yet: LFW lost 5 of 1,244 photographs to very large faces under the detector's 0.5 floor (a black margin fixes all five), CelebA lost 1 of 1,736 (an ambiguous crop) and none to the subject rule, which lives only in the evaluation gate. My prediction that CelebA would show more losses was wrong. No threshold or policy changed; any detector change needs a dated owner decision after the owner's own close-up photographs are measured. CelebA is imported (`evaluation/datasets/celeba`; the importer's nested-layout fix is in the same PR).

**Current (2026-10-07):** M0 to M4 are done on the development profile. The next milestone is M5, the first
real recognition milestone: [`docs/plans/M5_PLAN.md`](../docs/plans/M5_PLAN.md) (an identity-management
track and a real-model track, converging before search; scope and order approved; R0, the library-profile guard (#137), is built; R1 is done and R3 partly: `buffalo_l` selected (record in `docs/research/reference-model-selection.md`), installed as a runtime package and run for real on CPU by a local real-worker smoke test (`tests/e2e/test_real_models.py`, `-m e2e`, never in CI); the owner's conservative rule (R4, `docs/research/measured-operating-point.md`) was evaluated and disables automatic acceptance (ABSTAIN-only) until a larger verified set exists; that policy takes effect when the real host reads it; CUDA is verified on the RTX 4070 and agrees with the CPU, `docs/implementations/2026-10-07-m5-r2-cuda-runtime.md`; the host's real profile (`backend/api/real.py`, `docs/implementations/2026-10-08-m5-real-host-profile.md`) runs the installed model through the application on CPU or CUDA under the measured policy file). The
numbered list below is the **historical** M2 and M3 record, kept for what was decided and built, not a
to-do list.

### Historical: M2 and M3 steps

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
   done; Source deletion and identity-level forget are built in M5 steps 4b and 4c; Recycle Bin cleanup remains).
7. **M3 (single-image ML integration), built 2026-10-02 to 2026-10-07 and complete as far as it can be without real models (history follows).** The 14-step plan is authoritative. Steps 1 through 6 are complete: decisions, the ML IPC contract (TST-033), machine-local runtime packages and recovery, shared-memory worker/supervisor, and image decode/import (TST-036/037). Step 7's versioned SCRFD/ArcFace contracts, ONNX worker handlers, runtime catalog registration, machine-specific planning, perception client, and PENDING-output writer are complete. The writer persists each detector result first as a PENDING observation, then attaches its settled embedding as a PENDING representation; an embedding failure leaves the observation PENDING and writes no representation. Each output records the runtime variant that actually executed (issue 88), while the representation space remains compatibility metadata. Steps 8 and 9 are complete: run-local/global retrieval (TST-040) and the recognition assessment/reasoner (TST-041/042). Step 10 now has its request, claim/start, and private execution boundaries: `ExecuteProcessingJob` performs decode → detect → private observation → embed → private representation → retrieve/reason → private decision, keeps ML outside write transactions, writes INTERMEDIATE then valid FINAL checkpoints, and moves the run to FINALIZING without making output authoritative. It checks cancellation only between safe boundaries. The runtime planner accepts the snapshot's exact detector and embedder exports and refuses a substitute. There are no M3 mutable defaults (decision 2026-10-04, issue 98); M4 defaults will produce the same request. M3 permits only the implemented uncalibrated interpretation and refuses a profile request or a runtime policy without usable matching detector/embedder variants. Identity-less ACTIVE representations remain readable candidate evidence but are never offered as MATCH_EXISTING targets. **Known conflict:** Persistence §14 says any provider/export/variant change starts a new execution segment, while the owner decision dated 2026-10-03 says segments must not be split per detector/embedder stage. The PerceptionClient supplies actual successful output variants but not fallback-history events; output provenance is correct, but fallback segment history is not yet claimed complete. Step 11 now accepts an identity-less ACTIVE candidate through migration 0006 and records `RECOGNITION_ABSTAINED` Evidence for accepted ABSTAIN output (PR #106, closing issue #104). Runtime packages remain machine-local and are never substituted; `ABSTAIN` creates no Occurrence and is resolved later without an `ann_key` change; a representation-space key excludes provider and descriptive family. TST-044 remains post-M3, Q16 remains deferred unless M3 makes it unavoidable, and issue 80's installation-MISSING sweep was built 2026-10-08 (`mark_missing_installations`, `docs/implementations/2026-10-08-m5-installation-sweep.md`).

   > **Decision 2026-10-06 (owner):** M4 runs the vertical slice on a clearly named development/evaluation decision-policy profile, marked uncalibrated and non-release in the frozen snapshot and shown as such in the UI; its numbers are not shipped defaults, and TST-044 gates any calibrated release policy. The real SCRFD/ArcFace path stays blocked on issue #69 (source, exact artifact and version, hash, licence, redistribution status, verifier); M4 uses fakes. Startup recovery must complete before the scheduler claims work. See `docs/plans/M3_M4_COMPLETION_PLAN.md`.

   > **Decision 2026-10-05 (owner):** The apparent §14 conflict is resolved by #102 and PR #101: only a real provider fallback starts a successor execution segment; detector-to-embedder movement does not. The step-11 acceptance branch now validates a current FINAL checkpoint and atomically activates outputs, writes occurrences/evidence plus durable ADD operations, moves the source pointer and completes run/job before a post-commit index wake. `ABSTAIN` creates `RECOGNITION_ABSTAINED` evidence, an identity-less ACTIVE representation and no Occurrence. **Remediation 2026-10-06:** FINAL's v1 decision evidence now fails closed for unknown/missing versions and fields, contradictory decision facts, incoherent semantic/candidate snapshots, and a CREATE_NEW FINAL records the resolved Identity in both outer and evidence forms. Repeated acceptance revalidates exact durable Evidence/link/candidates, Occurrence membership or its absence, and one ADD operation. The focused acceptance/execution suite passed 151 tests at 100% line/branch coverage with thirteen guard mutations caught; the final full gate passed 2,328 tests at 100% coverage. The independent review and exact-head CI passed before PR #106 merged and closed issue #104. Step 12 wires recovery to this boundary.
8. Owner's build order (2026-10-01): ~~the remaining repositories (issue 32)~~ done, ~~the downgrade policy (35)~~ done, ~~the library root and lock (36, 39)~~ built and wired into `open_library`, ~~lifespan wiring and process-kill tests (33)~~ done except the FastAPI lifespan itself (no web app exists yet),
   the rest of Q26 (34), the downgrade policy (35, question 19), the library root (36, question 17), and the
   validations Q20, Q21, Q23, Q27 (37 to 41, all final now; the M3 run-local index of Q21 is built, step 8), deriving a missing original's availability from its artifact (Q24).
   Issue 55 (block `INSERT OR REPLACE` on snapshots) was built in revision `0005` (2026-10-03).

Model rules: CHECK constraints only where a spec defines the complete value set; otherwise a
plain string, listed as an open question. Every schema change is now a reviewed Alembic revision
(see `backend/alembic/README`).
