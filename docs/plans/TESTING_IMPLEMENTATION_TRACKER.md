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
| TST-019 | `PASSING` | `backend/app/identities/use_cases.py`: `resolve_recognition_candidates` (`API and Contracts.md` §12.2: "ANN candidate retrieval -> authoritative SQLite revalidation"). Read-only: a candidate is resolved through any merge chain to its current identity, dropped if missing or not ACTIVE, and de-duplicated; the function never creates or updates any row, proven for a mix of known/unknown/merged/forgotten/deleted/duplicated candidates in the same call |
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
| TST-031 | P0 | Deletion tests | Cleanup and isolation rules hold |
| TST-032 | P1 | Migration tests | Supported populated schemas migrate correctly |

**Dependencies:** M0, applicable M1 domain contracts, Persistence Implementation.

**Milestone gate:** Representative identity and observation records can be committed, retrieved and recovered without violating authoritative-state invariants.

### M2 status (2026-09-24)

Verified locally on Windows 11 (Python 3.12.14): `uv run pytest` gives 272 passed, 0 skipped, 0
warnings, `backend/` coverage 100%. Remote CI observed green on PR #11. Only part of M2 has been
started.

| ID | Status | Evidence / remaining work |
|---|---|---|
| TST-032 | `IN_PROGRESS` | `backend/alembic/` with revision `0001_initial_schema`; `tests/integration/test_migrations.py`: a fresh upgrade produces exactly the models' tables, indexes (including partial-index `WHERE` clauses), columns and named CHECK/FK/UNIQUE constraints; `alembic check` reports no drift; head is a single linear chain; upgrade is idempotent; downgrade removes every table and round-trips; a failed migration leaves an existing database untouched (no partial schema, data intact); offline `--sql` works. Every other persistence test also runs on the migrated schema. **Remaining:** "supported populated schemas migrate correctly" needs a second revision to migrate *from* `0001` |
| TST-021 | `PASSING` | Pragmas (`foreign_keys`, WAL, `synchronous`, `busy_timeout`, `temp_store`) and per-connection FK enforcement: `test_persistence_fixtures.py`; required constraints: `test_schema_contract.py`, `test_core_models.py`; WAL *behaviour*: `test_sqlite_wal_behaviour.py` (WAL persisted in the file itself, a reader is not blocked by an open write transaction, a second writer is refused while the lock is held, and a reader-turned-writer fails immediately once another writer has committed — see CONTEXT open question 20) |
| TST-024 | `PASSING` | `tests/concurrency/test_optimistic_concurrency.py`: with separate sessions, a stale rename, activation and merge are each rejected and change nothing; with simultaneous threads (5 rounds each) exactly one rename lands (revision bumped once, never per writer), exactly one activation, and exactly one merge of a shared loser. Mutation-checked, and stable over 25 repeated runs. Only Person and Identity have revision-guarded use cases so far |
| TST-022, 023, 025 to 031 | `PLANNED` | Not started |

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