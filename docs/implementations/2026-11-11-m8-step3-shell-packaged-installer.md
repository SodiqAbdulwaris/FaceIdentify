# M8 step 3: the shell runs the packaged backend; the installer builds

- **Date:** 2026-11-11
- **Milestone / tracker IDs:** M8 step 3 · TST-078 (not `PASSING`: the first-run flow and the CI install are not built)
- **Status:** done
- **Commits:** PR (number added when opened): `feat(shell): run the packaged backend and default to Documents`

## What changed

- `desktop/src-tauri/src/config.rs`: `resolve_launch` picks how the backend starts: `FACEIDENTIFY_PYTHON`
  (development and tests), else the `faceidentify-backend` folder next to the installed application, else
  the repository's `.venv`. `default_library_root` moves the default library to `Documents\FaceIdentify`
  (decision R8) unless a library already exists at the old default, which keeps being used.
  `resolve_local_state_root` adds `FACEIDENTIFY_LOCAL_STATE_ROOT`, so an installer check can keep the
  machine-local state (models, policy, indexes) away from the real one.
- `sidecar.rs`, `lib.rs`: the launch is a program plus its arguments, so the frozen executable (no
  `-m` module) and the development Python use the same path.
- `tauri.conf.json`: NSIS target only. `tauri.installer.conf.json`: the frozen backend and the notices file
  as resources, per-user install, the WebView2 bootstrapper embedded.
- `packaging/build_installer.py`: notices, frozen backend, then Tauri; prints the installer's SHA-256.

## Verification (this machine, Windows 11)

- Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (26 passed, 1
  ignored) and `npx tauri build --debug --no-bundle` pass. Backend and frontend are untouched.
- `uv run --group build python packaging/build_installer.py` produced `FaceIdentify_0.1.0_x64-setup.exe`
  (55 MB, unsigned; SHA-256 of the build verified below is not a release hash).
- **Scratch install** (`/S /D=<temp>\app`; no earlier install, no `Documents\FaceIdentify` existed): exit
  0; the folder holds `faceidentify.exe`, `faceidentify-backend\faceidentify-backend.exe`,
  `THIRD_PARTY_NOTICES.md` and `uninstall.exe`.
- **Launch** with the library and the local state pointed at scratch folders and the development profile
  on: `faceidentify.exe` started `faceidentify-backend.exe` as its child, which created the SQLite library
  in the scratch library and the state folders in the scratch state root. Closing the window ended both
  processes within 6 s. The silent uninstall exited 0, removed the registry entry and the application
  files (`uninstall.exe` stays because of the `_?=` form) and left the library database in place.
- The owner's real state folder was not touched (its modification time is unchanged).

## Not verified

- The packaged app processing an image end to end with the real models: the weights are not available to
  an agent (step 8, the owner's machine). The frozen worker's request path was verified in step 2.
- A machine without the WebView2 runtime, a clean Windows install, SmartScreen behaviour (unsigned, R10).
- Whether Tauri's NSIS template shows a "delete application data" option in the interactive uninstaller:
  the silent uninstall does not, and the library lives outside the application-data folder either way (R8).

## Decisions (delegated, 2026-11-11; the owner may reverse any)

- `FACEIDENTIFY_LOCAL_STATE_ROOT` is read in every build, like `FACEIDENTIFY_LIBRARY_ROOT`: it chooses a
  folder the user already owns, so it opens no new capability, and the CI install check (step 7) needs it.

## Open issues / follow-ups

- The notices still do not list the Python runtime, OpenSSL, SQLite and Visual C++ runtime DLLs in the
  frozen folder (step 4).
