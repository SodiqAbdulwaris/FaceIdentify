"""Check an installed FaceIdentify: the files, the backend, one image and one video (M8 step 7).

    uv run python packaging/check_installed.py <installation folder>

The installation folder is where the installer put `faceidentify.exe`. The check starts the
installed backend on the development profile (a fake perception, so no weights are needed) with a
scratch library and local state, and runs: the notices and FFmpeg's manifest are there; the
backend reaches READY; a generated image is imported and processed to COMPLETED; a one-second video
made by the **shipped** `ffmpeg.exe` is imported (so the shipped `ffprobe.exe` is found and its
files match their hashes); the frozen executable decodes that video's frames; the backend stops with
exit code 0 when its standard input closes. It prints a JSON report and exits 1 on any failure.
It never reads or writes a real library or state folder.
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
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image

DONE = ("COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED")


def provider_report(exe: Path, extra: dict[str, str]) -> Any:
    """What the frozen build offers and would try, with `extra` added to the environment."""
    run = subprocess.run(
        [str(exe), "--probe-providers"], capture_output=True, text=True, timeout=300, check=False,
        env={**os.environ, **extra},
    )  # fmt: skip
    return json.loads(run.stdout) if run.returncode == 0 else run.stderr[-800:]


def providers_ok(report: Any) -> bool:
    """Both paths hold. By default DirectML is tried first and the CPU last (a machine without a
    working GPU falls back at run time, which step 8 checks with the real models); forced to the
    CPU, only the CPU is tried. Either way this build offers the CPU provider."""
    default, forced = report["default"], report["forced_cpu"]
    return (
        isinstance(default, dict)
        and isinstance(forced, dict)
        and default["selected"] == ["DmlExecutionProvider", "CPUExecutionProvider"]
        and "CPUExecutionProvider" in default["child"]
        and forced["selected"] == ["CPUExecutionProvider"]
    )


def check(installed: Path) -> dict[str, Any]:
    exe = installed / "faceidentify-backend" / "faceidentify-backend.exe"
    ffmpeg = installed / "ffmpeg" / "ffmpeg.exe"
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    report: dict[str, Any] = {
        "notices": (installed / "THIRD_PARTY_NOTICES.md").is_file(),
        "ffmpeg_manifest": (installed / "ffmpeg" / "SHA256SUMS").is_file(),
        # the DirectML runtime itself, whatever GPU this machine has (the provider list below
        # shows what the build offers; the DLL shows PyInstaller did not leave it out)
        "directml_dll": any((installed / "faceidentify-backend").rglob("DirectML.dll")),
    }
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        library, state = Path(scratch, "library"), Path(scratch, "state")
        library.mkdir()
        image, clip = Path(scratch, "picture.png"), Path(scratch, "clip.mp4")
        Image.new("RGB", (320, 240), (200, 180, 160)).save(image)
        subprocess.run(
            [str(ffmpeg), "-v", "error", "-f", "lavfi"]
            + ["-i", "testsrc=size=160x120:rate=10:duration=1"]
            + ["-pix_fmt", "yuv420p", "-c:v", "mpeg4", str(clip)],
            check=True, timeout=120,
        )  # fmt: skip
        process = subprocess.Popen(
            [str(exe), "--library-root", str(library), "--local-state-root", str(state),
             "--development-profile", "--stdin-lifeline"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "FACEIDENTIFY_LAUNCH_TOKEN": token},
        )  # fmt: skip
        assert process.stdin
        assert process.stdout
        try:
            port = json.loads(process.stdout.readline())["port"]

            def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
                request = Request(  # noqa: S310 - loopback only
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(body).encode() if body is not None else None,
                    method=method,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                with urlopen(request, timeout=60) as response:  # noqa: S310
                    return json.load(response)

            for _ in range(240):
                report["readiness"] = call("GET", "/readiness")["state"]
                if report["readiness"] != "INITIALIZING":
                    break
                time.sleep(0.5)
            source = call("POST", "/api/v1/sources/import", {"path": str(image)})
            run = call("POST", f"/api/v1/sources/{source['id']}/process")
            for _ in range(120):
                run = call("GET", f"/api/v1/processing-runs/{run['id']}")
                if run["state"] in DONE:
                    break
                time.sleep(0.5)
            report["image_run"] = run["state"]
            report["video_imported"] = bool(
                call("POST", "/api/v1/sources/import", {"path": str(clip)})["id"]
            )
            probe = subprocess.run(
                [str(exe), "--probe-video", str(clip)], capture_output=True, text=True,
                timeout=120, check=False,
            )  # fmt: skip
            report["video_frames"] = (
                json.loads(probe.stdout) if probe.returncode == 0 else probe.stderr[-800:]
            )
            report["providers"] = {
                "default": provider_report(exe, {}),
                "forced_cpu": provider_report(
                    exe, {"FACEIDENTIFY_PROVIDERS": "CPUExecutionProvider"}
                ),
            }
        finally:
            process.stdin.close()  # the shell's stop signal
            try:
                report["exit_code"] = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                report["exit_code"] = "did not stop"
    return report


def main(installed: Path) -> int:
    report = check(installed)
    print(json.dumps(report, indent=2))
    ok = (
        report["notices"]
        and report["ffmpeg_manifest"]
        and report["directml_dll"]
        and report["readiness"] == "READY"
        and report["image_run"] == "COMPLETED"
        and report["video_imported"]
        and isinstance(report["video_frames"], dict)
        and report["video_frames"]["frames"] >= 1
        and providers_ok(report["providers"])
        and report["exit_code"] == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
