# 02 The four programs

## 1. What this is and why it exists

When the app runs, **four separate programs** are involved. A running program with its own private
memory is called a **process**. Learn these four names; everything else in the codebase hangs on them.

```
 you
  |  clicks, types
  v
+--------------------------+      starts and stops       +-------------------------------+
| 1. THE SHELL             | --------------------------> | 2. THE BACKEND (the "sidecar") |
|    Rust + Tauri          |  gives it a secret token    |    Python + FastAPI            |
|    desktop/src-tauri     |  reads one line back        |    backend/api/host.py         |
|  shows a window          |                             |  HTTP + WebSocket on           |
+-----------+--------------+                             |  127.0.0.1:<random port>       |
            |  loads                                     +---+------------------+---------+
            v                                                |                  |
+--------------------------+       HTTP requests with          |                  | starts and
| 3. THE FRONT END         | <--------------------------------+                  | supervises
|    TypeScript + React    |   the token; WebSocket events                       v
|    frontend/src          |                                      +----------------------------+
| runs inside the window   |                                      | 4. THE ML WORKER           |
+--------------------------+                                      |    Python + ONNX Runtime   |
                                                                  |    backend/ml/worker       |
                                                                  | runs the face models       |
                                                                  +----------------------------+
```

1. **The shell** (Rust, using a toolkit called **Tauri**) is what you double-click. It opens a window,
   picks the folder where your library lives, starts the backend, and stops it when you quit.
2. **The backend** (Python, using a framework called **FastAPI**) is the real application. It owns the
   database, the files, the rules and the memory. It listens only on your own machine (`127.0.0.1`,
   called *loopback*), on a random port, and only answers requests that carry a secret token the shell
   generated for this launch.
3. **The front end** (TypeScript, using **React**) is the web page shown inside the window. It has no
   memory of its own: it asks the backend for everything and tells the backend what you did.
4. **The ML worker** (Python, using **ONNX Runtime**) is a separate process that only runs the neural
   networks. It is separate so that a crash inside native model code can never corrupt your data: the
   backend notices, restarts it and carries on.

**Why a web page in a desktop window?** Building screens with web technology is faster and better
supported than building them natively, and Tauri gives a small, secure window to host them.
**Why Python for the real work?** The machine-learning libraries (ONNX Runtime, NumPy, image
libraries) live in Python. **Why Rust for the shell?** Tauri is written in Rust, and the shell is a
thin, careful piece that handles processes and secrets.

### Two profiles: what the worker does today

The backend runs in one of two **profiles** (see [profiles](../03-backend/architecture/04-profiles.md)):

- **development profile** [built]: a fake in-process "perception" stands in for the worker and the
  models. Started by `--development-profile`. A *debug* build of the shell passes it for you.
- **real profile** [built]: starts a real ML worker per plan and uses the installed `buffalo_l`
  package under a measured policy file. It is the host's default when the flag is absent, and a
  *release* build of the shell uses it. With no model package installed the app is `DEGRADED`
  (`runtime_package: UNAVAILABLE`) and refuses to process (`503`); with no usable policy it reports
  `processing_policy: UNAVAILABLE`. It never guesses.

## 2. Where it lives

| Program | Folder | Entry point |
|---|---|---|
| Shell | `desktop/src-tauri/src/` | `main.rs` calls `lib.rs` (`run`); `sidecar.rs` starts the backend |
| Backend | `backend/` | `python -m backend.api.host` = `backend/api/host.py` |
| Front end | `frontend/src/` | `main.tsx` mounts `app/App.tsx` |
| ML worker | `backend/ml/worker/` | `main.py`, started by `backend/ml/supervisor/` |

## 3. How they connect (the sidecar contract in six lines)

1. The shell generates a **token**: 32 random bytes from the operating system, written as URL-safe
   base64 (`generate_token` in `sidecar.rs`).
2. It starts `python -m backend.api.host --library-root ... --local-state-root ... --parent-pid <its own id> --stdin-lifeline`
   (plus `--development-profile` in debug builds). The token goes in the environment variable
   `FACEIDENTIFY_LAUNCH_TOKEN`, **never** on the command line, because other programs can read command
   lines.
3. The backend binds `127.0.0.1` on a free port and prints **one JSON line** to its standard output,
   the *handshake*: `{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":38733,"pid":592}`.
4. The shell reads that line, builds the connection `{ base_url, events_url, token }` and hands it to
   the web page when the page asks (`invoke('backend_status')`).
5. The page sends `Authorization: Bearer <token>` with every request and offers the token on the
   WebSocket (`/api/v1/events`). Without it every route answers `401`.
6. To stop, the shell closes the backend's standard input (the *lifeline*). If the shell dies, the
   pipe closes by itself, and `--parent-pid` is the second safety net.

The full story is in [05-desktop-shell](../05-desktop-shell/03-sidecar-contract.md) and
[host and startup](../03-backend/architecture/03-host-and-startup.md).

## 4. Try it

**Works with no models. Verified 2026-10-12.** You will play the shell by hand.

1. Make a token and a scratch library (bash; PowerShell form below):

   ```bash
   export FACEIDENTIFY_LAUNCH_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   mkdir -p ~/faceidentify-play/lib ~/faceidentify-play/state
   ```

   PowerShell (*unverified here, Windows not available*):

   ```powershell
   $env:FACEIDENTIFY_LAUNCH_TOKEN = uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   New-Item -ItemType Directory -Force "$HOME\faceidentify-play\lib","$HOME\faceidentify-play\state" | Out-Null
   ```

2. Start the backend in the foreground (leave this terminal open):

   ```bash
   uv run python -m backend.api.host --library-root ~/faceidentify-play/lib \
     --local-state-root ~/faceidentify-play/state --development-profile
   ```

   Expected: after a second or two, exactly one line such as
   `{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":38733,"pid":592}`.
   Your port and pid differ. Nothing else is printed to standard output. That line is the handshake.
3. In a **second** terminal (set `FACEIDENTIFY_LAUNCH_TOKEN` to the same value there, or paste it):

   ```bash
   curl -i http://127.0.0.1:PORT/readiness
   ```

   Expected: `HTTP/1.1 401 Unauthorized`, a `www-authenticate: Bearer` header and the one error shape
   `{"error":{"code":"UNAUTHORIZED",...}}`.

   ```bash
   curl -s -H "Authorization: Bearer $FACEIDENTIFY_LAUNCH_TOKEN" http://127.0.0.1:PORT/readiness
   ```

   Expected: `{"state":"READY","capabilities":{"database":"READY","storage":"READY","index":"READY","recovery":"READY","ml_worker":"NOT_CONFIGURED","scheduler":"READY"}}`.
   `ml_worker` is `NOT_CONFIGURED` because the development profile has no worker.
4. Stop the backend with Ctrl+C in the first terminal. Expected: it exits and returns to the prompt,
   on Linux with exit code 130 and a `KeyboardInterrupt` traceback on standard error. That traceback is
   noise from interrupting `asyncio`, not a fault: the operating system releases the library lock when
   the process ends, and the next start recovers whatever was open (that is the design, see
   [recovery](../03-backend/architecture/06-recovery.md)). A tidy stop is `kill -TERM <pid>` (the `pid`
   is in the handshake line), which lets uvicorn close the library first, or, as the shell does,
   closing the program's standard input when it was started with `--stdin-lifeline`.

You played the shell: you made the token, started the backend, read the handshake, and used the token.

## 5. Change it

Safe experiment: restart the backend with a **different** token (run step 1 again) and repeat the
`curl` with the old token. Expected: `401`. The token lasts for one launch. The tests that prove this
are in `tests/contracts/test_api_launch_capability.py`:

```bash
uv run pytest tests/contracts/test_api_launch_capability.py -q
```

Expected: all pass.

## 6. Break it on purpose

Set the token to something too short, then start the host:

```bash
export FACEIDENTIFY_LAUNCH_TOKEN=short
uv run python -m backend.api.host --library-root ~/faceidentify-play/lib --local-state-root ~/faceidentify-play/state
```

Expected: `backend.api.host: the launch token is not URL-safe base64` and exit code 2 (verified by
calling `validate_launch_token("short")`, which raises `LaunchTokenError`). The error never prints the
token itself.

## 7. Exercises

1. Which of the four programs owns the database? Which one shows buttons?
2. Why is the token passed in the environment and not as `--token ...`?
3. What happens to the backend if the shell crashes?
4. Why is the ML worker a separate process instead of a function the backend calls?

**Answers**

1. The backend owns the database; the front end shows the buttons.
2. Command lines are visible to other programs on the machine; an environment is private to the
   process (and is never logged).
3. The pipe on its standard input closes, the backend notices and stops gracefully; `--parent-pid` is a
   second check.
4. Native model code can crash, hang or leak memory; isolation means a crash costs one request and a
   restart, never the library.

## 8. Related files

- Previous: [01 What it is](01-what-it-is.md) · Next: [03 Authoritative and derived data](03-authoritative-and-derived.md)
- [`backend/api/host.py`](../../../backend/api/host.py), [`desktop/src-tauri/src/sidecar.rs`](../../../desktop/src-tauri/src/sidecar.rs)
- [The sidecar contract](../05-desktop-shell/03-sidecar-contract.md)
