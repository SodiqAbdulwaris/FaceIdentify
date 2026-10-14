"""Collect reviewable, identity-labelled portraits from Wikimedia Commons.

    PYTHONPATH=. uv run python evaluation/collect_commons_portraits.py \
        --out evaluation/datasets/celebs-commons --licence free --per-person 15

Based on the owner's `facescrape.py` (2026-10-14), with these changes: the title filter matches
whole words; only the person's own subcategories are followed (by year, in a year, at an event;
never a pair, a group or a longer name); the face check uses the project's SCRFD detector with the
gate's dominant-subject rule instead of a Haar cascade (no new dependency, and profile faces are
not filtered out before the model sees them); a picture is de-duplicated against every person's
pictures; the licence is validated from the short name and the licence URL together; a run is
single (a lock file), pictures are published into a free name and never replaced, and a picture's
provenance is journalled *before* the picture is published, so an interrupted run is recovered;
the output must be under the Git-ignored `evaluation/datasets/`.

Why Commons: every file states its own licence in machine-readable metadata, and the API is an
allowed, rate-limited way to read it. A category name is a *candidate* identity label, not verified
ground truth, and the rights metadata still needs a human look: every record says
`identity_verified: false` and `rights_reviewed: false`.

`--licence pd` keeps public-domain and CC0 files only; `free` also keeps CC BY and CC BY-SA
(2.0 to 4.0, never NC or ND). A set made with one policy cannot be resumed with another. CC BY and
BY-SA ask for attribution (and share-alike for adaptations): the manifest keeps author, licence
and source page, which is provenance and not a statement of compliance for any future sharing; the
files stay local and are never redistributed. `--dry-run` reads metadata only (no pictures).

**What this set can and cannot show.** A picture is kept only if SCRFD finds one dominant face of
at least `--min-face` pixels, so every detector miss and every crowded or tiny-face picture is
absent by construction. The set therefore cannot measure detector recall or unfiltered end-to-end
performance; it is for identity-matching experiments on pictures where a subject is found. The
filter configuration and the rejection counts are recorded in `PROVENANCE.json`.

People: `--people-file` takes one name per line; `Display Name = Commons Category` when they differ
(for example `Chris Evans = Chris Evans (actor)`). Output layout and manifest match the other
evaluation tools (`<Person_Name>/001.jpg`, `manifest.json`), so `label_review.py` reads it.
"""

import argparse
import contextlib
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
from collections import Counter, deque
from collections.abc import Iterator
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
MAX_CATEGORIES = 70  # per person: a bound, so a wide category cannot start an endless crawl
DOMINANCE = 2.5  # the gate's rule: the subject face is at least this many times the next one
JOURNAL = "collect-journal.jsonl"
LOCK = ".collect.lock"
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
    "Tom Holland", "Chadwick Boseman"
]  # fmt: skip
_BAD_WORDS = (
    "signatures?", "autographs?", "logos?", "posters?", "covers?", "albums?", "costumes?",
    "dress(?:es)?", "outfits?", "shoes?", "handbags?", "wax figures?", "statues?", "drawings?",
    "illustrations?", "caricatures?", "screenshots?", "film stills?", "collages?", "montages?",
    "graffiti", "audio", "icons?", "svg", "star on", "walk of fame", "cosplay(?:er)?s?",
    "as character",
)  # fmt: skip
BAD = re.compile(r"\b(?:" + "|".join(_BAD_WORDS) + r")\b", re.IGNORECASE)
# a category that holds more than the person: a pair, a group, a list
PAIR = re.compile(r"&|,|\b(?:and|with|family|fans|wife|husband|friends|cast)\b", re.IGNORECASE)
# what may follow the person's name in a subcategory that holds photographs of them
SUFFIX = re.compile(
    r"^ (?:by (?:year|decade|event|location)|in (?:19|20)\d\d|at [^,&]+)$", re.IGNORECASE
)
PD_NAME = re.compile(r"^(?:public domain|pd-[a-z0-9_-]+|cc0(?: 1\.0)?)$", re.IGNORECASE)
CC_NAME = re.compile(
    r"^cc (?P<family>by(?:-sa)?) (?P<version>[234]\.[05])"
    r"(?: (?:generic|unported|[a-z]{2}(?:-[a-z]{2})?))?$",
    re.IGNORECASE,
)
CC_URL = re.compile(
    r"^https?://creativecommons\.org/licenses/(?P<family>by(?:-sa)?)/(?P<version>[234]\.[05])(?:/|$)",
    re.IGNORECASE,
)
PD_URL = re.compile(r"^https?://creativecommons\.org/publicdomain/", re.IGNORECASE)
RESTRICTED = re.compile(r"(?:^|[ /-])(?:nc|nd)(?:$|[ /-])", re.IGNORECASE)


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
    """Is `title` a subcategory that holds photographs of this person alone? Its name must be the
    person's name (with or without the disambiguation) followed by one of the allowed forms, or
    `Portraits of` / `Photographs of` the name; never a longer name, a pair or a list."""
    name = title.removeprefix("Category:")
    if BAD.search(name) or PAIR.search(name):
        return False
    for known in {category, base_name(category)}:
        escaped = re.escape(known)
        if re.fullmatch(rf"(?:portraits?|photographs?) of {escaped}", name, re.IGNORECASE):
            return True
        if name.lower().startswith(known.lower()) and SUFFIX.fullmatch(name[len(known) :]):
            return True
    return False


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
    """Accept a file only when the short name and the licence URL agree and are free. A Creative
    Commons licence must come from creativecommons.org, family and version must match, and a name
    or URL that mentions NC or ND is refused."""
    name = md(metadata, "LicenseShortName")
    url = md(metadata, "LicenseUrl")
    if not name or md(metadata, "NonFree").lower() == "true":
        return False
    if RESTRICTED.search(name) or RESTRICTED.search(url):
        return False
    if PD_NAME.fullmatch(name):
        flagged_free = md(metadata, "Copyrighted").lower() == "false"
        if url and not PD_URL.match(url):
            return False
        return flagged_free or bool(PD_URL.match(url))
    if policy == "pd":
        return False
    by_name, by_url = CC_NAME.fullmatch(name), CC_URL.match(url)
    if not by_name or not by_url:
        return False
    return by_name.group("family").lower() == by_url.group("family").lower() and by_name.group(
        "version"
    ) == by_url.group("version")


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
    if len(ranked) > 1 and box_area(ranked[0]) < DOMINANCE * box_area(ranked[1]):
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


def is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def confine(root: Path, path: Path) -> Path:
    """`path` as it really is on disk must be inside `root` and must not itself be a link or a
    junction (a person folder that is one would carry writes out of the datasets folder)."""
    if is_link(path):
        raise SystemExit(f"{path} is a link or junction: not followed")
    real = path.resolve()
    if real != root and root not in real.parents:
        raise SystemExit(f"{path} leads outside {root}")
    return real


def write_atomic(path: Path, data: bytes) -> None:
    """Replace a metadata file: an exclusive, uniquely named temporary file, then a move."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
    os.replace(temporary, path)


def publish_picture(folder: Path, data: bytes) -> str:
    """Write a picture under the next free number and return its name. The name is taken with a
    hard link, which refuses an existing file: an existing picture is never replaced."""
    temporary = folder / f".{uuid.uuid4().hex[:8]}.tmp"
    with temporary.open("xb") as handle:
        handle.write(data)
    try:
        taken = {p.name.lower() for p in folder.iterdir()}
        numbers = [
            int(p.stem) for p in folder.iterdir() if p.suffix.lower() == ".jpg" and p.stem.isdigit()
        ]
        number = max(numbers, default=0) + 1
        for _ in range(1000):
            name = f"{number:03d}.jpg"
            if name.lower() not in taken:
                try:
                    os.link(temporary, folder / name)
                    return name
                except FileExistsError:
                    pass
                except OSError:  # no hard links here: a rename, which refuses on Windows
                    if not (folder / name).exists():
                        os.rename(temporary, folder / name)
                        return name
            number += 1
        raise SystemExit(f"no free picture number in {folder}")
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def single_run(out: Path) -> Iterator[None]:
    """One collection at a time on a folder: an exclusive lock file, removed at the end."""
    lock = out / LOCK
    try:
        with lock.open("xb") as handle:
            handle.write(str(os.getpid()).encode())
    except FileExistsError:
        raise SystemExit(
            f"{lock} exists: another run is in progress (delete it if none is)"
        ) from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


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


def journal_append(out: Path, record: dict[str, Any]) -> None:
    with (out / JOURNAL).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def recover(out: Path, manifest: dict[str, list[dict[str, Any]]]) -> int:
    """Records that were journalled and whose picture reached the disk but not the manifest (an
    interrupted run) are added to the manifest. Returns how many were recovered."""
    path = out / JOURNAL
    if not path.is_file():
        return 0
    have = {r["file"] for records in manifest.values() for r in records}
    added = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn last line
        file = record.get("file", "")
        target = out / file
        if not file or file in have or is_link(target) or not target.is_file():
            continue
        confine(out, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != record.get("sha256"):
            continue
        manifest.setdefault(record["person"], []).append(record)
        have.add(file)
        added += 1
    return added


def policy_conflict(manifest: dict[str, list[dict[str, Any]]], requested: str) -> str | None:
    """Why this set cannot be resumed with the requested licence policy, if it cannot."""
    for records in manifest.values():
        for record in records:
            if requested == "pd" and record.get("licence_policy") == "free":
                return "this set already holds CC BY / CC BY-SA files: use another --out for 'pd'"
    return None


def known_hashes(out: Path) -> list[int]:
    """The perceptual hash of every picture already in the set, for every person."""
    found: list[int] = []
    for path in sorted(out.glob("*/[0-9][0-9][0-9]*.jpg")):
        if is_link(path):
            continue
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
    stats: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    stats = stats if stats is not None else Counter()
    folder = out / slug(display)
    folder.mkdir(parents=True, exist_ok=True)
    confine(out, folder)
    saved: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for record in manifest.get(display, []):
        path = out / record.get("file", "")
        if is_link(path) or not path.is_file() or path.parent.resolve() != folder.resolve():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha256"):
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
            if info.get("mime") != "image/jpeg":
                stats["rejected_not_jpeg"] += 1
                continue
            if not license_ok(meta, args.licence):
                stats["rejected_licence"] += 1
                continue
            url = info.get("thumburl") or info.get("url")
            if not url or min(info.get("width", 0), info.get("height", 0)) < args.min_dimension:
                stats["rejected_size"] += 1
                continue
            allowed += 1
            if args.dry_run:
                continue
            try:
                data = get_bytes(url)
                with Image.open(io.BytesIO(data)) as original:
                    image = ImageOps.exif_transpose(original).convert("RGB")
                if min(image.size) < args.min_dimension:
                    stats["rejected_size"] += 1
                    continue
                faces = detector.faces(np.asarray(image, dtype=np.uint8))
                if not subject_ok(faces, image.width, image.height, args.min_face):
                    stats["rejected_no_dominant_face"] += 1
                    continue
                phash = perceptual_hash(image)
                if any((phash ^ old).bit_count() <= args.hash_distance for old in hashes):
                    stats["rejected_duplicate"] += 1
                    continue  # the same picture, for this person or any other
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=92, optimize=True)
                saved_bytes = buffer.getvalue()
                digest = hashlib.sha256(saved_bytes).hexdigest()
                numbers = [
                    int(p.stem)
                    for p in folder.iterdir()
                    if p.suffix.lower() == ".jpg" and p.stem.isdigit()
                ]
                record = {
                    "file": f"{folder.name}/{max(numbers, default=0) + 1:03d}.jpg",
                    "person": display, "commons_category": category,
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
                    "sha256": digest,
                    "width": image.width, "height": image.height, "faces_detected": len(faces),
                    "identity_verified": False, "rights_reviewed": False,
                }  # fmt: skip
                # the provenance first: if the run stops after the picture, the next run recovers it
                journal_append(out, record)
                name = publish_picture(folder, saved_bytes)
                record["file"] = f"{folder.name}/{name}"
                hashes.append(phash)
                seen_sources.add(title)
                saved.append(record)
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
                stats["errors"] += 1
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
    for display, category in people:
        if not display or not category or not slug(display):
            raise SystemExit(
                f"{display!r} / {category!r}: needs a name with Latin letters or digits"
            )
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
    if args.dry_run:
        return run(args, out, people, None)
    with single_run(out):
        return run(args, out, people, Detector(args.local_state_root))


def run(
    args: argparse.Namespace,
    out: Path,
    people: list[tuple[str, str]],
    detector: Any,
) -> int:
    manifest = load_manifest(out)
    if not args.dry_run:
        recovered = recover(out, manifest)
        if recovered:
            print(f"recovered {recovered} picture(s) from an interrupted run")
    conflict = policy_conflict(manifest, args.licence)
    if conflict:
        raise SystemExit(conflict)
    hashes = known_hashes(out)
    stats: Counter[str] = Counter()
    total = 0
    for display, category in people:
        try:
            result = collect(display, category, args, out, manifest, hashes, detector, stats)
            total += len(result)
            print(f"{display}: {len(result)}/{args.per_person} images")
        except Exception as error:  # noqa: BLE001 - one person failing must not stop the rest
            print(f"{display}: failed ({error})")
    if not args.dry_run:
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        write_atomic(out / "manifest.json", manifest_bytes)
        provenance = {
            "schema_version": 1,
            "dataset": "Portraits of well-known people from Wikimedia Commons categories",
            "source": "https://commons.wikimedia.org (per-file licence in the manifest)",
            "labels_by": "the Commons category of the person (candidate labels)",
            "label_status": "NOT verified by this project; review with label_review.py",
            "licence_policy": args.licence,
            "terms": "licence per file in the manifest; local evaluation only; not redistributed",
            "selection": {
                "detector": "SCRFD (insightface-buffalo-l, CPU)",
                "rule": f"one dominant face (at least {DOMINANCE} times the next)",
                "min_face_px": args.min_face,
                "min_dimension_px": args.min_dimension,
                "hash_distance": args.hash_distance,
                "note": "pictures with no dominant face are absent by construction: this set "
                "cannot measure detector recall or unfiltered end-to-end performance",
                "rejected_in_the_last_run": dict(stats),
            },
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "people": len(manifest),
            "photographs": sum(len(v) for v in manifest.values()),
        }
        write_atomic(out / "PROVENANCE.json", json.dumps(provenance, indent=2).encode("utf-8"))
    print(f"{total} images across {len(people)} people. Review every image and licence.")
    if stats:
        print("rejected: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
