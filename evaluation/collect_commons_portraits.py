"""Collect reviewable, identity-labelled portraits from Wikimedia Commons.

    PYTHONPATH=. uv run python evaluation/collect_commons_portraits.py \
        --out evaluation/datasets/celebs-commons --licence free --per-person 15

Based on the owner's `facescrape.py` (2026-10-14), with these changes: the title filter matches
whole words; only subcategories of the person's own name are followed (never "X and Y"); the
face check uses the project's SCRFD detector with the gate's dominant-subject rule instead of a Haar
cascade (no new dependency, and profile faces are not filtered out before the model sees them); a
picture is de-duplicated against every person's pictures, not just their own; files are written
atomically and never overwritten; and the output must be under the Git-ignored
`evaluation/datasets/`.

Why Commons: every file states its own licence in machine-readable metadata, and the API is an
allowed, rate-limited way to read it. A category name is a *candidate* identity label, not verified
ground truth, and the rights metadata still needs a human look: every record says
`identity_verified: false` and `rights_reviewed: false`.

`--licence pd` keeps public-domain and CC0 files only; `free` also keeps CC BY and CC BY-SA
(2.0 to 4.0, never NC or ND). CC BY and BY-SA ask for attribution (and share-alike for
adaptations): the manifest keeps author, licence and source page; the files stay local and are never
redistributed. `--dry-run` reads the metadata only and downloads no picture.

People: `--people-file` takes one name per line; `Display Name = Commons Category` when they differ
(for example `Chris Evans = Chris Evans (actor)`). Output layout and manifest match the other
evaluation tools (`<Person_Name>/001.jpg`, `manifest.json`), so `label_review.py` reads it.
"""

import argparse
import hashlib
import html
import io
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

API = "https://commons.wikimedia.org/w/api.php"
AGENT = (
    "FaceIdentifyEvaluation/0.3 (personal local research project; "
    "https://github.com/SodiqAbdulwaris/FaceIdentify)"
)
DATASETS_ROOT = (Path(__file__).resolve().parent / "datasets").resolve()
PROVISIONAL_MAX_PIXELS = 100_000_000
MAX_CATEGORIES = 70  # per person: a bound, so a wide category cannot start an endless crawl
PEOPLE = [
    "Jason Statham", "Dwayne Johnson", "Jennifer Lawrence", "Jennifer Lopez",
    "Jenna Ortega", "Zendaya", "Tom Hanks", "Vin Diesel", "Kevin Hart",
    "Mark Wahlberg", "Morgan Freeman", "Leonardo DiCaprio", "Idris Elba",
    "Will Smith", "Lady Gaga", "Selena Gomez", "Brad Pitt", "Keanu Reeves",
    "Natalie Portman", "Emma Stone", "Angelina Jolie", "Tom Cruise",
    "Taylor Swift", "Scarlett Johansson", "Margot Robbie", "Emma Watson",
    "Rihanna", "Beyoncé", "Ariana Grande", "Chris Hemsworth", "Henry Cavill",
    "Ryan Reynolds", "Zoe Saldaña", "Gal Gadot", "Anne Hathaway",
    "Robert Downey Jr.", "Chris Evans = Chris Evans (actor)", "Michael B. Jordan",
]  # fmt: skip
_BAD_WORDS = (
    "signatures?",
    "autographs?",
    "logos?",
    "posters?",
    "covers?",
    "albums?",
    "costumes?",
    "dress(?:es)?",
    "outfits?",
    "shoes?",
    "handbags?",
    "wax figures?",
    "statues?",
    "drawings?",
    "illustrations?",
    "caricatures?",
    "screenshots?",
    "film stills?",
    "collages?",
    "montages?",
    "graffiti",
    "audio",
    "icons?",
    "svg",
    "star on",
    "walk of fame",
    "cosplay(?:er)?s?",
    "as character",
)
BAD = re.compile(r"\b(?:" + "|".join(_BAD_WORDS) + r")\b", re.IGNORECASE)
PD = re.compile(r"^(public domain|pd-[a-z0-9_-]+|cc0(?: 1\.0)?)$", re.IGNORECASE)
CC = re.compile(r"^cc by(?:-sa)?(?: [234]\.[05](?: [a-z-]+)?)?$", re.IGNORECASE)
# a subcategory that holds photographs of the person themselves, never of a pair or a group
WANTED = re.compile(
    r"\bby (?:year|decade|event|location)\b|\bin (?:19|20)\d\d\b|\bat\b", re.IGNORECASE
)
PAIR = re.compile(r"\b(?:and|with|&|family|fans|wife|husband|friends|cast)\b", re.IGNORECASE)


def get_bytes(url: str, *, retries: int = 5) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": AGENT, "Accept": "application/json,image/*"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310 (https)
                data: bytes = response.read()
            time.sleep(0.5)
            return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            delay = error.headers.get("Retry-After", "")
            time.sleep(min(120, int(delay)) if delay.isdigit() else 3 * (attempt + 1) ** 2)
    raise RuntimeError("retries exhausted")


def api(**params: Any) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"action": "query", "format": "json", "formatversion": 2, **params}
    )
    response = json.loads(get_bytes(f"{API}?{query}"))
    if "error" in response:
        raise RuntimeError(str(response["error"]))
    result: dict[str, Any] = response
    return result


def members(category: str, member_type: str, maximum: int) -> list[str]:
    result: list[str] = []
    cursor: dict[str, Any] = {}
    while len(result) < maximum:
        response = api(
            list="categorymembers", cmtitle=category, cmtype=member_type, cmlimit=100, **cursor
        )
        result.extend(x["title"] for x in response.get("query", {}).get("categorymembers", []))
        cursor = response.get("continue", {})
        if not cursor:
            break
    return result[:maximum]


def parse_person(entry: str) -> tuple[str, str]:
    """`Display Name` or `Display Name = Commons Category` as (display name, category name)."""
    display, _, category = entry.partition("=")
    display = display.strip()
    return display, (category.strip() or display)


def base_name(category: str) -> str:
    """The category name without a trailing disambiguation, like ` (actor)`."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", category).strip()


def follows(category: str, title: str) -> bool:
    """Is `title` a subcategory that holds photographs of this person? Only categories that start
    with the person's own name (or Portraits/Photographs of it) and are about them alone."""
    name = title.removeprefix("Category:")
    base = base_name(category)
    own = name.lower().startswith(base.lower()) or bool(
        re.match(rf"(?:portraits?|photographs?) of {re.escape(base)}\b", name, re.IGNORECASE)
    )
    if not own or BAD.search(name) or PAIR.search(name.removeprefix(base)):
        return False
    return WANTED.search(name) is not None or name.lower().startswith(
        ("portraits of", "photographs of")
    )


def candidates(category: str, depth: int, max_files: int, reader: Any = None) -> list[str]:
    """File titles in the person's category and its person-only subcategories, filtered."""
    read = reader or members
    queue: deque[tuple[str, int]] = deque([(f"Category:{category}", 0)])
    visited: set[str] = set()
    files: set[str] = set()
    while queue and len(files) < max_files:
        current, level = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for title in read(current, "file", min(500, max_files - len(files))):
            if not BAD.search(title):
                files.add(title)
        if level < depth:
            subcats = read(current, "subcat", 150)
            # photographs by year tend to be the highest-yield source of varied portraits
            subcats.sort(key=lambda s: ("by year" not in s.lower(), s.lower()))
            for sub in subcats:
                if follows(category, sub) and len(visited) + len(queue) < MAX_CATEGORIES:
                    queue.append((sub, level + 1))
    return sorted(files)


def md(metadata: dict[str, Any], key: str) -> str:
    raw = str(metadata.get(key, {}).get("value", ""))
    return html.unescape(re.sub(r"<[^>]*>", "", raw)).strip()


def license_ok(metadata: dict[str, Any], policy: str) -> bool:
    name = md(metadata, "LicenseShortName")
    url = md(metadata, "LicenseUrl").lower()
    copyright_flag = md(metadata, "Copyrighted").lower()
    if not name or md(metadata, "NonFree").lower() == "true":
        return False
    # Commons metadata can be imperfect or ambiguous: the file page still needs a look.
    is_pd = bool(PD.fullmatch(name)) and (
        copyright_flag == "false"
        or "publicdomain" in url
        or "creativecommons.org/publicdomain" in url
    )
    if is_pd:
        return True
    if policy == "pd":
        return False
    return bool(CC.fullmatch(name)) and "creativecommons.org/licenses/" in url


def info_pages(titles: list[str]) -> list[dict[str, Any]]:
    response = api(
        titles="|".join(titles), prop="imageinfo", iiurlwidth=1200,
        iiprop="url|mime|size|extmetadata|sha1|timestamp",
    )  # fmt: skip
    pages: list[dict[str, Any]] = response.get("query", {}).get("pages", [])
    return pages


def box_area(face: dict[str, Any]) -> float:
    x0, y0, x1, y1 = face["box"]
    return float((x1 - x0) * (y1 - y0))


def subject_ok(faces: list[dict[str, Any]], width: int, height: int, minimum: int) -> bool:
    """One dominant face (the gate's rule: at least 2.5 times the next) and big enough to use."""
    if not faces:
        return False
    ranked = sorted(faces, key=box_area, reverse=True)
    if len(ranked) > 1 and box_area(ranked[0]) < 2.5 * box_area(ranked[1]):
        return False
    x0, y0, x1, y1 = ranked[0]["box"]
    return bool(min((x1 - x0) * width, (y1 - y0) * height) >= minimum)


def perceptual_hash(image: Image.Image) -> int:
    small = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    a = np.asarray(small, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).ravel()
    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def slug(person: str) -> str:
    plain = unicodedata.normalize("NFKD", person).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_")


def write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


class Detector:
    """The project's SCRFD detector, run in this process (no library, no policy)."""

    def __init__(self, local_state_root: Path) -> None:
        from backend.app.runtime.package_store import RuntimePackageStore
        from backend.infrastructure.storage.layout import StorageRoots
        from backend.ml.worker.onnx_session import load_session
        from scripts.smoke_real_models import plan_from

        store = RuntimePackageStore(StorageRoots(Path(), local_state_root), new_id=uuid.uuid4)
        plan = plan_from(store, "insightface-buffalo-l", ["CPUExecutionProvider"])
        variant = plan.detector[0]
        self.session = load_session(variant.model_path, variant.sha256, variant.provider)
        self.input_name = self.session.get_inputs()[0].name

    def faces(self, pixels: np.ndarray) -> list[dict[str, Any]]:
        from evaluation.analyse_exclusions import look

        kept: list[dict[str, Any]] = look(self.session, self.input_name, pixels)["kept"]
        return kept


def load_manifest(out: Path) -> dict[str, list[dict[str, Any]]]:
    path = out / "manifest.json"
    if not path.is_file():
        return {}
    manifest: dict[str, list[dict[str, Any]]] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def known_hashes(out: Path) -> list[int]:
    """The perceptual hash of every picture already in the set, for every person."""
    found: list[int] = []
    for path in sorted(out.glob("*/[0-9][0-9][0-9]*.jpg")):
        try:
            with Image.open(path) as image:
                found.append(perceptual_hash(ImageOps.exif_transpose(image)))
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    return found


def collect(
    display: str,
    category: str,
    args: argparse.Namespace,
    out: Path,
    manifest: dict[str, list[dict[str, Any]]],
    hashes: list[int],
    detector: Any,
) -> list[dict[str, Any]]:
    folder = out / slug(display)
    folder.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for record in manifest.get(display, []):
        path = out / record.get("file", "")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha256"):
            saved.append(record)
            seen_sources.add(record.get("title", ""))
    if len(saved) >= args.per_person:
        return saved[: args.per_person]

    titles = candidates(category, args.depth, args.max_candidates)
    # stable order across reruns, while spreading candidates beyond the first category page
    titles.sort(key=lambda x: hashlib.sha256(x.encode("utf-8")).digest())
    allowed = 0
    for start in range(0, len(titles), 20):
        if len(saved) >= args.per_person:
            break
        try:
            pages = info_pages(titles[start : start + 20])
        except Exception as error:  # noqa: BLE001 - one bad batch must not stop the person
            print(f"  metadata batch error: {error}")
            continue
        for page in pages:
            if len(saved) >= args.per_person:
                break
            title = page.get("title", "")
            if title in seen_sources:
                continue
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            if info.get("mime") != "image/jpeg" or not license_ok(meta, args.licence):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url or min(info.get("width", 0), info.get("height", 0)) < args.min_dimension:
                continue
            allowed += 1
            if args.dry_run:
                continue
            try:
                data = get_bytes(url)
                with Image.open(io.BytesIO(data)) as original:
                    image = ImageOps.exif_transpose(original).convert("RGB")
                if min(image.size) < args.min_dimension:
                    continue
                faces = detector.faces(np.asarray(image, dtype=np.uint8))
                if not subject_ok(faces, image.width, image.height, args.min_face):
                    continue
                phash = perceptual_hash(image)
                if any((phash ^ old).bit_count() <= args.hash_distance for old in hashes):
                    continue  # the same picture, for this person or any other
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=92, optimize=True)
                saved_bytes = buffer.getvalue()
                numbers = [
                    int(p.stem)
                    for p in folder.iterdir()
                    if p.suffix.lower() == ".jpg" and p.stem.isdigit()
                ]
                filename = f"{max(numbers, default=0) + 1:03d}.jpg"
                write_atomic(folder / filename, saved_bytes)
                hashes.append(phash)
                seen_sources.add(title)
                saved.append(
                    {
                        "file": f"{folder.name}/{filename}", "person": display,
                        "commons_category": category,
                        "title": title, "source_page": info.get("descriptionurl", ""),
                        "download_url": url, "original_url": info.get("url", ""),
                        "commons_original_sha1": info.get("sha1", ""),
                        "licence": md(meta, "LicenseShortName"),
                        "licence_url": md(meta, "LicenseUrl"),
                        "licence_policy": args.licence,
                        "usage_terms": md(meta, "UsageTerms"),
                        "author": md(meta, "Artist"), "credit": md(meta, "Credit"),
                        "attribution": md(meta, "Attribution"),
                        "copyrighted": md(meta, "Copyrighted"),
                        "restrictions": meta.get("Restrictions", {}).get("value", []),
                        "date_original": md(meta, "DateTimeOriginal"),
                        "commons_revision_time": info.get("timestamp", ""),
                        "acquired_at": datetime.now(UTC).isoformat(),
                        "sha256": hashlib.sha256(saved_bytes).hexdigest(),
                        "width": image.width, "height": image.height, "faces_detected": len(faces),
                        "identity_verified": False, "rights_reviewed": False,
                    }
                )  # fmt: skip
                manifest[display] = saved
                write_atomic(
                    out / "manifest.json",
                    json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
                )
            except (
                OSError,
                ValueError,
                urllib.error.URLError,
                Image.DecompressionBombError,
            ) as error:
                print(f"  rejected/error: {title}: {error}")
    if args.dry_run:
        print(f"  {len(titles)} candidate files, {allowed} with an accepted licence and size")
    return saved


def read_people(path: Path | None) -> list[tuple[str, str]]:
    if path is None:
        entries = PEOPLE
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = [s.strip() for s in lines if s.strip() and not s.lstrip().startswith("#")]
    people = [parse_person(e) for e in dict.fromkeys(entries)]
    folders = [slug(d).lower() for d, _ in people]
    if len(set(folders)) != len(folders):
        raise SystemExit("two people would share a folder name (case and accents aside)")
    return people


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-person", type=int, default=15)
    parser.add_argument("--licence", choices=("pd", "free"), default="pd")
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--max-candidates", type=int, default=400)
    parser.add_argument("--min-dimension", type=int, default=400)
    parser.add_argument("--min-face", type=int, default=75, help="the dominant face's short side")
    parser.add_argument("--hash-distance", type=int, default=5)
    parser.add_argument("--people-file", type=Path)
    parser.add_argument("--local-state-root", type=Path, default=Path("local-models/state"))
    parser.add_argument("--dry-run", action="store_true", help="metadata only: download nothing")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if DATASETS_ROOT not in out.parents:
        parser.error(f"--out must be a subdirectory of {DATASETS_ROOT} (Git-ignored)")
    if args.per_person < 1 or args.depth < 0 or args.max_candidates < 1:
        parser.error("invalid target, depth or candidate limit")
    people = read_people(args.people_file)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out)
    hashes = known_hashes(out)
    detector = None if args.dry_run else Detector(args.local_state_root)
    total = 0
    for display, category in people:
        try:
            result = collect(display, category, args, out, manifest, hashes, detector)
            total += len(result)
            print(f"{display}: {len(result)}/{args.per_person} images")
        except Exception as error:  # noqa: BLE001 - one person failing must not stop the rest
            print(f"{display}: failed ({error})")
    if not args.dry_run:
        write_atomic(
            out / "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        provenance = {
            "schema_version": 1,
            "dataset": "Portraits of well-known people from Wikimedia Commons categories",
            "source": "https://commons.wikimedia.org (per-file licence in the manifest)",
            "labels_by": "the Commons category of the person (candidate labels)",
            "label_status": "NOT verified by this project; review with label_review.py",
            "licence_policy": args.licence,
            "terms": "licence per file in the manifest; local evaluation only; not redistributed",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "people": len(manifest),
            "photographs": sum(len(v) for v in manifest.values()),
        }
        write_atomic(out / "PROVENANCE.json", json.dumps(provenance, indent=2).encode("utf-8"))
    print(f"{total} images across {len(people)} people. Review every image and licence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
