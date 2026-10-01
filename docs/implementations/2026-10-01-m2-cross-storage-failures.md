# M2: cross-storage failures

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-029; also advances TST-030)
- **Status:** done
- **Commits:** [PR 25](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/25): `feat(sources): mark missing managed files at startup`,
  `feat(memory): rebuild an index that has drifted from SQLite`, `feat(recovery): recover missing
  managed files`, `test(recovery): add the cross-storage failure matrix`, `docs: record cross-storage
  failures`, then the review fixes (`fix(recovery): ...`, see Review)

## What changed

- **Two recovery gaps the failure matrix exposed, both backed by the specs:**
  - `backend/app/sources/artifact_storage.py`: `mark_missing_managed_files(session_factory, store)`
    marks an `AVAILABLE` managed artifact whose file is gone `MISSING` (`MANAGED_FILE_MISSING`), by
    existence alone, keeping the row's hash, size and references. Architecture §16.4: startup
    "reconciles pending records, staging/temp files, **missing available files**, and managed
    orphans"; nothing did the third. Startup recovery now calls it (`StartupReport.missing_managed`).
  - `backend/app/memory/index_coordinator.py`: `validate_indexes` now also rebuilds a sound index
    that is **stale**, one whose entries differ from what SQLite says belong in it (a key missing, an
    extra one, or the same count with a different key). Before, only a missing or unusable index was
    rebuilt, so a database restored from another moment left a valid-looking index answering with
    entries SQLite no longer stood behind (INDEX-02: the index is rebuildable from SQLite).
- `tests/fixtures/consistency.py`: `library_problems(...)`, a reusable cross-storage check that
  returns every disagreement between the three stores as a sentence: artifacts still `PENDING` or
  `DELETING`, an `AVAILABLE` artifact whose bytes are not intact, staging files left, files no row owns
  (optionally allowed), operations pending and due, and for every active space an index that is
  unusable, lacks a key SQLite has, or holds more than SQLite does.
- Review fixes (below): `LibraryRootUnavailableError` / `require_library_root` and
  `reverify_managed_artifact` in `artifact_storage.py`; `CoordinatorReport.leftover_files` and an
  optional `report` argument to `validate_indexes`; a key-only drift check (`_active_keys`).
- Tests: `tests/recovery/test_cross_storage_failures.py` (28) and
  `tests/recovery/test_missing_managed_files.py` (15).

## Why

TST-029 ("Partial failures are recoverable"). There is no distributed transaction across SQLite, the
filesystem and USearch (architecture §19); they are kept consistent by ordering and recovery.
PERSISTENCE §1, §23, §28 and TESTING_STRATEGY INDEX-01/INDEX-02.

## Decisions

- **The failure matrix: 15 durable states a failure at one seam leaves**, built with the real steps,
  not hand-written rows: a reservation whose bytes never arrived, bytes renamed into place but never
  made available, an available but unreferenced original, an accepted image whose index was never
  touched, an index persisted but its operation not settled, an index deleted, an index manifest
  corrupt, an index holding a key SQLite dropped, one lacking a key SQLite has, one holding a
  *different* key with the same count, a managed file deleted behind the application's back, a
  staging file left by a settled artifact, an orphan file no row owns, a deletion intent with the
  bytes still there, and a full disk while persisting the index.
- **Each case proves it is broken before recovery and consistent after.** `library_problems` must
  find something before (except the one state that is consistent by definition), so no case can pass
  vacuously; after `recover_on_startup` it must find nothing, and a second recovery must report
  `repaired_nothing` and still find nothing.
- **Orphan files are reported and kept, never deleted** (the row may only have been lost, and then
  the file is the only copy), so that case allows orphans after recovery and a test asserts the file
  survives.
- **A stale index is replaced, not quarantined.** It is not damaged, and quarantining would keep the
  old file, which still holds every vector it was built with. Rebuild-on-drift is deliberately
  indifferent to why: pending operations let the index legitimately lag SQLite, but rebuilding from
  SQLite is then simply correct sooner.
- **`MISSING`, not deletion.** A managed artifact whose file vanished keeps its row, hash, size and
  references (persistence §4.1: `MISSING` "records a verified failure to resolve bytes"), so a
  restored file can be verified and brought back (`reverify_managed_artifact`: the file must match the
  recorded size and SHA-256 exactly), and a Source that references it is not corrupted.
- **Testing found that the factories add artifacts of their own.** An observation factory creates a
  Source with a default `AVAILABLE` artifact that has no bytes and an invalid key; the matrix builds
  its Source, run and observation explicitly so the factories add none.
- **A space with no eligible representation needs no index file**, so the checker does not call a
  missing one a problem; recovery builds an empty index anyway.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 735 passed (43 new, 0 regressions in the 692
  before); `backend/` coverage 100%. The recovery directory was run 5 times in a row: 115 passed each
  time.
- Mutation checks, each reverted and confirmed byte-identical: 19. The missing-file step (its state
  filter, the invalid-key and unexaminable-file branches, the settled-meanwhile branch, the failure
  code), the drift check (the early return on a missing key, the count comparison in each direction),
  and the checker (each of its terms, so a regression in the checker cannot hide a regression in
  recovery). Six survived at first: the four branches of the new missing-file step had no direct test
  (now `test_missing_managed_files.py`), one was a drift case with equal counts and a different key
  (now a matrix case), and the last two are equivalent: widening the missing-file candidates to
  `MISSING` changes nothing because the guarded transition refuses any row that is not `AVAILABLE`,
  and `expected < len(index)` equals `expected != len(index)` once every expected key has been found.
- **Not verified:** a real subprocess killed mid-operation (architecture §25.13 asks for a smaller
  set of those; they need the backend process), and power-loss durability of any store.

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes,
five findings.

| Finding | Resolution |
|---|---|
| Critical: a drift rebuild reported success although the old generation file could not be deleted (`remove_leftovers` swallows `OSError`), and it still held vectors SQLite no longer authorizes | Fixed. `validate_indexes(report)` now records every `stale_files()` left after opening or rebuilding a space in `CoordinatorReport.leftover_files`; startup lists them in `unresolved` ("superseded index files not removed"), so the run is not `clean`, and the next start removes them. The consistency checker now reports superseded index files too, and a new matrix case and a locked-file test cover it |
| High: one `FileNotFoundError` marks an artifact `MISSING` permanently; a transient root outage would mislabel everything, and the "can be brought back" claim had no code | Fixed. `require_library_root` runs first in `recover_on_startup` and in `mark_missing_managed_files`: a library root that is not a directory raises `LibraryRootUnavailableError` before any row is touched (including the existing `PENDING` reading). `reverify_managed_artifact` brings a `MISSING` managed artifact back only when the file matches the recorded size and SHA-256. It is a function, not a startup step: hashing every missing original at each start would be unbounded, so who calls it (a verify action, or a later startup policy) is left to the API work |
| Medium: the drift check decoded every vector at startup | Fixed. `_is_stale` streams only `ann_key` (`_active_keys`). One consequence is stated: a non-finite vector has a key but never enters the index, so its space is rebuilt at every start and reported as unindexable until the representation is dealt with (test added). A wrong-length vector cannot exist (the schema's CHECK refuses it), so no length filter was added |
| Medium: the matrix only proved "something is wrong" beforehand | Fixed. Each `Case` names the phrase the checker must report before recovery (`shows`), and the checker reports superseded index files. Doing so showed one expectation of mine was wrong (a full disk while persisting leaves no index at all, not an overdue operation) |
| Low: the test commit is 718 lines, above the ~400 guidance | Answered, not changed. The checker and the matrix are one reviewable unit (the matrix is meaningless without the checker and the checker unproven without it), and the commit is already pushed. The review-fix commit is separate and small |

Mutations for the fixes (each reverted and confirmed): the leftover recording, both root
preflights, the digest comparison and the state check in `reverify_managed_artifact`, and the
checker's new term, all caught. Two guards were removed after mutation showed them unobservable: a
SQL length filter in the key-only query (the schema already forbids the case) and a `set()` around
the unindexable count (no flow produces duplicates).

## Open issues / follow-ups

- Process-level kill-and-restart tests remain for when the backend process exists.
- The consistency checker is a test helper. A production "verify library" action (processing
  architecture §32) could reuse its logic; that belongs with the API/UI work.
