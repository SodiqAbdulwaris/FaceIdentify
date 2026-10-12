# Desktop shell 03 The sidecar contract

## 1. What this is and why it exists

A **sidecar** is a program the shell starts and supervises. Here it is `python -m backend.api.host`. The shell and the backend were
written separately, so their meeting is a short written contract with two ends. Both ends are shown here, and the Python end can be
exercised on any machine.

## 2. Where it lives

| End | File |
|---|---|
| Shell (start, handshake, stop) | `desktop/src-tauri/src/sidecar.rs` (`SidecarConfig::command`, `parse_handshake`, `generate_token`, `start`, `Sidecar::stop`) |
| Backend (host) | `backend/api/host.py` ([host lesson](../03-backend/architecture/03-host-and-startup.md)) |
| Spec | decided 2026-10-06; `IMPLEMENTATION_ARCHITECTURE.md` section 22 |
| Tests | Rust: 14 tests in `sidecar.rs` (including `the_command_carries_the_token_only_in_the_environment`); Python: `tests/integration/test_api_host.py` |

## 3. How it works

The shell, in order:

1. Makes a **token**: 32 random bytes from the operating system (`getrandom`), URL-safe base64 without padding: 43 characters.
2. Builds the command: `<python> -m backend.api.host --library-root <dir> --local-state-root <dir> --parent-pid <shell pid> --stdin-lifeline`
   plus one `--allow-origin <origin>` per web view origin (`http://tauri.localhost`, `https://tauri.localhost`, `tauri://localhost`, and in a debug build only
   `http://localhost:5173`; this is the CORS fix, [its entry](../../implementations/2026-10-12-webview-cors.md)) and `--development-profile` in debug builds. **The token goes only in the environment** (`FACEIDENTIFY_LAUNCH_TOKEN`), never an argument.
   On Windows it adds `CREATE_NO_WINDOW` so no console flashes up. Standard input, output and error are pipes.
3. Spawns it; a thread logs its stderr; another reads **one line** from stdout with a timeout (120 s in `lib.rs`).
4. Validates the line (`parse_handshake`): `schema_version` 1, `protocol` `faceidentify.v1`, `host` exactly `127.0.0.1`, a nonzero `port`. Anything else
   kills the child and fails. It then builds the `Connection` (`http://127.0.0.1:<port>`, `ws://127.0.0.1:<port>/api/v1/events`).
5. Keeps reading stdout forever (so the host never blocks on a full pipe) and **keeps the stdin pipe open**.
6. To stop: closes stdin (**the lifeline**); waits up to 10 s for the host to leave on its own; kills it if it does not.

The host, in order: reads and validates the token (exit code 2 if missing or short, before binding); binds `127.0.0.1` on a free port;
prints the one JSON line; serves; stops gracefully when stdin ends (`--stdin-lifeline`), or when the process with `--parent-pid` disappears
(polled every second), or on a signal. The two stop conditions cover a polite end (closing the pipe) and an impolite one (the shell
crashing), so a backend is never orphaned.

## 4. Try it

**Python end: works with no models. Verified 2026-10-12.** Play the shell's part with a script: [host and startup, Try it](../03-backend/architecture/03-host-and-startup.md)
(handshake, readiness, closing stdin gives exit code 0). The other stop condition, with a stand-in "shell" that is just a sleeping process:

```bash
uv run python - <<'EOF'
import json, os, secrets, subprocess, sys, tempfile, time, pathlib
play = pathlib.Path(tempfile.mkdtemp())
(play / "lib").mkdir(); (play / "state").mkdir()
parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
env = dict(os.environ, FACEIDENTIFY_LAUNCH_TOKEN=secrets.token_urlsafe(32))
host = subprocess.Popen([sys.executable, "-m", "backend.api.host", "--library-root", str(play / "lib"),
                         "--local-state-root", str(play / "state"), "--development-profile",
                         "--parent-pid", str(parent.pid)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, env=env, text=True)
print("handshake:", json.loads(host.stdout.readline())["protocol"])
time.sleep(1.0)
print("host running before parent dies:", host.poll() is None)
parent.kill(); parent.wait()
t = time.time()
print("host exit code after parent died:", host.wait(timeout=30), "in %.1fs" % (time.time() - t))
EOF
```

Observed: `handshake: faceidentify.v1`, `host running before parent dies: True`, then `host exit code after parent died: 0 in 1.3s`. Also observed
earlier in this work: a token of 31 bytes gives exit code 2 with `the launch token is not 256 bits`; closing stdin gives exit code 0.

**Rust end: unverified here** (`cargo test` not run; CI runs it on Windows). The tests to read in `sidecar.rs`:
`the_handshake_is_accepted_only_when_it_is_loopback_on_a_port_and_our_protocol`, `a_host_that_does_not_stop_when_asked_is_ended_after_the_grace_period`,
`a_host_that_never_reports_is_ended_and_reported`, `a_host_that_reports_nonsense_is_ended_and_refused`. Each uses a tiny **fake host** written to a temp
folder as a Python file, so the shell's logic is tested without the real backend; `the_real_host_starts_with_the_development_profile_and_stops_cleanly`
(ignored by default; `cargo test -- --ignored`) uses the real one.

## 5. Change it

A contract change (a new handshake field, a new flag) is made on **both ends in one change**: `parse_handshake` and its tests in
Rust, `host.py` and `test_api_host.py` in Python, a new `schema_version` if it breaks old shells, and the architecture document. Never
put the token in an argument or a log line.

## 6. Break it on purpose

Make the fake host print `"host":"0.0.0.0"` (as `parse_handshake`'s test does with `GOOD.replace("127.0.0.1","0.0.0.0")`): the shell refuses it.
The point: even our own backend is not trusted to say where it listens.

## 7. Exercises

1. Why does the token travel in the environment?
2. What are the two ways the host learns the shell is gone?
3. What does the shell do if the host does not answer within the timeout?

**Answers**

1. Other programs can read a command line; the environment is private to the child.
2. Standard input closing (`--stdin-lifeline`) and the shell's pid disappearing (`--parent-pid`).
3. Kills the child, waits for it, and reports the backend did not start.

## 8. Related files

- Previous: [02](02-tauri-commands.md) · Next: [04 Library folder and dialogs](04-library-folder-and-dialogs.md)
- [`desktop/src-tauri/src/sidecar.rs`](../../../desktop/src-tauri/src/sidecar.rs), [`backend/api/host.py`](../../../backend/api/host.py), [security](../03-backend/architecture/08-security.md)
