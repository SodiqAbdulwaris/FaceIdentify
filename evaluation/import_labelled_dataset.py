"""Import a ready-labelled face dataset (LFW or CelebA) for the evaluation scripts.

    uv run python evaluation/import_labelled_dataset.py lfw    --source <extracted lfw folder>
    uv run python evaluation/import_labelled_dataset.py celeba --source <folder with the
        images and identity_CelebA.txt>

You download the dataset yourself (accepting its terms); this script only reads the folder you give
it and writes a **selection** of it under `evaluation/datasets/<name>/`, the Git-ignored folder, in
the shape `assisted_recognition_gate.py` and `label_review.py` read:

    <person>/<NN>.jpg ..., manifest.json (person -> [{file, title, sha256, licence}]),
    PROVENANCE.json

* **Labels are the dataset creators', not the owner's.** `PROVENANCE.json` says so, and the gate's
  report repeats it. Nothing here is verified by this project; run `label_review.py` on the result
  if you want to confirm photographs by eye.
* **Selection is deterministic**: people with at least `--minimum` distinct pictures, ordered by a
  hash of their name, at most `--people` of them and `--maximum` pictures each. A byte-identical
  picture is used once.
* **Nothing is downloaded and nothing leaves the machine.** The terms of these datasets are *not
  verified* here (see `docs/research/licensing-and-commercialization.md` section 10); they are for
  local research use and are never committed or redistributed.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

DATASETS_ROOT: Final = (Path(__file__).resolve().parent / "datasets").resolve()
IMAGE_SUFFIXES: Final = {".jpg", ".jpeg", ".png"}

TERMS: Final = {
    "lfw": {
        "name": "Labeled Faces in the Wild (LFW)",
        "source": "http://vis-www.cs.umass.edu/lfw/",
        "labels_by": "the dataset creators (names from the captions the photographs came with)",
        "terms": "research use; terms not verified by this project",
    },
    "celeba": {
        "name": "CelebFaces Attributes (CelebA)",
        "source": "https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html",
        "labels_by": "the dataset creators (identity_CelebA.txt)",
        "terms": "stated as non-commercial research only; not verified by this project",
    },
}


def guard(path: Path) -> Path:
    resolved = path.resolve()
    if DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


def photograph(root: Path, path: Path) -> Path | None:
    """`path` as a regular, permitted image file that really lies inside `root` (a link or a
    `..` that leaves it is refused), or None."""
    real = path.resolve()
    inside = root.resolve() in real.parents
    return real if inside and real.is_file() and real.suffix.lower() in IMAGE_SUFFIXES else None


def read_lfw(source: Path) -> dict[str, list[Path]]:
    """`<source>/<Person_Name>/<Person_Name_0001.jpg>`: the folder name is the person."""
    people: dict[str, list[Path]] = {}
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        pictures = sorted(
            real for f in folder.iterdir() if (real := photograph(source, f)) is not None
        )
        if pictures:
            people[folder.name.replace("_", " ")] = pictures
    return people


def read_celeba(source: Path) -> dict[str, list[Path]]:
    """`identity_CelebA.txt` lines `<file> <identity number>`, the images in a folder beside it
    (`img_align_celeba` or `img_celeba`, or the source itself). A line is used only when the
    identity is a plain number and the file name is a bare name of a picture inside the source."""
    table = next(source.rglob("identity_CelebA.txt"), None)
    if table is None:
        raise SystemExit(f"no identity_CelebA.txt under {source}")
    # The standard download nests the pictures once more (`Img/img_align_celeba/img_align_celeba`)
    # and keeps the table in `Anno/`, so look for the folder that holds a listed picture.
    listed = [ln.split()[0] for ln in table.read_text(encoding="utf-8").splitlines() if ln.split()]
    candidates = [source / "img_align_celeba", source / "img_celeba", table.parent]
    candidates += sorted(p for n in ("img_align_celeba", "img_celeba") for p in source.rglob(n))
    folder = next(  # (any of the first listed pictures will do: one of them may be missing)
        (c for c in candidates if c.is_dir() and any((c / n).is_file() for n in listed[:50])),
        source,
    )
    people: dict[str, list[Path]] = {}
    for line in table.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9]+", parts[1]):
            continue
        if Path(parts[0]).name != parts[0]:  # no folders, no `..`, no drive letters
            continue
        real = photograph(source, folder / parts[0])
        if real is not None:
            people.setdefault(f"identity {parts[1]}", []).append(real)
    return {name: sorted(files) for name, files in people.items()}


def select(
    people: dict[str, list[Path]], *, minimum: int, count: int, maximum: int
) -> dict[str, list[Path]]:
    """The first `count` people (stable hash order) with `minimum` or more distinct pictures, each
    capped at `maximum`. A picture used for one person is not offered to another: only the
    pictures a person actually keeps are taken from the pool."""
    if minimum < 1 or count < 1 or maximum < 1:
        raise SystemExit("--minimum, --people and --maximum must be at least 1")
    taken: set[str] = set()
    chosen: dict[str, list[Path]] = {}
    for name in sorted(people, key=lambda n: hashlib.sha256(n.encode()).hexdigest()):
        files: list[Path] = []
        digests: set[str] = set()
        for path in people[name]:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest not in taken and digest not in digests:
                digests.add(digest)
                files.append(path)
        if len(files) >= minimum:
            kept = files[:maximum]
            chosen[name] = kept
            taken |= {hashlib.sha256(path.read_bytes()).hexdigest() for path in kept}
        if len(chosen) >= count:
            break
    return chosen


def write(dataset: str, chosen: dict[str, list[Path]], out: Path) -> dict[str, Any]:
    out = guard(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty: choose a new folder, nothing is overwritten")
    manifest: dict[str, list[dict[str, str]]] = {}
    for name, files in chosen.items():
        folder = out / re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or out / "person"
        if out.resolve() not in folder.resolve().parents:
            raise SystemExit(f"{name!r} would be written outside {out}")
        folder.mkdir(parents=True)
        entries = []
        for number, path in enumerate(files):
            target = folder / f"{number:02d}{path.suffix.lower()}"
            shutil.copyfile(path, target)
            entries.append(
                {
                    "file": f"{folder.name}/{target.name}",
                    "title": path.name,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "licence": TERMS[dataset]["terms"],
                }
            )
        manifest[name] = entries
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    provenance = {
        "schema_version": 1,
        "dataset": TERMS[dataset]["name"],
        "source": TERMS[dataset]["source"],
        "labels_by": TERMS[dataset]["labels_by"],
        "label_status": "supplied by the dataset creators; NOT verified by this project",
        "terms": TERMS[dataset]["terms"],
        "imported_at": datetime.now(UTC).isoformat(),
        "people": len(manifest),
        "photographs": sum(len(v) for v in manifest.values()),
    }
    (out / "PROVENANCE.json").write_text(json.dumps(provenance, indent=1), encoding="utf-8")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=sorted(TERMS))
    parser.add_argument("--source", required=True, help="the extracted dataset folder")
    parser.add_argument("--out", help="default: evaluation/datasets/<dataset>")
    parser.add_argument("--minimum", type=int, default=5, help="pictures a person needs")
    parser.add_argument("--people", type=int, default=300)
    parser.add_argument("--maximum", type=int, default=12, help="pictures kept per person")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.is_dir():
        raise SystemExit(f"{source} is not a folder")
    people = (read_lfw if args.dataset == "lfw" else read_celeba)(source)
    chosen = select(people, minimum=args.minimum, count=args.people, maximum=args.maximum)
    if not chosen:
        raise SystemExit("no person has that many distinct pictures: lower --minimum")
    out = Path(args.out) if args.out else DATASETS_ROOT / args.dataset
    print(json.dumps(write(args.dataset, chosen, out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
