# M2: Source repository

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-022, partly: the fifth repository)
- **Status:** partial: done for `sources`; TST-022 continues (issue #32)
- **Commits:** [PR 45](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/45): `feat(sources): add the
  source repository`, `test(sources): add the library page contract tests`, `test(sources): add the current
  run contract tests`, `docs: record the source repository` (review fixes are folded in; see Review)

## What changed

- `backend/app/sources/repository.py`: `SourceRepository(session)` with `add`, `get`, `library_page` and
  `set_current_run`, and the values `LibraryCursor`, `LibraryEntry` and `LibraryPage`. "Update
  lifecycle" in persistence §26 is already `lifecycle.py` (recycle and restore), so it is not repeated.
- `tests/integration/test_source_repository.py` (29 tests) against real SQLite, with separate sessions
  and threads.

## Why

TST-022, continued: persistence §26 lists "add/get, library page, set current run, update lifecycle"
for Source. The library page and the current-run pointer are the parts with real database behaviour
to prove: stable pagination while sources are imported, and a cross-row rule SQLite cannot express.

## Decisions

- **Same rules as the other repositories:** join the caller's transaction, never commit, one guarded
  statement per change, decided by the database; `add` flushes; `get` and the page re-read
  (`populate_existing`). `set_current_run` goes through the shared `optimistic_locked_update`, and a held
  `Source` is stale afterwards (stated in the docstring).
- **The library page is keyset-paginated** (§22, "large/growing collection -> explicit cursor-paginated
  query"), by `(created_at DESC, id DESC)` over one state, using the `(state, created_at, id)` index
  (§21). The cursor is the last row's `(created_at, id)`, so a source imported between two requests
  cannot shift or repeat a page (tested: an offset would repeat a row). It asks for one row more than the
  limit to know whether a next page exists, so a page that exactly fits has no cursor.
- **Q24, as decided: a missing original is derived from the artifact, and `Source.UNAVAILABLE` stays
  unassigned.** Each `LibraryEntry` carries `original_state`, the state of the source's original artifact
  (`AVAILABLE`, `MISSING`, ...), read in the same query with a join, not one lookup per source (API and
  Contracts §101: "Do not introduce N+1 queries merely to preserve repository purity"). A test shows a
  source whose original is `MISSING` stays `ACTIVE`. No schema change.
- **`set_current_run` enforces the cross-row rule SQLite cannot** (§20: "A source points to a completed
  accepted `current_processing_run_id` for that source only"): the `UPDATE` requires, in its own `WHERE`,
  a run with that id, belonging to this source, in state `FINALIZING` or `COMPLETED`. Evaluated by the
  database, so a run another session changed after this one last looked is refused, not trusted from a
  cached read (tested). It returns `False` rather than raising: for a stale revision, an unknown source or
  run, another source's run, or a run in any of the nine other states (all tested), because telling those
  apart is the use case's job, not a repository's.
- **Why `FINALIZING` is accepted, not only `COMPLETED`** (the review's critical finding). §30 gives the
  acceptance sequence: "...set `Source.current_processing_run_id`; then mark Run and Job `COMPLETED`", in one
  transaction. My first guard required `COMPLETED` (§12: it means the acceptance transaction committed),
  which would refuse the spec's own order. The reviewer proposed guarding the pre-acceptance state; one
  correction to the reasoning: marking the run `COMPLETED` first would not have broken atomicity (it is one
  transaction and would roll back together), but the guard should follow the spec's order. So a run being
  accepted is accepted, and one already `COMPLETED` is too (re-pointing). **This leaves one duty to the
  caller:** in the same transaction it must mark the run `COMPLETED`, so that at commit the pointer names a
  completed run (§20). The repository cannot see the commit; the acceptance use case's tests must (a test
  here shows the order ending consistent, and issue #34 now says so).
- **A source's own state is not checked** by `set_current_run`; no spec says a recycled source cannot
  point to its accepted result, and inventing the rule would be a decision for the use case.
- **Not built:** clearing the pointer, and the acceptance use case that calls `set_current_run`.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 829 passed (29 new, 0 regressions in the 800 before);
  `backend/` coverage 100%. The new file was run 5 times in a row: 29 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 19 (the limit guard; the artifact join and
  the state it reports; the state filter; each part of the keyset condition; the extra row that decides
  the cursor and which row it names; each ordering key; the run's id, its source, and its state filter,
  and the acceptable set with either state dropped or `RUNNING` added; the updated time; the expected
  revision; both freshness reads). One survived at first (the page did not
  re-read a row held in the session); a test now holds one in a session that does not expire on commit.
  Two writers racing on one expected revision, held together at their first `UPDATE`, get one winner and
  one bump of the revision, not two.
- **Not verified:** a use case calling `set_current_run`; `library_page` over a very large library.

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes, two
findings.

| Finding | Resolution |
|---|---|
| Critical: `set_current_run` required `COMPLETED`, but the acceptance sequence (persistence §30) sets the pointer *before* marking the run `COMPLETED`, so the acceptance use case would be refused | Confirmed against §30 and fixed: the guard accepts `FINALIZING` (being accepted) and `COMPLETED`; the caller must mark the run `COMPLETED` in the same transaction, which a new test shows and issue #34 records. The reviewer's side remark that marking `COMPLETED` first would break atomicity is not right (one transaction), and the entry says so |
| The test commit changes 416 lines, over the ~400 guidance, with no justification | Fixed: split into `test(sources): add the library page contract tests` and `test(sources): add the current run contract tests` |

The reviewer found no problem in the keyset pagination, the artifact join, the Q24 derivation, the
threaded test or the section numbers.

## Open issues / follow-ups

- Issue #32 (remaining repositories) loses Source. Issue #40 (Q24) stays open for the Source use cases.
