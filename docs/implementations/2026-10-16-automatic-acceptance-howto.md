# M5: how to turn automatic acceptance on and off

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 track R; TST-057B (documentation only)
- **Status:** done
- **Commits:** PR to be recorded when merged (`docs: explain turning automatic acceptance on and off`)

## Why

The owner installed the live policy on 2026-10-15 and needs a short, safe way to go back to
abstain-only and forward again without editing JSON by hand or guessing which folder the desktop app
reads.

## What changed

- New guide [`docs/guides/AUTOMATIC_ACCEPTANCE.md`](../guides/AUTOMATIC_ACCEPTANCE.md): the live policy
  file and its restore copy, where `<state root>` is for the desktop app and for a development
  checkout, the two accepted policies, the copy command to switch off, how to keep a copy of the
  approved policy to switch on, what a switch does and does not do, and how to tell which is live.
  The policy contents stay in `INSTALLING_MODELS_WINDOWS.md` section 4.
- Entry added to the index in `docs/implementations/README.md`.

## Decisions

No policy, threshold or margin changed (those are the owner's). The guide says the 0.10 lead applies
when another person is a candidate, as in `IdentityReasoner`. It does not quote screen wording that
is not yet on `main`.

## Verification

Checked against the code, not run on the owner's files: the policy is read when a run is created
(`request_for`, `backend/api/real.py`); runs report `policy.automatic_matching`
(`backend/api/routes/processing.py`); the decision rules are covered by
`tests/unit/test_recognition_reasoner.py` and `tests/unit/test_approved_operating_point.py`. A
read-only Codex review found six issues, all addressed. No file under `local-models/` was written.

## Open issues / follow-ups

The owner may save the approved-policy copy named in the guide; the guide does not create it.
