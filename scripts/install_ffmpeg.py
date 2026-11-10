"""Install the pinned LGPL FFmpeg build into the machine-local state (M6 step 3, D2).

    uv run python scripts/install_ffmpeg.py --zip <downloaded zip> --local-state-root <dir>

The zip is downloaded by hand (or by CI) from `URL` and refused unless its SHA-256 is `SHA256`. Its
`bin` folder (ffmpeg, ffprobe and their DLLs) and `LICENSE.txt` are unpacked into
`<local state>/runtime/ffmpeg`, staged next to it and renamed into place, so the folder is either
absent or complete. An existing install is replaced only with `--replace`: it is moved aside first
and removed only once the new one is in place (a backup left by an interrupted replace is put back
by the next run). The binaries are never
committed: they are third-party bytes with their own licence (docs/research/licensing-and-
commercialization.md section 4.1).
"""

import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

URL = (
    "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/"
    "ffmpeg-n9.0.2-39-g7adfbe40dc-win64-lgpl-shared-9.0.zip"
)
SHA256 = "e907b01fa4783913151237e37df2a10fa97d99a1598a021bf59d4ae62ffed4c0"
KEEP = ("ffmpeg.exe", "ffprobe.exe", "LICENSE.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    arguments = parser.parse_args()

    digest = hashlib.sha256(arguments.zip.read_bytes()).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"refused: the zip's SHA-256 is {digest}, not the pinned {SHA256}")
    runtime = arguments.local_state_root / "runtime"
    target = runtime / "ffmpeg"
    backup = runtime / "ffmpeg.previous"
    if backup.exists() and not target.exists():
        backup.rename(target)  # an interrupted replace: the old install comes back
    if target.exists() and not arguments.replace:
        raise SystemExit(f"{target} exists; pass --replace to install again")
    runtime.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="ffmpeg.", dir=runtime))
    with zipfile.ZipFile(arguments.zip) as archive:
        for member in archive.infolist():
            name = PurePosixPath(member.filename).name
            if not member.is_dir() and (name in KEEP or name.endswith(".dll")):
                (staging / name).write_bytes(archive.read(member))
    missing = [name for name in KEEP if not (staging / name).is_file()]
    if missing:
        shutil.rmtree(staging)
        raise SystemExit(f"refused: the zip has no {', '.join(missing)}")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    staging.rename(target)
    if backup.exists():
        shutil.rmtree(backup)
    print(f"installed FFmpeg into {target}")


if __name__ == "__main__":
    main()
