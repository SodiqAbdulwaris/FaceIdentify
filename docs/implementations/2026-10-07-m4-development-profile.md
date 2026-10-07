# M4: the development profile and the host's processing wiring

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 (plan decision 1, development policy profile) · TST-044 stays the gate for real defaults · issue #69 stays the gate for real models
- **Status:** done; the sidecar can now import and process with no real model; real models are still blocked
- **Commits:** PR (this change): `feat(api): add the development profile and wire the host`

## What changed

- `backend/api/development.py` (new): the **development profile**, on only with the host flag
  `--development-profile` (off by default; never a release setting):
  - a **fake catalog** registered once in the library's own database (a detector, an embedder, one
    CPU variant each, one 64-dimension cosine representation space), as ordinary rows; repeating
    the registration on every start changes nothing. Its exports are referenced artifacts whose
    file exists (this module), so startup recovery never reports them missing;
  - **fake perception**: one face in the middle of every image, embedded as a unit vector derived
    from the image's pixels, so the same picture is the same identity and different pictures are
    far apart;
  - a **development decision policy**, version `development-uncalibrated-v1`
    (`match_threshold` 0.9, `new_identity_ceiling` 0.5, `margin` 0.1, `min_detection_score` 0.1),
    frozen into every run under calibration mode `UNCALIBRATED`, so every run reports
    `calibrated: false` (the UI's uncalibrated-policy notice, W3.6);
  - `development_plan`, a perception planner that builds the plan from the registered rows (the
    real planner reads installed model packages).
- `ExecuteProcessingJob` takes a `planner` (default: the real `plan_perception`); `ProcessingSettings`
  gains `planner` and `prepare` (a hook that runs after the library has opened and recovered,
  before the scheduler starts; a failure leaves the backend `FAILED` and no scheduler).
- `backend/api/host.py`: `--development-profile`; the host now **always** passes the media limits
  (so import works) and, with the flag, the development processing settings (so process works).
  `PROVISIONAL_MAX_PIXELS` (100 million) and `PROVISIONAL_MAX_BYTES` (512 MiB) are unmeasured
  placeholders, like the host's other limits.

## Why

The plan's definition of done is a complete desktop image workflow that survives a restart. With no
model cleared (issue #69) the sidecar had no way to process anything: the host did not pass the
media limits or any processing configuration, so import and process answered 503. This gives the
shell and the end-to-end test a real, honest path, labelled as what it is.

## Decisions

> **Decision 2026-10-07 (agent's, for the owner to confirm; M4 plan decision 1):** the development
> profile's catalog is **registered in the library database**, not held in memory, because a
> processing run freezes references to catalog rows (and a restart must find the same rows). The
> consequence is that a library used with `--development-profile` contains two development
> components and a development representation space (and identities recognised through it). A
> library meant to be kept should not be opened with the flag; removing that data later is a
> migration concern, not solved here. The thresholds are chosen only so identical and unrelated
> pictures separate; they are not calibrated and not candidates for defaults.

> **Decision 2026-10-07 (owner):** confirmed, **with a strong guard**. Persisting the catalog is
> right because frozen run references must resolve across a restart. A kept or real library must be
> refused when opened with `--development-profile` (and the reverse), enforced in code, not only
> documented: development provenance is recorded explicitly on those catalog and runtime records and
> the library itself is marked so incompatible opening modes are rejected. Cleanup or migration of
> development data stays unsolved on purpose; no migration machinery is to be built for it. The
> guard is not built yet (GitHub issue recorded in `CONTEXT.md`).

## Known limits

- The catalog's export artifacts point at this module's file path. A library carried to another
  install location keeps a dangling path (recovery marks it `MISSING`, which does not affect
  processing). The profile is not packaged for release (M8).
- Pictures are compared by their whole pixels, so a re-encoded or resized copy of a photo is a
  different identity. That is what makes it a fake; real recognition is issue #69.

## Verification

- `tests/integration/test_api_development_profile.py` (7), driving the real host over a loopback
  socket exactly as the shell would: import two identical pictures and one different one, process
  each, see two identities (counts 2 and 1), every run reporting `UNCALIBRATED` and the profile
  version; stop the host, start it again on the same library, see the same identities, process a
  third copy of the first picture and see it recognised (no new identity, count 3); without the
  flag importing works and processing is 503 with the scheduler `NOT_CONFIGURED`; the flag parses;
  the catalog registers once, survives a restart with its artifacts still `AVAILABLE`, and yields
  the exact documented request and a plan; no request before registration; the perception is
  deterministic, unit length, tells pictures apart and answers per detection; a profile that cannot register leaves the
  backend `FAILED` with the class name and no scheduler. `development.py` and `host.py` are at
  100% line and branch.
- Mutation probes (19 on the profile, the host flag and the startup hooks): all killed after
  assertions were tightened (the policy thresholds, the policy name, the artifacts after a restart,
  the detection indices).
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,534 passed**, 100% coverage.
