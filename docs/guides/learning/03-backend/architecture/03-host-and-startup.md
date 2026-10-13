# Architecture 03 The host and startup

## 1. What this is and why it exists

The backend is started by a small program, the **host** (`python -m backend.api.host`), which binds a socket, prints one
line so the shell knows where to connect, serves, and shuts down cleanly when told. Inside the application a **lifespan**
opens the library *after* serving begins, so the shell can poll `/readiness` and see `INITIALIZING` instead of a refused
connection while migrations and recovery run. This lesson follows startup and shutdown step by step and shows how to
play the shell's part yourself.

## 2. Where it lives

| Thing | Where |
|---|---|
| The host: options, the token, the socket, the handshake, the stop conditions | `backend/api/host.py` (`parse_options`, `read_launch_token`, `serve`, `main`, `stdin_lifeline`, `parent_alive`) |
| The lifespan and lifecycle | `backend/api/startup.py` (`Backend`, `backend_lifespan`, `capabilities_from`, `LifecycleState`) |
| Opening the library | `backend/app/lifecycle.py` (`open_library`) |
| Startup recovery | `backend/app/recovery/startup.py` |
| Tests | `tests/integration/test_api_host.py`, `test_api_lifespan.py`, `test_library_lifecycle.py` |

## 3. How it works

### The host

1. Reads the token from `FACEIDENTIFY_LAUNCH_TOKEN` and validates it (a missing or malformed one stops the process with
   exit code 2 *before anything is bound*; the error never contains the token).
2. Builds the application (`create_backend_app`) with the profile's processing settings
   ([profiles](04-profiles.md)) and the provisional media limits.
3. Binds `127.0.0.1` on a free port the OS picks. On Windows the socket is made *exclusive* (`SO_EXCLUSIVEADDRUSE`) so another
   process cannot share the port.
4. Once uvicorn is accepting connections, prints **exactly one JSON line** to standard output, the handshake:
   `{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":37101,"pid":7609}`.
5. Serves until told to stop: the shell closes the program's standard input (**`--stdin-lifeline`**; on Windows there is no
   gentle signal, so closing a pipe is the clean request), or the shell's process disappears (**`--parent-pid`**, polled each
   second). Either sets `server.should_exit` and uvicorn shuts down gracefully.
6. Exit code `0` after a graceful stop, `2` for a bad launch.

### The lifespan

`backend_lifespan` stores the `Backend` on the app and starts `_boot()` as a background task, then yields (serving begins).
`_boot` runs `_open` in a worker thread:

1. `open_library(...)`: validate the root, take the **library lock**, lay out the folders, **migrate** (a database newer than
   this program is refused untouched), build the engine, storage manager, index coordinator and eraser, run **startup
   recovery**.
2. `claim_library_profile` records or checks the library's profile.
3. `capabilities_from(report)` turns the recovery report into the readiness capabilities.
4. A permanent deletion that a crash interrupted is **resumed** now (`PermanentSourceDeletion.resume`), before any request
   sees it.
5. The profile's `prepare` step runs (the development profile registers its fake catalog; the real profile registers installed
   packages).
6. The state becomes `READY`, or `DEGRADED` if any capability is `DEGRADED` or `UNAVAILABLE`. A failure at any step is
   `FAILED` with **only the exception class name** (never a path, never the token), and the process keeps answering so the
   shell can show why.
7. **Only then** the scheduler loop is created and started, so recovery and normal scheduling can never race.

### Readiness

`GET /readiness` returns `{"state": ..., "capabilities": {...}}` (and `failure`, and `missing_dependencies` when relevant).
States: `INITIALIZING`, `READY`, `DEGRADED` (something recoverable is outstanding; the library is usable), `FAILED`,
`SHUTTING_DOWN`. Capabilities: `database`, `storage`, `index`, `recovery`, `ml_worker`, `scheduler` (`READY`, `DEGRADED`,
`UNAVAILABLE`, `NOT_CONFIGURED`, `NOT_STARTED`, `STOPPED`...), plus `runtime_package`, `processing_policy`, `library_packages` on the
real profile. Routes that need the library answer `503 LIBRARY_UNAVAILABLE` until `READY` or `DEGRADED`.

### Shutdown

`_shutdown` sets `SHUTTING_DOWN`, stops the scheduler first (the job in flight finishes; nothing more is claimed), then the
profile's `close` (the real profile stops its workers), then closes the library (disposes the engine, releases the lock).

## 4. Try it

**Works with no models. Verified 2026-10-12.** Play the shell: start the host as a child process, read its handshake,
poll readiness, and stop it by closing its input. Save as `play_shell.py` anywhere and run
`uv run python play_shell.py` from the repository folder (the two folders it uses are created for you):

```python
import json, os, secrets, subprocess, sys, time, urllib.request, pathlib

play = pathlib.Path.home() / "faceidentify-play" / "boot"
(play / "lib").mkdir(parents=True, exist_ok=True)
(play / "state").mkdir(parents=True, exist_ok=True)

token = secrets.token_urlsafe(32)
env = dict(os.environ, FACEIDENTIFY_LAUNCH_TOKEN=token)
child = subprocess.Popen(
    [sys.executable, "-m", "backend.api.host", "--library-root", str(play / "lib"),
     "--local-state-root", str(play / "state"), "--development-profile", "--stdin-lifeline"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)

started = time.time()
handshake = json.loads(child.stdout.readline())              # blocks until the one line arrives
print("handshake after %.1fs" % (time.time() - started), handshake)

seen = []
while True:
    request = urllib.request.Request(f"http://127.0.0.1:{handshake['port']}/readiness",
                                     headers={"Authorization": "Bearer " + token})
    state = json.load(urllib.request.urlopen(request))
    key = (state["state"], state.get("capabilities", {}).get("scheduler"))
    if not seen or seen[-1][0] != key:
        seen.append((key, round(time.time() - started, 2)))
    if state["state"] != "INITIALIZING":
        break
    time.sleep(0.02)
print(seen)

child.stdin.close()                                           # the lifeline: ask for a clean stop
print("exit code after closing stdin:", child.wait(timeout=20))
```

Expected (observed): `handshake after 1.0s {'schema_version': 1, 'protocol': 'faceidentify.v1', 'host': '127.0.0.1', 'port': ..., 'pid': ...}`,
then a list like `[(('INITIALIZING', None), 1.09), (('INITIALIZING', 'NOT_CONFIGURED'), 1.36), (('READY', 'READY'), 1.39)]`
(the library was opening for a few hundred milliseconds after the handshake; times vary), then `exit code after closing stdin: 0`
in about three seconds. You just did what `desktop/src-tauri/src/sidecar.rs` does. Then:

1. Run the host tests: `uv run pytest tests/integration/test_api_host.py tests/integration/test_api_lifespan.py tests/integration/test_library_lifecycle.py -q`.
   Expected: pass.
2. See `FAILED` honestly: start a second backend on the same library folders as a running one: `/readiness` answers `{"state":"FAILED","failure":"LibraryLockedError"}`
   (observed; the class name only).

## 5. Change it

The operational limits are named, provisional constants in `host.py`: `PROVISIONAL_INDEX_RETRY` (3 attempts),
`PROVISIONAL_TRANSACTION_RETRY` (3 attempts, 0.1 s steps), `PROVISIONAL_INDEX_BATCH` (100), `PROVISIONAL_INDEX_PASSES` (10) and
`PARENT_POLL_SECONDS` (1.0). They are "to be set from benchmarks". A change of one needs the tests that cover its
behaviour (`test_api_host.py` for the poll, `test_index_coordinator.py` for the retry shape) and an implementation entry saying
why. The most common safe change is to a *capability*: a new thing `/readiness` should report goes through
`capabilities_from` (and a test that asserts the report), never through a new status route (owner decision 2026-10-07).

## 6. Break it on purpose

Run `uv run python -m backend.api.host --library-root ./lib --local-state-root ./lib/state` with the two folders nested:
the library refuses to open (`/readiness` `FAILED`, `InvalidLibraryRootError`: the two roots must not be nested). Give
a relative library root: also refused (a root must be absolute). Give a token of 31 bytes: exit code 2 and the message
`the launch token is not 256 bits`.

## 7. Exercises

1. Why does the host print the handshake only after the server is accepting connections?
2. Why is the library opened after serving starts instead of before?
3. What does `DEGRADED` mean for a client?
4. How does the host learn that the shell is gone?
5. In which order does shutdown happen and why?

**Answers**

1. The shell polls the address in the line; announcing a port nothing listens on yet would be a lie.
2. So the shell sees `INITIALIZING` while migrations and recovery run, instead of a refused connection.
3. The library is usable; something recoverable is outstanding (a locked file, an owed cleanup), and `/readiness` says what.
4. Standard input reaches end of file (`--stdin-lifeline`) or the parent process id disappears (`--parent-pid`).
5. Scheduler first (no new work), then the profile's workers, then the library and its lock, so nothing uses a closed library.

## 8. Related files

- Previous: [02 HTTP and FastAPI](02-http-and-fastapi.md) · Next: [04 Profiles](04-profiles.md)
- [`backend/api/host.py`](../../../../../backend/api/host.py), [`backend/api/startup.py`](../../../../../backend/api/startup.py)
- [The sidecar contract](../../05-desktop-shell/03-sidecar-contract.md), [recovery](06-recovery.md)
