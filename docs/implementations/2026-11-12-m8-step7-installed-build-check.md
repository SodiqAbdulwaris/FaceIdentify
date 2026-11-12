# M8 step 7: the installed-build check and the installer CI job

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M8 step 7 (a, and part of b) · TST-078, TST-079 (not `PASSING`: the first-run flow and the real-model check are not built)
- **Status:** done for the installed-build check; the CI job is untested until it runs (see below)
- **Commits:** PR (number added when opened): `test(installer): check an installed build and add an installer job`, `test(installer): check both provider paths of the frozen build`

## Why

M8 step 7 and the owner's requirement of 2026-11-12 (use a supported GPU, else the CPU, no manual step): the installer is only
as good as what is checked on the installed files, and the check must be repeatable on a clean machine, not only by hand.

## What changed

- `packaging/check_installed.py <installation folder>`: starts the **installed** backend on the development profile with a scratch
  library and state (no weights, no real folders), and checks: the notices file and FFmpeg's `SHA256SUMS` are installed; `READY`; a
  generated image imported and processed to `COMPLETED`; a one-second video made by the **shipped** `ffmpeg.exe` imported (the shipped
  `ffprobe.exe` is found and its hashes match); the frozen executable decodes that video's frames; both provider paths (below); `DirectML.dll` is in the frozen folder; and the
  backend stops with exit code 0 when its standard input closes. It prints a JSON report and exits 1 on any failure.
- `packaging/frozen_entry.py`: `--probe-video <file>` (probe a video with the FFmpeg the frozen build finds, as an installed application does, and
  decode its sampled frames) and the `--probe-providers` output gains `selected`, the providers `FACEIDENTIFY_PROVIDERS` / the default would make
  the real profile try.
- `.github/workflows/installer.yml`: builds the installer on a Windows runner, installs it silently into a scratch folder, runs the check, uninstalls.
  It runs on demand and on pull requests that touch `packaging/`, `desktop/`, `backend/`, the FFmpeg and notices scripts or the lock file (the backend is frozen into the installer), not on every push, and uploads the check report as its one artifact.

## Verification (this machine, Windows 11, a DirectX 12 GPU)

- Built the installer from this branch (`packaging/build_installer.py`), installed it silently to a scratch folder, ran
  `check_installed.py`: `READY`, image run `COMPLETED`, video imported, 2 frames decoded from the 1 s clip by the frozen executable through the shipped
  FFmpeg, exit code 0; uninstalled (exit 0, registry entry gone). The real state folder was not touched.
- **Provider paths:** by default the build offers `DmlExecutionProvider` and `CPUExecutionProvider` in the process and in a spawned child and would try
  DirectML first, the CPU last; with `FACEIDENTIFY_PROVIDERS=CPUExecutionProvider` it would try only the CPU.

## Not verified

- **The video does not go through detection on the development profile**: its fake perception does not run a video job (the run fails the same way
  from source, so it is not a packaging fault). A video processed end to end needs the real models (step 8).
- **Which provider actually runs a model** (DirectML works on this GPU, falls back to the CPU on one that does not, and the adapter selection another
  session is changing in `onnx_session.py`): the check proves what the installed build offers and would try; running the models on each path is step 8.
- **The CI job has not run**: a workflow can only be dispatched from the default branch, so it first runs on pull requests that touch its paths,
  starting with this one. A runner usually has no DirectX 12 device, so the check does not demand DirectML there (it demands the selection order).
- A clean machine without the WebView2 runtime, SmartScreen (unsigned, R10).

## Decisions (delegated, 2026-11-12; the owner may reverse any)

- The job runs on pull requests that touch the installer's inputs, not on every push (the plan says on demand; a regression in the frozen build or the installer
  files would otherwise be found only when someone remembers to run it).
- The check uses the development profile so no weights are needed; the real-model check is a separate, local step (R12).

## Open issues / follow-ups

- The first-run flow (step 5) and the integrity and rollback tests; the installer-level upgrade, uninstall and reinstall tests of step 6 (they need a second installer
  build of a different revision, which the job above can run once step 5 exists).
