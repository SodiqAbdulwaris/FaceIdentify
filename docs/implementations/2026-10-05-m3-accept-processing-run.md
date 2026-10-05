# M3: atomic processing-run acceptance and abstention evidence

- **Date:** 2026-10-05
- **Milestone / tracker IDs:** M3 step 11 · TST-042 · TST-043 (partial) · issue #104
- **Status:** ready for independent review; pending PR
- **Commits:** pending PR

## What changed

`AcceptProcessingRunUseCase` validates a current, supported `FINAL` checkpoint and, in one
`UnitOfWork` transaction, activates private observations and representations, activates a
run-created Identity or assigns a validated active identity, makes one image Occurrence per
identity-bearing observation, persists evidence, appends durable `ADD` index operations, moves the
source pointer, and completes the Run and its Job.

The transaction accepts an `ABSTAIN` as identity-less `ACTIVE` representation evidence: it receives
its permanent `ann_key` and `ADD` intent, writes `RECOGNITION_ABSTAINED` plus bounded candidates,
and creates neither Identity nor Occurrence. The enum constraint is delivered by migration `0006`,
which recreates only `evidence` while preserving its rows, foreign keys, and indexes.

The index wake occurs only after SQLite commits. A failed wake therefore leaves an accepted,
replayable `IndexOperation`, never a rolled-back authoritative result. Repeated acceptance checks
the committed result rather than returning blindly and does not duplicate evidence or operations.

## Why

Persistence sections 6.2, 10--12, 16 and 30 make acceptance the sole SQLite-authority boundary;
issue #104 defines the immutable historical abstention record.

## Decisions

- **2026-10-05 (owner; #104):** `RECOGNITION_ABSTAINED` records why identity assignment was declined
  and remains when later resolution adds new evidence.
- **2026-10-05:** A coordinator wake failure is observable to the caller, but it occurs after the
  authority transaction; recovery/replay handles the durable pending operation.

## Verification

- Focused acceptance suite — **41 passed** with 100% line-and-branch coverage for
  `AcceptProcessingRunUseCase`; migration compatibility suites — **90 passed**.
- Ruff format/check and both native/Linux mypy targets — passed.
- Migration mutation: removing `RECOGNITION_ABSTAINED` from revision `0006` made its migration test
  fail; the migration SHA-256 was restored byte-identically.
- Acceptance mutations: suppressing the guard rejecting an ABSTAIN representation that secretly
  names an Identity, and requiring an ACTIVE rather than PENDING Observation at acceptance, each
  made their acceptance tests fail; the source SHA-256 was restored byte-identically after each.
- Full repository gate — **2,291 passed, 100% backend coverage** (`HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider`, 2026-10-05). Independent review, PR and exact-head CI
  remain before this entry is done.

## Open issues / follow-ups

- Step 11 still needs independent review, PR, and exact-head CI.
- Step 12 recovery must invoke this use case for a valid FINAL checkpoint without rerunning ML.
- Issue #79 remains the separate later `ResolveUnresolvedRepresentation` use case.
