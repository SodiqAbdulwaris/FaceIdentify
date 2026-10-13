# Processing: how a photograph is processed

Processing turns an imported picture into faces, vectors and decisions without ever showing a half-finished result. The shape
is always the same: **request** (write intent down) → **claim** (the scheduler takes it) → **execute** (heavy work, private
output) → **accept** (one transaction makes the output real).

| Lesson | Teaches |
|---|---|
| [01 Jobs and runs](01-jobs-and-runs.md) | the request, the job, the run, the segment, and their states |
| [02 Configuration snapshots](02-configuration-snapshots.md) | the frozen settings each run carries |
| [03 Executing an image](03-executing-an-image.md) | decode, detect, embed, decide, write private output |
| [04 Checkpoints and acceptance](04-checkpoints-and-acceptance.md) | the FINAL checkpoint and the one authoritative moment |
| [05 Cancel and retry](05-cancel-and-retry.md) | stopping work and trying again |

The loop that drives this is in [architecture 05](../architecture/05-scheduler-and-runner.md); the decision made during execution
is in [recognition](../recognition/README.md).

**Works with no models. Verified 2026-10-12.** The tests for the whole folder:

```bash
uv run pytest tests/integration/test_process_source.py tests/integration/test_cancel_processing.py tests/integration/test_accept_processing_run.py tests/integration/test_execute_processing_job.py tests/integration/test_processing_runner.py -q
```

Observed: `209 passed`.
Back to [the backend](../README.md).
