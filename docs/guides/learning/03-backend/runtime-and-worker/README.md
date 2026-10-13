# Runtime and worker: the models and the process that runs them

The backend never loads a model itself. A separate, long-lived **ML worker process** does, behind a small message protocol, and
the backend decides everything that needs judgement (which provider, whether to fall back, what to record).

| Lesson | Teaches |
|---|---|
| [01 The worker and its messages](01-worker-and-messages.md) | the protocol, the loop, shared memory, error codes |
| [02 The supervisor](02-supervisor.md) | starting, watching and restarting the worker |
| [03 The perception client and providers](03-perception-client-and-providers.md) | detect/represent, variants, fallback, provenance |
| [04 Packages and the catalog](04-packages-and-catalog.md) | manifests, atomic install, registration into the catalog |

**Works with no models. Verified 2026-10-12 (Linux).** The tests for this folder:

```bash
uv run pytest tests/integration/test_ml_worker_loop.py tests/contracts/test_ml_ipc_contract.py tests/unit/test_runtime_manifest.py \
  tests/integration/test_ml_perception_handlers.py tests/integration/test_runtime_perception_client.py \
  tests/integration/test_runtime_worker_config.py tests/integration/test_runtime_registration.py \
  tests/unit/test_reference_package.py tests/integration/test_runtime_sweep.py -q
```

Observed: `304 + 96 + 117` tests across the three groups, all passed. Two test files **fail on Linux for platform reasons** and
are meant for Windows: `tests/integration/test_ml_supervisor.py` (11 tests call the Windows command `tasklist`:
`FileNotFoundError: 'tasklist'`) and three race tests in `tests/integration/test_runtime_package_store.py` (a directory
rename over an empty directory fails on Windows and succeeds on Linux: `OSError: [Errno 39] Directory not empty`). They are
recorded as findings, not fixed here (documentation-only task).

Tests that need the real models are local only (`tests/e2e/test_real_models.py`, `-m e2e`). Back to [the backend](../README.md).
