# M2: revalidating ANN candidates at representation level

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2/M3 boundary (TST-019 extended; INDEX-03, retrieval half); implements GitHub
  issue #44
- **Status:** done; a latent `ann_key` defect found on the way is open as issue #48
- **Commits:** [PR 49](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/49): `feat(identities): revalidate
  ANN candidates at representation level`, `test(identities): cover ANN candidate revalidation`, `docs: record
  the ANN candidate revalidation` (review fixes are folded in; see Review)

## What changed

- `resolve_ann_candidates(session, representation_space_id, ann_keys)` and its value
  `RecognitionCandidate` (`ann_key`, `representation_id`, `identity_id`: plain values, no ORM objects) in `backend/app/identities/use_cases.py`, next to the existing
  `resolve_recognition_candidates`.
- `tests/integration/test_ann_candidate_revalidation.py` (21 tests).
- Persistence §6.2 item 6 now names the function instead of saying it is not built.

## Why

Persistence §23: an index returns only `ann_key`s, and "SQLite revalidates space, state, identity, and
current eligibility". The only revalidation that existed, `resolve_recognition_candidates`, takes
*identity ids* and checks the identity's state, so it cannot see a representation's own state. That matters
for erasure (decided in PR 42): a representation whose erasure is queued (`ERASING`) keeps its vector and key
until the index has been rebuilt without it, so a stale index can return its key for an identity that is
perfectly active, and an identity-only check would accept it. The review of PR 42 found this; this closes it.

## Decisions

- **A key is kept only if its row is in the given space, `ACTIVE`, with an `ACTIVE` identity.** Every other
  representation state (`PENDING`, `SUPERSEDED`, `ERASING`, `ERASED`, `DELETED`), every other identity state
  (`PENDING`, `MERGED`, `SPLIT`, `FORGOTTEN`, `DELETED`), another space's key and an unknown key are dropped.
  Each is its own test case.
- **A merged-away identity's key resolves to the survivor** with no extra code: a merge moves the loser's
  `ACTIVE` representations to the survivor (`merge_identities`), so the stale key's row already names the
  current owner. The function is deliberately strict (no merge-chain walking); a representation still pointing
  at a `MERGED` identity is dropped.
- **One `SELECT` per 500 keys** (a join of representation and identity), not one lookup per key (API and
  Contracts §101), so one SELECT serves any realistic top-k. Repeats are removed *before* the query, and a
  longer list is read a chunk at a time, because SQLite limits bound variables (999 before 3.32): an unbounded
  `IN` list could fail a face search with "too many SQL variables". A test checks the statement asks for those
  keys (`ann_key IN`), not the whole space; the filter does not change the output, it keeps the query from
  loading every active representation of a space, so it needed its own assertion (a mutation showed it).
- **Reads only, and touches no ORM object.** It selects plain columns and returns values, so it neither
  answers from a row this session cached nor overwrites a change the caller made but did not flush. (My first
  version returned ORM rows with `populate_existing`, copying its sibling, and the review showed the hazard:
  with the project's `autoflush=False`, a caller that had just set a representation `ERASING` would have had
  that pending change silently replaced by the database's still-`ACTIVE` row.) The answer is the database's,
  so a caller that wants a pending change seen must flush first (stated in the docstring).
- **Input order is kept and a repeated key is listed once;** it returns the representation id and the identity
  id, since the caller needs them for the assessment and for evidence, and loads the rows it needs itself.
- **Not built:** the search use case that calls it, and the assessment that follows (M3).

## A defect found on the way (issue #48; decided afterwards, see below)

*Update 2026-10-01:* the owner decided uniqueness per space, `UNIQUE(representation_space_id, ann_key)`, as
revision `0003` (not yet built); this was also CONTEXT's older open question 13, which I had not noticed.

`representations.ann_key` is globally `UNIQUE`, but `ann_key_sequences` has one row per space and each starts
at 1. A throwaway test showed two spaces both allocating `1`, and the second `ACTIVE` representation raising
`IntegrityError`. Persistence §6.2 ("unique") and §6.3 (per-space sequences) conflict, so per the rules this
is the owner's decision. Recommendation: unique per space, `UNIQUE(representation_space_id, ann_key)`, as a
revision `0003`. This function looks keys up by `(space, key)` and works under either choice. Recorded as
open question 28 in CONTEXT.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 870 passed (21 new, 0 regressions in the 849 before);
  `backend/` coverage 100%. The new file was run 5 times in a row: 21 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 9 (the space filter, the representation state
  filter, the identity state filter, the key filter, removing repeats before the query, the chunk size, an
  off-by-one in the chunk slice, the output order twice). One survivor remains, equivalent: `populate_existing`
  added to a column query changes nothing. Survivors that led to a test or a change: the key filter
  (unobservable in the output, now asserted in the SQL), the chunk slice (valid keys now sit on every chunk
  edge), and a type-checker-only `is not None` branch (replaced by a `cast`).
- **Not verified:** a search use case end to end (none exists yet).

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes, two
findings, both correct.

| Finding | Resolution |
|---|---|
| `populate_existing` overwrites unflushed changes on matching ORM instances: with `autoflush=False` a caller that set a representation `ERASING` and then called this would lose the erasure at commit; it also contradicted "reads only" | Confirmed and fixed by changing the design: the function returns plain values from a column projection and touches no ORM object. A test sets an unflushed `ERASING` on a representation and an unflushed change on an identity and shows both survive the call |
| The `IN` list is unbounded: repeats were removed only after the query, and any `k` is allowed, so a face search could hit SQLite's bound-variable limit | Confirmed and fixed: repeats are removed first and keys are read 500 at a time. Tests: 5000 repeats of one key issue one statement with one key; 1150 distinct keys issue three statements and lose no key at a chunk edge |

## Open issues / follow-ups

- Issue #48: the `ann_key` uniqueness decision.
- Issue #29 still carries the rest of the erasure work (use case, generation retirement, recovery, INDEX-04,
  INDEX-05, PER-07), waiting on #31.
