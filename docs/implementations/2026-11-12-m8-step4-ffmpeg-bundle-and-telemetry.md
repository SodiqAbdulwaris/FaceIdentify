# M8 step 4: FFmpeg in the installer, hash-checked; ONNX Runtime telemetry off

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M8 step 4 · TST-079 (not `PASSING`: the first-run flow and the CI install are not built); the rollback tests of TST-080 and TST-082 move to step 5, where the model package installer they test is built
- **Status:** done (the rollback tests excepted, see below)
- **Commits:** PR (number added when opened): `feat(ml): turn ONNX Runtime telemetry off in the worker`, `feat(media): ship FFmpeg beside the app and check its hashes`, `build(installer): bundle FFmpeg and list the runtime in the notices`

## Why

M8 decisions R4 (the application is offline and local, so ONNX Runtime sends no trace events) and R5
(the pinned LGPL FFmpeg ships in the package, hash-checked at build and again before first use). M6 has
merged, so the video code and the pinned build exist.

## What changed

- `backend/ml/worker/onnx_session.py`: `ort.disable_telemetry_events()` is called before any session is created.
- `scripts/install_ffmpeg.py`: also writes `SHA256SUMS` (one `<sha-256>  <name>` line per file) into the folder it installs.
- `backend/infrastructure/media/video.py`: `media_tools` looks, in order, at `FACEIDENTIFY_FFMPEG_DIR`, the `ffmpeg` folder beside the
  frozen backend's own folder (an installed application), then `<local state>/runtime/ffmpeg`. Before the first use in a process every file in the folder's
  `SHA256SUMS` must match; a changed or missing file raises `MediaToolsMissingError`. A folder without a manifest (a hand-made development folder) is not checked.
- `packaging/build_installer.py`: downloads the pinned zip once into `build/ffmpeg-download` (the installer script verifies its SHA-256), unpacks it, passes
  the folder to the notices generator, and `tauri.installer.conf.json` ships it as the `ffmpeg` resource (`ffplay` is never in it).
- `scripts/generate_notices.py`: a `bundled` ecosystem lists CPython (with its licence text), the libraries its DLLs and extension modules link
  (OpenSSL, SQLite, libffi, expat, bzip2, XZ, the Visual C++ runtime) and, with `--ffmpeg <folder>`, FFmpeg with its `LICENSE.txt`.
  That closes the follow-up of step 2. A build that ships FFmpeg without its licence text fails.
- Tests: manifest accepted, changed or missing file refused, a name that points outside the folder refused, the packaged lookup order, the notices
  entries, and that telemetry is turned off before the session is created.

## Verification (this machine, Windows 11)

- Backend gate with the pinned FFmpeg installed: see the PR description for the result.
- Built the installer (`packaging/build_installer.py`), installed it silently into a scratch folder: `faceidentify-backend`, `ffmpeg` (with
  `ffmpeg.exe`, `ffprobe.exe`, the DLLs, `LICENSE.txt` and `SHA256SUMS`), `THIRD_PARTY_NOTICES.md`, `faceidentify.exe`, `uninstall.exe`.
- Drove the **installed** backend on the development profile with scratch library and state folders: `READY`; a generated PNG imported and
  processed to `COMPLETED`; a one-second MP4 made with the **shipped** `ffmpeg.exe` imported (the shipped `ffprobe.exe` read it, after the hash check);
  the process stopped with exit code 0 when its stdin closed. Silent uninstall exited 0 and removed the registry entry. The real state folder was untouched.

## Not verified

- Processing with the real `buffalo_l` models (the development profile uses the fake perception): step 8, the owner's machine.
- The installer-time hash check protects against damage and a swapped file in the folder; it is not a defence against someone who can also edit `SHA256SUMS` (they could replace the program itself).

## Decisions (delegated, 2026-11-12; the owner may reverse any)

- The shipped FFmpeg wins over the machine-local one, so a build always uses the build it was tested with.
- The rollback tests of the plan's step 4 (a corrupted runtime or model package is refused and the previous configuration keeps working) are written with the
  model package installer in step 5: the runtime package store already refuses a wrong-hash package, and the installer is what they exercise.

## Open issues / follow-ups

- Bundled FFmpeg is the only runtime binary the installer carries beyond the frozen folder; when M7 lands (cameras) the only packaging follow-up is re-freezing (a rebuild).
