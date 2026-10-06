# M3: durable source-processing request

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 step 10 · TST-040, TST-041, TST-042
- **Status:** partial
- **Commits:** PR #97: `feat(processing): queue source processing`

## What changed

Added `ProcessSourceUseCase`, the first durable command in processing orchestration. For one
active image Source whose original Artifact is available, it resolves the caller's strict
`ProcessingRequestV1` inside the write UnitOfWork, then commits its canonical immutable snapshot,
a `PENDING` ProcessingRun, and a queued `PROCESS_SOURCE` Job. The scheduler wake occurs only after
that transaction commits and is best-effort: a lost wake cannot lose the durable queued Job.

The integration tests cover the successful graph, strict request parsing, immutable catalog facts
in the snapshot, mutually incompatible selections, unsupported profile calibration, every refused
source/request precondition, rollback with no partial processing rows, and a failing post-commit
wake.

## Why

`ProcessSourceUseCase` is the explicit top-level processing command required by API and Contracts
§5.3 and §§89, 95–96 plus Persistence Implementation §§13 and 26. It establishes the durable boundary before
the later executor performs decoding or ML work outside a database transaction.

## Decisions

- **Decision 2026-10-04 (owner, issue 98):** the command accepts `ProcessingRequestV1`, not a
  pre-resolved arbitrary object. Its resolver fail-closes on unknown schemas, validates selected
  catalog objects in the transaction, and freezes their immutable semantic values. There are no
  M3 defaults; M4 may produce the same request from settings later.
- **Review correction 2026-10-04:** schema versions accept only the exact integer `1`, never
  Python's `true`/`1.0` aliases. M3's current recognition implementation is uncalibrated, so a
  `PROFILE` request fails closed rather than preserving a calibration contract it cannot execute.
- Scheduler wake failure is recoverable because the Job is already committed and later scheduler
  recovery can claim it.  The use case therefore does not roll back or report the committed work
  as absent.

## Verification

- `uv run ruff format --check backend/app/processing/process_source.py tests/integration/test_process_source.py`
  — passed.
- `uv run ruff check backend/app/processing/process_source.py tests/integration/test_process_source.py`
  — passed.
- `uv run mypy backend/app/processing/process_source.py tests/integration/test_process_source.py`
  — passed.
- `uv run pytest tests/integration/test_process_source.py -q -p no:cacheprovider` — 37 passed.
- `$env:HYPOTHESIS_PROFILE = 'ci'; uv run pytest --cov -q -p no:cacheprovider` — 2131 passed,
  100% coverage, before mutation testing.
- Mutated the original source/request preconditions, the strict exact-integer schema guard, the
  catalog-kind guard, and detector/embedder provider/state compatibility predicates; each focused
  run failed.
  Removed an unobservable profile-specific branch because the generic unsupported-mode failure
  already rejected it. Restored `configuration.py` byte-identically after the mutation probes
  (SHA-256 `AF55EBCB26C8CDA2C5EF1BDEC7A5A98A19EBD607BE6D5A5334F148C1421D6ED4`)
  and reran the focused checks successfully.
- **Independent review correction 2026-10-04:** the resolver validates a usable provider/state
  variant for both the selected detector and embedder. A request with no detector variant is
  rejected before it creates its snapshot, run, or Job.

## Open issues / follow-ups

This is only the request half of step 10.  The next slice claims the Job, owns execution
segments/checkpoints, and performs decode/ML with no transaction held.  Acceptance remains the
only transition from private PENDING output to authoritative ACTIVE state.
