# M5 R2/R3: the real host profile, and the real models through the host

- **Date:** 2026-10-08
- **Milestone / tracker IDs:** M5 track R, R2/R3 remainder; TST-038, TST-039 (real path through the host, local)
- **Status:** done, except the installation sweep of issue #80 (its own change)
- **Commits:** PR to be recorded when merged

## What changed

- **`backend/api/real.py`** is the host's real processing profile, and the host's default without
  `--development-profile`:
  - `prepare` registers every installed runtime package in the library catalog (find-or-create, so it
    is safe on every start) and returns the `ml_worker` capability: `READY` when the package this
    profile runs is registered, `UNAVAILABLE` otherwise (never another package instead).
  - `ClientPool` keeps one supervised worker and `PerceptionClient` per plan for the life of the
    process (the models load once) and stops them all at shutdown.
  - `request_for` builds the processing request on each command from the registered catalog and the
    measured policy file `<local state>/policies/<package>.json` (the `decision_policy` object
    only), validated by the real `ProcessingRequestV1` parser. No package, no file, an unreadable or
    invalid file: `ProcessingUnavailableError`, which the route answers as `503
    PROCESSING_UNAVAILABLE`. Calibration is `UNCALIBRATED`: raw cosine scores, never probabilities.
  - Providers come from `FACEIDENTIFY_PROVIDERS` (a comma list, preferred first; CPU by default). More
    than one provider sets `allow_fallback`; an unknown or repeated name is an error, never a silent CPU.
- **`ProcessingSettings.close`** runs at shutdown after the scheduler has stopped (the pool stops its
  workers) and the library is closed in a `finally`, so a worker that will not stop can never leave the
  library lock held. `prepare` may return capability updates; a capability of `UNAVAILABLE` makes the
  app `DEGRADED`.
- **Tests.** `tests/integration/test_real_profile.py` (18): providers, the policy file's failure modes,
  the pool (one worker per plan, all stopped once), registration and request building against a real
  library with a fixture package, and the whole application (readiness, a run under the abstain-only
  policy, the unresolved face, workers stopped at shutdown, `503` without a policy, `DEGRADED` without
  the package, a failing close). Two existing host tests changed because a host without the flag now
  runs the real profile (`DEGRADED` with nothing installed). Five guards were mutation-tested.
- **`tests/e2e/test_real_host.py`** (local, `-m e2e`, never in CI): real photographs through the real
  host profile, on CPU and on CUDA-first with CPU fallback. First photograph: an identity is created;
  a second photograph of the same person is not matched (automatic matching is off) and waits, with
  the right identity ranked first (Recall@1) and a high similarity score; a different person scores
  lower; the application restarts and the identity and the waiting faces persist; one click places the
  face. Every result's recorded runtime variant is the provider that was asked for first, so a silent
  fallback would fail.

## Findings worth recording

- A library's vector index lives in machine-local state under the space id. Test libraries built with
  seeded ids therefore share one index folder when they share a local state root, and the stale vectors
  made the first face abstain with `RETRIEVAL_INCOMPLETE` (candidates the index returned that SQLite
  refused). The system failed closed, as designed. Production ids are random, so libraries do not
  collide; the e2e test uses random ids and removes the index folders it makes. A leftover folder from
  earlier seeded runs remains in `local-models/state/indexes` and is harmless derived data.
- Under the abstain-only policy a face with candidates always waits for a person. This is assisted
  recognition (TST-057A); automatic recognition (TST-057B) stays blocked.

## Verification

- `uv run pytest -m e2e tests/e2e/test_real_host.py`: 1 passed on CPU, and 1 passed with
  `FACEIDENTIFY_ORT_GPU_DIR` and `FACEIDENTIFY_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider`.
- Full gate results are in the PR.

## Open issues / follow-ups

- Issue #80's installation-MISSING sweep (next change): a package removed from this machine marks its
  installation records `MISSING`, and registration reinstates them after verifying the bytes.
- A first-run installer for the model package and the policy file is part of M8 packaging.
