"""Build a small, identity-labelled evaluation set from public-domain Wikimedia Commons photographs.

    uv run python evaluation/build_commons_dataset.py --out evaluation/datasets/commons-pd

Why this source: the licence of every photograph is read per file from Commons' own metadata and
only an allow-listed public-domain status is kept (US government works), the identity label is the
Commons category of the person (a human-curated label, not a verified one), and several photographs
of one person taken years apart are common. For each kept file the manifest records the exact
licence name and URL, the author and credit, the source page, the acquisition date and the SHA-256
of the downloaded bytes, so the rights and the contents can be re-checked later.

Nothing is committed: the output must be under `evaluation/datasets/` (Git-ignored), because the
photographs are biometric data; any other `--out` is refused. The set is a development calibration
aid, not a benchmark: it is small, skewed toward adults photographed formally, and its labels are
only as good as Commons' categories.

Needs network access to commons.wikimedia.org. Each request is polite (a user agent and a pause).
"""

import argparse
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API = "https://commons.wikimedia.org/w/api.php"
AGENT = "FaceIdentifyEvaluation/0.1 (personal development project; local use)"
DATASETS_ROOT = (Path(__file__).resolve().parent / "datasets").resolve()
# Exact public-domain statuses accepted (lower case); `pd-usgov*` covers US federal works.
EXACT_STATUSES = {"public domain"}
STATUS_PREFIXES = ("pd-usgov",)
# People with many public-domain official photographs (astronauts, US officials, military).
PEOPLE = [
    "Eileen Collins", "Sally Ride", "Neil Armstrong", "Buzz Aldrin", "John Glenn",
    "Mae Jemison", "Peggy Whitson", "Scott Kelly", "Mark Kelly", "Sunita Williams",
    "Jessica Meir", "Christina Koch", "Kathryn D. Sullivan", "Story Musgrave",
    "Bruce McCandless II", "Alan Shepard", "Jim Lovell", "John Young (astronaut)",
    "Eugene Cernan", "Pete Conrad", "Michael Collins (astronaut)", "Charles Duke",
    "Barack Obama", "George W. Bush", "Hillary Clinton", "Joe Biden", "Michelle Obama",
    "Colin Powell", "Condoleezza Rice", "Donald Rumsfeld", "Dick Cheney", "Jimmy Carter",
    "Ronald Reagan", "Bill Clinton", "Robert Gates", "Leon Panetta", "John Kerry",
    "Madeleine Albright", "Janet Napolitano", "Ash Carter",
    "Nancy Pelosi", "Mitch McConnell", "Chuck Schumer", "Bernie Sanders", "Elizabeth Warren",
    "John McCain", "Mitt Romney", "Paul Ryan", "Kamala Harris", "Mike Pence",
    "Antony Blinken", "Lloyd Austin", "Mark Milley", "David Petraeus", "Jim Mattis",
    "Eric Holder", "Janet Yellen", "Ben Bernanke", "Alan Greenspan", "Timothy Geithner",
    "Sonia Sotomayor", "Elena Kagan", "John Roberts", "Ruth Bader Ginsburg", "Stephen Breyer",
    "Clarence Thomas", "Samuel Alito", "Antonin Scalia", "Sandra Day O'Connor",
    "Al Gore", "Gerald Ford", "George H. W. Bush", "Richard Nixon", "Lyndon B. Johnson",
    "Dwight D. Eisenhower", "Harry S. Truman", "Henry Kissinger", "Chuck Hagel", "Tom Vilsack",
]  # fmt: skip


def get(url: str) -> bytes:
    """One GET, politely: it waits and retries when Commons says "too many requests"."""
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (https)
                data: bytes = response.read()
            time.sleep(1.0)
            return data
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            time.sleep(30 * (attempt + 1))
    raise AssertionError("unreachable")


def api(**params: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"format": "json", **params})
    result: dict[str, Any] = json.loads(get(f"{API}?{query}"))
    return result


def public_domain(metadata: dict[str, Any]) -> bool:
    name = str(metadata.get("LicenseShortName", {}).get("value", "")).strip().lower()
    return name in EXACT_STATUSES or name.startswith(STATUS_PREFIXES)


def plain(metadata: dict[str, Any], key: str) -> str:
    """A metadata value as text: Commons returns small HTML fragments."""
    value = str(metadata.get(key, {}).get("value", ""))
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def photographs(person: str, limit: int) -> list[dict[str, Any]]:
    """Public-domain JPEG photographs in the person's category, with their rights metadata."""
    members = api(
        action="query", list="categorymembers", cmtitle=f"Category:{person}",
        cmtype="file", cmlimit="250",
    )["query"]["categorymembers"]  # fmt: skip
    found: list[dict[str, Any]] = []
    for start in range(0, len(members), 25):
        titles = "|".join(m["title"] for m in members[start : start + 25])
        pages = api(
            action="query", titles=titles, prop="imageinfo",
            iiprop="url|mime|extmetadata", iiurlwidth="900",
        ).get("query", {}).get("pages", {})  # fmt: skip
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            metadata = info.get("extmetadata", {})
            if info.get("mime") == "image/jpeg" and public_domain(metadata):
                found.append(
                    {
                        "title": page["title"],
                        "url": info["thumburl"],
                        "source_page": info.get("descriptionurl", ""),
                        "licence": plain(metadata, "LicenseShortName"),
                        "licence_url": plain(metadata, "LicenseUrl"),
                        "usage_terms": plain(metadata, "UsageTerms"),
                        "author": plain(metadata, "Artist"),
                        "credit": plain(metadata, "Credit"),
                    }
                )
    return found[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-person", type=int, default=24)
    parser.add_argument("--minimum", type=int, default=4, help="people with fewer are dropped")
    arguments = parser.parse_args()
    out = arguments.out.resolve()
    if out != DATASETS_ROOT and DATASETS_ROOT not in out.parents:
        raise SystemExit(
            f"--out must be under {DATASETS_ROOT} (Git-ignored): photographs are private"
        )
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict[str, Any]]] = {}
    for person in PEOPLE:
        try:
            items = photographs(person, arguments.per_person)
        except Exception as error:  # noqa: BLE001 - one person failing must not stop the rest
            print(f"{person}: skipped ({error})")
            continue
        if len(items) < arguments.minimum:
            print(f"{person}: only {len(items)} public-domain photographs, dropped")
            continue
        folder = out / re.sub(r"[^A-Za-z0-9]+", "_", person).strip("_")
        folder.mkdir(exist_ok=True)
        saved = []
        for number, item in enumerate(items):
            path = folder / f"{number:02d}.jpg"
            try:
                if not path.exists():
                    path.write_bytes(get(item["url"]))
            except Exception as error:  # noqa: BLE001
                print(f"  {item['title']}: not downloaded ({error})")
                continue
            saved.append(
                {
                    "file": f"{folder.name}/{path.name}",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "acquired_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    **item,
                }
            )
        manifest[person] = saved
        print(f"{person}: {len(saved)} photographs")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{sum(len(v) for v in manifest.values())} photographs of {len(manifest)} people")


if __name__ == "__main__":
    main()
