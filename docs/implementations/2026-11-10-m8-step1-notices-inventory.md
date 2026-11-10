# M8 step 1: licence inventory and the third-party notices generator

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M8 step 1 · feeds TST-086 and SEC-008 (neither is `PASSING`; they need the packaged build)
- **Status:** done
- **Commits:** PR (number added when opened): `build(notices): generate the third-party notices file`

## What changed

- `scripts/generate_notices.py` (standard library only) lists every component a build ships and
  carries its licence text, as MIT, BSD, ISC, Apache-2.0 and OFL require. Three runtime closures:
  Python (`uv export --no-dev`, as installed), JavaScript (the frontend's production dependencies as
  Vite bundles them) and Rust (`cargo metadata` for the Windows target, dev-only crates left out).
  `--output` writes the notices file, `--check` writes nothing and exits 1 when a component has no
  licence identifier, a licence the application cannot ship (GPL, AGPL, SSPL), or `DirectML.dll`
  without Microsoft's terms. An LGPL or MPL component is printed as `REVIEW`, not failed.
- `packaging/third-party/DirectML-LICENSE.txt` and its README: Microsoft's DirectML terms, which the
  `onnxruntime-windowsml` wheel does not carry. The generator adds them to the notices file.
- CI: the Desktop job runs `scripts/generate_notices.py --check` (it is the job that has `uv`, `npm`
  and `cargo`), so a new dependency with an unknown or forbidden licence fails a pull request.
- `tests/unit/test_generate_notices.py` (6 tests). `build/` is Git-ignored (the notices file is a
  build output, not committed).
- The licensing record (sections 4b, 7 and 11) gets the inventory results.

## Inventory result (2026-11-10, this checkout)

390 components: 30 Python, 91 JavaScript, 269 Rust. No component lacks an SPDX or declared licence
and none is GPL, AGPL or SSPL. Licences seen: MIT, Apache-2.0, BSD-2/3-Clause, ISC-like, 0BSD,
Zlib, Unlicense, Unicode-3.0, PSF-2.0, MIT-CMU, OFL-1.1 (Geist font) and **MPL-2.0** in six places
(file-level copyleft, no obligation for unmodified use but the source must stay available): the
Python `tqdm` (MPL-2.0 AND MIT) and the Rust crates `cssparser`, `cssparser-macros`, `dtoa-short`,
`option-ext` and `selectors`. 14 crates or packages carry no licence file in their package (most are
monorepo members); they are listed under "Declared licence only" with their SPDX identifier.

## Decisions (delegated, 2026-11-10; the owner may reverse any)

- **Own script instead of `cargo-license`, `cargo deny` or `pip-licenses`.** The plan allows the
  inventory tools as build tools, but `cargo metadata`, `importlib.metadata` and `npm ls` give the
  same facts and the script also has to collect the texts, so no tool is installed or added.
- **The web closure is declared, not discovered.** Vite's bundle contents are not listed anywhere
  cheap, so the generator names the bundled roots (`NPM_BUNDLED`, `NPM_INLINED_CSS`,
  `NPM_NOT_SHIPPED`) and a test fails when a frontend dependency is in none of them.
  `lucide-react` is not imported anywhere in `frontend/src`, so it is not listed.
- **Commit the DirectML terms text, never the library.** Fetching the 200 MB NuGet package at build
  time would make every build need the network; the text is 10 KB and is licence text meant to
  travel with the software. Reversible: delete the file and the generator fails its check.
- **Missing licence files do not fail the check;** a missing identifier does.

## Verification

- `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy --platform linux`
  clean (317 files). `uv run pytest -q tests/unit/test_generate_notices.py`: 6 passed.
- `uv run python scripts/generate_notices.py --check`: 390 components, 0 problems. `--output` wrote
  a 1.4 MB file with the DirectML terms and ONNX Runtime's `ThirdPartyNotices.txt` in it.
- Full backend gate: see the PR description.

## Open issues / follow-ups

- **The DirectML.dll in the wheel is not byte-identical to the NuGet 1.15.4 one** (SHA-256
  `89fcd116...` against `9c9e6d82...`), so that these terms govern the wheel's copy is still an
  inference. Recorded in the licensing record 4b; unchanged risk for a personal build.
- FFmpeg's `LICENSE.txt` and notices join the generator when M6 step 3 lands (the plan's step 1/4).
- The notices file is generated, not yet shipped: step 3 puts it in the installer.
- Rust licence texts: the crates' own files are used; those with none are declared only.
