# Fix: settling an operation that was superseded while in flight

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-028, TST-022); bug fix
- **Status:** done
- **Commits:** [PR 43](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/43): `fix(memory): settle
  around an operation deleted while in flight`, `docs: record the settle fix`

## What changed

`IndexCoordinator._settle` no longer raises `KeyError` when an operation it is settling has been
deleted in the meantime. It skips that operation, as it already does for one settled by someone else,
and settles the rest. One test added to `tests/integration/test_index_coordinator.py`.

## Why

Found by the independent review of the Q25/Q26 decision record (PR 42). `IndexOperationRepository.append_batch`
(PR 28) supersedes a pending operation of the opposite kind by deleting its row (CONTEXT open question
27). The coordinator reads attempt counts in one transaction and writes outcomes in the next, and
`_settle` indexed `seen[operation_id]` directly, so an operation deleted between claiming it and
settling it raised `KeyError`. That aborted the whole pass: the other operations of the batch were left
unsettled until the next pass. It is transient (the deleted row is not claimed again), but it is a crash
in the very path the supersede decision created. No test had deleted a claimed operation while the
coordinator was running, so nothing exercised it.

## Decisions

- **Skip, do not report.** An operation that no longer exists has nothing to settle and nothing to retry;
  the new state of the representation was queued by whatever superseded it. It is neither applied,
  retrying nor failed, so it appears in no report list.
- **No change to the supersede rule** (open question 27 stands).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform linux`:
  clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 800 passed (1 new, 0 regressions in the 799 before);
  `backend/` coverage 100%. The coordinator's test file was run 5 times in a row: 27 passed each time.
- Mutation check: removing the guard makes the new test fail with the original `KeyError`; the file was
  restored byte-identical.
- **Not verified:** a real second process deleting during a pass (the test deletes inside the persist step,
  which is the window between claiming and settling).
