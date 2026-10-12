"""R5: a small local tool to review identity labels by eye and export a verified manifest.

    uv run python evaluation/label_review.py serve --dataset evaluation/datasets/commons-pd \n        --reviewer sodiq
    uv run python evaluation/label_review.py status --dataset evaluation/datasets/commons-pd
    uv run python evaluation/label_review.py export --dataset evaluation/datasets/commons-pd

The dataset's labels are Commons categories: a human-curated hint, not identity evidence. This tool
turns them into evidence only when a person looks and says so. It never approves anything itself and
never looks at embeddings.

* **Nothing is overwritten.** The original `manifest.json` and the photographs are never touched.
  Every decision is one line appended to `<dataset>/review/decisions.jsonl` (reviewer, UTC time,
  photograph, its SHA-256, the manifest's SHA-256, the decision, any correction, flags, a note). The
  latest line for a photograph is its current decision; the older ones stay as the audit trail.
  Stopping and starting again resumes from the log.
* **Decisions:** `VERIFIED` (the label is right), `INCORRECT` (it is wrong; give the right name if you
  know it, which then counts as a human-confirmed label), `UNCERTAIN` and `EXCLUDED` (neither ever
  counts). **Flags:** `AMBIGUOUS`, `LOW_QUALITY`, `MULTI_PERSON`; a flagged photograph is kept out of
  the verified set even if it was marked verified (conservative on purpose).
* **The verified manifest** (`review/exports/verified-<UTC time>.json`, schema 1) lists only
  photographs that are verified, unflagged, unchanged since they were reviewed, and used once (a
  repeated picture is listed under `duplicates_dropped`). It has the same `people` shape the gate
  script reads, plus provenance: the source manifest's and the decision log's digests, the reviewers,
  counts and the shortfall against the TST-057B targets. It is never padded: a shortfall is reported.

The server listens on 127.0.0.1 only and every request carries a per-run token, so another page in
the browser cannot post decisions. It serves only files the manifest lists.
"""

# ruff: noqa: E501  (the page below is one string of HTML and JavaScript)

import argparse
import hashlib
import http.server
import json
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


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReviewError(ValueError):
    """A decision that is not allowed."""


class Review:
    """The photographs of a dataset, the decisions made about them and what they add up to."""

    def __init__(self, dataset: Path, reviewer: str = "") -> None:
        self.dataset = guard(dataset)
        self.reviewer = reviewer.strip()
        manifest_path = self.dataset / "manifest.json"
        self.manifest_sha256 = sha256_of(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
                        "sha256": sha256_of(path),
                    }
        self.log_path = self.dataset / "review" / "decisions.jsonl"
        self._lock = threading.Lock()

    # --- the log -------------------------------------------------------------------------

    def history(self) -> list[dict[str, Any]]:
        if not self.log_path.is_file():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def current(self) -> dict[str, dict[str, Any]]:
        """The latest decision for each photograph that is still listed (the log replayed)."""
        latest: dict[str, dict[str, Any]] = {}
        for record in self.history():
            if record["file"] in self.entries:
                latest[record["file"]] = record
        return latest

    def decide(
        self,
        file: str,
        decision: str,
        *,
        corrected_identity: str | None = None,
        flags: tuple[str, ...] = (),
        note: str = "",
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
        record = {
            "schema_version": SCHEMA,
            "at": datetime.now(UTC).isoformat(),
            "reviewer": self.reviewer,
            "file": file,
            "sha256": entry["sha256"],
            "manifest_sha256": self.manifest_sha256,
            "original_identity": entry["identity"],
            "decision": decision,
            "corrected_identity": correction or None,
            "flags": sorted(set(flags)),
            "note": note.strip(),
        }
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(record, sort_keys=True) + "\n")
                log.flush()
        return record

    # --- what the decisions add up to ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        counts = dict.fromkeys(DECISIONS, 0)
        for record in self.current().values():
            counts[record["decision"]] += 1
        return {
            "photographs": len(self.entries),
            "reviewed": sum(counts.values()),
            "unreviewed": len(self.entries) - sum(counts.values()),
            **counts,
        }

    def verified(self) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
        """The photographs that may enter the verified set, by identity, and what was left out."""
        people: dict[str, list[dict[str, Any]]] = {}
        left_out: dict[str, list[str]] = {
            "not_verified": [],
            "flagged": [],
            "changed_since_review": [],
            "duplicates_dropped": [],
        }
        seen: set[str] = set()
        for file, record in sorted(self.current().items()):
            entry = self.entries[file]
            confirmed = record["decision"] == "VERIFIED" or (
                record["decision"] == "INCORRECT" and record["corrected_identity"]
            )
            if not confirmed:
                left_out["not_verified"].append(file)
                continue
            identity = record["corrected_identity"] or entry["identity"]
            if record["flags"]:
                left_out["flagged"].append(file)
            elif record["sha256"] != entry["sha256"]:
                left_out["changed_since_review"].append(file)
            elif entry["sha256"] in seen:
                left_out["duplicates_dropped"].append(file)
            else:
                seen.add(entry["sha256"])
                people.setdefault(identity, []).append(
                    {
                        "file": file,
                        "title": entry["title"],
                        "sha256": entry["sha256"],
                        "corrected": record["decision"] == "INCORRECT",
                    }
                )
        left_out["not_verified"] += sorted(set(self.entries) - set(self.current()))
        return people, left_out

    def export(self) -> dict[str, Any]:
        people, left_out = self.verified()
        counts = {name: len(items) for name, items in people.items()}
        usable = {name: n for name, n in counts.items() if n >= TARGETS["images_per_identity"]}
        queries = {name: max(1, n // 4) for name, n in usable.items()}  # as the gate holds out
        shortfall = {
            "verified_identities": max(0, TARGETS["verified_identities"] - len(usable)),
            "identities_with_two_queries": sum(1 for q in queries.values() if q < 2),
            "verified_queries": max(0, TARGETS["verified_queries"] - sum(queries.values())),
        }
        history = self.history()
        return {
            "schema_version": SCHEMA,
            "kind": "verified-manifest",
            "exported_at": datetime.now(UTC).isoformat(),
            "source_manifest_sha256": self.manifest_sha256,
            "decisions_sha256": hashlib.sha256(
                self.log_path.read_bytes() if self.log_path.is_file() else b""
            ).hexdigest(),
            "reviewers": sorted({record["reviewer"] for record in history}),
            "counts": {
                "status": self.status(),
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
        document = self.export()
        folder = self.dataset / "review" / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = folder / f"verified-{stamp}.json"
        path.write_text(json.dumps(document, indent=1), encoding="utf-8")
        return path


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
const q=(p,o)=>fetch(p+(p.includes('?')?'&':'?')+'t='+T,o).then(r=>r.json());
async function load(){state=await q('/api/state');const sel=document.getElementById('who');
 const keep=sel.value;sel.innerHTML='';for(const n of Object.keys(state.people)){
 const o=document.createElement('option');o.value=o.textContent=n;sel.appendChild(o)}
 if(keep)sel.value=keep;document.getElementById('status').textContent=
 Object.entries(state.status).map(([k,v])=>k+': '+v).join(' | ');draw()}
function draw(){const g=document.getElementById('grid');g.innerHTML='';
 const who=document.getElementById('who').value;for(const e of state.people[who]||[]){
 const c=state.decisions[e.file]||{};const d=document.createElement('div');d.className='card';
 d.innerHTML='<img src="/image?f='+encodeURIComponent(e.file)+'&t='+T+'" alt="">'+
 '<div><b>'+e.file+'</b><br><small>'+e.title+'</small></div>'+
 '<div class=badge>'+(c.decision?'<span class='+c.decision+'>'+c.decision+'</span>'+
 (c.corrected_identity?' as '+c.corrected_identity:'')+(c.flags&&c.flags.length?' ['+c.flags+']':''):'not reviewed')+'</div>'+
 '<div>'+['AMBIGUOUS','LOW_QUALITY','MULTI_PERSON'].map(f=>'<label><input type=checkbox data-f='+f+
 (c.flags&&c.flags.includes(f)?' checked':'')+'>'+f+'</label>').join(' ')+'</div>'+
 '<input placeholder=note value="'+(c.note||'').replace(/"/g,'&quot;')+'">'+
 '<div>'+['VERIFIED','INCORRECT','UNCERTAIN','EXCLUDED'].map(x=>'<button data-d='+x+'>'+x+'</button>').join('')+'</div>';
 d.querySelectorAll('button').forEach(b=>b.onclick=async()=>{
  let corrected=null;if(b.dataset.d==='INCORRECT'){corrected=prompt('Who is it, if you know? (leave empty if not)','')}
  const flags=[...d.querySelectorAll('input[type=checkbox]')].filter(x=>x.checked).map(x=>x.dataset.f);
  const r=await q('/api/decision',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({file:e.file,decision:b.dataset.d,corrected_identity:corrected,flags,
   note:d.querySelector('input[placeholder=note]').value})});
  if(r.error)alert(r.error);await load()});g.appendChild(d)}}
document.getElementById('who').onchange=draw;load();
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
                    data = (review.dataset / listed["file"]).read_bytes()
                    self._send(200, data, "image/jpeg")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if (
                not self._allowed(urllib.parse.parse_qs(parsed.query))
                or parsed.path != "/api/decision"
            ):
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
                )
            except (ReviewError, KeyError, ValueError, TypeError) as error:
                self._json(400, {"error": str(error) or "that is not a valid decision"})
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
    args = parser.parse_args(argv)
    review = Review(Path(args.dataset), args.reviewer)
    if args.command == "status":
        print(json.dumps(review.status(), indent=1))
    elif args.command == "export":
        path = review.write_export()
        document = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "written": str(path),
                    "counts": document["counts"],
                    "shortfall": document["shortfall"],
                },
                indent=1,
            )
        )
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
