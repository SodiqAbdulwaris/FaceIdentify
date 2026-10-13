# Desktop shell 04 The library folder, dialogs and the window's limits

## 1. What this is and why it exists

Two questions: **where does my data live**, and **what is the page allowed to reach**. The shell owns both answers: it chooses the
library folder and the private state folder, and it fences the page with a Content Security Policy.

## 2. Where it lives

| Thing | Where |
|---|---|
| Library root choice (environment, saved choice, default) | `config::resolve_library_root`, `load_saved_library_root`, `save_library_root` in `config.rs` |
| The saved choice | `shell.json` in the app config directory (one small JSON file, written atomically) |
| The local state root | `<app local data dir>/state` (`start_backend` in `lib.rs`) |
| Environment overrides | `FACEIDENTIFY_LIBRARY_ROOT`, `FACEIDENTIFY_PYTHON`, `FACEIDENTIFY_DEVELOPMENT_PROFILE` (constants in `config.rs`) |
| The window's limits | `app.security.csp` in `desktop/src-tauri/tauri.conf.json` |

## 3. How it works

- **Library root** (the user's data: database and originals; the vector indexes live under the local state root), first match wins: the environment variable
  `FACEIDENTIFY_LIBRARY_ROOT` (empty counts as unset) → the folder saved by `choose_library` (only if absolute; a broken or relative
  file means "nothing saved") → `<app data dir>/library`. The shell creates it if missing. A new choice takes effect **at the next start**: the
  library cannot change under a running backend.
- **Local state root** (`<app local data dir>/state`): machine-local things that must not travel with a library (installed model packages,
  the policy file). Two roots must not be nested; the host refuses nested or relative roots ([host lesson](../03-backend/architecture/03-host-and-startup.md)).
- **Python**: `FACEIDENTIFY_PYTHON`, else the repository's `.venv` (`Scripts\python.exe` on Windows, `bin/python` elsewhere). A packaged build will ship its own
  (not built yet: M8 in the code's comment).
- **Development profile**: on in debug builds, off in release; the variable `1`/`true` or `0`/`false` overrides; anything else lets the build decide
  (the profile guard in the library stops you from mixing, [profiles](../03-backend/architecture/04-profiles.md)).
- **The Content Security Policy** (`tauri.conf.json`): `default-src 'self'`; scripts only from the app itself, styles from the app plus inline styles (`style-src 'self' 'unsafe-inline'`);
  `connect-src` allows the app, Tauri's IPC, and `http://127.0.0.1:*` and `ws://127.0.0.1:*` (the loopback backend); `img-src` and `media-src` allow
  `blob:` (pictures are shown from object URLs) and the loopback backend. So even if page code were tricked, it could not send data to an
  arbitrary website.
- **Only paths cross** from dialogs to the page, never contents; the backend reads the file itself. The face-search route refuses network
  (UNC) paths ([face search](../03-backend/api/routes/face-search.md)).
- **One instance**: `tauri-plugin-single-instance` makes a second launch focus the first window, so two backends never fight for one library
  (the library lock is the second line of defence).

## 4. Try it

**Python side: verified. Rust side: unverified here.**

The same resolution order, on the Python side, is visible in the two roots the host accepts:

```bash
mkdir -p /tmp/lib-demo /tmp/state-demo
FACEIDENTIFY_LAUNCH_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  timeout 5 uv run python -m backend.api.host --library-root /tmp/lib-demo --local-state-root /tmp/state-demo --development-profile
```

Observed: one JSON handshake line (`{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":44151,"pid":14544}`; your port and pid differ), then the process runs until the timeout ends it (exit code 124). (If you pipe the output through `grep`, the line may not appear before `timeout` kills it, because `grep` buffers.) Delete
`/tmp/lib-demo /tmp/state-demo` afterwards. The shell's own choice logic is `config.rs`: read its eight tests
(`the_environment_beats_the_saved_choice_which_beats_the_default` is the specification of the paragraph above). `cargo test` would run them
(*not run here*).

## 5. Change it

Changing the default folder is a one-line change in `setup` (`app_data_dir()?.join("library")`), but it is a user-data decision: existing
users would "lose" their library unless it is migrated. That needs an owner decision and a migration note, so it is not a casual edit. Changing the
CSP is a security change: widen `connect-src` only for a documented need, and say so in the implementation entry.

## 6. Break it on purpose

Put a relative path in `shell.json` (`{"library_root":"relative/path"}`): `load_saved_library_root` ignores it and the default applies (this is the
`nothing_saved_a_broken_file_or_a_relative_path_all_mean_use_the_default` test). Safe defaults beat guessing.

## 7. Exercises

1. In what order is the library root chosen?
2. Why is a new choice applied only at the next start?
3. What stops the page from sending data to a website?

**Answers**

1. Environment variable, then the saved choice, then the default under the app data directory.
2. A running backend holds the library lock and open files; swapping the library underneath it is unsupported.
3. The Content Security Policy: `connect-src` lists only the app, IPC and the loopback backend.

## 8. Related files

- Previous: [03](03-sidecar-contract.md) · Next: [05 Build and test the shell](05-build-and-test-the-shell.md)
- [`desktop/src-tauri/tauri.conf.json`](../../../desktop/src-tauri/tauri.conf.json), [storage roots](../02-data-and-storage/08-storage-roots-and-artifacts.md)
