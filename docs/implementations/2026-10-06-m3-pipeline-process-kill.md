# M3.2: the pipeline in a real process, killed at each stage

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M3.2 · TST-043, TST-030
- **Status:** done (planted perception; real weights remain blocked on issue #69)
- **Commits:** PR (this change): `test(recovery): kill the real pipeline at each stage`

## What changed

Test-only. `tests/recovery/test_pipeline_process_kill.py` starts a real child process
(`tests/fixtures/pipeline_child.py`) that opens the library through `open_library`, runs one image
through the real pipeline with planted perception, and parks at a named stage. The parent kills the
child's whole process tree and reopens the library. Stages and what the next start must do:

| Killed at | State left | Next start |
|---|---|---|
| `represent` | one PENDING observation, embedding in flight | run, job and segment `INTERRUPTED`; output private; nothing requeued |
| `decide` | observation and representation PENDING, no FINAL | the same |
| `final` | FINAL written, run `FINALIZING` | accepted once, without perception, index applied |
| `accept-open` | acceptance written but its transaction never committed | rolled back by the kill; then accepted once |
| `accepted` | committed, index not applied | nothing to accept; the queued ADD is applied |

After a pre-FINAL crash the test also retries (a new Job and Run through `RetryProcessingUseCase`),
runs it to completion and checks one identity and occurrence, the old attempt's observation still
PENDING, and one vector in the index. Every case ends with a further start that repairs nothing.

The pipeline helpers moved from the end-to-end test to `tests/fixtures/pipeline.py` (shared by both,
and by the child); the end-to-end test now asserts perception is untouched after the restart.

## Why

Persistence section 30: a crash after FINAL completes acceptance without rerunning ML and without
duplicate memory; a crash before it never exposes private output (TST-043, TST-030). The in-process
matrix stops a function; this kills a real process.

## Decisions

None. Planted perception only, no weights.

## Verification

- Full gate (2026-10-06): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,359 passed in 286.51s, 100% line and branch coverage**.
- Mutations (restored byte-identically): skipping recovery's FINALIZING acceptance, skipping the
  index passes, and skipping the interruption each fail a kill test. Accepting after the interruption
  step instead of before survives by design: the FINALIZING-job exemption makes the order
  irrelevant, so no artificial test was added.

## Open issues / follow-ups

- Real weights, and a real worker process in the loop, wait for issue #69.
- TST-043 stays `IN_PROGRESS` until then.
