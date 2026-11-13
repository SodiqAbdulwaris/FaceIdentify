# M8 step 5(b): the recognition-mode choice

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M8 step 5(b) (R7) · TST-079 (not `PASSING`: the screens and the end-to-end flow are not built)
- **Status:** done; the plan's "run the self-check" part is decided differently (below)
- **Commits:** PR (number added when opened): `feat(api): let the user choose assisted or automatic recognition`, and its docs commit

## Why

M8 decision R7: the package ships no policy and never overwrites one, so a fresh install cannot process until the user chooses how
automatic recognition is. The owner's live policy must never be touched by the installer or by this route.

## What changed

- `backend/app/runtime/recognition_mode.py`: the two policies the code admits (Assisted, the abstain-only `buffalo-l-abstain-only-v1`; Automatic, the
  owner-approved `buffalo-l-verified-match-v1` at 0.45 / margin 0.10), `current_mode(path)` (none, one of the two, or a file this application did not write)
  and `choose_mode(path, mode, shown_version)`: refuses when the version is not the one shown for that mode, never replaces a policy file that is not exactly one of the two,
  writes under a `.partial` name and renames (the old policy or the new one, never half).
- `backend/api/routes/recognition_mode.py`: `GET /api/v1/runtime/recognition-mode` (the current mode: `NONE`, `ASSISTED`, `AUTOMATIC` or `CUSTOM`, and the two options with the
  exact policy each would write and a plain-language description) and `PUT` (`{mode, shown_version}`; `409 POLICY_NOT_CONFIRMED`, `409 POLICY_NOT_REPLACEABLE`). The real profile reads
  the file on every request, so a choice applies at once.
- `docs/specs/API and Contracts.md` section 5.9, the contract regenerated.

## Verification

- 11 tests (the module and the API), on temporary state folders only: the real policy file under `local-models/state` was never read or written. Backend gate: see the PR description.
- Not verified: a first real processing run under each mode (step 8).

## Decisions (delegated, 2026-11-13; the owner may reverse any)

- **The self-check is the readiness the backend already reports, not a new route.** `/readiness` carries `runtime_package`, `processing_policy`, `ml_worker`, `execution_provider` and
  `provider_fallback`; the worker loads its models on its first request, so which provider runs them is known only after the first processing, and a self-check that processed a generated
  image would have to write one into the library (or add a second, library-free path through the worker). The first-run screen shows the readiness checklist after each step; the provider
  line fills in after the first image. A dedicated self-run is left to step 8 if the real-model check shows it is needed.
- An owner-made policy (`CUSTOM`) is reported and never replaced by the app: changing it is a file the owner edits, as today.

## Open issues / follow-ups

- 5(c) the first-run screens and 5(d) the desktop end-to-end test; the rollback tests of TST-080 and TST-082.
