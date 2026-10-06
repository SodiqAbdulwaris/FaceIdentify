# M3: atomic processing-run acceptance and abstention evidence

- **Date:** 2026-10-05; remediation 2026-10-06
- **Milestone / tracker IDs:** M3 step 11 · TST-042 · TST-043 (partial) · issue #104
- **Status:** full gate passed; ready for final focused independent review and fresh exact-head CI
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

The review remediation makes FINAL's version-1 decision evidence a strict acceptance contract:
every required field/version, outcome/reason/resolved identity, representation space, finite policy
and retrieval facts, and bounded ordered candidate snapshot are validated before anything becomes
authoritative. FINAL construction now replaces CREATE_NEW's proposal-time null evidence identity
with its resolved pending Identity. A completed run also revalidates its exact Evidence payload,
subject link, candidate rows, image Occurrence/membership rule, and exactly one durable ADD intent.

The follow-up review fix resolves the evidence against SQLite, rejects private, stale, wrong-space,
wrong-identity, or unordered candidate members (including a global member whose Identity is no
longer `ACTIVE`), reconstructs the `RecognitionAssessment`, and runs
the existing `IdentityReasoner` again. The checkpoint outcome, reason, and matched Identity must be
the result of that canonical evidence rather than a worker-supplied assertion.

The reconstructed decision uses only the immutable run snapshot's exact decision policy and the
private Observation's version-1 persisted detection score. Checkpoint copies of either value must
agree before acceptance, so they cannot alter the decision rationale.

The release review additionally refuses a snapshot or canonical snapshot root outside version 1.
It requires a run-local candidate Identity to be `ACTIVE` or a pending Identity created by the
same run, preventing an unrelated private or retired identity from altering a final decision.

Snapshot compatibility is checked before any lifecycle branch, including zero-face and completed
runs, rather than only while validating individual decisions.

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
  pytest --cov -q -p no:cacheprovider`, 2026-10-05) was for the original PR commit, before the
  remediation and must not be treated as verification of it.
- Review-remediation focused suite — **151 passed**, with **100% line and branch coverage** for
  `accept_run.py` and `execute_job.py` (`uv run pytest tests/integration/test_accept_processing_run.py
  tests/integration/test_execute_processing_job.py --cov=backend.app.processing.accept_run
  --cov=backend.app.processing.execute_job --cov-branch -q -p no:cacheprovider`, 2026-10-06).
- Remediation mutation proofs: disabling the evidence cross-check, weakening exact schema/version
  validation, admitting a repeated candidate representation, ignoring a corrupted Evidence link,
  admitting an ABSTAIN occurrence, or ignoring a missing ADD operation each made the relevant
  acceptance test fail. `accept_run.py` returned byte-identically after every probe (SHA-256
  `46EE853BBCFE2E344821B5BBCB6D9946D4A2D5D3CC240B4C3CC2DE1D84E851D4`).
- The reviewer-P1 mutation which disables the re-derived-decision guard made
  `test_final_decision_must_follow_its_valid_candidate_snapshot` fail. `accept_run.py` was restored
  byte-identically (SHA-256 `52349907668370ECD1AD522A4DBB119077FD62D54932D7843E6D4094556D06AD`).
- The second reviewer-P1 mutation which admits an active global representation whose Identity is
  `PENDING` made `test_global_candidate_member_must_name_an_active_identity` fail. The source was
  restored byte-identically (SHA-256 `6D813DF9BC58CD34C65A6875B90551AD6B12F8CF4CEF9A0C18A13123D0BDADE1`).
- The final reviewer-P1 mutations which accept a checkpoint policy different from the frozen run
  configuration or accept an altered checkpoint quality both failed their targeted regressions.
  The source was restored byte-identically (SHA-256
  `22919DE0358E259A5FC74D7F62189061E9309505E801B968174B5A1B2D54BE39`).
- The release-review P1 mutations which skip frozen snapshot-version validation or admit an
  unrelated pending run-local Identity both failed their targeted regressions. The source was
  restored byte-identically (SHA-256 `1D97EABF21745DD0CCC455D560D8F9AC8566B48CD5D1CC55567F40D28F1AC0DB`).
- The final focused-review mutation which moves snapshot validation behind the lifecycle branch
  made all zero-face and completed-run snapshot regressions fail. The source was restored
  byte-identically (SHA-256 `768F41C4C83FF7477C3E7D9D87F6382F95DD9F2537E8137A1D1A8E5D1A1A224E`).
- Ruff format/check and native/Linux mypy passed after the remediation.
- Full repository gate after remediation — **2,317 passed in 406.28s, 100% backend coverage**
  (`HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider`, 2026-10-06).
- Full repository gate after the review fix — **2,321 passed in 277.63s, 100% backend line and
  branch coverage** (`HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider`,
  2026-10-06).
- Full repository gate after the active-Identity review fix — **2,322 passed in 371.78s, 100%
  backend line and branch coverage** (`HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p
  no:cacheprovider`, 2026-10-06).
- Full repository gate after the durable-input review fix — **2,324 passed in 399.32s, 100%
  backend line and branch coverage** (`HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p
  no:cacheprovider`, 2026-10-06).
- Full repository gate after the release-review fixes — **2,327 passed in 566.21s, 100% backend
  line and branch coverage** (`HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider`,
  2026-10-06).

## Open issues / follow-ups

- PR #106 still needs a fresh full gate, final focused independent review, and fresh exact-head CI
  before merge.
- Step 12 recovery must invoke this use case for a valid FINAL checkpoint without rerunning ML.
- Issue #79 remains the separate later `ResolveUnresolvedRepresentation` use case.
