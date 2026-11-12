# Fix: a run whose acceptance failed is accepted on the loop's next turn

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M6 (the `FINALIZING` stall seen once in the D8 real-world check)
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(processing): retry a run's acceptance on the
  loop's next turn`

## What changed

`ProcessingRunner` (`backend/app/processing/runner.py`) remembers a run it executed whose acceptance
raised before it committed, and its next `run_once` accepts that run first, before claiming
anything. An acceptance refused for cause (`AcceptanceError`) is still settled `NOT_RESUMABLE` at
once, and an error after the commit (the index wake) is still only reported.

## Why

During the D8 check one video run sat `FINALIZING` for over 55 minutes on a heavily loaded machine,
and a restart's recovery accepted the same run in 30.7 s. Reading the runner explains how: an
acceptance that fails before committing (for example `DatabaseBusyError`, after three tries of SQLite's
5 s busy timeout while another loop holds the write lock) left the run `FINALIZING` "for recovery",
and recovery runs only at startup. Nothing in a running host tried again, and the video loop admits
no new video while a video run is `FINALIZING`, so every later video waited for a restart.

**What is shown and what is not.** The mechanism is reproduced deterministically: an acceptance that
fails once with `DatabaseBusyError` left the run `FINALIZING` across turns before this change (the
existing test `test_an_error_before_the_acceptance_commits_propagates_and_the_run_stays_finalizing`
pinned that), and is accepted on the next turn after it. That the D8 stall had this cause is likely
but not proven: it happened before a failing loop was logged (PR #257 added that), so no log shows
the acceptance's error. Since #257, a repeat would show `the processing loop failed
(DatabaseBusyError)` in the host log, and now it also recovers by itself.

Only the loop that executed a run retries its acceptance, so the two loops never race over one run;
accepting a run that did commit after all only finds it already accepted.

## Verification

- New `test_the_next_turn_accepts_a_run_whose_acceptance_failed_before_it_committed` (the first
  acceptance raises `DatabaseBusyError`, the next turn accepts that run before the second queued job,
  then the queue goes on); it fails with the retry removed (mutation run). New
  `test_a_failed_acceptance_that_did_commit_is_not_retried`.
- `uv run pytest -q tests/integration/test_processing_runner.py tests/integration/test_api_scheduler.py
  tests/recovery`: all passed (the recovery tests need `FACEIDENTIFY_FFMPEG_DIR`); ruff and mypy clean.
