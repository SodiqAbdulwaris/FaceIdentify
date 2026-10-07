# Licences and commercialisation record

**Status:** started 2026-10-07 at the owner's request. **Use today:** FaceIdentify is **personal and
local only** (owner decision 2026-10-07): it is not sold, bundled or distributed. This file records
every third-party thing whose terms would matter if that ever changes, so a decision to commercialise
starts from a list instead of an archaeology project. It is **not legal advice**, and anything marked
*not verified* has not been read at source.

Keep it true: whoever adds a dependency, a model, a dataset, a font, an icon set or a build tool adds
a row here in the same change (`.agents/rules/documentation.md`).

## 1. What would block a commercial release today

| # | Blocker | Why | What would unblock it |
|---|---|---|---|
| 1 | **The face models** (`buffalo_l`: SCRFD-10GF and ArcFace ResNet50) | InsightFace states that all its pretrained models are "available for non-commercial research purposes only"; the code is MIT, the weights are not. Using them in a personal app is the owner's accepted risk (section 2), not a verified permission. | A commercial licence from InsightFace for these weights, or different weights whose licence and **training-data terms** permit commercial use (section 2.3). A change of model is a new representation space and a re-run of R2 to R4 in `docs/plans/M5_PLAN.md`. |
| 2 | **No licence for our own code** | The repository has no `LICENSE` file, so no licence grants anyone else rights to the code: by default all rights stay with the rightsholder(s), who may still grant permission by contract. | The owner chooses a licence (or keeps it proprietary) and adds the file. See section 3. |
| 3 | **Biometric-privacy law** | Face recognition of identifiable people is regulated separately from copyright (section 9). | Legal review per market, consent flows, retention and deletion. |
| 4 | **NVIDIA runtime libraries** | The GPU path uses NVIDIA's CUDA and cuDNN runtime libraries, which are proprietary and have their own redistribution terms (section 4). | Read the current NVIDIA licence for every file that would be shipped; or ship the CPU path only. |
| 5 | **Unverified Rust crates and the build tools of M8** | `cargo-license` has not been run; the installer, signing and any bundled FFmpeg are not chosen yet. | Run the inventory in section 8 and fill sections 5 to 7. |

## 2. The models

### 2.1 What is used (verified 2026-10-07)

Source: the official InsightFace model zoo,
<https://github.com/deepinsight/insightface/tree/master/model_zoo>, release assets
`https://github.com/deepinsight/insightface/releases/download/v0.7/<pack>.zip`.
Licence as stated there: "ALL models are available for non-commercial research purposes only."
Commercial use needs a separate licence from InsightFace (their site's licensing page).

| Pack | Detector | Recogniser | Zip SHA-256 |
|---|---|---|---|
| `buffalo_l` (**selected**) | SCRFD-10GF `det_10g.onnx` | ResNet50 on WebFace600K `w600k_r50.onnx` | `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` |
| `buffalo_sc` (downloaded, not used) | SCRFD-500MF | MobileFaceNet on WebFace600K | `57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72` |
| `antelopev2` (downloaded, not used) | SCRFD-10GF (same bytes as `det_10g`) | ResNet100 on Glint360K | `8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5` |

File hashes and the selection record: [`reference-model-selection.md`](reference-model-selection.md).
The weights are local files (`local-models/`, `*.onnx` are Git-ignored) and every installed package
manifest records them as `redistributable: false`.

### 2.2 The architectures

SCRFD and ArcFace are published methods; the *architecture* is not the issue here, the *trained
weights* and their *training data* are. A model trained by the owner on data the owner may use would
carry no third-party weight licence.

### 2.3 Training-data terms (not verified)

The WebFace600K and Glint360K training sets behind these weights come with their own terms, which
may restrict commercial use of models trained on them, independent of InsightFace's own licence. Any
replacement weights need the same check. From search results only (not verified): the ONNX Model Zoo
`arcfaceresnet100-8.onnx` is listed under Apache-2.0 and was trained on MS1M-derived data; the status
of that training data must be checked before anyone relies on it.

## 3. Our own code

- No `LICENSE` file exists. Decide before any sharing: proprietary, or an open licence. Whether a
  chosen licence fits the dependencies depends on how the product is distributed: the notice and
  source obligations of the licences below (MPL-2.0, OFL-1.1, Apache-2.0, LGPL builds of FFmpeg) must
  be reviewed for the actual distribution, not assumed.
- **Authorship.** Much of the code was written with an AI coding assistant under the owner's
  direction. Whether and how that affects ownership or licensing differs by jurisdiction and is a
  question for the owner's lawyer before commercial use; record the assistant's involvement honestly
  rather than assuming it away.
- Specs, plans and documents under `docs/` are the owner's/assistant's own text.

## 4. Runtime libraries

| Component | Licence | Where used | Note |
|---|---|---|---|
| ONNX Runtime (`onnxruntime` 1.30.0, CPU) | MIT | the ML worker | verified from package metadata |
| ONNX Runtime GPU (`onnxruntime-gpu` 1.23.2) | MIT (its own files) | optional CUDA path, installed as a machine-local runtime library | the CUDA/cuDNN files it needs are NVIDIA's, next row |
| NVIDIA CUDA runtime, cuDNN, cuBLAS, cuFFT, cuRAND, NVRTC (pip `nvidia-*-cu12`) | NVIDIA proprietary licences (not verified in detail) | GPU inference only | redistribution inside an installer is governed by NVIDIA's terms; read them per file before shipping |
| USearch (`usearch` 2.26.2) | Apache-2.0 | the vector index | verified |

## 5. Python dependencies (verified from installed metadata, 2026-10-07)

Runtime: `alembic` 1.20.0 MIT; `fastapi` 0.142.2 MIT (with `starlette` 1.7.0 BSD-3-Clause and
`pydantic` 2.13.5 MIT); `numpy` 2.5.3 BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; `pillow`
12.3.0 MIT-CMU; `sqlalchemy` 2.0.54 MIT; `uvicorn` 0.54.0 BSD-3-Clause; `websockets` 17.2
BSD-3-Clause; `usearch` Apache-2.0; `onnxruntime` MIT.
Development only (not shipped): `pytest` 9.1.1 MIT; `pytest-asyncio` 1.4.0 Apache-2.0; `pytest-cov`
7.1.0 MIT (with `coverage` 7.16.1 Apache-2.0); `httpx` 0.28.1 BSD-3-Clause; `hypothesis` 6.168.1
**MPL-2.0** (file-level copyleft; fine as a test tool, do not bundle); `ruff` 0.16.8 MIT; `mypy` 2.3.1
MIT; `onnx` 1.23.1 Apache-2.0.
This is the list of **direct** dependencies. Transitive packages were not individually reviewed:
regenerate with the commands in section 8 before a release.

## 6. Front end (verified from `node_modules` metadata, 2026-10-07)

Direct runtime packages: `react` and `react-dom` 19.3.0 MIT; `react-router` 8.4.0 MIT;
`@tanstack/react-query` 5.104.1 MIT; `zustand` 5.0.15 MIT; `tailwindcss` and `@tailwindcss/vite` 4.3.3
MIT; `radix-ui` 1.6.7 MIT; `shadcn` 4.21.0 MIT (its components are copied into the repo; keep its
licence notice); `class-variance-authority` 0.7.1 Apache-2.0; `cn` 0.4.0 MIT; `tw-animate-css` 1.4.0
MIT; `lucide-react` 1.47.0 **ISC** (icons); `@tauri-apps/api` 2.11.1 Apache-2.0 OR MIT;
`@fontsource-variable/geist` 5.3.0 **OFL-1.1** (the Geist font: bundling is allowed, selling the font
alone is not, and the reserved font name must not be reused for a modified font).
Build and test only (direct): `vite` 8.3.0, `vitest` 5.0.1, `@vitejs/plugin-react` 6.1.1, `jsdom` 30.1.1,
`ws` 8.22.0, `openapi-typescript` 7.13.0, `oxlint` 1.85.0, `@testing-library/dom` 10.4.2,
`@testing-library/jest-dom` 7.0.1, `@testing-library/react` 16.3.3, `@testing-library/user-event`
14.6.7, `@types/node` 24.13.6, `@types/react` 19.3.0, `@types/react-dom` 19.3.0, `@types/ws`
8.18.2: all MIT; `typescript` 6.0.3 Apache-2.0. At the repository root: `@tauri-apps/cli` 2.11.5
`Apache-2.0 OR MIT` (the Tauri build command).
A bundle shipped to users must carry the notices these licences require (MIT, ISC, Apache-2.0 and
OFL all require the licence text to travel with the software): generate a third-party notices file
at packaging time (M8).

## 7. Desktop shell, build and packaging (not verified)

Rust crates used directly (`desktop/src-tauri/Cargo.toml`): `tauri` (MIT OR Apache-2.0 as far as is
known), `tauri-plugin-log`, `tauri-plugin-dialog`, `tauri-plugin-single-instance`, `serde`,
`serde_json`, `log`, `base64`, `getrandom`; build: `tauri-build`; dev: `tempfile`. All are expected
to be MIT and/or Apache-2.0 but **none has been checked**: run `cargo license` (or `cargo deny`) before a release.
Not chosen yet (M6 to M8), each needing a row when it is: FFmpeg or PyAV for video (an LGPL build is
usable in a closed product only if its conditions are met: dynamic linking, the exact build
configuration, the licence text and notices, a source offer where it applies, and the user's ability to
replace the library; a GPL or `--enable-nonfree` build is not suitable for a closed product); PyInstaller or another bundler for the Python sidecar; the Windows installer toolkit; code
signing; the Python and Node distributions that would be shipped (the Python licence is permissive).

## 8. How to regenerate the inventory

These print name, resolved version and licence, and work in PowerShell and Git Bash alike:

```bash
# Python (every installed package)
uv run python -c "from importlib.metadata import distributions as d; [print(x.metadata['Name'], x.version, x.metadata.get('License-Expression') or x.metadata.get('License')) for x in sorted(d(), key=lambda y: y.metadata['Name'].lower())]"
# JavaScript (every package under node_modules)
node -e "const fs=require('fs'),path=require('path');const walk=d=>{for(const n of fs.readdirSync(d)){if(n.startsWith('.'))continue;const p=path.join(d,n);if(n.startsWith('@')){walk(p);continue}try{const j=JSON.parse(fs.readFileSync(path.join(p,'package.json')));console.log(j.name,j.version,typeof j.license==='object'?j.license.type:j.license)}catch(e){}}};walk('node_modules')"
# Rust (after installing cargo-license)
cargo license --manifest-path desktop/src-tauri/Cargo.toml
```

## 9. Obligations that are not licences

A product that recognises faces is regulated apart from the licences above. Examples to take advice
on before commercial use (not exhaustive, not advice): the EU GDPR (biometric data for identification
is special-category data, Article 9) and the EU AI Act's rules on biometric identification; Illinois
BIPA and similar US state laws (written notice and consent, retention schedules, private rights of
action); CCPA/CPRA; local rules on video and camera surveillance (M7). The product's design already
helps (everything local, user-controlled deletion and forgetting, query-is-not-ingest), but none of
that replaces consent and retention rules for other people's faces.

## 10. Evaluation data

- **Wikimedia Commons public-domain photographs** (`evaluation/build_commons_dataset.py`): only files
  whose own metadata names an allow-listed public-domain status (`Public domain`, `PD-USGov*`) are
  kept; the per-file licence name and URL, author, credit, source page, acquisition time and SHA-256
  are recorded in the local `manifest.json`. They are used locally for measurement and **never
  committed or redistributed** (`evaluation/datasets/` is Git-ignored). Public-domain copyright does
  not remove personality, privacy or biometric-data rights of the people shown.
- **Test pictures** under `local-models/images` (NASA photographs from Wikimedia Commons) are local
  and not committed.
- The Labeled Faces in the Wild dataset was not used (its host was unreachable and its terms could
  not be checked).
- Owner-supplied photographs, when added, are the owner's private data and stay local.

## 11. Before any release: checklist

1. Choose the licence for our code and add `LICENSE`.
2. Replace or license the face models (section 2) and re-run the evaluation.
3. Resolve the NVIDIA redistribution question or ship CPU only.
4. Run the three inventory commands, review transitive packages, fill section 7.
5. Generate the third-party notices file for the installer.
6. Legal review of the biometric-privacy obligations for each target market.
7. Remove or relabel everything marked developer-only (the development profile, local weights,
   evaluation scripts).
