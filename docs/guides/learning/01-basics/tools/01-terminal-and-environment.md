# Tools 01 The terminal and environment variables

## 1. What this is and why it exists

A **terminal** is a window where you type commands; a **shell** is the program inside it that
interprets them (PowerShell, or Git Bash, or bash on Linux and macOS). A command is a program name
followed by *arguments*. Flags start with `-` or `--`. Nearly everything in this guide is a command, so
this lesson makes you fluent in reading one. It also explains **environment variables**: named values a
program can read, which this project uses to pass secrets and options (never on the command line,
where other programs can see them).

## 2. Where it lives

The project's settings that come from the environment, and who reads them (all verified in the code on
2026-10-12):

| Variable | Read by | Meaning |
|---|---|---|
| `FACEIDENTIFY_LAUNCH_TOKEN` | `backend/api/host.py` (`read_launch_token`); set by `desktop/src-tauri/src/sidecar.rs` | the per-launch secret (43 characters of URL-safe base64) |
| `FACEIDENTIFY_LIBRARY_ROOT` | `backend/alembic/env.py` (command-line migrations) and the shell (`config.rs`) | the library folder, a development/test override |
| `FACEIDENTIFY_LOCAL_STATE_ROOT` | `backend/infrastructure/storage/library_root.py` | the machine-local folder (indexes, temp, logs) when `LOCALAPPDATA` is not available |
| `FACEIDENTIFY_PROVIDERS` | `backend/api/real.py` (`providers_from`) | comma list of ONNX Runtime providers to try, preferred first, for the real profile (default CPU) |
| `FACEIDENTIFY_ORT_GPU_DIR` | `backend/ml/worker/gpu_path.py` | folder of a machine-local `onnxruntime-gpu` so CUDA can run |
| `FACEIDENTIFY_PROVIDER` | `tests/e2e/test_real_models.py` | the single provider for that local-only test |
| `FACEIDENTIFY_PYTHON` | the shell (`config.rs`, `sidecar.rs`) | which Python runs the backend (default `.venv`) |
| `FACEIDENTIFY_DEVELOPMENT_PROFILE` | the shell (`config.rs`) | `1`/`true` forces the development profile, `0`/`false` the real one; unset follows the build (debug = development) |
| `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE` | `backend/infrastructure/db/downgrade_guard.py` | exactly `1` lets `alembic downgrade` run on a populated library (development only) |
| `FACEIDENTIFY_DATABASE_PATH` | `backend/alembic/env.py` | **deprecated** old way to point Alembic at a database file |
| `HYPOTHESIS_PROFILE` | `tests/conftest.py` | `ci` makes property tests deterministic, as CI does |

Notice that the **Python host has no environment variable for the library or the profile**: it takes
`--library-root`, `--local-state-root` and `--development-profile` on its command line, and only the
launch token from the environment. The *shell* is the program that reads `FACEIDENTIFY_LIBRARY_ROOT`
and `FACEIDENTIFY_DEVELOPMENT_PROFILE` and turns them into those arguments.

## 3. How it works

### Reading a command

```text
uv run pytest tests/unit -q -k reasoner
│  │   │      │          │  └── -k <text>: only tests whose name contains this
│  │   │      │          └───── -q: quiet output
│  │   │      └──────────────── an argument: where to look
│  │   └─────────────────────── the program uv runs
│  └─────────────────────────── a subcommand of uv
└────────────────────────────── the program
```

Useful moves: `cd folder` changes directory, `ls` (or `dir`) lists files, `pwd` prints where you are.
The shell's **history** (arrow up) repeats commands. **Tab** completes names. `Ctrl+C` stops a running
command.

### Pipes and redirects

`a | b` sends the output of `a` into `b`; `a > file` writes output to a file; `a 2> file` writes error
output (the second stream, "standard error", where warnings and tracebacks go). The backend host uses
exactly this split: **standard output carries only the one handshake line; everything else goes to
standard error.**

### Setting an environment variable

| | bash / Git Bash / zsh | PowerShell |
|---|---|---|
| for this terminal | `export NAME=value` | `$env:NAME = "value"` |
| for one command only | `NAME=value command` | (set it, run it, then `Remove-Item Env:NAME`) |
| read it | `echo "$NAME"` | `echo $env:NAME` |
| remove it | `unset NAME` | `Remove-Item Env:NAME` |
| a path with spaces | `"$HOME/my folder"` | `"$HOME\my folder"` |

An environment variable lasts only for that terminal window. Child programs inherit it.

## 4. Try it

**Works with no models. The bash column is verified (Linux, 2026-10-12); PowerShell is *unverified
here*.**

1. A child program sees what you export:

   ```bash
   export FACEIDENTIFY_DEMO=hello
   uv run python -c "import os; print(os.environ.get('FACEIDENTIFY_DEMO'))"
   ```

   Expected: `hello`. Then `unset FACEIDENTIFY_DEMO` and run the second line again: `None`.
2. A variable for one command only: `FACEIDENTIFY_DEMO=once uv run python -c "import os; print(os.environ.get('FACEIDENTIFY_DEMO'))"`
   prints `once`; the next plain command no longer has it.
3. Standard output versus standard error: start the backend with its output split into two files.

   ```bash
   export FACEIDENTIFY_LAUNCH_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   uv run python -m backend.api.host --library-root ~/faceidentify-play/lib \
     --local-state-root ~/faceidentify-play/state --development-profile > out.txt 2> err.txt &
   sleep 6; cat out.txt; kill %1
   ```

   Expected: `out.txt` holds exactly one JSON line (the handshake); anything the program complains about
   is in `err.txt`. (If `uv` prints a warning about its own environment variables, it lands in
   `err.txt` too.) Delete `out.txt` and `err.txt` afterwards.
4. Count the tests without running them: `uv run pytest --co -q tests/unit | tail -1` prints a line such
   as `384 tests collected` (the number grows as tests are added).

## 5. Change it

Change *how the host is told* rather than the code: start the backend twice with different
`--library-root` folders and observe two separate libraries. Or set `HYPOTHESIS_PROFILE=ci` before
`uv run pytest tests/property -q` and see the property tests run deterministically (same result every
time; the `dev` profile explores randomly). The place this is defined is `tests/conftest.py`
(`settings.register_profile("ci", derandomize=True, ...)`).

## 6. Break it on purpose

Use the wrong shell's syntax. In PowerShell, `export NAME=value` gives
`export : The term 'export' is not recognized...`; in bash, `$env:NAME = "x"` gives
`$env:NAME: command not found`. Another classic: setting a variable in one terminal and expecting it in
another (the second shows `None`). And never put the launch token on the command line (`--token ...`):
there is no such option, precisely so nobody can.

## 7. Exercises

1. Which stream carries the handshake line, and why does it matter that nothing else is on it?
2. Where does the real profile read the list of execution providers from?
3. Does `FACEIDENTIFY_DEVELOPMENT_PROFILE=1` make `python -m backend.api.host` use the fake models? Why or why not?
4. What does `2> err.txt` do?

**Answers**

1. Standard output; the shell reads the first line as the handshake and would be confused by noise.
2. `FACEIDENTIFY_PROVIDERS`, parsed by `providers_from` in `backend/api/real.py`.
3. No. The Python host only understands the flag `--development-profile`; the Tauri shell reads
   `FACEIDENTIFY_DEVELOPMENT_PROFILE` and adds the flag.
4. Writes standard error (warnings, tracebacks) to a file.

## 8. Related files

- Next: [02 uv and dependencies](02-uv-and-dependencies.md) · [Tools index](README.md)
- [Host and startup](../../03-backend/architecture/03-host-and-startup.md)
- [`backend/api/host.py`](../../../../../backend/api/host.py)
