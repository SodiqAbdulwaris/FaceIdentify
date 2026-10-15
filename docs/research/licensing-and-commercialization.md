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
| 4b | **Microsoft DirectML** (since 2026-10-15) | The shipped Windows build bundles `DirectML.dll` under Microsoft's proprietary DirectML terms (section 4). They permit distribution inside an application for Windows (read 2026-10-15). | Ship the terms with the installer and keep Microsoft's notices; confirm the wheel's copy is covered (section 4). |
| 5 | **Unverified Rust crates and the build tools of M8** | `cargo-license` has not been run; the installer, signing and any bundled FFmpeg are not chosen yet. | Run the inventory in section 8 and fill sections 5 to 7. |

> **Decision 2026-10-15:** (owner; `.agents/CONTEXT.md` Known conflicts 32) CUDA is developer-only and never shipped (the shipped Windows build is `onnxruntime-windowsml`, DirectML then the CPU), so blocker 4 no longer applies to a release; blocker 4b replaces it.

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
| ONNX Runtime (`onnxruntime` 1.30.0, CPU) | MIT | the ML worker off Windows (Linux CI), through an environment marker since 2026-10-15 | verified from package metadata |
| ONNX Runtime Windows ML (`onnxruntime-windowsml` 1.30.0.202609102321) | MIT (wheel metadata `License: MIT License` and its `LICENSE`, "Copyright (c) Microsoft Corporation", read 2026-10-15) | **the shipped Windows build** (owner decision 2026-10-15): the ML worker, DirectML then the CPU | 74 MB installed. Ships `ThirdPartyNotices.txt` and a `Privacy.md` stating that official builds send ONNX Runtime trace events through Windows' ETW telemetry, on by default and subject to the user's Windows diagnostic-data consent; whether the worker should turn it off (`onnxruntime.disable_telemetry_events()`) is a follow-up, not decided here |
| Microsoft DirectML (`DirectML.dll` 1.15.4, "DirectML Redistributable Library", bundled in `onnxruntime-windowsml`) | Microsoft Software License Terms for DirectML (proprietary), read 2026-10-15 from the `LICENSE.txt` of the matching `Microsoft.AI.DirectML` 1.15.4 NuGet package | GPU inference on Windows | Section 1a permits copying and distributing the software "in applications and services you develop" that run on Windows and Xbox; no reverse engineering, no removing Microsoft's notices, no stand-alone redistribution (3e); section 2 says the software may collect usage data. The wheel itself does not carry these terms (they were read from the NuGet package of the same version), so whether they are the terms that govern the copy inside the wheel is an inference, not verified; ship the terms file with the installer |
| ONNX Runtime GPU (`onnxruntime-gpu` 1.23.2) | MIT (its own files) | optional CUDA path, installed as a machine-local runtime library | the CUDA/cuDNN files it needs are NVIDIA's, next row |
| NVIDIA CUDA runtime 12.9, cuDNN 9.27, cuBLAS, cuFFT, cuRAND, NVRTC, nvJitLink (pip `nvidia-*-cu12`, installed 2026-10-07 into the Git-ignored `local-models/ort-gpu`) | NVIDIA proprietary licences (not verified in detail) | GPU inference only (`FACEIDENTIFY_ORT_GPU_DIR`) | redistribution inside an installer is governed by NVIDIA's terms; read them per file before shipping |
| ONNX Runtime DirectML builds (`onnxruntime-directml` 1.23.0, `onnxruntime-windowsml` 1.30.0) | MIT (wheel `LICENSE`); each bundles Microsoft's `DirectML.dll`, whose redistribution terms are not verified | **evaluated only** (2026-10-15, installed into a scratch folder outside the repository, never a dependency) | candidate shipped build, owner decision pending (`docs/research/onnx-runtime-gpu-packaging.md`); read the `DirectML.dll` terms before shipping |
| USearch (`usearch` 2.26.2) | Apache-2.0 | the vector index | verified |

> **Decision 2026-10-15:** (owner; `.agents/CONTEXT.md` Known conflicts 32) `onnxruntime-windowsml` 1.30.0 is the shipped Windows build and a dependency (rows above); `onnxruntime-directml` stays evaluated only. The `DirectML.dll` terms were read (row above); CUDA is developer-only and never shipped, so the NVIDIA libraries are not part of a release (blocker 4).

## 5. Python dependencies (verified from installed metadata, 2026-10-07)

Runtime: `alembic` 1.20.0 MIT; `fastapi` 0.142.2 MIT (with `starlette` 1.7.0 BSD-3-Clause and
`pydantic` 2.13.5 MIT); `numpy` 2.5.3 BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; `pillow`
12.3.0 MIT-CMU (its wheel bundles libavif 1.4.2 BSD-2-Clause with the dav1d 1.5.3 decoder,
BSD-2-Clause, used to read AVIF pictures since 2026-10-15, issue 188; the bundled aom 3.14.1,
BSD-2-Clause with the AOMedia patent licence, is only an encoder, which the application never calls); `sqlalchemy` 2.0.54 MIT; `uvicorn` 0.54.0 BSD-3-Clause; `websockets` 17.2
BSD-3-Clause; `usearch` Apache-2.0; `onnxruntime` MIT (off Windows); `onnxruntime-windowsml` MIT with Microsoft's `DirectML.dll` (on Windows, since 2026-10-15; section 4).
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

## 10. Datasets and training data

**FaceIdentify does not train or fine-tune any model.** The two networks it runs (a face detector and a
face recogniser) are third-party pretrained weights used **unmodified** (section 2), so the project has no
training set of its own. The datasets that matter are therefore (a) the data *upstream* trained the weights
on, whose terms may affect training and downstream commercial use of the weights (subject to
verification: none of it has been read at source), and (b) the data *we* use to evaluate and calibrate them. If the
project ever trains or fine-tunes a model, every training set is added here in the same change.

### 10.1 Data the pretrained weights were trained on (not ours; terms not verified)

| Dataset | Behind which weights | Used here | Status of its terms |
|---|---|---|---|
| WebFace600K (derived from WebFace260M) | `buffalo_l` recogniser `w600k_r50.onnx` (selected); `buffalo_sc` | `buffalo_l` yes; `buffalo_sc` downloaded, not used | **Not verified.** Its own terms may restrict commercial use of models trained on it, independent of InsightFace's licence (section 2.3). |
| WIDER FACE (as the SCRFD paper reports training SCRFD) | `buffalo_l` detector `det_10g.onnx` | yes | **Not verified, twice over:** this is the paper-level training data of the SCRFD method, and the link from that paper to this exact model-zoo checkpoint is **not documented** here; the dataset's terms were not read at source either. An open question for any commercial release. |
| Glint360K | `antelopev2` recogniser `glintr100.onnx` | downloaded, **not used** | Not verified; irrelevant unless that package is adopted. |
| MS1M-derived data | `arcfaceresnet100-8.onnx` (ONNX Model Zoo, Apache-2.0), considered as an alternative | **not used** | Search results only, **not verified** (section 2.3): neither the licence listing nor the training-data attribution was read at source. |

### 10.2 Data we use to evaluate and calibrate (ours to account for)

| Dataset | Role | Size and provenance | Terms | Committed? |
|---|---|---|---|---|
| **Wikimedia Commons public-domain photographs** (`evaluation/build_commons_dataset.py`) | Measuring recognition (TST-044, TST-057A/B) and the operating point; the pool the owner reviews with `evaluation/label_review.py` | 44 people, 662 photographs on this machine, every one marked `public domain` by Commons' own metadata; only allow-listed statuses (`Public domain`, `PD-USGov*`) are kept | Public-domain copyright does **not** remove personality, privacy or biometric-data rights of the people shown. | **No**: `evaluation/datasets/` is Git-ignored; never redistributed |
| NASA test pictures from Wikimedia Commons (`local-models/images`) | Local smoke tests of the runtime | a handful of files | public domain per Commons | No (local only) |
| Owner-supplied photographs | The independent smoke test for TST-057A; any future private evaluation | the owner's own data | the owner's private data | No; stays local |

Honest limits of the Commons set, which matter for any claim built on it:

- **Its identity labels are Commons categories, not verified identity.** A human review is in progress
  (R5; owner, from 2026-10-12): decisions, reviewer, time and photograph digests are kept in the local
  `review/decisions.jsonl`, and only verified labels enter the verified manifest. Quality numbers are
  reported against provisional labels until then.
- **What the local manifest records.** Each of the 662 entries holds the file, the Commons title, the
  thumbnail URL and the licence name. The builder script is written to also record author, credit, source
  page, acquisition time and SHA-256, but the manifest currently on disk was built without them: those
  must be re-collected before any decision to share or publish the set. The review utility records a
  SHA-256 per photograph it reviews.
- The set is small, formal and skewed toward adults photographed officially; it is a development aid,
  not a benchmark.
- **LFW and CelebA (both downloaded and evaluated 2026-10-13):** ready-labelled research datasets the owner
  downloads and imports locally with `evaluation/import_labelled_dataset.py` (labels by their creators, not
  verified here). **Sources (owner, 2026-10-13):** LFW from the Kaggle mirror
  <https://www.kaggle.com/datasets/jessicali9530/lfw-dataset> (the original is the UMass LFW page; the mirror's own
  licence and terms were not retrievable from the agent's environment); CelebA from the creators'
  page <https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html> (its `README.txt` states non-commercial research use).
  **Terms: see section 10.3**; both are research datasets; they stay local, are never committed or
  redistributed, and their people may also appear in the recogniser's training data (evaluation
  leakage). Reading each dataset's terms at its source is issue 183 (CelebA done 2026-10-15; LFW's page still to read, section 10.3).
- **Celebrity portraits from Wikimedia Commons (`evaluation/datasets/celebs-commons`, from 2026-10-14):**
  read with `collect_commons_portraits.py --licence free` (the owner's script, reviewed and fixed). Each
  file's licence (public domain, CC0, CC BY or CC BY-SA 2.0 to 4.0; never NC or ND), licence URL, author,
  credit and source page are in the local manifest; Commons' metadata is taken as given and flagged
  `rights_reviewed: false`. CC BY and BY-SA ask for attribution (and share-alike for adaptations): the
  manifest keeps what attribution needs, but keeping it privately is not a compliance statement for
  any future sharing; the files stay local and are never redistributed.
- **`MyFaces/` (owner's own photographs, 11 files, 2026-10-13):** local only and Git-ignored. Used only to
  measure the detector on the owner's own pictures; never committed, uploaded or shared; the owner's
  own pictures as supplied by the owner (who took them and under what rights is not verified here),
  and biometric data like the others.
- The Commons set above is **parked**, not removed: its review log and exports stay for later.

### 10.3 LFW and CelebA terms, read at source (2026-10-15)

This is a **reading of published terms by an engineer's assistant, not legal advice.** Quotes are kept
to a few words; everything else is a summary.

**CelebA** (<https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html>, "Agreement" section, read 2026-10-15)

- *Who and what for:* available for "non-commercial research purposes only". Access can be terminated
  by MMLAB at any time.
- *Redistribution:* users agree not to copy, publish or distribute any portion of the dataset; copies
  for internal use at a single site within the same organisation are allowed. Selling, trading or
  exploiting the images or derived data commercially is excluded.
- *Third-party rights:* the images are stated not to be MMLAB's property; MMLAB is not responsible for
  their content. The page names no open licence (no Creative Commons or similar).
- *Citation:* Liu, Luo, Wang, Tang, "Deep Learning Face Attributes in the Wild", ICCV 2015.
- *Identities:* the identity labels are released on request, for research only.

**LFW** (official page <http://vis-www.cs.umass.edu/lfw/>: **could not be read**)

- The host did not resolve from this machine or from the fetch tool on 2026-10-15 (DNS failure, tried
  http and https and the README path; the Wayback copy is blocked). **The page's own terms, if any,
  remain unread.** Reading it, and the Kaggle mirror's licence field, are the two open steps of issue 183.
- What was read instead: the official technical report by Huang, Ramesh, Berg and Learned-Miller
  (<https://people.cs.umass.edu/~elm/papers/lfw.pdf>). It states no licence or conditions of use. It
  says the database is "an aid in studying" unconstrained face recognition, built from pre-existing
  photographs gathered from news articles on the web (images detected by Viola-Jones, 250x250), and
  that results should state which of its protocols was used. So the images were not made for the
  dataset and carry **their original photographers' and publishers' rights**; the creators' consent
  to anything beyond research use is not documented there.
- Third-party listings (a catalogue showing "Other"; scikit-learn's BSD marking covers its loader code
  only) are not terms and were not relied on. The Kaggle mirror's licence field is also still unread.

**What this means for the project**

| Question | CelebA | LFW |
|---|---|---|
| Use here (local evaluation of recognition) | within "non-commercial research" | research evaluation; page terms unread |
| Redistribute, commit, publish, bundle in an installer | **No** | **No** (treat as not allowed until the page is read) |
| Commercial product or any commercial use of the images or derived data | **No** | Not established; assume **no** |
| Images carry third-party rights | Yes (stated) | Yes (news photographs) |

Consequences: both stay under the Git-ignored `evaluation/datasets/`, are never committed, uploaded,
shipped or used to tune a shipped model, and the repository holds none (checked by the ignore rule
and `git ls-files`, 2026-10-15). A shared or commercial release cannot use them, and a release must
not depend on numbers measured only on them without the owner accepting that. Their people may also
appear in the recogniser's training data (evaluation leakage). Recorded here, not decided:
whether results measured on them may be published (a question for the licence holders or a lawyer).

## 11. Before any release: checklist

1. Choose the licence for our code and add `LICENSE`.
2. Replace or license the face models (section 2) and re-run the evaluation.
3. Resolve the NVIDIA redistribution question or ship CPU only.
4. Run the three inventory commands, review transitive packages, fill section 7.
5. Generate the third-party notices file for the installer.
6. Legal review of the biometric-privacy obligations for each target market.
7. Remove or relabel everything marked developer-only (the development profile, local weights,
   evaluation scripts).
