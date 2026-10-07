"""Build a small, identity-labelled evaluation set from public-domain Wikimedia Commons photographs.

    uv run python evaluation/build_commons_dataset.py --out evaluation/datasets/commons-pd

Why this source: the licence of every photograph is checked per file from Commons' own metadata and
only public-domain ones are kept (US government works and similar), the identity label is the
Commons category of the person (a human-curated label), and several photographs of one person taken
years apart are common. Nothing is committed: `evaluation/datasets/` is Git-ignored, because the
photographs are biometric data. The set is a development calibration aid, not a benchmark: it is
small, skewed toward adults photographed formally, and its limits are recorded with the policy it
produces.

Needs network access to commons.wikimedia.org. Each download is polite (a user agent and a pause).
"""

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
AGENT = "FaceIdentifyEvaluation/0.1 (personal development project; local use)"
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
]  # fmt: skip


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (https only)
        data: bytes = response.read()
    return data


def api(**params: str) -> dict:  # type: ignore[type-arg]
    query = urllib.parse.urlencode({"format": "json", **params})
    result: dict = json.loads(get(f"{API}?{query}"))  # type: ignore[type-arg]
    return result


def public_domain(metadata: dict) -> bool:  # type: ignore[type-arg]
    name = str(metadata.get("LicenseShortName", {}).get("value", "")).lower()
    return name.startswith("public domain") or name.startswith("pd")


def photographs(person: str, limit: int) -> list[dict]:  # type: ignore[type-arg]
    """Public-domain JPEG photographs in the person's category (title, 900 px URL, licence)."""
    members = api(
        action="query", list="categorymembers", cmtitle=f"Category:{person}",
        cmtype="file", cmlimit="60",
    )["query"]["categorymembers"]  # fmt: skip
    found: list[dict] = []  # type: ignore[type-arg]
    for start in range(0, len(members), 25):
        titles = "|".join(m["title"] for m in members[start : start + 25])
        pages = api(
            action="query", titles=titles, prop="imageinfo",
            iiprop="url|mime|extmetadata", iiurlwidth="900",
        ).get("query", {}).get("pages", {})  # fmt: skip
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") == "image/jpeg" and public_domain(info.get("extmetadata", {})):
                found.append({"title": page["title"], "url": info["thumburl"]})
        time.sleep(0.5)
    return found[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-person", type=int, default=10)
    parser.add_argument("--minimum", type=int, default=4, help="people with fewer are dropped")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for person in PEOPLE:
        try:
            items = photographs(person, arguments.per_person)
        except Exception as error:  # noqa: BLE001 - one person failing must not stop the rest
            print(f"{person}: skipped ({error})")
            continue
        if len(items) < arguments.minimum:
            print(f"{person}: only {len(items)} public-domain photographs, dropped")
            continue
        folder = arguments.out / re.sub(r"[^A-Za-z0-9]+", "_", person).strip("_")
        folder.mkdir(exist_ok=True)
        saved = []
        for number, item in enumerate(items):
            path = folder / f"{number:02d}.jpg"
            if not path.exists():
                try:
                    path.write_bytes(get(item["url"]))
                except Exception as error:  # noqa: BLE001
                    print(f"  {item['title']}: not downloaded ({error})")
                    continue
                time.sleep(0.3)
            saved.append({"file": f"{folder.name}/{path.name}", **item, "licence": "public domain"})
        manifest[person] = saved
        print(f"{person}: {len(saved)} photographs")
    (arguments.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{sum(len(v) for v in manifest.values())} photographs of {len(manifest)} people")


if __name__ == "__main__":
    main()
