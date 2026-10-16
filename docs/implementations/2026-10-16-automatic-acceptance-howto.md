# M5: how to turn automatic acceptance on and off

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 track R; TST-057B (documentation only)
- **Status:** done
- **Commits:** PR to be recorded when merged (`docs: explain turning automatic acceptance on and off`)

## What changed

- New guide [`docs/guides/AUTOMATIC_ACCEPTANCE.md`](../guides/AUTOMATIC_ACCEPTANCE.md): the live policy file
  and its restore copy, the two accepted policies, the copy commands to switch, what a switch does and
  does not do (read per run, nothing re-decided, old waiting faces block later matches until resolved)
  and how to tell which is live. The policy contents stay in `INSTALLING_MODELS_WINDOWS.md` section 4.
- Facts checked against the code: the policy is read in `request_for` for every run
  (`backend/api/real.py`), runs report `policy.automatic_matching`
  (`backend/api/routes/processing.py`), and the nil-margin consequence is asserted by
  `tests/integration/test_api_automatic_acceptance.py`.

No policy file or anything under `local-models/` was read for write or changed.
