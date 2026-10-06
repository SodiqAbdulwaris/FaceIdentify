"""The sidecar host: loopback bind, one-line handshake, token from the environment, parent watch
(M4 W1; decisions 2026-10-06; TST-047 backend half).

Most of it runs in this process against a real loopback socket (so coverage sees it); one test
starts the real `python -m`-style entry in a child process and kills it.
"""

import asyncio
import base64
import io
import json
import os
import runpy
import secrets
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from backend.api import host
from backend.api.app import WEBSOCKET_PROTOCOL, LaunchTokenError
from backend.api.host import (
    HANDSHAKE_SCHEMA_VERSION,
    LAUNCH_TOKEN_ENV,
    LOOPBACK,
    HostOptions,
    handshake_line,
    main,
    parent_alive,
    parse_options,
    read_launch_token,
    serve,
)
from backend.api.startup import LibrarySettings
from backend.app.memory.index_coordinator import RetryPolicy
from backend.infrastructure.db.unit_of_work import TransactionRetry
from backend.infrastructure.storage.library_lock import LibraryLock, LibraryLockedError
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.processes import REPOSITORY_ROOT, acquire_soon, close_streams, kill_tree


def token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def lock_is_free(root: Path) -> bool:
    try:
        with LibraryLock(root):
            return True
    except LibraryLockedError:
        return False


def dead_pid() -> int:
    """The id of a process that has just ended."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=60)
    return child.pid


def options_for(tmp_path: Path, parent_pid: int | None = None) -> HostOptions:
    (tmp_path / "library").mkdir(exist_ok=True)
    return HostOptions(tmp_path / "library", tmp_path / "local", parent_pid)


def settings_for(options: HostOptions, clock: FrozenClock, new_id: SeededUUIDs) -> LibrarySettings:
    return LibrarySettings(
        library_root=options.library_root,
        local_state_root=options.local_state_root,
        clock=clock,
        new_id=new_id,
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
        index_batch=50,
        max_index_passes=5,
    )


# --- the pure pieces --------------------------------------------------------------------------


def test_options_come_from_the_command_line_and_there_is_no_token_option(tmp_path: Path) -> None:
    options = parse_options(
        ["--library-root", str(tmp_path / "l"), "--local-state-root", str(tmp_path / "s")]
    )
    assert options == HostOptions(tmp_path / "l", tmp_path / "s", None)
    assert (
        parse_options(
            ["--library-root", "a", "--local-state-root", "b", "--parent-pid", "42"]
        ).parent_pid
        == 42
    )
    for bad in (
        ["--library-root", "a"],
        ["--library-root", "a", "--local-state-root", "b", "--token", "secret"],
        ["--library-root", "a", "--local-state-root", "b", "--parent-pid", "0"],
        ["--library-root", "a", "--local-state-root", "b", "--parent-pid", "-5"],
    ):
        with pytest.raises(SystemExit) as error:
            parse_options(bad)
        assert error.value.code == 2  # a launch capability on the command line is refused


def test_the_launch_capability_is_read_from_the_environment_and_never_echoed() -> None:
    good = token()
    assert read_launch_token({LAUNCH_TOKEN_ENV: good}) == good
    with pytest.raises(LaunchTokenError, match=LAUNCH_TOKEN_ENV):
        read_launch_token({})
    bad = "not-a-valid-capability"
    with pytest.raises(LaunchTokenError) as error:
        read_launch_token({LAUNCH_TOKEN_ENV: bad})
    assert bad not in str(error.value)


def test_the_handshake_is_one_json_line_with_no_secret() -> None:
    line = handshake_line(LOOPBACK, 51234, 99)

    assert "\n" not in line
    assert json.loads(line) == {
        "schema_version": HANDSHAKE_SCHEMA_VERSION,
        "protocol": WEBSOCKET_PROTOCOL,
        "host": LOOPBACK,
        "port": 51234,
        "pid": 99,
    }


def test_parent_alive_tells_a_running_process_from_an_ended_one() -> None:
    assert parent_alive(os.getpid())
    assert not parent_alive(dead_pid())


# --- serving, in this process, on a real loopback socket ----------------------------------------


async def until(condition: Any, seconds: float = 30) -> None:
    """Poll an external condition (a server in the same loop) with a bound; not a fixed sleep."""
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.02)


async def test_the_host_serves_loopback_prints_one_handshake_and_stops_when_the_parent_ends(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    secret = token()
    options = options_for(tmp_path, parent_pid=os.getpid())
    out = io.StringIO()
    parent_is_alive = True

    task = asyncio.create_task(
        serve(
            options,
            secret,
            out=out,
            parent_alive_check=lambda _pid: parent_is_alive,
            poll_seconds=0.02,
            settings=settings_for(options, clock, new_id),
        )
    )
    await until(lambda: out.getvalue().endswith("\n") or task.done())
    assert not task.done(), "the host stopped before its handshake"

    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    handshake = json.loads(lines[0])
    assert handshake["host"] == LOOPBACK
    assert handshake["port"] > 0
    assert handshake["pid"] == os.getpid()
    assert secret not in out.getvalue()
    # another local process cannot take the same port, even with SO_REUSEADDR (the Windows hijack)
    intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    with pytest.raises(OSError, match="(?i)access|usage|address"), intruder:
        intruder.bind((LOOPBACK, handshake["port"]))
    base = f"http://{LOOPBACK}:{handshake['port']}"
    auth = {"Authorization": f"Bearer {secret}"}

    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.get("/health")).status_code == 401  # the capability is required
        assert (await client.get("/health", headers=auth)).json() == {"status": "ok"}
        ready = {"state": ""}

        async def readiness_settled() -> None:
            async with asyncio.timeout(30):
                while ready["state"] in ("", "INITIALIZING"):
                    ready["state"] = (await client.get("/readiness", headers=auth)).json()["state"]
                    await asyncio.sleep(0.05)

        await readiness_settled()
        assert ready["state"] == "READY"
        assert not lock_is_free(options.library_root)  # the host holds the library while it runs

    parent_is_alive = False  # the shell went away
    async with asyncio.timeout(30):
        await task  # a graceful stop, not a hang

    assert lock_is_free(options.library_root)  # the lifespan released the library
    assert out.getvalue().count("\n") == 1  # still exactly one line


async def test_a_host_that_cannot_start_serving_raises_instead_of_hanging(
    tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = options_for(tmp_path)

    class Broken:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.started = False
            self.should_exit = False

        async def serve(self, sockets: Any = None) -> None:
            raise RuntimeError("could not start")

    monkeypatch.setattr(uvicorn, "Server", Broken)
    out = io.StringIO()

    with pytest.raises(RuntimeError, match="could not start"):
        await serve(options, token(), out=out, settings=settings_for(options, clock, new_id))
    assert out.getvalue() == ""  # no handshake for a server that never accepted connections


async def test_a_failure_while_binding_closes_the_listening_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[socket.socket] = []
    real_socket = socket.socket

    class Tracked(real_socket):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

        def listen(self, *args: Any) -> None:
            raise OSError("cannot listen")

    monkeypatch.setattr("backend.api.host.socket.socket", Tracked)

    with pytest.raises(OSError, match="cannot listen"):
        host._loopback_listener()

    assert len(opened) == 1
    assert opened[0].fileno() == -1  # closed, not leaked


# --- main -------------------------------------------------------------------------------------


def test_main_runs_to_a_graceful_stop_when_the_parent_is_already_gone(tmp_path: Path) -> None:
    secret = token()
    (tmp_path / "library").mkdir()
    out = io.StringIO()

    code = main(
        [
            "--library-root", str(tmp_path / "library"),
            "--local-state-root", str(tmp_path / "local"),
            "--parent-pid", str(dead_pid()),
        ],
        {LAUNCH_TOKEN_ENV: secret},
        out,
    )  # fmt: skip

    assert code == 0
    assert json.loads(out.getvalue())["host"] == LOOPBACK
    assert secret not in out.getvalue()
    assert lock_is_free(tmp_path / "library")


def test_main_refuses_a_missing_or_malformed_capability_before_binding_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--library-root", str(tmp_path), "--local-state-root", str(tmp_path / "s")]
    out = io.StringIO()
    bad = "definitely-not-canonical"

    assert main(arguments, {}, out) == 2
    assert main(arguments, {LAUNCH_TOKEN_ENV: bad}, out) == 2

    assert out.getvalue() == ""  # nothing was served, so no handshake
    assert bad not in capsys.readouterr().err


def test_main_reads_the_real_command_line_and_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "library").mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["host", "--library-root", str(tmp_path / "library"),
         "--local-state-root", str(tmp_path / "local"), "--parent-pid", str(dead_pid())],
    )  # fmt: skip
    monkeypatch.setenv(LAUNCH_TOKEN_ENV, token())

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["protocol"] == WEBSOCKET_PROTOCOL


def test_running_the_module_as_a_script_exits_with_the_host_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "library").mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["host", "--library-root", str(tmp_path / "library"),
         "--local-state-root", str(tmp_path / "local"), "--parent-pid", str(dead_pid())],
    )  # fmt: skip
    monkeypatch.setenv(LAUNCH_TOKEN_ENV, token())

    monkeypatch.delitem(sys.modules, "backend.api.host")  # run it fresh, as `python -m` would
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("backend.api.host", run_name="__main__")

    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip().startswith("{")


# --- a real process ---------------------------------------------------------------------------


def test_a_real_host_process_serves_then_a_kill_leaves_the_library_free(tmp_path: Path) -> None:
    secret = token()
    (tmp_path / "library").mkdir()
    environment = {**os.environ, LAUNCH_TOKEN_ENV: secret}
    child = subprocess.Popen(
        [sys.executable, "-m", "backend.api.host",
         "--library-root", str(tmp_path / "library"),
         "--local-state-root", str(tmp_path / "local"),
         "--parent-pid", str(os.getpid())],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=REPOSITORY_ROOT, env=environment,
    )  # fmt: skip
    assert child.stdout is not None
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        first_line = pool.submit(child.stdout.readline).result(timeout=60)
        handshake = json.loads(first_line)
        assert handshake["host"] == LOOPBACK
        response = httpx.get(
            f"http://{LOOPBACK}:{handshake['port']}/health",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=30,
        )
        assert response.json() == {"status": "ok"}
        assert secret not in first_line
        assert secret not in str(child.args)  # never on the command line
    finally:
        try:
            kill_tree(child)  # a crash: nothing is released by the process itself
        finally:
            pool.shutdown(wait=False)
            close_streams(child)

    acquire_soon(tmp_path / "library")  # the operating system freed the library lock
