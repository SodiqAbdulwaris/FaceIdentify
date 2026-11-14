"""Headless check of the frozen backend (M8 step 2, TST-078 and TST-079, backend half).

    uv run python packaging/check_frozen_backend.py build/dist/faceidentify-backend

Starts the executable on the development profile in a scratch library, reads the handshake, calls
`/health` and `/readiness`, checks the library was migrated, closes its standard input (the shell's
stop signal) and expects a clean exit. Then it runs one request through the real worker process
with model-free handlers, and asks which ONNX Runtime providers the executable and a spawned child
see. Prints one JSON report and exits 1 on any failure.
"""

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen


def fetch(port: int, path: str, token: str) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - loopback only
        return json.load(response)  # type: ignore[no-any-return]


def main(folder: Path) -> int:
    exe = folder / "faceidentify-backend.exe"
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    report: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as scratch:
        library, state = Path(scratch, "library"), Path(scratch, "state")
        library.mkdir()
        started = time.monotonic()
        process = subprocess.Popen(
            [str(exe), "--library-root", str(library), "--local-state-root", str(state),
             "--development-profile", "--stdin-lifeline"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "FACEIDENTIFY_LAUNCH_TOKEN": token},
        )  # fmt: skip
        assert process.stdin
        assert process.stdout
        handshake = json.loads(process.stdout.readline())
        report["seconds_to_handshake"] = round(time.monotonic() - started, 2)
        port = handshake["port"]
        report["health"] = fetch(port, "/health", token)
        readiness = fetch(port, "/readiness", token)
        while readiness["state"] == "INITIALIZING" and time.monotonic() - started < 120:
            time.sleep(0.5)
            readiness = fetch(port, "/readiness", token)
        report["seconds_to_ready"] = round(time.monotonic() - started, 2)
        report["readiness"] = readiness
        process.stdin.close()  # the shell's stop signal
        try:
            report["exit_code"] = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            report["exit_code"] = "did not stop"
        report["database_created"] = (library / "database" / "library.db").is_file()
        report["stderr"] = process.stderr.read()[-2000:] if process.stderr else ""
    probe = subprocess.run(
        [str(exe), "--probe-providers"], capture_output=True, text=True, timeout=300, check=False
    )
    report["providers"] = (
        json.loads(probe.stdout) if probe.returncode == 0 else probe.stderr[-2000:]
    )
    # Standard input stays open while the probe runs, as the shell keeps it for the host.
    with subprocess.Popen(
        [str(exe), "--probe-worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    ) as worker:  # fmt: skip
        assert worker.stdout
        assert worker.stdin
        try:
            worker.wait(timeout=300)  # (a hang is a failure within five minutes, not forever)
            answer = worker.stdout.readline()
        finally:
            worker.stdin.close()
            worker.kill()
    report["worker"] = json.loads(answer) if worker.returncode == 0 else answer[-2000:]
    report["folder_megabytes"] = round(
        sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6
    )
    print(json.dumps(report, indent=2))
    ok = (
        report["readiness"]["state"] == "READY"  # type: ignore[index]
        and report["exit_code"] == 0
        and report["database_created"]
        and worker.returncode == 0
        and probe.returncode == 0
        and report["providers"]["usearch_size"] == 1  # type: ignore[index]
        and report["providers"]["avif"]  # type: ignore[index]
        and "CPUExecutionProvider" in report["providers"]["child"]  # type: ignore[index,operator]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
