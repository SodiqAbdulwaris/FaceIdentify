# Fix: the index catches up fully after an acceptance

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M6 step 8 (D8, the real-world check), which found it
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(memory): catch the index up fully after an
  acceptance`

## What changed

`IndexCoordinator.drain(batch=...)` (`backend/app/memory/index_coordinator.py`) applies the index
operations that are due when it starts, a batch at a time (`IndexOperationRepository.due_count`
fixes the budget). Each turn of a host processing loop (`run_once` in `backend/api/startup.py`)
drains before it claims a job, so recognition always runs on an index that has caught up with
everything accepted before it, including a backlog left by a restart. The wake after an acceptance
still makes its one pass, which keeps face search current between jobs.

## Why

After an accepted run the host made one pass of 100 operations and nothing ran the queue again
until the next acceptance (startup recovery makes at most 10 passes). A photo accepts a handful of
faces, so this never showed. A video accepts thousands at once: on the D8 check, the first
episode's 7,264 faces left the index 7,064 operations behind, the second episode's recognition
found the index not converged, and every one of its 5,191 faces abstained as
`RETRIEVAL_INCOMPLETE` (shown as `TRACK_UNSETTLED` by the track rule, with the real reason in each
face's `proposal`). Nobody named after the first video could ever be recognised in a later one.

Retrieval refusing an unconverged index is right (an index that lags looks exactly like a person
never seen); the defect was only that the host never let it catch up.

The review (Codex, PR #254) rejected the first version, which drained after an acceptance until the
queue was empty: another loop queueing as fast as it drained could keep it going for ever, and a
restart with a backlog beyond recovery's bounded passes still left the next run's recognition on an
unconverged index. Draining a budget fixed at the start, before each claim, answers both. Operations
that fail are backed off, so they are no longer due and do not stop the rest.

## Verification

- New tests: `test_drain_applies_every_due_operation_a_batch_at_a_time` (five operations with a batch
  of 2 all applied, one not yet due left pending) and
  `test_drain_stops_at_what_was_due_when_it_started` (every pass queues one more; the drain ends
  after the five it found, three left for the next one).
- `uv run pytest -q tests/integration/test_index_coordinator.py tests/integration/test_api_lifespan.py
  tests/integration/test_api_development_profile.py`: 64 passed; ruff and mypy clean.
- On the D8 scratch library (real models, CPU): one acceptance drained a backlog of 11,255
  operations in about 17 s, and the index reported converged afterwards.
