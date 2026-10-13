# Processing 04 Checkpoints and acceptance

## 1. What this is and why it exists

Acceptance is **the one moment output becomes real**: private `PENDING` rows turn `ACTIVE`, identities are created or
matched, occurrences and evidence appear, and the source's current run changes, all in a single transaction that either
fully happens or not at all. Before it, a **FINAL checkpoint** records the complete result so that a crash between "done" and
"accepted" is finished at the next start *without running any model again*.

## 2. Where it lives

| Thing | Where |
|---|---|
| Acceptance | `AcceptProcessingRunUseCase` in `backend/app/processing/accept_run.py` (`accept`, `_accept`, `_final`, `_validate_private_output`) |
| Checkpoints | `ProcessingCheckpoint`, `CheckpointKind` in `backend/app/processing/models.py` |
| Startup acceptance of a left-over FINAL | `recover_on_startup` ([recovery](../architecture/06-recovery.md)) |
| Tests | `tests/integration/test_accept_processing_run.py` (42), `tests/recovery/test_pipeline_process_kill.py` |

## 3. How it works

- **Checkpoints**: an `INTERMEDIATE` one marks private output written (observation and representation ids); the `FINAL` one
  (payload schema 1, exactly the keys `schema_version`, `observations`, `decisions`) holds each face's decision
  (outcome, reason, identity, evidence, candidates). Each is `VALID` or `INVALIDATED`.
- **Acceptance steps** (`accept`): lock the run; read and strictly validate the FINAL checkpoint; check the frozen snapshot;
  check the run is `FINALIZING` and its job `RUNNING` and the source acceptable; validate every decision against the private
  rows (the policy must match the frozen run, each quality must match its observation, a matched identity must be
  `ACTIVE` or owned by this run, an abstention must not secretly name an identity); then, for every face, create or match the
  identity and write the occurrence, evidence and `ADD` index operation; turn observations and representations `ACTIVE`;
  make the run and job `COMPLETED`; set the source's current run. **Any failure rolls the whole transaction back.**
- **After the commit**, the index is woken (`wake_index`). An error here changes nothing: the `ADD`s are durable and replayed.
- **Idempotent**: accepting a `COMPLETED` run validates it and returns `already_accepted` without duplicating rows
  (`test_repeated_acceptance_validates_and_does_not_duplicate_rows`).
- A FINAL that acceptance refuses leaves the run `NOT_RESUMABLE` and the output private.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_accept_processing_run.py -q
```

Expected: pass (42 tests). The most important to read:
`test_acceptance_activates_private_output_atomically`, `test_bad_final_output_rolls_back_without_waking_or_exposing_anything`,
`test_a_post_commit_wake_error_cannot_undo_the_authoritative_acceptance`. Then see acceptance's footprint on the practice
library ([domain README](../domain/README.md)): three `ACTIVE` observations, representations, occurrences, three evidence rows, and
sources at `revision` 2.

The kill tests need real processes: `uv run pytest tests/recovery/test_pipeline_process_kill.py -q` (they passed on Linux in this session's recovery run).

## 5. Change it

A new validation belongs in `_validate_private_output` or the helper it calls, with a test that builds a bad FINAL (the
existing tests show the pattern, for example `test_final_quality_must_match_its_private_observation`). Acceptance must stay
one transaction; never add a model call or file write to it.

## 6. Break it on purpose

In a scratch edit make `_validate_decision_identity` return early, and run `test_accept_processing_run.py`: the tests that
plant a bad identity fail, proving acceptance is the guard. Restore with `git restore`.

## 7. Exercises

1. Why is acceptance one transaction?
2. What happens if the index wake fails after the commit?
3. What does a FINAL checkpoint let recovery do?
4. Why can acceptance be run twice safely?

**Answers**

1. So memory never shows half a result; any failure rolls everything back.
2. Nothing is undone; the durable `ADD` operations are replayed later.
3. Accept a finished run at the next start without any model call.
4. It checks the run's recorded result and creates nothing the second time.

## 8. Related files

- Previous: [03](03-executing-an-image.md) · Next: [05 Cancel and retry](05-cancel-and-retry.md)
- [`backend/app/processing/accept_run.py`](../../../../../backend/app/processing/accept_run.py), [decisions in memory](../recognition/04-decisions-in-memory.md)
