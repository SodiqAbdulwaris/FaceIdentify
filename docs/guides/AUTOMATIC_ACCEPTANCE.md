# Turning automatic acceptance on and off

Automatic acceptance means a new face that is clearly the same person as one already known is
placed with that person without waiting for you. It is controlled by one file, the decision policy.
The application never writes it; you do. Background and evidence:
[`../implementations/2026-10-15-enable-automatic-acceptance.md`](../implementations/2026-10-15-enable-automatic-acceptance.md).

## The two files

Both live in `local-models/state/policies/`:

| File | Role |
|---|---|
| `insightface-buffalo-l.json` | **The live policy.** Read by the host for every processing request. |
| `insightface-buffalo-l.abstain-only-v1.json` | A restore copy of the abstain-only policy. Never edited. |

The full contents of each policy are in section 4 of
[`INSTALLING_MODELS_WINDOWS.md`](INSTALLING_MODELS_WINDOWS.md#4-the-decision-policy). The two that
the code accepts:

- **On:** `buffalo-l-verified-match-v1`, match threshold 0.45, margin 0.10, no automatic new
  identity. A face is placed only if its best similarity is at least 0.45 *and* leads the next
  person by at least 0.10.
- **Off:** `buffalo-l-abstain-only-v1`, `"match_threshold": 2.0`. Nothing is matched; every face
  after the first waits for you.

Any other matching numbers are refused: readiness reports `processing_policy: UNAVAILABLE` and
processing does not start. Changing the threshold or margin is the owner's decision and a code
change (`APPROVED_MATCHING` in `backend/api/real.py`), not a file edit.

## Turn it off

```powershell
Copy-Item local-models\state\policies\insightface-buffalo-l.abstain-only-v1.json `
          local-models\state\policies\insightface-buffalo-l.json -Force
```

## Turn it on

Replace the live file with the `buffalo-l-verified-match-v1` JSON from section 4 of the install
guide (the restore copy stays as it is).

## What happens, and what does not

- No restart is needed: the policy is read when a run is created, and a run keeps the policy it
  started with. A run already queued or running finishes under the old one.
- **Nothing is re-decided.** Faces that waited before you turned it on keep waiting, with their
  abstention Evidence untouched. Turning it off does not undo matches already made.
- While an old waiting face is unresolved it counts as a neighbour with no identity, as close as
  the person it resembles, so a new picture of that person has no lead and also waits. Resolve the
  waiting faces (the unresolved-faces list on the source screen) to let later pictures match.

## Checking which one is live

- The run record shows it: `policy.automatic_matching` is `true` under the on policy and `false`
  under the off one, with `policy.decision_policy_version`.
- A matched face says "Matched automatically (similarity score …)" on the face check; a face you
  confirmed or moved says "Checked by you." Undo a wrong match with "This is someone new" or "Move
  this face"; the match stays on record as Evidence, the correction is added beside it.
- Readiness (`/readiness`) shows `processing_policy: READY` for either accepted file.
