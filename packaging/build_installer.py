"""Build the personal-use Windows installer (M8 step 3): one NSIS `.exe`, per-user, unsigned.

    uv run --group build python packaging/build_installer.py

Order: the third-party notices, the frozen backend, then Tauri, which builds the web app and the
shell and bundles the first two as resources (`desktop/src-tauri/tauri.installer.conf.json`). The
face models are never included (decision R6). Prints the installer's path and SHA-256, which the
release notes record (decision R10: unsigned, so the hash is the only integrity check).
"""

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, shell=sys.platform == "win32")


def main() -> int:
    run(
        "uv",
        "run",
        "python",
        "scripts/generate_notices.py",
        "--output",
        "build/THIRD_PARTY_NOTICES.md",
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
