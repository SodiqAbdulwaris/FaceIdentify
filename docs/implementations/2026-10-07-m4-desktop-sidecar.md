# M4 W6: the Tauri shell starts, serves to and stops the backend

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W6 · TST-047 (desktop half)
- **Status:** done for the shell's backend management; the web view's use of it is W7; packaging the Python runtime is M8
- **Commits:** PR (this change): `feat(desktop): start and stop the backend sidecar`

## What changed

- `desktop/src-tauri/src/sidecar.rs` (new), the shell's side of the 2026-10-06 handshake contract:
  - a fresh 256-bit token from the operating system's random source (URL-safe base64, no padding),
    passed **only** in the environment (`FACEIDENTIFY_LAUNCH_TOKEN`), never in the arguments (tested);
  - the host is started as `python -m backend.api.host --library-root … --local-state-root …
    --parent-pid <shell pid> --stdin-lifeline` (plus `--development-profile` when configured), with
    stdin/stdout/stderr piped and no console window on Windows;
  - the one JSON handshake line is read with a timeout and **validated**: schema version 1, protocol
    `faceidentify.v1`, host exactly `127.0.0.1`, a real port. Anything else is refused and the child
    ended; a host that never reports, exits early or prints nonsense is ended and reported (and
    verified not left running);
  - `stop` closes the pipe (the host's `--stdin-lifeline`), waits up to a grace period for the host to
    close the library, and ends it only if it did not;
  - the host's stderr is forwarded to the shell's log and its stdout kept drained, both read as bytes
    (text in a Windows code page is shown with replacement characters and never ends the reading,
    which would let a full pipe block the child);
- `desktop/src-tauri/src/config.rs` (new): the shell owns where things are. The library root is the
  environment (`FACEIDENTIFY_LIBRARY_ROOT`), else the user's saved choice (`shell.json` in the app
  config directory; an unreadable or relative record means "nothing saved"), else
  `<app data>/library`. Python is `FACEIDENTIFY_PYTHON` or the repository's `.venv` (development;
  the packaged runtime is M8). The development profile follows the build (on in debug, off in
  release) unless `FACEIDENTIFY_DEVELOPMENT_PROFILE` says otherwise.
- `desktop/src-tauri/src/lib.rs`: a single instance (a second launch focuses the first window), the
  dialog plugin, and the backend started on a worker thread after the window exists. Three commands
  for the web view: `backend_status` (`starting`, `ready` with the connection - base URL, events URL,
  token, protocol - or `failed` with a message), `library_info`, and `choose_library` (a native folder
  picker; the choice is saved and used at the next start). On exit the shell stops the backend
  cleanly.
- `.github/workflows/ci.yml`: a `desktop` job on `windows-latest` runs `cargo fmt --check`, clippy with
  warnings denied, `cargo test`, and the test that starts the **real** backend with the development
  profile and checks the clean stop (it needs the repository's Python environment, so it is `#[ignore]`
  elsewhere).

## Why

W6 of the completion plan: the desktop shell is the only thing that starts the backend, so the
handshake, the token handling and the clean shutdown have to be right before the web view builds on
them.

## Decisions

None new beyond the 2026-10-06 handshake decision, which is implemented as written. Not built, by
choice: switching the library while the backend runs (the choice applies at the next start), and a
supervisor that restarts a crashed backend (the web view shows `failed`; a restart button is W7 if
the screens need one).

## Verification

- `cargo test` (18, plus 1 ignored): token shape and uniqueness; the handshake accepted only when
  loopback, on a port, and our protocol and version; the token only in the environment, the exact
  arguments, the working directory, the profile flag only when configured; a started stand-in host
  reports its connection and leaves cleanly when its pipe is closed; one that ignores the request is
  ended after the grace period; a host that never reports, exits early (with its exit code), prints
  nonsense or cannot be spawned is reported, and a host that failed to start is verified not left
  running; the lossy line reading; the config rules (environment over saved over default, saving replaces the old choice atomically, broken/relative/missing saved
  record, Python and profile resolution). The ignored test starts the **real** Python host with the
  development profile through this contract and stops it cleanly (4 s).
- Mutation probes (19 by hand on the handshake checks, the token size, the arguments, the profile
  flag, the stop path, the connection URLs and the config rules): all killed after one test was added
  (a failed start leaves no process behind).
- `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings` are clean; the scaffold's
  `build.rs` and `main.rs` were reformatted to rustfmt's default.
- Not run here: the interactive window (`npm run tauri dev`); the next change builds the web view's
  side and the end-to-end test.
