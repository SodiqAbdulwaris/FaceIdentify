"""A folder-per-person set that the owner fills by hand, and the numbering of what they save.

    uv run python evaluation/prepare_manual_dataset.py init   --out <folder under datasets>
    uv run python evaluation/prepare_manual_dataset.py number --out <folder under datasets>
    uv run python evaluation/prepare_manual_dataset.py number --out <folder> --apply

with, for example, `<folder>` = `evaluation/datasets/celebs-manual`.

`init` makes one folder per person (from `people.txt`, which it writes from a default list the
first time and which the owner may edit; an existing folder is kept) and a short `HOW_TO.txt`.

`number` is a dry run until `--apply`. For each person folder it finds the pictures that are not
numbered yet, checks that each one opens as a picture, and gives the good ones the next number:
`001.jpg`, `002.jpg`, ... Rules that keep the set, and the owner's pictures, safe:

* **nothing is ever deleted or overwritten.** The numbered copy is written first (to a temporary
  file, checked, then moved into place), and only then is the original moved into `_originals/`
  (a rejected file goes to `_skipped/`); a name that is taken gets a suffix. A crash at any point
  leaves every picture somewhere, and a re-run recognises a picture it already numbered by its hash;
* a numbered file (`NNN.jpg`, case aside) is never renamed again, because a review decision is keyed
  by the file's path; a numbered file that does not open as a JPEG stops the run untouched;
* a JPEG keeps its bytes; PNG, WebP and BMP are converted to JPEG (quality 95); a picture that
  does not open (or an AVIF this machine cannot read: convert it to JPG first) or that is a
  byte-identical copy of one anywhere in the set is set aside, so one picture never carries two
  people's labels;
* every path is confined to the output folder: a linked person folder or metadata file is refused;
* the original name and hashes are appended to `rename-log.jsonl` (one line per picture, written
  before the original is moved); `manifest.json` and `PROVENANCE.json` are replaced atomically in
  the shape the evaluation scripts read (the label is the folder name: the owner's, not verified).

Everything stays under `evaluation/datasets/` (Git-ignored): the pictures are biometric data and
copyrighted works, kept for local evaluation only and never redistributed.
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

DATASETS_ROOT = (Path(__file__).resolve().parent / "datasets").resolve()
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
NUMBERED = re.compile(r"^(\d{3,})\.jpg$", re.IGNORECASE)
ORIGINALS = "_originals"
SKIPPED = "_skipped"
LOG = "rename-log.jsonl"
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
   Your original files are kept in _originals/ inside each person's folder.
5. Then review the labels: label_review.py serve --dataset <this folder> --reviewer <you>
"""


def guard(path: Path) -> Path:
    """Biometric data stays under the Git-ignored datasets folder."""
    resolved = path.resolve()
    if resolved != DATASETS_ROOT and DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


def confine(root: Path, path: Path) -> Path:
    """`path` as it really is on disk (links and junctions followed) must be inside `root`."""
    real = path.resolve()
    if real != root and root not in real.parents:
        raise SystemExit(f"{path} leads outside {root}: links are not followed")
    return real


def folder_name(person: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", person).strip("_")
    if not name:
        raise SystemExit(f"{person!r} has no letters or digits to make a folder name from")
    return name


def read_people(root: Path) -> list[str]:
    path = root / "people.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else DEFAULT_PEOPLE
    people = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    names = [folder_name(p).lower() for p in people]  # (Windows folders ignore case)
    if len(set(names)) != len(names):
        raise SystemExit("two people would share a folder name (case aside): " + ", ".join(people))
    return people


def write_atomic(path: Path, data: bytes) -> None:
    """Write beside the target, then move into place: a reader sees the old file or the new one."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def unique(directory: Path, name: str) -> Path:
    """`name` in `directory`, or the first `name-N` not taken (case aside): never an overwrite."""
    taken = {p.name.lower() for p in directory.iterdir()} if directory.is_dir() else set()
    candidate = name
    stem, dot, suffix = name.rpartition(".")
    count = 1
    while candidate.lower() in taken:
        count += 1
        candidate = f"{stem}-{count}{dot}{suffix}" if dot else f"{name}-{count}"
    return directory / candidate


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


def open_picture(raw: bytes) -> tuple[bytes, str, tuple[int, int]]:
    """The bytes to store as `.jpg`, the picture's real format and its size, or ValueError."""
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            kind = str(image.format)
            size = image.size
            if kind == "JPEG":
                return raw, kind, size
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError(f"does not open as a picture ({type(error).__name__})") from error
    out = io.BytesIO()
    upright.save(out, format="JPEG", quality=95)
    return out.getvalue(), kind, size


def read_log(root: Path) -> list[dict[str, Any]]:
    """The rename log; a torn last line (a crash while writing it) is ignored."""
    path = root / LOG
    entries: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def append_log(root: Path, entry: dict[str, Any]) -> None:
    with (root / LOG).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def person_folders(root: Path, people: list[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for person in people:
        folder = root / folder_name(person)
        if not folder.is_dir():
            continue
        if folder.is_symlink():
            raise SystemExit(f"{folder} is a link: not followed")
        confine(root, folder)
        found[person] = folder
    return found


def numbered_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir() if f.is_file() and NUMBERED.match(f.name))


def existing_numbered(folders: dict[str, Path]) -> dict[str, str]:
    """Digest of every numbered file in the set, validated; stops on a bad or repeated one."""
    owners: dict[str, str] = {}
    for folder in folders.values():
        for path in numbered_files(folder):
            raw = path.read_bytes()
            try:
                _, kind, _ = open_picture(raw)
            except ValueError as error:
                raise SystemExit(f"{path}: {error}; fix or remove it, then run again") from None
            if kind != "JPEG":
                raise SystemExit(f"{path} is a {kind} saved as .jpg; convert or remove it")
            digest = sha256_of(raw)
            if digest in owners and owners[digest] != folder.name:
                raise SystemExit(
                    f"the same picture is numbered in {owners[digest]}/ and {folder.name}/: "
                    "remove one"
                )
            owners.setdefault(digest, folder.name)
    return owners


def plan_person(folder: Path, owners: dict[str, str]) -> list[dict[str, Any]]:
    """What `number` would do to this person's folder, in file-name order. `owners` is updated."""
    numbers = [int(m.group(1)) for f in numbered_files(folder) if (m := NUMBERED.match(f.name))]
    following = max(numbers, default=0) + 1
    actions: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.is_symlink() or not path.is_file() or NUMBERED.match(path.name):
            continue
        if path.name.startswith("."):
            continue  # (our own temporary files)
        suffix = path.suffix.lower()
        if suffix not in IMAGE_SUFFIXES and suffix != ".avif":
            actions.append({"from": path.name, "action": "skip", "reason": "not a picture type"})
            continue
        raw = path.read_bytes()
        try:
            data, kind, size = open_picture(raw)
        except ValueError as error:
            hint = " (convert AVIF to JPG first)" if suffix == ".avif" else ""
            actions.append({"from": path.name, "action": "skip", "reason": str(error) + hint})
            continue
        digest = sha256_of(data)
        if digest in owners:
            reason = (
                "already numbered here"
                if owners[digest] == folder.name
                else f"same picture as one in {owners[digest]}/"
            )
            actions.append({"from": path.name, "action": "skip", "reason": reason})
            continue
        owners[digest] = folder.name
        actions.append(
            {
                "from": path.name,
                "action": "keep" if kind == "JPEG" else "convert",
                "to": f"{following:03d}.jpg",
                "format": kind,
                "size": list(size),
                "sha256": digest,
                "original_sha256": sha256_of(raw),
                "small": min(size) < SMALL_SIDE,
                "_data": data,
            }
        )
        following += 1
    return actions


def move_aside(folder: Path, source: Path, directory: str) -> None:
    target = folder / directory
    target.mkdir(exist_ok=True)
    if target.is_symlink():
        raise SystemExit(f"{target} is a link: not followed")
    confine(folder, target)
    os.replace(source, unique(target, source.name))  # (a unique name: nothing is replaced)


def publish(folder: Path, item: dict[str, Any]) -> None:
    """Write the numbered file safely: temporary, checked, then moved into a free name."""
    destination = folder / item["to"]
    if unique(folder, item["to"]).name != item["to"]:
        raise SystemExit(f"{destination} is already taken: run `number` again")
    temporary = folder / f".{item['to']}.tmp"
    temporary.write_bytes(item["_data"])
    try:
        open_picture(temporary.read_bytes())
    except ValueError:
        temporary.unlink()
        raise
    os.replace(temporary, destination)


def number(root: Path, apply: bool) -> dict[str, Any]:
    people = read_people(root)
    for name in (LOG, "manifest.json", "PROVENANCE.json"):
        if (root / name).is_symlink():
            raise SystemExit(f"{root / name} is a link: not followed")
    folders = person_folders(root, people)
    owners = existing_numbered(folders)  # all existing numbers, before any plan
    plans = {person: plan_person(folder, owners) for person, folder in folders.items()}
    titles = {(e["person"], e["to"]): e["from"] for e in read_log(root) if e.get("to")}
    report: dict[str, Any] = {"people": {}, "applied": apply}
    manifest: dict[str, list[dict[str, Any]]] = {}
    for person, folder in folders.items():
        plan = plans[person]
        if apply:
            for item in plan:
                source = folder / item["from"]
                if item["action"] == "skip":
                    move_aside(folder, source, SKIPPED)
                    continue
                publish(folder, item)
                append_log(
                    root,
                    {
                        "person": folder.name,
                        "from": item["from"],
                        "to": item["to"],
                        "action": item["action"],
                        "original_sha256": item["original_sha256"],
                        "sha256": item["sha256"],
                        "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    },
                )
                titles[(folder.name, item["to"])] = item["from"]
                move_aside(folder, source, ORIGINALS)  # the original is kept, never removed
        names = [f.name for f in numbered_files(folder)]
        if not apply:
            names = sorted({*names, *(i["to"] for i in plan if i["action"] != "skip")})
        report["people"][person] = {
            "numbered_after": len(names),
            "to_rename": sum(1 for i in plan if i["action"] in ("keep", "convert")),
            "to_skip": sum(1 for i in plan if i["action"] == "skip"),
            "small": sum(1 for i in plan if i.get("small")),
            "plan": [{k: v for k, v in i.items() if not k.startswith("_")} for i in plan],
        }
        if apply and names:
            manifest[person] = [
                {
                    "file": f"{folder.name}/{n}",
                    "title": titles.get((folder.name, n), ""),
                    "sha256": sha256_of((folder / n).read_bytes()),
                    "licence": "collected by the owner; terms not verified by this project",
                }
                for n in names
            ]
    if apply:
        write_atomic(root / "manifest.json", json.dumps(manifest, indent=1).encode("utf-8"))
        provenance = {
            "schema_version": 1,
            "dataset": "Pictures collected by hand by the owner (one folder per person)",
            "labels_by": "the owner (the folder a picture was saved in)",
            "label_status": "supplied by the owner; NOT verified by this project",
            "terms": "copyrighted works, local evaluation only; never redistributed",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "people": len(manifest),
            "photographs": sum(len(v) for v in manifest.values()),
        }
        write_atomic(root / "PROVENANCE.json", json.dumps(provenance, indent=1).encode("utf-8"))
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
