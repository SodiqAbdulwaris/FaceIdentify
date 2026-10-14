"""R5: a small local tool to review identity labels by eye and export a verified manifest.

    uv run python evaluation/label_review.py serve --dataset evaluation/datasets/commons-pd \
        --reviewer <your name>
    uv run python evaluation/label_review.py status --dataset evaluation/datasets/commons-pd
    uv run python evaluation/label_review.py export --dataset evaluation/datasets/commons-pd

The dataset's labels are Commons categories: a human-curated hint, not identity evidence. This tool
turns them into evidence only when a person looks and says so. It never approves anything itself and
never looks at embeddings.

* **Nothing is overwritten.** The original `manifest.json` and the photographs are never touched.
  Every decision is one line appended to `<dataset>/review/decisions.jsonl` (reviewer, UTC time,
  photograph, its SHA-256, the label it was reviewed under, the manifest's SHA-256, the decision, any
  correction, flags, a note). The latest line for a photograph is its current decision; the older
  ones stay as the audit trail. Stopping and starting again resumes from the log (a half-written
  last line from a crash is ignored).
* **A decision belongs to what was looked at.** It counts only while the photograph still has the
  same bytes and the same proposed label; if either changed, it is listed as `stale` and the
  photograph needs a new review.
* **Decisions:** `VERIFIED` (the label is right), `INCORRECT` (it is wrong; give the right name if you
  know it, which then counts as a human-confirmed label), `UNCERTAIN` and `EXCLUDED` (neither ever
  counts). **Flags:** `AMBIGUOUS`, `LOW_QUALITY`, `MULTI_PERSON`; a flagged photograph is kept out of
  the verified set even if it was marked verified (conservative on purpose). **Same picture:** if two
  photographs are the same picture (a copy, a crop, another encoding) say so with `same_picture_as`;
  such a group counts once and never crosses a split. Spotting them is the reviewer's job.
* **The verified manifest** (`review/exports/verified-<UTC time>.json`, schema 1) lists only
  photographs that are verified, unflagged, unchanged since they were reviewed, and used once. It has
  the same `people` shape the gate script reads, plus provenance: the source manifest's and the
  decision log's digests, the reviewers, counts and the shortfall against the TST-057B targets. It is
  never padded: a shortfall is reported. Each export is a new file; none is ever replaced.

The server listens on 127.0.0.1 only and every request carries a per-run token, so another page in
the browser cannot post decisions. It serves only files the manifest lists, and the page draws
photograph names and labels as text, never as markup.
"""

# ruff: noqa: E501  (the page below is one string of HTML and JavaScript)

import argparse
import difflib
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

DATASETS_ROOT: Final = (Path(__file__).resolve().parent / "datasets").resolve()
DECISIONS: Final = ("VERIFIED", "INCORRECT", "UNCERTAIN", "EXCLUDED")
FLAGS: Final = ("AMBIGUOUS", "LOW_QUALITY", "MULTI_PERSON")
SCHEMA: Final = 1
# TST-057B dataset targets (owner, 2026-10-12): initial targets, never a reason to force labels.
TARGETS: Final = {
    "verified_identities": 40,
    "images_per_identity": 5,
    "queries_per_identity": 2,
    "verified_queries": 80,
}


def guard(path: Path) -> Path:
    """Biometric data stays under the Git-ignored datasets folder."""
    resolved = path.resolve()
    if DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReviewError(ValueError):
    """A decision that is not allowed."""


class Review:
    """The photographs of a dataset, the decisions made about them and what they add up to."""

    def __init__(self, dataset: Path, reviewer: str = "") -> None:
        self.dataset = guard(dataset)
        self.reviewer = reviewer.strip()
        manifest_path = self.dataset / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        self.manifest_sha256 = sha256_of(manifest_bytes)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        self.entries: dict[str, dict[str, Any]] = {}
        for identity, items in manifest.items():
            for item in items:
                path = (self.dataset / item["file"]).resolve()
                if self.dataset not in path.parents:
                    raise SystemExit(f"{item['file']} is outside the dataset folder")
                if path.is_file():
                    self.entries[item["file"]] = {
                        "file": item["file"],
                        "identity": identity,
                        "title": item.get("title", ""),
                    }
        self.shown: frozenset[str] | None = None  # people the page lists (None: everyone)
        self.review_dir = self.dataset / "review"
        self.log_path = self.review_dir / "decisions.jsonl"
        self._lock = threading.Lock()
        self._hashes: dict[str, tuple[tuple[int, int], str]] = {}
        self._confine(self.review_dir)

    def focus(self, names: list[str]) -> None:
        """List only these people in the page. A name must be one the manifest has (case aside):
        a typo stops the tool rather than showing an empty page. Decisions, status and export are
        about the whole dataset and are not affected."""
        known = {
            identity.lower(): identity
            for identity in {e["identity"] for e in self.entries.values()}
        }
        chosen: set[str] = set()
        unknown: list[str] = []
        for name in names:
            found = known.get(name.strip().lower())
            if found is None:
                unknown.append(name)
            else:
                chosen.add(found)
        if unknown:
            hints = {
                n: difflib.get_close_matches(n, list(known.values()), n=2, cutoff=0.5)
                for n in unknown
            }
            raise SystemExit(f"not in the manifest: {unknown} (close: {hints})")
        if not chosen:
            raise SystemExit("--people names nobody")
        self.shown = frozenset(chosen)

    # --- the files ---------------------------------------------------------------------

    def _confine(self, path: Path) -> Path:
        """`path` as it really is on disk (links and junctions followed) must be inside the
        dataset, so a link cannot carry a write or a read out of the Git-ignored folder."""
        real = Path(os.path.realpath(path))
        if self.dataset != real and self.dataset not in real.parents:
            raise SystemExit(f"{path} leads outside the dataset folder")
        return real

    def read_photograph(self, file: str) -> tuple[bytes, str]:
        """The bytes of a listed photograph as they are now, and their SHA-256."""
        path = self._confine(self.dataset / file)
        data = path.read_bytes()
        return data, sha256_of(data)

    def digest(self, file: str) -> str:
        """The SHA-256 of a listed photograph as it is now (re-read only when its size or
        modification time changed, so the whole set is not read on every request)."""
        path = self._confine(self.dataset / file)
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        cached = self._hashes.get(file)
        if cached is None or cached[0] != stamp:
            cached = (stamp, sha256_of(path.read_bytes()))
            self._hashes[file] = cached
        return cached[1]

    # --- the log -----------------------------------------------------------------------

    def _read_log(self) -> tuple[bytes, list[dict[str, Any]]]:
        """The log's bytes and the complete decisions in them, from one read under the lock. A
        half-written last line (a crash while appending) is ignored; the rest stays usable."""
        with self._lock:
            self._confine(self.log_path)
            data = self.log_path.read_bytes() if self.log_path.is_file() else b""
        records: list[dict[str, Any]] = []
        lines = data.decode("utf-8", errors="replace").split("\n")
        for position, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if position != len(lines) - 1 and any(
                    rest.strip() for rest in lines[position + 1 :]
                ):
                    raise SystemExit(f"{self.log_path} is damaged before its end") from None
        return data, records

    def history(self) -> list[dict[str, Any]]:
        return self._read_log()[1]

    def _latest(self, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            if record["file"] in self.entries:
                latest[record["file"]] = record
        return latest

    def _split(
        self, records: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """The latest decision per photograph: those that still describe what is there, and the
        stale ones (the photograph's bytes or proposed label changed since the review)."""
        valid: dict[str, dict[str, Any]] = {}
        stale: dict[str, dict[str, Any]] = {}
        for file, record in self._latest(records).items():
            entry = self.entries[file]
            same = (
                record["sha256"] == self.digest(file)
                and record["original_identity"] == entry["identity"]
            )
            (valid if same else stale)[file] = record
        return valid, stale

    def current(self) -> dict[str, dict[str, Any]]:
        return self._split(self._read_log()[1])[0]

    def decide(
        self,
        file: str,
        decision: str,
        *,
        corrected_identity: str | None = None,
        flags: tuple[str, ...] = (),
        note: str = "",
        same_picture_as: str | None = None,
    ) -> dict[str, Any]:
        if not self.reviewer:
            raise ReviewError("a reviewer name is needed: decisions are attributed")
        entry = self.entries.get(file)
        if entry is None:
            raise ReviewError("that photograph is not in the manifest")
        if decision not in DECISIONS:
            raise ReviewError(f"a decision is one of {', '.join(DECISIONS)}")
        bad = [flag for flag in flags if flag not in FLAGS]
        if bad:
            raise ReviewError(f"unknown flags: {', '.join(bad)}")
        correction = (corrected_identity or "").strip()
        if correction and decision != "INCORRECT":
            raise ReviewError("a correction goes with an INCORRECT decision")
        twin = (same_picture_as or "").strip()
        if twin and (twin not in self.entries or twin == file):
            raise ReviewError("same_picture_as must be another photograph of the manifest")
        data, digest = self.read_photograph(file)  # (the bytes as they are at this moment)
        record = {
            "schema_version": SCHEMA,
            "at": datetime.now(UTC).isoformat(),
            "reviewer": self.reviewer,
            "file": file,
            "sha256": digest,
            "manifest_sha256": self.manifest_sha256,
            "original_identity": entry["identity"],
            "decision": decision,
            "corrected_identity": correction or None,
            "flags": sorted(set(flags)),
            "note": note.strip(),
            "same_picture_as": twin or None,
        }
        del data
        with self._lock:
            self._confine(self.review_dir)
            self.review_dir.mkdir(parents=True, exist_ok=True)
            self._confine(self.log_path)
            line = json.dumps(record, sort_keys=True) + "\n"
            self._set_aside_torn_tail()
            with self.log_path.open("ab") as log:
                log.write(line.encode("utf-8"))
                log.flush()
                os.fsync(log.fileno())
        return record

    def _set_aside_torn_tail(self) -> None:
        """A crash can leave a last line without its newline: an incomplete record, never a
        decision. It is moved to `decisions.torn.jsonl` (kept, not deleted) so the next record
        starts on a clean line and the log has no damage in its middle."""
        if not self.log_path.is_file():
            return
        data = self.log_path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        with (self.review_dir / "decisions.torn.jsonl").open("ab") as torn:
            torn.write(data[cut:] + b"\n")
        with self.log_path.open("r+b") as log:
            log.truncate(cut)

    # --- what the decisions add up to ----------------------------------------------------

    def _counts(self, valid: dict[str, dict[str, Any]], stale: dict[str, Any]) -> dict[str, Any]:
        counts = dict.fromkeys(DECISIONS, 0)
        for record in valid.values():
            counts[record["decision"]] += 1
        reviewed = sum(counts.values())
        return {
            "photographs": len(self.entries),
            "reviewed": reviewed,
            "unreviewed": len(self.entries) - reviewed - len(stale),
            "stale_needs_review": len(stale),
            **counts,
        }

    def status(self) -> dict[str, Any]:
        valid, stale = self._split(self._read_log()[1])
        return self._counts(valid, stale)

    def _verified(
        self, valid: dict[str, dict[str, Any]], stale: dict[str, Any]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
        people: dict[str, list[dict[str, Any]]] = {}
        left_out: dict[str, list[str]] = {
            "not_verified": [],
            "flagged": [],
            "stale_needs_review": sorted(stale),
            "duplicates_dropped": [],
        }
        # photographs declared to be the same picture form one group; the first one counts
        group = {file: file for file in self.entries}

        def root(file: str) -> str:
            while group[file] != file:
                file = group[file]
            return file

        for file, record in valid.items():
            twin = record.get("same_picture_as")
            if twin in group:
                a, b = sorted((root(file), root(twin)))
                group[b] = a
        counted: set[str] = set()
        for file, record in sorted(valid.items()):
            confirmed = record["decision"] == "VERIFIED" or (
                record["decision"] == "INCORRECT" and record["corrected_identity"]
            )
            if not confirmed:
                left_out["not_verified"].append(file)
            elif record["flags"]:
                left_out["flagged"].append(file)
            elif root(file) in counted or self.digest(file) in counted:
                left_out["duplicates_dropped"].append(file)
            else:
                counted.add(root(file))
                counted.add(self.digest(file))
                identity = record["corrected_identity"] or self.entries[file]["identity"]
                people.setdefault(identity, []).append(
                    {
                        "file": file,
                        "title": self.entries[file]["title"],
                        "sha256": record["sha256"],
                        "corrected": record["decision"] == "INCORRECT",
                    }
                )
        left_out["not_verified"] += sorted(set(self.entries) - set(valid) - set(stale))
        return people, left_out

    def verified(self) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
        """The photographs that may enter the verified set, by identity, and what was left out."""
        valid, stale = self._split(self._read_log()[1])
        return self._verified(valid, stale)

    def export(self) -> dict[str, Any]:
        data, records = self._read_log()  # one snapshot of the log for the whole document
        valid, stale = self._split(records)
        people, left_out = self._verified(valid, stale)
        counts = {name: len(items) for name, items in people.items()}
        usable = {name: n for name, n in counts.items() if n >= TARGETS["images_per_identity"]}
        queries = {name: max(1, n // 4) for name, n in usable.items()}  # as the gate holds out
        shortfall = {
            "verified_identities": max(0, TARGETS["verified_identities"] - len(usable)),
            "identities_with_two_queries": sum(1 for q in queries.values() if q < 2),
            "verified_queries": max(0, TARGETS["verified_queries"] - sum(queries.values())),
        }
        return {
            "schema_version": SCHEMA,
            "kind": "verified-manifest",
            "exported_at": datetime.now(UTC).isoformat(),
            "source_manifest_sha256": self.manifest_sha256,
            "decisions_sha256": sha256_of(data),
            "reviewers": sorted({record["reviewer"] for record in records}),
            "counts": {
                "status": self._counts(valid, stale),
                "verified_photographs": sum(counts.values()),
                "identities": len(people),
                "identities_with_enough_images": len(usable),
                "held_out_queries": sum(queries.values()),
                "left_out": {key: len(value) for key, value in left_out.items()},
            },
            "targets": TARGETS,
            "shortfall": shortfall,
            "left_out": left_out,
            "people": people,
        }

    def write_export(self) -> Path:
        """A new file every time: an earlier export is never replaced."""
        document = self.export()
        folder = self.review_dir / "exports"
        self._confine(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self._confine(folder)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for attempt in range(1000):
            suffix = "" if attempt == 0 else f"-{attempt}"
            path = folder / f"verified-{stamp}{suffix}.json"
            try:
                with path.open("x", encoding="utf-8") as out:
                    out.write(json.dumps(document, indent=1))
            except FileExistsError:
                continue
            return path
        raise SystemExit("could not find a free name for the export")


# --- the page ----------------------------------------------------------------------------

PAGE = """<!doctype html><meta charset="utf-8"><title>Label review</title>
<style>
body{font:15px system-ui;margin:1rem;background:#fff;color:#111}
header{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1rem}
.card{border:1px solid #bbb;border-radius:8px;padding:.5rem}
.card img{width:100%;height:240px;object-fit:contain;background:#eee}
.badge{font-weight:600}.VERIFIED{color:#0a6b2d}.INCORRECT{color:#a00}.UNCERTAIN{color:#8a6000}
.EXCLUDED{color:#555}button{margin:.15rem;padding:.35rem .6rem}
</style>
<header><h1>Label review</h1><label>Person <select id=who></select></label>
<span id=status role=status></span></header>
<p>The label comes from a Commons category and is not evidence. Say VERIFIED only if you can
tell it is the same person as in the other photographs of this person.</p>
<div id=grid class=grid></div>
<script>
const T=new URLSearchParams(location.search).get('t');let state=null;
const FLAGS=['AMBIGUOUS','LOW_QUALITY','MULTI_PERSON'],DEC=['VERIFIED','INCORRECT','UNCERTAIN','EXCLUDED'];
const api=(p,o)=>fetch(p+(p.includes('?')?'&':'?')+'t='+encodeURIComponent(T),o).then(r=>r.json());
const el=(tag,props,...kids)=>{const e=document.createElement(tag);Object.assign(e,props||{});
 for(const k of kids)e.append(k);return e};
async function load(focus){state=await api('/api/state');const sel=document.getElementById('who');
 const keep=sel.value;sel.replaceChildren();for(const n of Object.keys(state.people)){
 sel.append(el('option',{value:n,textContent:n}))}
 if(keep)sel.value=keep;document.getElementById('status').textContent=
 Object.entries(state.status).map(([k,v])=>k+': '+v).join(' | ');draw(focus)}
function draw(focus){const g=document.getElementById('grid');g.replaceChildren();
 const who=document.getElementById('who').value;
 for(const e of state.people[who]||[]){
  const c=state.decisions[e.file]||{};
  const card=el('div',{className:'card',role:'group'});card.setAttribute('aria-label',e.file);
  const img=el('img');img.alt=e.file;img.src='/image?f='+encodeURIComponent(e.file)+'&t='+encodeURIComponent(T);
  const badge=el('div',{className:'badge'});
  if(c.decision){badge.append(el('span',{className:c.decision,textContent:c.decision}));
   if(c.corrected_identity)badge.append(' as '+c.corrected_identity);
   if(c.flags&&c.flags.length)badge.append(' ['+c.flags.join(', ')+']')}else badge.append('not reviewed');
  const note=el('input',{placeholder:'note',value:c.note||''});note.setAttribute('aria-label','Note for '+e.file);
  const twin=el('input',{placeholder:'same picture as (file)',value:c.same_picture_as||''});
  twin.setAttribute('aria-label','Same picture as, for '+e.file);
  const flags=FLAGS.map(f=>{const box=el('input',{type:'checkbox',checked:!!(c.flags&&c.flags.includes(f))});
   box.dataset.f=f;return el('label',{},box,f)});
  const buttons=DEC.map(x=>{const b=el('button',{type:'button',textContent:x});b.dataset.d=x;
   b.setAttribute('aria-label',x+' '+e.file);
   b.onclick=async()=>{let corrected=null;
    if(x==='INCORRECT')corrected=prompt('Who is it, if you know? (leave empty if not)','');
    const r=await api('/api/decision',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({file:e.file,decision:x,corrected_identity:corrected,
      flags:flags.map(l=>l.firstChild).filter(b=>b.checked).map(b=>b.dataset.f),
      note:note.value,same_picture_as:twin.value||null})});
    if(r.error)alert(r.error);await load({file:e.file,d:x})};return b});
  card.append(img,el('div',{},el('b',{textContent:e.file}),el('br'),el('small',{textContent:e.title})),
   badge,el('div',{},...flags),note,twin,el('div',{},...buttons));g.append(card)}
 if(focus){for(const b of g.querySelectorAll('button')){
  if(b.dataset.d===focus.d&&b.getAttribute('aria-label')===focus.d+' '+focus.file){b.focus()}}}}
document.getElementById('who').onchange=()=>draw();load();
</script>"""


def make_handler(review: Review, token: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return  # quiet

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value).encode(), "application/json")

        def _allowed(self, query: dict[str, list[str]]) -> bool:
            return secrets.compare_digest(query.get("t", [""])[0], token)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if not self._allowed(query):
                self._json(403, {"error": "not allowed"})
            elif parsed.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/state":
                people: dict[str, list[dict[str, str]]] = {}
                for entry in review.entries.values():
                    if review.shown is not None and entry["identity"] not in review.shown:
                        continue
                    people.setdefault(entry["identity"], []).append(
                        {"file": entry["file"], "title": entry["title"]}
                    )
                self._json(
                    200,
                    {
                        "people": people,
                        "decisions": review.current(),
                        "status": review.status(),
                    },
                )
            elif parsed.path == "/image":
                listed = review.entries.get(query.get("f", [""])[0])
                if listed is None:  # only photographs the manifest lists are ever served
                    self._json(404, {"error": "unknown photograph"})
                else:
                    try:
                        data, _ = review.read_photograph(listed["file"])
                    except SystemExit:  # a link that leads outside the dataset
                        self._json(404, {"error": "unknown photograph"})
                    else:
                        self._send(200, data, "image/jpeg")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            allowed = self._allowed(urllib.parse.parse_qs(parsed.query))
            if not allowed or parsed.path != "/api/decision":
                self._json(403, {"error": "not allowed"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(min(length, 65536)))
                record = review.decide(
                    body["file"],
                    body["decision"],
                    corrected_identity=body.get("corrected_identity"),
                    flags=tuple(body.get("flags", [])),
                    note=str(body.get("note", "")),
                    same_picture_as=body.get("same_picture_as"),
                )
            except (ReviewError, KeyError, ValueError, TypeError) as error:
                self._json(400, {"error": str(error) or "that is not a valid decision"})
                return
            except SystemExit:  # a link that leads outside the dataset
                self._json(400, {"error": "that photograph cannot be read"})
                return
            self._json(200, record)

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def serve(review: Review, port: int = 0) -> tuple[Server, str]:
    token = secrets.token_urlsafe(24)
    server = Server(("127.0.0.1", port), make_handler(review, token))
    return server, token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "status", "export"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--people",
        help="serve only these people, comma separated, exactly as the manifest names them",
    )
    args = parser.parse_args(argv)
    review = Review(Path(args.dataset), args.reviewer)
    if args.people:
        review.focus([n for n in args.people.split(",") if n.strip()])
    if args.command == "status":
        print(json.dumps(review.status(), indent=1))
    elif args.command == "export":
        path = review.write_export()
        document = json.loads(path.read_text(encoding="utf-8"))
        summary = {
            "written": str(path),
            "counts": document["counts"],
            "shortfall": document["shortfall"],
        }
        print(json.dumps(summary, indent=1))
    else:
        if not review.reviewer:
            raise SystemExit("--reviewer is required to serve: decisions are attributed")
        server, token = serve(review, args.port)
        url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
        print(f"Review at {url}\nCtrl+C to stop; decisions are saved as you make them.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
