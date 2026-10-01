# M2: ProcessingRun and snapshot repositories

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-022, partly: the sixth and seventh repositories)
- **Status:** partial: done for `processing_runs` and `processing_configuration_snapshots`; TST-022 continues
  (issue #32)
- **Commits:** [PR 50](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/50): `feat(processing): add the
  run and snapshot repositories`, `test(processing): add the run and snapshot contract tests`, `docs: record
  the run and snapshot repositories` (review fixes are folded in; see Review)

## What changed

- `backend/app/processing/run_repository.py`: `ProcessingRunRepository` (`add`, `get`, `lock`,
  `list_transient`), `SnapshotRepository` (`create`, `get`) and `canonical_json_bytes`. This is the
  "ProcessingRun/Snapshot" row of persistence §26: "add/get/lock, list transient, create/get immutable
  snapshot".
- `tests/integration/test_processing_run_repository.py` (36 tests), against real SQLite.

## Why

TST-022, continued. The run is the unit recovery, acceptance and the scheduler all reason about, and `lock`
is the one repository operation whose meaning depends on how SQLite works.

## Decisions

- **`lock` is "write first, then read".** §9 and §26 say "lock/reload", and SQLite has one writer and no
  row locks. So `lock` runs a write statement that changes nothing (`SET revision = revision`) and then
  returns the run fresh. That takes the database's write lock at the start of the caller's transaction,
  before any read. Tested with a second `lock` told not to wait (`busy_timeout = 0`): it is refused while the first holds the
  lock and, once the first commits, returns the committed row; a raw second connection is refused too; a
  missing run still takes the lock (and returns `None`); nothing about the row changes, not even
  `updated_at` or `revision`.
- **Why that matters (open question 20).** A transaction that reads first and then writes fails at once with
  `SQLITE_BUSY_SNAPSHOT` if another writer commits in between. A test shows that failure mode. `lock` as the
  first call avoids it; it cannot help a caller that has already read. `get` says the same: inside a
  transaction that has already read, SQLite shows that transaction's snapshot whatever `populate_existing`
  does, so "the row as the database has it" holds for a new transaction (what the freshness tests prove). This is the repository-level piece
  of the direction the owner agreed (`BEGIN IMMEDIATE` and retry in the unit of work, to be validated then),
  not a replacement for it.
- **No transition method.** A run's state changes go through the shared optimistic-locked `UPDATE` in the use
  cases (§2), which `SourceRepository.set_current_run` also uses; §26 lists none for runs.
- **`list_transient` returns exactly `TRANSIENT_RUN_STATES`** (what startup recovery must inspect), least
  recently updated first. A test runs every one of the eleven states and checks it is listed iff transient.
  (`NOT_RESUMABLE` is therefore not listed.)
- **The snapshot fingerprint is the SHA-256 of a canonical form I had to define.** §13 says the snapshot
  has `canonical_json` and a `fingerprint_sha256` that "helps diagnostics and is not an authorization token",
  and nothing says how it is computed. It is the SHA-256 of the JSON with sorted keys, no insignificant
  whitespace and non-ASCII kept as UTF-8 (`canonical_json_bytes`), so key order does not change it and
  content does (tested, including a non-ASCII value). This is a diagnostic choice; changing it would only
  change fingerprints of future snapshots, not the meaning of any row.
- **Settings JSON cannot represent exactly are refused, before anything is staged** (`ValueError` naming the
  path): non-string keys (`json.dumps` would turn `1` into `"1"`), `NaN` and infinities (not JSON), sets,
  tuples, bytes and any other object. Nine cases are tested, plus a valid document using every kind of value
  (a 70-bit integer included) that round-trips.
- **One snapshot per run is a database guarantee; immutability is not yet.** `create` is the only write and
  there is no update or delete. A second run cannot reference a snapshot a run already uses
  (`uq_processing_runs_configuration_snapshot_id`, in `0001`; tested). SQLite does allow an `UPDATE` of a
  snapshot; two triggers are decided for revision `0003` (issue #51). The fingerprint is deliberately not
  unique, so runs with identical settings each keep their own row (tested with real runs).
  **Correction (added 2026-10-01):** this entry first said the database enforced *neither*, and that nothing
  stopped two runs from sharing a snapshot because `configuration_snapshot_id` "is not unique". That was
  wrong: the unique constraint was in the model and in `0001` all along (a test now shows the second run is
  refused), and the review comment I "corrected" in response was right to expect it. I had not looked at the
  schema before asserting it.
- **Not built:** run state transitions, the acceptance use case, and database-level snapshot immutability
  (revision `0003`, issue #51).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 906 passed (36 new, 0 regressions in the 870 before);
  `backend/` coverage 100%. The new file was run 5 times in a row: 36 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 23 (canonical form: key order, separators,
  non-ASCII; the digest, the user action and the schema version; each flush; the fresh read in `get` and in
  the list; the lock statement removed or made a real change; the transient filter and its two ordering keys;
  each branch of the JSON validation and its recursion into objects and lists; the validation not being
  called). Three survived at first and are now covered: the schema version (every test used `1`), the
  snapshot's flush (a raw read in the same transaction now finds it) and the transient list's fresh read. One
  guard was deleted as redundant: `allow_nan=False` on `json.dumps`, which the finiteness check already makes
  unreachable.
- **Not verified:** the lock under a retrying unit of work (none exists yet); a snapshot `UPDATE` at the
  database level (nothing forbids it).

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes, five
findings.

| Finding | Resolution |
|---|---|
| Snapshots are not immutable: SQLite allows an `UPDATE`, which would rewrite a run's intent; add a trigger | Right for immutability, but a trigger is a schema change, so it was not slipped into a repository PR: issue #51 asked the owner, who decided on 2026-10-01 to add two triggers in revision `0003`. (My statement here that "one per run" was also unenforced was wrong: see the correction in Decisions) |
| `json.dumps` accepts `NaN`/`Infinity` and coerces non-string keys | Confirmed and fixed: `_require_json` refuses anything JSON cannot say exactly, before staging (see Decisions) |
| The "one snapshot per run" test made two snapshots and no runs | Confirmed. It now creates real runs referencing each snapshot. My "correction" that the database does not enforce one-per-run was itself wrong (it does: see Decisions), and a test now shows a second run on the same snapshot is refused |
| The freshness tests commit before the concurrent update, so they do not prove freshness inside an open transaction (WAL read snapshot) | Right, and the code is qualified rather than the tests changed: `get` says a transaction that has already read sees its snapshot, the tests are renamed to say "in a new transaction", and the answer for a caller that needs the current row is `lock` first |
| No test had a second writer wait for `lock` (the locking session committed before the reader started) | Replaced: a second `lock`, told not to wait, is refused while the first holds the lock and returns the committed row once it commits. The earlier test is renamed to what it shows (the read-first failure) |

## Open issues / follow-ups

- Issue #32: Observation/Representation (ann-key allocation waits for #48 and Q21), Identity/Occurrence/
  Evidence, RuntimeCatalog/Settings.
- Issue #51: database enforcement of snapshot immutability and one snapshot per run.
