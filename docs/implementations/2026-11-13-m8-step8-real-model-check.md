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

## Not verified

- The live camera (the shutter is closed; the live check stays the owner's) and adding "Integrated Camera" in the app.
- The first-run screens driven by a person with the real native dialogs (the page itself was read from the installed web view earlier; the API calls it makes were run here).
- A second clean machine, WebView2 absent, SmartScreen (unsigned), and an installer upgrade between two different revisions.
- The process-tree check beyond the connection count (a full SEC-005 run), and activation rollback after a failed self-check (TST-082).
- A GPU that DirectML cannot use (this machine's works), so the visible GPU-to-CPU fallback on another machine.
