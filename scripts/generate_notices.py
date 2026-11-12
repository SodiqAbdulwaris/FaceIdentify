"""Build the third-party notices file of the packaged application (M8 step 1).

    uv run python scripts/generate_notices.py --output build/THIRD_PARTY_NOTICES.md
    uv run python scripts/generate_notices.py --check

It lists what a build ships and carries each component's licence text, as MIT, BSD, ISC, Apache-2.0,
OFL and the like require. The sets are the runtime closures only:

* Python: the locked runtime packages (`uv export --no-dev`) that are installed in this environment.
* JavaScript: the production dependencies of the frontend (`npm ls --omit=dev`), which Vite bundles.
* Rust: the crates the Windows shell links or builds with (no dev-only crates),
  from `cargo metadata`.

Standard library only; it needs `uv`, `npm` and `cargo` on the path, which a build has anyway.
`--check` changes nothing and exits 1 when a component has no licence identifier or carries a
licence the application cannot ship (GPL, AGPL, SSPL). A component whose package ships no licence
file (a monorepo crate, for example) is listed under "Declared licence only" with its identifier.
"""

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTML_TERMS = ROOT / "packaging" / "third-party" / "DirectML-LICENSE.txt"
CARGO_TARGET = "x86_64-pc-windows-msvc"
LICENCE_FILE = re.compile(r"(licen[cs]e|notice|copying|copyright|third[-_ ]?party)", re.IGNORECASE)
# A GPL, AGPL or SSPL token (the `(?<![A-Za-z])` keeps the LGPL out of it).
FORBIDDEN = re.compile(r"(?<![A-Za-z])(A?GPL|SSPL)", re.IGNORECASE)
REVIEW = re.compile(r"\b(LGPL|MPL|EPL|CDDL)", re.IGNORECASE)


@dataclass
class Component:
    ecosystem: str
    name: str
    version: str
    licence: str
    texts: dict[str, str] = field(default_factory=dict)  # file name -> text
    missing: list[str] = field(default_factory=list)  # terms the package needs and we do not have

    @property
    def problems(self) -> list[str]:
        found = list(self.missing)
        if not self.licence:
            found.append("no licence identifier")
        # `X OR Y` lets the user choose, so one alternative without a forbidden licence suffices; an
        # `AND` (or a bare name) binds every part.
        alternatives = re.split(r"\s+OR\s+", self.licence, flags=re.IGNORECASE)
        if all(FORBIDDEN.search(alternative) for alternative in alternatives):
            found.append(f"licence {self.licence!r} cannot be shipped")
        return found

    @property
    def needs_review(self) -> bool:
        return bool(REVIEW.search(self.licence))


def read_texts(folder: Path, names: list[str]) -> dict[str, str]:
    texts = {}
    for name in names:
        path = folder / name
        if LICENCE_FILE.search(Path(name).name) and path.is_file():
            texts[Path(name).name] = path.read_text(encoding="utf-8", errors="replace").strip()
    return texts


def python_licence(meta: metadata.PackageMetadata) -> str:
    expression = meta.get("License-Expression") or ""
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if "License ::" in c
    ]
    declared = (meta.get("License") or "").strip()
    return " OR ".join(classifiers) if classifiers else (declared if len(declared) < 80 else "")


def python_components() -> list[Component]:
    exported = subprocess.run(
        ["uv", "export", "--no-dev", "--no-hashes", "--frozen"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    found = []
    for line in exported.splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==(\S+)", line)
        if not match:
            continue
        try:
            dist = metadata.distribution(match.group(1))
        except metadata.PackageNotFoundError:
            continue  # a platform-marked package that this environment does not install
        files = [str(f) for f in dist.files or []]
        texts = {}
        for name in files:
            if LICENCE_FILE.search(Path(name).name) and not name.endswith((".py", ".pyc", ".pyi")):
                located = Path(str(dist.locate_file(name)))
                if located.is_file():
                    texts[Path(name).name] = located.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
        missing = []
        if any(Path(name).name.lower() == "directml.dll" for name in files):
            # The wheel carries Microsoft's DirectML.dll but not its terms (licensing record 4b).
            if DIRECTML_TERMS.is_file():
                texts[DIRECTML_TERMS.name] = DIRECTML_TERMS.read_text(encoding="utf-8").strip()
            else:
                missing.append(f"DirectML.dll ships without its terms: {DIRECTML_TERMS} is missing")
        found.append(
            Component(
                "python",
                dist.metadata["Name"],
                dist.version,
                python_licence(dist.metadata),
                texts,
                missing,
            )
        )
    return found


# What Vite puts in the web bundle. Every `dependencies` entry of the frontend must be listed here
# (a test enforces it, so a new dependency forces the question). BUNDLED packages are shipped with
# everything they depend on; INLINED_CSS ones are shipped alone (their CSS is copied into the
# bundle, their own dependencies are tools); the rest is build-time or unused.
NPM_BUNDLED = {
    "@fontsource-variable/geist",
    "@tanstack/react-query",
    "@tauri-apps/api",
    "class-variance-authority",
    "cn",
    "radix-ui",
    "react",
    "react-dom",
    "react-router",
    "zustand",
}
NPM_INLINED_CSS = {"shadcn", "tailwindcss", "tw-animate-css"}
NPM_NOT_SHIPPED = {"@tailwindcss/vite", "lucide-react"}  # a build plugin; imported nowhere in src


def npm_folder(name: str, parent: Path) -> Path | None:
    for base in (parent, *parent.parents):
        candidate = base / "node_modules" / name
        if (candidate / "package.json").is_file():
            return candidate
    return None


def npm_components() -> list[Component]:
    frontend = ROOT / "frontend"
    declared = set(
        json.loads((frontend / "package.json").read_text(encoding="utf-8"))["dependencies"]
    )
    unknown = declared - NPM_BUNDLED - NPM_INLINED_CSS - NPM_NOT_SHIPPED
    if unknown:
        raise SystemExit(f"classify these frontend dependencies in generate_notices.py: {unknown}")
    found: dict[tuple[str, str], Component] = {}
    pending = [(name, frontend, True) for name in sorted(NPM_BUNDLED | NPM_INLINED_CSS)]
    while pending:
        name, parent, deep = pending.pop()
        folder = npm_folder(name, parent)
        if folder is None:
            raise SystemExit(f"{name} is not installed; run npm ci")
        manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        key = (manifest["name"], manifest["version"])
        if key in found:
            continue
        licence = manifest.get("license") or ""
        if isinstance(licence, dict):
            licence = licence.get("type", "")
        names = [p.name for p in folder.iterdir() if p.is_file()]
        found[key] = Component("npm", key[0], key[1], licence, read_texts(folder, names))
        if deep and name not in NPM_INLINED_CSS:
            pending += [(dep, folder, True) for dep in manifest.get("dependencies", {})]
    return list(found.values())


def cargo_components() -> list[Component]:
    raw = subprocess.run(
        [
            "cargo",
            "metadata",
            "--manifest-path",
            "desktop/src-tauri/Cargo.toml",
            "--format-version",
            "1",
            "--filter-platform",
            CARGO_TARGET,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    data = json.loads(raw)
    packages = {p["id"]: p for p in data["packages"]}
    nodes = {n["id"]: n for n in data["resolve"]["nodes"]}
    roots = list(data["workspace_members"])
    reachable, stack = set(), list(roots)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for dep in nodes[current]["deps"]:
            if any(kind["kind"] != "dev" for kind in dep["dep_kinds"]):
                stack.append(dep["pkg"])
    found = []
    for ident in sorted(reachable - set(roots)):
        package = packages[ident]
        folder = Path(package["manifest_path"]).parent
        names = [p.name for p in folder.iterdir() if p.is_file()]
        found.append(
            Component(
                "rust",
                package["name"],
                package["version"],
                package.get("license") or package.get("license_file") or "",
                read_texts(folder, names),
            )
        )
    return found


# What the frozen backend folder carries beyond the locked Python packages: the interpreter and the
# libraries Python's own DLLs and extension modules link (`_internal/*.dll`, `*.pyd`), with the
# licence each declares. Their texts live upstream (see the URLs); CPython's own file is read here.
RUNTIME_LIBRARIES = (
    ("OpenSSL", "3", "Apache-2.0", "libssl-3-x64.dll, libcrypto-3-x64.dll"),
    ("SQLite", "3", "Public domain (blessing)", "sqlite3.dll"),
    ("libffi", "8", "MIT", "libffi-8.dll"),
    ("expat", "2", "MIT", "pyexpat.pyd"),
    ("bzip2", "1", "bzip2-1.0.6", "_bz2.pyd"),
    ("XZ Utils (liblzma)", "5", "0BSD", "_lzma.pyd"),
    ("Microsoft Visual C++ Redistributable", "14", "LicenseRef-Microsoft-VC-Redistributable",
     "msvcp140.dll, vcruntime140.dll, vcruntime140_1.dll"),
)  # fmt: skip


def bundled_components(ffmpeg: Path | None = None) -> list[Component]:
    """The non-package components of a packaged build: CPython and its libraries, and FFmpeg when
    the build ships it (`ffmpeg` is the folder it ships, whose LICENSE.txt is its licence text)."""
    cpython = Component("bundled", "CPython", platform.python_version(), "PSF-2.0")
    licence = Path(sys.base_prefix) / "LICENSE.txt"
    if licence.is_file():
        cpython.texts[licence.name] = licence.read_text(encoding="utf-8", errors="replace").strip()
    else:
        cpython.missing.append(f"CPython ships without its licence: {licence} is missing")
    found = [cpython] + [
        Component("bundled", f"{name} ({files})", version, licence_id)
        for name, version, licence_id, files in RUNTIME_LIBRARIES
    ]
    if ffmpeg is not None:
        build = Component(
            "bundled", "FFmpeg (shared libraries, LGPL build)", "9.0", "LGPL-2.1-or-later"
        )
        licence = ffmpeg / "LICENSE.txt"
        if licence.is_file():
            build.texts[licence.name] = licence.read_text(encoding="utf-8").strip()
        else:
            build.missing.append(f"FFmpeg ships without its licence: {licence} is missing")
        found.append(build)
    return found


def collect(ffmpeg: Path | None = None) -> list[Component]:
    components = (
        python_components() + npm_components() + cargo_components() + bundled_components(ffmpeg)
    )
    return sorted(components, key=lambda c: (c.ecosystem, c.name.lower(), c.version))


def render(components: list[Component]) -> str:
    out = [
        "# Third-party notices",
        "",
        "FaceIdentify is built from the open-source components below. Their licence texts follow.",
        "Generated by `scripts/generate_notices.py`; the face-recognition model weights are not",
        "part of this software and are installed separately by the user under their own licence.",
        "",
        "## Components",
        "",
        "| Ecosystem | Name | Version | Licence |",
        "|---|---|---|---|",
    ]
    for c in components:
        out.append(f"| {c.ecosystem} | {c.name} | {c.version} | {c.licence or '?'} |")
    by_text: dict[str, list[str]] = defaultdict(list)
    for c in components:
        for text in c.texts.values():
            by_text[text].append(f"{c.name} {c.version}")
    declared_only = [c for c in components if not c.texts]
    if declared_only:
        out += [
            "",
            "## Declared licence only",
            "",
            "These packages carry no licence file; the licence is the one their metadata declares.",
            "",
        ]
        out += [f"- {c.ecosystem}: {c.name} {c.version}: {c.licence}" for c in declared_only]
    out += ["", "## Licence texts", ""]
    for text, users in sorted(by_text.items(), key=lambda item: item[1][0].lower()):
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        out += [
            f"### Used by: {', '.join(sorted(set(users)))} ({digest})",
            "",
            "```text",
            text,
            "```",
            "",
        ]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, help="write the notices file here")
    parser.add_argument("--check", action="store_true", help="report problems only, write nothing")
    parser.add_argument("--ffmpeg", type=Path, help="the FFmpeg folder this build ships")
    args = parser.parse_args()
    components = collect(args.ffmpeg)
    problems = {f"{c.ecosystem}:{c.name} {c.version}": c.problems for c in components if c.problems}
    for name, found in problems.items():
        print(f"PROBLEM {name}: {'; '.join(found)}")
    for c in components:
        if c.needs_review:
            print(f"REVIEW {c.ecosystem}:{c.name} {c.version}: {c.licence}")
    counts: dict[str, int] = defaultdict(int)
    for c in components:
        counts[c.ecosystem] += 1
    print(f"{len(components)} components: {dict(counts)}; {len(problems)} with problems")
    if args.output and not args.check:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render(components), encoding="utf-8")
        print(f"wrote {args.output}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
