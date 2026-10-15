# Architecture 04 Profiles: development and real

## 1. What this is and why it exists

The same backend can run in two **profiles** that differ in what stands behind "recognise this picture":

- the **development profile**: a fake catalog and a fake perception that finds one face in the middle of every picture and
  embeds it as a vector derived from the picture's pixels, under a demo policy labelled uncalibrated. It lets the whole
  application be exercised, and tested, with no model files.
- the **real profile**: installed model packages, a real ML worker per plan, and a *measured* decision policy read from a file.

A profile is chosen when the host starts, and it is **recorded inside the library**, so a development library and a real one
can never be mixed. This lesson shows exactly what each needs and what each refuses, with runs that need no model files.

## 2. Where it lives

| Thing | Where |
|---|---|
| The development profile | `backend/api/development.py` (`development_processing`, `register_development_catalog`, `DevelopmentPerception`, `development_request`) |
| The real profile | `backend/api/real.py` (`real_processing`, `ClientPool`, `load_policy`, `require_approved_policy`, `APPROVED_MATCHING`, `providers_from`) |
| The guard | `backend/api/library_profile.py` (`claim_library_profile`, `LibraryProfile`, `LibraryProfileMismatchError`) |
| The choice | the host flag `--development-profile`; the shell passes it in debug builds (`desktop/src-tauri/src/config.rs`, `FACEIDENTIFY_DEVELOPMENT_PROFILE`) |
| Settings both share | `ProcessingSettings` in `backend/api/startup.py` |
| Tests | `tests/integration/test_api_development_profile.py`, `test_real_profile.py`, `test_library_profile.py`; local-only `tests/e2e/test_real_host.py` |

## 3. How it works

### The development profile

`prepare` registers a small catalog (a detector, an embedder, one representation space of dimension 64) **in the library's own
database**, as ordinary rows whose exports point at no real model. Its perception returns one face (box 0.2, 0.2, 0.8, 0.8,
score 0.9) and the vector is a seeded random vector from a hash of the pixel bytes: **identical pictures give identical
vectors, any other picture an unrelated one**. The policy `development-uncalibrated-v1` (quality gate 0.1, match 0.9,
margin 0.1, new-identity ceiling 0.5) is chosen only so those two cases separate; every run frozen under it reports
`calibrated: false`, and the UI shows the uncalibrated-policy notice.

### The real profile

- **`prepare`**: marks installation records `MISSING` if their files left this machine, then registers every installed
  package in the catalog (find-or-create; a damaged package is skipped, not fatal), and reports capabilities.
- **`runtime_package`**: `READY` when the package this profile runs (`insightface-buffalo-l`) is installed and registered,
  else `UNAVAILABLE` (and the app is `DEGRADED`).
- **`processing_policy`**: `READY` when `<local state>/policies/<package key>.json` exists and is usable.
  The file holds the `decision_policy` object of a processing request: `schema_version`, `version`,
  `min_detection_score`, `match_threshold`, `margin`, `new_identity_ceiling`. It is read on **every** request, so a newly
  measured policy applies without a restart.
- **Abstain-first only (`require_approved_policy`, formerly `require_abstain_first`).** Until a verified evaluation exists, a policy is accepted only if its
  `match_threshold` is above 1 (no automatic matching) **and** its `new_identity_ceiling` is `-1` (no identity from a weak
  score). A file that enables matching is refused however plausible its numbers, because nothing binds it to a measurement.
- **`ml_worker`**: the workers' own state, `NOT_STARTED` until a job starts one. `ClientPool` keeps one supervised worker per
  plan for the life of the process (loading models takes seconds) and gives every job a fresh client (so each job records
  its own provider fallbacks).
- **Providers** come from `FACEIDENTIFY_PROVIDERS` (a comma list, default DirectML then the CPU on Windows, the CPU alone elsewhere; `allow_fallback` is on only when more
  than one provider is named, because a lone accelerator must never silently become the CPU).
- With no package or no usable policy, `POST .../process` and `POST /search/face` answer `503 PROCESSING_UNAVAILABLE`. It
  never invents numbers.

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The owner confirmed option A on 2026-10-15:** "A: threshold 0.45, margin 0.10, no automatic new identity." (`buffalo-l-verified-match-v1`; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md)).

### The guard

The first time a backend opens a library it writes `library_profile` into `app_state`; every later open checks it. A
library of the other profile is **refused** (`LibraryProfileMismatchError`, reported as `FAILED` with that class name).
There is no override. A library from before the guard is classified from what it holds (development catalog rows mean
development; any other catalog row or an imported source means real; an empty one takes the requested profile).

## 4. Try it

**Works with no models. Verified 2026-10-12.** All of this needs only the repository.

1. **The guard.** Take the scratch library from [start-here 07](../../00-start-here/07-run-it-and-see-it-work.md), which is a
   *development* library, and start the backend **without** `--development-profile`:

   ```bash
   uv run python -m backend.api.host --library-root ~/faceidentify-play/lib --local-state-root ~/faceidentify-play/state
   ```

   Then `curl -s -H "$H" $B/readiness`. Expected (observed):
   `{"state":"FAILED","capabilities":{"runtime_package":"UNAVAILABLE","processing_policy":"UNAVAILABLE","library_packages":"READY","ml_worker":"NOT_STARTED"},"failure":"LibraryProfileMismatchError"}`.
   The library is untouched; the real profile refused to open a development library.
2. **The real profile on a new library, no model.** Make empty folders and start the host without the flag:

   ```bash
   mkdir -p ~/faceidentify-play/real-lib ~/faceidentify-play/real-state
   uv run python -m backend.api.host --library-root ~/faceidentify-play/real-lib --local-state-root ~/faceidentify-play/real-state
   ```

   `/readiness` (observed): `{"state":"DEGRADED","capabilities":{"database":"READY","storage":"READY","index":"READY","recovery":"READY","ml_worker":"NOT_STARTED","scheduler":"READY","runtime_package":"UNAVAILABLE","library_packages":"READY","processing_policy":"UNAVAILABLE"}}`.
   You can import a picture, but `POST /api/v1/sources/{id}/process` and `POST /api/v1/search/face` both answer
   `503 PROCESSING_UNAVAILABLE` ("No processing configuration is available.").
3. **The policy file.** Create `~/faceidentify-play/real-state/policies/insightface-buffalo-l.json`:

   ```json
   {"schema_version": 1, "version": "practice-abstain-only-v1", "min_detection_score": 0.5,
    "match_threshold": 2.0, "margin": 2.0, "new_identity_ceiling": -1.0}
   ```

   `/readiness` now shows `"processing_policy":"READY"` (observed) while `runtime_package` is still `UNAVAILABLE`:
   the policy alone is not enough. Replace it with a policy that *would* match, `"match_threshold": 0.5, "margin": 0.1,
   "new_identity_ceiling": 0.3` and look again, **without restarting**: `"processing_policy":"UNAVAILABLE"` (observed). The
   file is judged on every ask, and a matching policy is refused.
4. Run the profile tests: `uv run pytest tests/integration/test_api_development_profile.py tests/integration/test_real_profile.py tests/integration/test_library_profile.py -q`.
   Expected: pass.
5. *(Needs the local models; unverified here.)* With `buffalo_l` installed ([a real-model run](../../06-evaluation-and-operations/05-real-model-run.md)),
   `runtime_package` becomes `READY`, the state `READY`, and a first `process` starts a worker (`ml_worker` `READY`).
   `tests/e2e/test_real_host.py` (`-m e2e`, local only) proves it.

## 5. Change it

The honest "change" is to a *policy file*, which is data, not code. To see the effect of the abstain-only rule on the
**development** profile, nothing changes: the development profile does not read a policy file; its numbers are in
`development_request` and are deliberately not shipped defaults. Changing them in a scratch edit (say `match_threshold` to
`1.5`) turns every run's `automatic_matching` to `false`, which `tests/integration/test_api_development_profile.py` pins as
`True`; revert it. Admitting a policy that can match is a **separate, explicit change** gated on a verified evaluation
(the label-review work, M5 track R5); it is an owner decision, not an edit.

## 6. Break it on purpose

Create a development library, then start the real profile on it (step 1) and the reverse: a real library under
`--development-profile` fails the same way (`LibraryProfileMismatchError`). Put a malformed policy file (not JSON, or a
list) in place: `processing_policy` is `UNAVAILABLE` and `process` answers `503`; the backend never falls back to a
default policy.

## 7. Exercises

1. Which flag selects the development profile, and which program usually passes it?
2. Why can the real profile not start on your scratch library?
3. What two properties must a policy file have to be accepted today?
4. With no model package installed, what does `process` answer?
5. Why is the policy file read on every request?

**Answers**

1. `--development-profile` on the host; the Tauri shell passes it in debug builds (or when `FACEIDENTIFY_DEVELOPMENT_PROFILE`
   is `1`/`true`).
2. The library is marked `DEVELOPMENT`; the guard refuses to open it as `REAL` (and the reverse).
3. `match_threshold` above 1 (no automatic matching) and `new_identity_ceiling` of exactly `-1`.
4. `503 PROCESSING_UNAVAILABLE`.
5. So a newly measured policy applies without restarting the application.

## 8. Related files

- Previous: [03 Host and startup](03-host-and-startup.md) · Next: [05 The scheduler and runner](05-scheduler-and-runner.md)
- [`backend/api/real.py`](../../../../../backend/api/real.py), [`backend/api/development.py`](../../../../../backend/api/development.py)
- [Packages and the catalog](../runtime-and-worker/04-packages-and-catalog.md), [thresholds](../../01-basics/recognition-ideas/05-thresholds-and-errors.md)
- [`docs/research/measured-operating-point.md`](../../../../research/measured-operating-point.md)
