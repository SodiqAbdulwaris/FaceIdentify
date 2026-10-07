"""The sidecar host: run the API on loopback for the desktop shell (M4 W1; tech-stack section 5).

`python -m backend.api.host --library-root R --local-state-root L [--parent-pid P]`

* The per-launch capability (token) arrives only in the environment (`FACEIDENTIFY_LAUNCH_TOKEN`),
  never argv, and is never printed or logged (decided 2026-10-06). A missing or malformed one stops
  the process before anything is bound.
* The server binds `127.0.0.1` on a free port the operating system picks, then writes exactly one
  JSON line to stdout, the startup handshake, and nothing else to stdout. The shell reads the line,
  then polls `/readiness` (the library opens after serving starts, `backend.api.startup`).
* The shell passes its own process id as `--parent-pid`; if that process ends, the host shuts down
  gracefully (the lifespan releases the library lock). A crash is still safe: the OS frees the lock
  and the next start recovers (architecture section 23).
* With `--stdin-lifeline` the shell keeps the host's standard input open for as long as it wants the
  host to run; closing it (or dying, which closes it) shuts the host down gracefully. This is how
  the shell asks for a clean stop on Windows, where there is no gentle signal to send.

The retry policies and index catch-up limits are operational limits no measurement has chosen yet;
the constants below are provisional starting points, named as such, to be set from benchmarks.
"""

import argparse
import asyncio
import json
import os
import socket
import sys
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Final

import uvicorn

from backend.api.app import WEBSOCKET_PROTOCOL, LaunchTokenError, validate_launch_token
from backend.api.development import development_processing
from backend.api.startup import (
    PROVISIONAL_MAX_BYTES,
    PROVISIONAL_MAX_PIXELS,
    LibrarySettings,
    MediaLimits,
    create_backend_app,
)
from backend.app.memory.index_coordinator import RetryPolicy
from backend.infrastructure.db.unit_of_work import TransactionRetry

LAUNCH_TOKEN_ENV: Final = "FACEIDENTIFY_LAUNCH_TOKEN"
LOOPBACK: Final = "127.0.0.1"  # the only address this host ever binds
HANDSHAKE_SCHEMA_VERSION: Final = 1
PARENT_POLL_SECONDS: Final = 1.0

# Provisional operational limits (see the module docstring): not measured, not product defaults.
PROVISIONAL_INDEX_RETRY: Final = RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n))
PROVISIONAL_TRANSACTION_RETRY: Final = TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n)
PROVISIONAL_INDEX_BATCH: Final = 100
PROVISIONAL_INDEX_PASSES: Final = 10


@dataclass(frozen=True)
class HostOptions:
    library_root: Path
    local_state_root: Path
    parent_pid: int | None
    # Run with the fake catalog, fake perception and uncalibrated policy (not a release setting).
    development_profile: bool = False
    # Stop gracefully when standard input reaches end of file.
    stdin_lifeline: bool = False


def _process_id(text: str) -> int:
    """A positive process id: 0 and below are not the shell (and 0 is the Windows idle process)."""
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("a process id is positive")
    return value


def parse_options(argv: Sequence[str]) -> HostOptions:
    """Parse the command line. There is deliberately no option for the launch capability."""
    parser = argparse.ArgumentParser(prog="backend.api.host")
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--parent-pid", type=_process_id, default=None)
    parser.add_argument(
        "--development-profile",
        action="store_true",
        help="use the fake development catalog and perception (uncalibrated; never for release)",
    )
    parser.add_argument(
        "--stdin-lifeline",
        action="store_true",
        help="shut down gracefully when standard input is closed",
    )
    arguments = parser.parse_args(list(argv))  # a usage error exits 2, as argparse does
    return HostOptions(
        arguments.library_root,
        arguments.local_state_root,
        arguments.parent_pid,
        arguments.development_profile,
        arguments.stdin_lifeline,
    )


def read_launch_token(environ: Mapping[str, str]) -> str:
    """The launch capability from the environment, validated; the error never contains it."""
    token = environ.get(LAUNCH_TOKEN_ENV)
    if token is None:
        raise LaunchTokenError(f"{LAUNCH_TOKEN_ENV} is not set")
    return validate_launch_token(token)


def handshake_line(host: str, port: int, pid: int) -> str:
    """The one line the shell reads: where to connect and which protocol to speak. `host` is the
    address the socket is actually bound to, so the line cannot claim loopback for anything else."""
    return json.dumps(
        {
            "schema_version": HANDSHAKE_SCHEMA_VERSION,
            "protocol": WEBSOCKET_PROTOCOL,
            "host": host,
            "port": port,
            "pid": pid,
        },
        separators=(",", ":"),
    )


if sys.platform == "win32":

    def parent_alive(pid: int) -> bool:
        """Whether the shell's process still exists."""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False  # no such process
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x102)  # WAIT_TIMEOUT: running
        finally:
            kernel32.CloseHandle(handle)

else:  # pragma: no cover - the suite runs on Windows

    def parent_alive(pid: int) -> bool:
        """Whether the shell's process still exists."""
        try:
            os.kill(pid, 0)  # signal 0 only checks existence (never use it on Windows)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def stdin_lifeline(stream: IO[bytes] | None = None) -> Callable[[], bool]:
    """A check that is true until standard input reaches end of file: the shell closed it, or the
    shell ended (which closes it). A daemon thread blocks on the read, so nothing polls the pipe."""
    source = sys.stdin.buffer if stream is None else stream
    closed = threading.Event()

    def watch() -> None:
        try:
            source.read()  # returns only at end of file (the input is never meant to carry data)
        finally:
            closed.set()

    threading.Thread(target=watch, name="stdin-lifeline", daemon=True).start()
    return lambda: not closed.is_set()


def _loopback_listener() -> socket.socket:
    """A listening socket on loopback and a port the operating system picks. Never SO_REUSEADDR:
    on Windows that lets another process share the port; there it is made exclusive instead."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":  # pragma: no branch - the suite runs on Windows
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((LOOPBACK, 0))
        listener.listen(16)
    except BaseException:
        listener.close()
        raise
    return listener


async def serve(
    options: HostOptions,
    token: str,
    *,
    out: IO[str],
    parent_alive_check: Callable[[int], bool] = parent_alive,
    poll_seconds: float = PARENT_POLL_SECONDS,
    settings: LibrarySettings | None = None,
    lifeline: Callable[[], bool] | None = None,
) -> None:
    """Bind loopback on a free port, serve until told to stop, and print the handshake once
    the server is accepting connections. Returns after a graceful shutdown."""
    library = settings or LibrarySettings(
        library_root=options.library_root,
        local_state_root=options.local_state_root,
        clock=lambda: datetime.now(UTC),
        new_id=uuid.uuid4,
        retry=PROVISIONAL_INDEX_RETRY,
        transaction_retry=PROVISIONAL_TRANSACTION_RETRY,
        index_batch=PROVISIONAL_INDEX_BATCH,
        max_index_passes=PROVISIONAL_INDEX_PASSES,
    )
    app = create_backend_app(
        token,
        library,
        development_processing(library) if options.development_profile else None,
        MediaLimits(PROVISIONAL_MAX_PIXELS, PROVISIONAL_MAX_BYTES),
    )
    listener = _loopback_listener()  # from here on, whatever happens, it is closed below
    server = uvicorn.Server(
        uvicorn.Config(app, log_config=None, log_level="warning", access_log=False, lifespan="on")
    )
    bound_host, port = listener.getsockname()[:2]
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started and not serving.done():
            await asyncio.sleep(0.01)
        if server.started:
            print(handshake_line(bound_host, port, os.getpid()), file=out, flush=True)
            while not serving.done():
                gone = options.parent_pid is not None and not parent_alive_check(options.parent_pid)
                if gone or (lifeline is not None and not lifeline()):
                    server.should_exit = True  # the shell is gone or let go: shut down gracefully
                await asyncio.sleep(poll_seconds)
        await serving
    finally:
        server.should_exit = True
        await asyncio.wait({serving})  # (does not re-raise: the error, if any, is already ours)
        _ = serving.cancelled() or serving.exception()  # retrieved: never reported twice
        listener.close()  # whatever happened above, the port is released


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    out: IO[str] | None = None,
) -> int:
    """Run the host; the exit code is 0 after a graceful stop and 2 for a bad launch (a usage error
    exits 2 through argparse)."""
    options = parse_options(sys.argv[1:] if argv is None else argv)
    try:
        token = read_launch_token(os.environ if environ is None else environ)
    except LaunchTokenError as error:
        print(f"backend.api.host: {error}", file=sys.stderr)
        return 2
    lifeline = stdin_lifeline() if options.stdin_lifeline else None
    asyncio.run(serve(options, token, out=sys.stdout if out is None else out, lifeline=lifeline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
