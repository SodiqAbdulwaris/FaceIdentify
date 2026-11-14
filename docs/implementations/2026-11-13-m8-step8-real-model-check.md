# M8 step 8: the real-model check of the installed build, and the defect it found

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M8 step 8 · TST-078, TST-079 (the installed build with the real models)
- **Status:** done for what is listed as verified; see the open items
- **Commits:** PR (number added when opened): `fix(host): keep the stdin pipe away from the spawned ML worker`, and its docs commit

## Delegated decision (2026-11-13; the owner may reverse it)

The owner told the orchestrating session on 2026-11-09 that it had full access to do anything and asked for the project to be finished and tested, and on
2026-11-12 to install whatever is needed. The `buffalo_l` weights and the evaluation pictures are already on this machine in Git-ignored folders, so this
check ran the installed build against them with **scratch library and state roots**, copied the weights only into the scratch state (deleted with it), wrote
nothing to the owner's real folders (the real state folder's modification time is unchanged), and records **counts and outcomes only**.

## The defect

On the first run the real worker never started in an installed (or any standalone) backend: processing ended `FAILED` after about 120 s (`WorkerFailedError`, `ml_worker UNAVAILABLE`),
although the worker alone and the in-process end-to-end test passed. Bisecting showed it only happens with `--stdin-lifeline`, which the shell always passes. The lifeline thread
blocks reading the standard-input pipe, and the ML worker is spawned from the same process and **inherited that pipe**, which stops a child from starting on Windows. Every packaged run
would have been affected.

- `backend/api/host.py` `stdin_lifeline()`: reads through a private copy of the pipe (`os.dup`, not inheritable) and leaves the null device as standard input, and closes the copy when the pipe ends.
- Tests: an in-process test of the copy and the null device; a subprocess regression test that spawns a child from a process holding the lifeline (it hung for a minute without the fix and passes with it).
  The development profile never found this because its fake perception has no worker process.

## Verification (this machine, Windows 11, RTX 4070 Laptop GPU; installer built from this branch, scratch install)

- First run: the models were refused when the files were not the selected ones (`MODEL_SOURCE_INVALID`), installed from the weights folder (every file checked against the table), readiness went from `UNAVAILABLE` to `READY`
  for both the models and the policy; Assisted was saved and the policy file is exactly the abstain-only policy; Automatic later saved exactly the approved policy. No policy was overwritten: the scratch state started without one.
- Real processing: 4 pictures imported and processed, all `COMPLETED`; in Assisted 3 pictures left faces waiting for the user (1, 10 and 1 unresolved faces) and 1 face was placed;
  one identity was named; a face search by a picture of the same person ranked the named person first; a later picture of the same person was processed `COMPLETED` but its face was **not** placed automatically (it waits: not a failure).
- Reprocessing one source `COMPLETED`; a two-second video made by the shipped FFmpeg from a still imported and processed `COMPLETED` with 1 appearance.
- **Providers:** by default readiness showed `DmlExecutionProvider` (no fallback) and `ml_worker READY`; with `FACEIDENTIFY_PROVIDERS=CPUExecutionProvider` the same library reprocessed `COMPLETED` on `CPUExecutionProvider`.
- **Network:** 0 established connections outside loopback from the backend process in both runs (a count taken after processing).
- Clean stop: exit code 0 both times; silent uninstall exit 0 and the scratch library kept; the camera device list answered with 1 device.

## The whole check again on the exact build from `main` with the fix (installer built from `main`; launched as the shell launches it)

The backend was started with `--parent-pid`, `--allow-origin` for the web view's origins, a piped stdin, stdout and stderr and no console window, as `sidecar.rs` does. Everything above held, and:

- 4 pictures `COMPLETED` (real models, `DmlExecutionProvider` on the RTX 4070, no fallback, worker `READY`); a face search ranked the named person first; reprocess `COMPLETED`; a two-second video `COMPLETED` with 1 appearance;
  forced CPU reprocessed `COMPLETED` on `CPUExecutionProvider`; 0 outbound connections in both runs; both stops exit 0; uninstall kept the library.
- **Camera:** the device list returned 1 device; "Integrated Camera" was added, a session started, **32 frames counted and 0 dropped in 8 seconds** (the camera works; 0 encounters, nothing kept), the session stopped; the scratch library was deleted.
- A later picture of the named person was processed `COMPLETED` but not placed automatically: at the owner-approved operating point (0.45, margin 0.10) a face that is not clear enough waits. That is the policy, not a failure.

## What else only the shell exercises (audit)

| Path | Checked | How |
|---|---|---|
| `--stdin-lifeline` with a spawned worker | **found a defect, fixed** | the installed run; regression tests in `test_api_host.py` and now in the frozen CI job (below) |
| `--parent-pid` watching | no problem | the second real run passed it; the host stopped cleanly |
| `--allow-origin` | no problem | passed in the second real run; CORS is unit-tested |
| no console window (`CREATE_NO_WINDOW`) for the host, the worker and FFmpeg | no problem | the second real run used it for the host; the worker, the video and the camera session ran under it |
| piped stdout and stderr | no problem | the shell drains stderr and reads one line of stdout; the worker writes to stderr only |

Result of the new check locally: `uv run python packaging/check_frozen_backend.py build/dist/faceidentify-backend` on a frozen build of this branch gave `READY`, exit 0 and a worker detection count of 1 with standard input held open.

CI-safe regression: `packaging/frozen_entry.py --probe-worker` now starts the host's `stdin_lifeline()` before it spawns the worker, and `check_frozen_backend.py` keeps the probe's standard input open, so the `Frozen backend` job spawns a worker from a process holding the lifeline.

## Not verified

- A person watching the live camera preview (the check counted frames only).
- The first-run screens driven by a person with the real native dialogs (the page itself was read from the installed web view earlier; the API calls it makes were run here).
- A second clean machine, WebView2 absent, SmartScreen (unsigned), and an installer upgrade between two different revisions.
- The process-tree check beyond the connection count (a full SEC-005 run), and activation rollback after a failed self-check (TST-082).
- A GPU that DirectML cannot use (this machine's works), so the visible GPU-to-CPU fallback on another machine.
