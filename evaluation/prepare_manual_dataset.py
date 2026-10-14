"""A folder-per-person set that the owner fills by hand, and the renaming of what they save.

    uv run python evaluation/prepare_manual_dataset.py init   --out <folder under datasets>
    uv run python evaluation/prepare_manual_dataset.py number --out <folder under datasets>
    uv run python evaluation/prepare_manual_dataset.py number --out <folder> --apply

with, for example, `<folder>` = `evaluation/datasets/celebs-manual`.

`init` makes one folder per person (from `people.txt`, which it writes from a default list the
first time and which the owner may edit; an existing folder is kept) and a short `HOW_TO.txt`.

`number` is a dry run until `--apply`. For each person folder it finds the pictures that are not
numbered yet, checks that each one opens as a picture, and gives the good ones the next number:
`001.jpg`, `002.jpg`, ... Rules that keep the set honest:

* a numbered file is never renamed again (a review decision is keyed by the file's path);
* a JPEG keeps its bytes; PNG, WebP and BMP are converted to JPEG (quality 95); anything that does
  not open (or an AVIF this machine cannot read: convert it to JPG first) is moved to `_skipped/`
  with its reason, never deleted; so is a byte-identical copy of a picture already in the set;
* the original name, the original and the new SHA-256 and the action are appended to
  `rename-log.json`, so nothing about where a file came from is lost by the renaming;
* `manifest.json` and `PROVENANCE.json` are rewritten in the shape the evaluation scripts read
  (`label_review.py`, `assisted_recognition_gate.py`, `import_labelled_dataset.py`): the label is
  the folder name, said plainly to be the owner's and not verified.

Everything stays under `evaluation/datasets/` (Git-ignored): the pictures are biometric data and
copyrighted works, kept for local evaluation only and never redistributed.
"""

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

DATASETS_ROOT = (Path(__file__).resolve().parent / "datasets").resolve()
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
NUMBERED = re.compile(r"^(\d{3,})\.jpg$")
SKIPPED = "_skipped"
SMALL_SIDE = 112  # below this a face is probably too small to be useful: a warning, not a refusal
DEFAULT_PEOPLE = [
    "Jason Statham", "Dwayne Johnson", "Jennifer Lawrence", "Jennifer Lopez", "Jenna Ortega",
    "Zendaya", "Tom Hanks", "Vin Diesel", "Kevin Hart", "Mark Wahlberg", "Morgan Freeman",
    "Leonardo DiCaprio", "Idris Elba", "Will Smith", "Lady Gaga", "Selena Gomez", "Brad Pitt",
    "Keanu Reeves", "Natalie Portman", "Emma Stone", "Angelina Jolie", "Tom Cruise",
    "Taylor Swift", "Scarlett Johansson", "Margot Robbie", "Emma Watson", "Rihanna", "Beyonce",
    "Ariana Grande", "Chris Hemsworth", "Henry Cavill", "Ryan Reynolds", "Zoe Saldana",
    "Gal Gadot", "Anne Hathaway", "Robert Downey Jr", "Chris Evans", "Michael B Jordan",
]  # fmt: skip
HOW_TO = """How to fill this folder
=======================

1. Put 8 to 15 pictures of each person into that person's folder (any file names).
2. Prefer: one person only, the face clearly visible and fairly large, a mix of years, lighting,
   expressions and angles, with and without glasses or a beard if they had both.
3. Avoid: groups, wardrobe or dress close-ups, posters, logos, signatures, screenshots of video
   with a watermark, very small thumbnails, heavy filters, and the same picture twice.
4. When you have added some, run (from the project folder):
       uv run python evaluation/prepare_manual_dataset.py number --out <this folder>
   to see what it would do, then add --apply to rename them to 001.jpg, 002.jpg, ...
5. Then review the labels: label_review.py serve --dataset <this folder> --reviewer <you>
"""


def guard(path: Path) -> Path:
    """Biometric data stays under the Git-ignored datasets folder."""
    resolved = path.resolve()
    if resolved != DATASETS_ROOT and DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


def folder_name(person: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", person).strip("_")
    if not name:
        raise SystemExit(f"{person!r} has no letters or digits to make a folder name from")
    return name


def read_people(root: Path) -> list[str]:
    path = root / "people.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else DEFAULT_PEOPLE
    people = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    names = [folder_name(p) for p in people]
    if len(set(names)) != len(names):
        raise SystemExit("two people would share a folder name: " + ", ".join(sorted(people)))
    return people


def init(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    listing = root / "people.txt"
    if not listing.exists():
        listing.write_text("\n".join(DEFAULT_PEOPLE) + "\n", encoding="utf-8")
    created = []
    for person in read_people(root):
        folder = root / folder_name(person)
        if not folder.exists():
            folder.mkdir()
            created.append(folder.name)
    (root / "HOW_TO.txt").write_text(HOW_TO, encoding="utf-8")
    return {"root": str(root), "folders_created": len(created), "people": len(read_people(root))}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_picture(path: Path) -> tuple[bytes, str, tuple[int, int]]:
    """The bytes to store as `.jpg`, the picture's real format and its size, or ValueError."""
    raw = path.read_bytes()
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            kind = str(image.format)
            size = image.size
            if kind == "JPEG":
                return raw, kind, size
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError(f"does not open as a picture ({type(error).__name__})") from error
    out = io.BytesIO()
    upright.save(out, format="JPEG", quality=95)
    return out.getvalue(), kind, size


def plan_person(folder: Path, known: set[str]) -> list[dict[str, Any]]:
    """What `number` would do to this person's folder, in file-name order."""
    numbers = [int(m.group(1)) for f in folder.iterdir() if (m := NUMBERED.match(f.name))]
    following = max(numbers, default=0) + 1
    seen = set(known)
    actions: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.is_symlink() or not path.is_file() or NUMBERED.match(path.name):
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES and path.suffix.lower() != ".avif":
            actions.append({"from": path.name, "action": "skip", "reason": "not a picture type"})
            continue
        try:
            data, kind, size = open_picture(path)
        except ValueError as error:
            hint = " (convert AVIF to JPG first)" if path.suffix.lower() == ".avif" else ""
            actions.append({"from": path.name, "action": "skip", "reason": str(error) + hint})
            continue
        digest = sha256_of(data)
        if digest in seen:
            actions.append(
                {"from": path.name, "action": "skip", "reason": "same picture as one kept"}
            )
            continue
        seen.add(digest)
        action = {
            "from": path.name,
            "action": "keep" if kind == "JPEG" else "convert",
            "to": f"{following:03d}.jpg",
            "format": kind,
            "size": list(size),
            "sha256": digest,
            "original_sha256": sha256_of(path.read_bytes()),
            "small": min(size) < SMALL_SIDE,
            "_data": data,
        }
        actions.append(action)
        following += 1
    return actions


def existing_digests(folder: Path) -> dict[str, str]:
    return {f.name: sha256_of(f.read_bytes()) for f in folder.iterdir() if NUMBERED.match(f.name)}


def number(root: Path, apply: bool) -> dict[str, Any]:
    people = read_people(root)
    # one picture must not sit in two people's folders: a label would then be wrong for one of them
    everywhere: dict[str, str] = {}
    log_path = root / "rename-log.json"
    log: list[dict[str, Any]] = (
        json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else []
    )
    report: dict[str, Any] = {"people": {}, "applied": apply}
    titles = {(e["person"], e["to"]): e["from"] for e in log if e.get("to")}
    manifest: dict[str, list[dict[str, Any]]] = {}
    for person in people:
        folder = root / folder_name(person)
        if not folder.is_dir():
            continue
        digests = existing_digests(folder)
        for digest in digests.values():
            everywhere.setdefault(digest, folder.name)
        plan = plan_person(folder, set(digests.values()))
        for item in plan:
            other = everywhere.get(item.get("sha256", ""))
            if item["action"] != "skip" and other and other != folder.name:
                item.update(action="skip", reason=f"same picture as one in {other}/")
        for item in plan:
            if item["action"] != "skip":
                everywhere.setdefault(item["sha256"], folder.name)
        if apply:
            for item in plan:
                source = folder / item["from"]
                if item["action"] == "skip":
                    target = folder / SKIPPED
                    target.mkdir(exist_ok=True)
                    destination = target / item["from"]
                    if destination.exists():
                        destination = (
                            target / f"{sha256_of(source.read_bytes())[:8]}-{item['from']}"
                        )
                    shutil.move(str(source), str(destination))
                    continue
                (folder / item["to"]).write_bytes(item["_data"])
                if item["action"] == "keep":
                    source.unlink()
                else:  # a converted picture: the original goes aside, not away
                    target = folder / SKIPPED
                    target.mkdir(exist_ok=True)
                    shutil.move(str(source), str(target / f"converted-{item['from']}"))
                log.append(
                    {
                        "person": folder.name,
                        "from": item["from"],
                        "to": item["to"],
                        "action": item["action"],
                        "original_sha256": item["original_sha256"],
                        "sha256": item["sha256"],
                        "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                )
                titles[(folder.name, item["to"])] = item["from"]
        files = sorted(f.name for f in folder.iterdir() if NUMBERED.match(f.name))
        if not apply:  # the files that would exist after the run
            files = sorted({*files, *(i["to"] for i in plan if i["action"] != "skip")})
        counts = {
            "numbered_after": len(files),
            "to_rename": sum(1 for i in plan if i["action"] in ("keep", "convert")),
            "to_skip": sum(1 for i in plan if i["action"] == "skip"),
            "small": sum(1 for i in plan if i.get("small")),
            "enough": len(files) >= 6,
        }
        report["people"][person] = {
            **counts,
            "plan": [{k: v for k, v in i.items() if not k.startswith("_")} for i in plan],
        }
        if files:
            entries = []
            for name in files:
                path = folder / name
                digest = (
                    sha256_of(path.read_bytes())
                    if path.is_file()
                    else next(i["sha256"] for i in plan if i.get("to") == name)
                )
                entries.append(
                    {
                        "file": f"{folder.name}/{name}",
                        "title": titles.get((folder.name, name), ""),
                        "sha256": digest,
                        "licence": "collected by the owner; terms not verified by this project",
                    }
                )
            manifest[person] = entries
    if apply:
        log_path.write_text(json.dumps(log, indent=1), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        (root / "PROVENANCE.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "dataset": "Pictures collected by hand by the owner (one folder per person)",
                    "labels_by": "the owner (the folder a picture was saved in)",
                    "label_status": "supplied by the owner; NOT verified by this project",
                    "terms": "copyrighted works, local evaluation only; never redistributed",
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "people": len(manifest),
                    "photographs": sum(len(v) for v in manifest.values()),
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "number"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="number: do it (default: a dry run)")
    args = parser.parse_args(argv)
    root = guard(args.out)
    if args.command == "init":
        print(json.dumps(init(root), indent=1))
        return 0
    if not root.is_dir():
        raise SystemExit(f"{root} does not exist: run `init` first")
    report = number(root, args.apply)
    for person, info in report["people"].items():
        if info["to_rename"] or info["to_skip"]:
            print(f"{person}: rename {info['to_rename']}, skip {info['to_skip']}, "
                  f"{info['numbered_after']} numbered after, small {info['small']}")  # fmt: skip
            for item in info["plan"]:
                if item["action"] == "skip":
                    print(f"    skip  {item['from']}: {item['reason']}")
    short = [p for p, i in report["people"].items() if i["numbered_after"] < 6]
    total = sum(i["numbered_after"] for i in report["people"].values())
    print(f"{total} numbered pictures; {len(short)} people have fewer than 6")
    print("(dry run: nothing changed; add --apply)" if not args.apply else "(applied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
