# Processing 02 Configuration snapshots

## 1. What this is and why it exists

Settings change: a new model, a better policy. A result recorded last month must still be explainable by **what was in force
when it was made**. So every processing run carries an immutable **configuration snapshot**, a frozen copy of the catalog
facts and policies it ran with, and nothing reads a "current settings" object while a run executes. A retry copies the old
snapshot; it does not re-resolve today's settings.

## 2. Where it lives

| Thing | Where |
|---|---|
| The request and its resolver | `ProcessingRequestV1`, the resolver in `backend/app/processing/configuration.py` |
| The snapshot table | `processing_configuration_snapshots` (`SnapshotRepository` in `run_repository.py`) |
| The profile that builds the request | `development_request` in `backend/api/development.py`; the real profile in `backend/api/real.py` |
| Tests | `tests/integration/test_process_source.py` (strictness, `test_processing_request_v1_is_strict_and_fails_closed`) |

## 3. How it works

- **The request is strict**: `ProcessingRequestV1` has a `detector` and an `embedder` selection (an export each), a
  `representation_space_id`, a `calibration` selection, and `runtime_policy`, `crop_policy`, `quality_policy`, `decision_policy`
  and `command_options` objects. Unknown or missing fields are refused (fail closed); a non-object is refused.
- **The resolver** runs inside the request transaction: it verifies that each selected export exists, that the embedder belongs
  to the space, and that the pieces are compatible, *before any row is written*; then it freezes both the selections and
  the catalog facts that give them meaning (component keys and versions, export format and hash, the space's dimension and metric).
- **Runtime variants are deliberately absent.** The snapshot says what was *asked for*; which variant (and provider) actually
  *ran* is recorded later on the segment, observation and representation as provenance.
- **Calibration**: a profile-calibrated policy is rejected until that milestone is built; the development profile freezes
  `mode: UNCALIBRATED`, which acceptance carries to the evidence.
- **Fingerprint**: `fingerprint_sha256` of the canonical JSON identifies equal settings. One snapshot per run (rows are not shared).

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library:

```bash
uv run python q.py ~/faceidentify-play/lib "select schema_version, count(*), count(distinct fingerprint_sha256) from processing_configuration_snapshots group by 1" "select json_extract(canonical_json,'\$.detector.component.key'), json_extract(canonical_json,'\$.embedder.component.key'), json_extract(canonical_json,'\$.representation_space.dimension'), json_extract(canonical_json,'\$.calibration.mode'), json_extract(canonical_json,'\$.decision_policy.version') from processing_configuration_snapshots limit 1"
```

Observed: `(1, 3, 1)`: three snapshots (one per run) with one distinct fingerprint, since the settings were identical; the second
query shows `development-face-detector`, `development-face-embedder`, `64`, `UNCALIBRATED`, and the demo policy's version. Read the
whole thing with `select canonical_json from processing_configuration_snapshots limit 1`.

## 5. Change it

A new policy field means: add it to `ProcessingRequestV1` and its parser, to the snapshot's canonical form, and to the code
that consumes it from the frozen copy. Add a test in the strictness style first. Never read the setting from anywhere
but the snapshot during execution; `test_final_policy_must_match_the_frozen_run_configuration` enforces that acceptance
uses the frozen policy.

## 6. Break it on purpose

Run `uv run pytest tests/integration/test_process_source.py -q -k strict` (`19 passed`, observed): the cases that mutate a request (a stray field, a missing
selection) must each fail closed. Then read one mutation in the test to see how small a change is rejected.

## 7. Exercises

1. Why does a retry copy the snapshot instead of resolving the settings again?
2. Why are runtime variants not in the snapshot?
3. What does an identical fingerprint tell you?
4. Where is the policy that judged a face recorded?

**Answers**

1. A retry must execute the same intent; resolving again could silently use a newer model or policy.
2. The snapshot is intent; the variant that actually ran is provenance, recorded as it happens.
3. The two runs used the same frozen settings.
4. In the run's snapshot (`decision_policy`) and in the evidence payload.

## 8. Related files

- Previous: [01 Jobs and runs](01-jobs-and-runs.md) · Next: [03 Executing an image](03-executing-an-image.md)
- [`backend/app/processing/configuration.py`](../../../../../backend/app/processing/configuration.py), [profiles](../architecture/04-profiles.md)
