"""Build the personal-use Windows installer (M8 step 3): one NSIS `.exe`, per-user, unsigned.

    uv run --group build python packaging/build_installer.py

Order: the pinned FFmpeg (downloaded once into `build/ffmpeg-download`, its SHA-256 checked, and
unpacked by `scripts/install_ffmpeg.py`), the third-party notices, the frozen backend, then Tauri,
which builds the web app and the shell and bundles those as resources
(`desktop/src-tauri/tauri.installer.conf.json`). The
face models are never included (decision R6). Prints the installer's path and SHA-256, which the
release notes record (decision R10: unsigned, so the hash is the only integrity check).
"""

import hashlib
import runpy
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, shell=sys.platform == "win32")


def pinned_ffmpeg() -> Path:
    """The folder of the pinned FFmpeg build, downloaded and unpacked if it is not there yet."""
    pin = runpy.run_path(str(ROOT / "scripts" / "install_ffmpeg.py"))
    archive = ROOT / "build" / "ffmpeg-download" / "ffmpeg.zip"
    if not archive.is_file():
        archive.parent.mkdir(parents=True, exist_ok=True)
        print("+ download", pin["URL"], flush=True)
        urllib.request.urlretrieve(pin["URL"], archive)  # noqa: S310 (a pinned https URL)
    run(
        "uv", "run", "python", "scripts/install_ffmpeg.py", "--zip", str(archive),
        "--local-state-root", "build/ffmpeg-state", "--replace",
    )  # fmt: skip
    return (
        ROOT / "build" / "ffmpeg-state" / "runtime" / "ffmpeg"
    )  # (checked against the pinned hash)


def main() -> int:
    ffmpeg = pinned_ffmpeg()
    run(
        "uv",
        "run",
        "python",
        "scripts/generate_notices.py",
        "--output",
        "build/THIRD_PARTY_NOTICES.md",
        "--ffmpeg",
        str(ffmpeg),
    )
    run(
        "uv", "run", "--group", "build", "pyinstaller", "packaging/faceidentify-backend.spec",
        "--noconfirm", "--distpath", "build/dist", "--workpath", "build/work",
    )  # fmt: skip
    run("npx", "tauri", "build", "--config", "desktop/src-tauri/tauri.installer.conf.json")
    installers = sorted((ROOT / "desktop/src-tauri/target/release/bundle/nsis").glob("*-setup.exe"))
    if not installers:
        print("no installer was produced", file=sys.stderr)
        return 1
    installer = installers[-1]
    print(f"{installer}\nsha256 {hashlib.sha256(installer.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
