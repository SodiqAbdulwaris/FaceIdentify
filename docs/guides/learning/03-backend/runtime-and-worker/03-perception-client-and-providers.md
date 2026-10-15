# Runtime 03 The perception client and providers

## 1. What this is and why it exists

The processing job asks for two things in a fixed order: **detect** the faces of one image, then **represent** them. The
`PerceptionClient` runs those against the worker according to a **plan** (the variants it may use, in the caller's order of
preference), and it is where the backend makes the *one* narrow decision the worker refuses to make: whether to move on to the
next variant. It also reports which variant **actually ran**, which becomes the output's provenance.

## 2. Where it lives

| Thing | Where |
|---|---|
| The client | `PerceptionClient` in `backend/app/runtime/perception_client.py` |
| Turning the catalog and installed packages into a plan | `backend/app/runtime/worker_config.py` |
| One client per job, one worker per plan | `ClientPool` in `backend/api/real.py` |
| The providers setting | `providers_from` and `FACEIDENTIFY_PROVIDERS` in `backend/api/real.py` |
| Tests | `tests/integration/test_runtime_perception_client.py`, `test_runtime_worker_config.py` |

## 3. How it works

- **Narrow fallback.** Only two worker error codes mean "this execution provider cannot run here":
  `RUNTIME_VARIANT_NOT_AVAILABLE` and `RUNTIME_INITIALIZATION_FAILED`. Those move to the next planned variant. **Every other
  error is the operation's own failure** (a model that will not load, bad input, an inference error) and is raised, because
  trying another variant would hide it. When every variant of a stage is ruled out the answer is `RuntimeUnavailableError`
  with a reason per variant: never a substitute.
- **A ruled-out variant stays out** for the life of the client, so one run does not bounce between providers.
- **Provenance**: the result carries `ran`, the variant that executed, and a list of `fallbacks`. The executor records them
  on the segment, observation and representation ([executing an image](../processing/03-executing-an-image.md)).
- **One thread, one client** (a record that is not locked); a **fresh client for every job** so each job records its own
  fallbacks, while the *worker* is kept for the process lifetime because loading models takes seconds.
- **The plan** (`worker_config.py`) offers a variant only if it can run *here and now*: the installation record points inside
  this machine's runtime-package directory; the path is a file the installed package's manifest declares, with the
  manifest's digest; the package still verifies against its manifest; and the variant's provider is one the caller allows. A
  missing required component is `RuntimeUnavailableError`; the **detector and embedder are required separately**.
- **Providers**: `FACEIDENTIFY_PROVIDERS` is a comma list in order of preference (default DirectML then the CPU on Windows, the CPU alone elsewhere). `allow_fallback` is on only
  when more than one is named, so a lone accelerator never silently becomes the CPU.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. The providers setting (the function reads a dict, so no environment change is needed):

   ```bash
   uv run python - <<'EOF'
   from backend.api.real import providers_from
   for env in ({}, {"FACEIDENTIFY_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider"},
               {"FACEIDENTIFY_PROVIDERS": "cuda"}):
       try:
           print(env, "->", providers_from(env))
       except ValueError as error:
           print(env, "-> ValueError:", error)
   EOF
   ```

   Observed: `{}` gives `('DmlExecutionProvider', 'CPUExecutionProvider')` on Windows (`('CPUExecutionProvider',)` elsewhere); the two-provider list is kept in order; `"cuda"` is
   `ValueError: FACEIDENTIFY_PROVIDERS must list distinct known providers, not 'cuda'`. A duplicate also fails. A typo never
   means CPU.
2. The behaviour tests: `uv run pytest tests/integration/test_runtime_perception_client.py tests/integration/test_runtime_worker_config.py -q`.
   Expected: `72 passed` (observed).
3. *(Needs the local models, unverified here.)* `FACEIDENTIFY_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider` with a GPU build
   would let a CUDA failure fall back; the fallback is then visible in the run's segments (`ended_reason` `FALLBACK`) and in the
   processing run response.

## 5. Change it

To allow another error code to trigger fallback you would change a policy decision, not just code: write the failing test
(a fake worker answering that code), get an owner decision (the narrowness is deliberate), then change the set of codes.
Adding a provider name means `KNOWN_PROVIDERS` in `real.py` and the worker's provider handling.

## 6. Break it on purpose

Add `INFERENCE_FAILED` to the fallback codes in a scratch edit and run the client tests: a test that asserts an inference failure
is raised, not retried on another variant, fails. Restore with `git restore`.

## 7. Exercises

1. Which two codes cause fallback?
2. Why is a failing inference not retried on the CPU?
3. What is `ran`, and who uses it?
4. Why a fresh client per job but a long-lived worker?

**Answers**

1. `RUNTIME_VARIANT_NOT_AVAILABLE` and `RUNTIME_INITIALIZATION_FAILED`.
2. It is the operation's own failure; a different variant would hide a real problem.
3. The variant that executed; the writer records it as provenance.
4. Per-job clients record per-job fallbacks; the worker holds loaded models, which take seconds to load.

## 8. Related files

- Previous: [02 The supervisor](02-supervisor.md) · Next: [04 Packages and the catalog](04-packages-and-catalog.md)
- [`backend/app/runtime/perception_client.py`](../../../../../backend/app/runtime/perception_client.py), [profiles](../architecture/04-profiles.md)
