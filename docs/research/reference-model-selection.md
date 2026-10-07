# Reference model selection (issue #69)

**Date:** 2026-10-07. **Status:** selection made by the agent under the owner's delegation of
2026-10-07 ("select by documented criteria"); the owner may override on return, which re-runs
tracks R2 to R4 of [`M5_PLAN.md`](../plans/M5_PLAN.md). Models are replaceable reference
components (ML spec 18.1).

## Intended use and what that allows

Owner decision 2026-10-07: FaceIdentify is **personal and local only**; it is never sold, bundled or
distributed, and the owner accepted using research-licensed weights as developer-supplied local files
under that. **This is not a legal opinion:** the licence text says "non-commercial research purposes
only", and whether a personal application falls inside "research" is the rights-holder's to say, so the
use right is an **owner-accepted risk**, not a verified permission. The licence is also a **release
blocker** (ML spec 18.1), recorded in every manifest as `redistributable: false`. The weights are
never committed (`local-models/` and `*.onnx` are Git-ignored).

## Candidates

All from the official InsightFace model zoo
(<https://github.com/deepinsight/insightface/tree/master/model_zoo>), downloaded from the official
release assets `https://github.com/deepinsight/insightface/releases/download/v0.7/<pack>.zip`.
Licence, stated by the zoo page: "ALL models are available for non-commercial research purposes
only". The code is MIT; the pretrained models are not. Commercial use needs a separate licence from
InsightFace.

| Pack | Detector | Recogniser | Zip size | Zip SHA-256 |
|---|---|---|---|---|
| `buffalo_l` | SCRFD-10GF (`det_10g.onnx`) | ResNet50 on WebFace600K (`w600k_r50.onnx`) | 288,621,354 | `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` |
| `buffalo_sc` | SCRFD-500MF (`det_500m.onnx`) | MobileFaceNet on WebFace600K (`w600k_mbf.onnx`) | 14,969,382 | `57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72` |
| `antelopev2` | SCRFD-10GF (`scrfd_10g_bnkps.onnx`, byte-identical to `det_10g.onnx`) | ResNet100 on Glint360K (`glintr100.onnx`) | 360,662,982 | `8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5` |

Model files measured after unpacking:

| File | Bytes | SHA-256 |
|---|---|---|
| `buffalo_l/det_10g.onnx` | 16,923,827 | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` |
| `buffalo_l/w600k_r50.onnx` | 174,383,860 | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` |
| `buffalo_sc/det_500m.onnx` | 2,524,817 | `5e4447f50245bbd7966bd6c0fa52938c61474a04ec7def48753668a9d8b4ea3a` |
| `buffalo_sc/w600k_mbf.onnx` | 13,616,099 | `9cc6e4a75f0e2bf0b1aed94578f144d15175f357bdc05e815e5c4a02b319eb4f` |
| `antelopev2/glintr100.onnx` | 260,665,334 | `4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf` |

## Selection: `buffalo_l` (`det_10g.onnx` + `w600k_r50.onnx`)

Criteria, from ML spec section on the detector and embedder: an artifact and a licence that fit the
stated use, five-point landmarks for the alignment contract, ONNX Runtime operators that load on CPU
and CUDA, a dimension and normalisation the contracts already cover, and a quality level worth
calibrating.

- **Licence:** acceptable for personal and local use; release blocker recorded.
- **Landmarks:** `det_10g` returns scores, boxes and five-point landmarks at strides 8, 16 and 32, the
  nine-tensor layout `scrfd-letterbox-v1` already decodes (scores 0 to 2, boxes 3 to 5, landmarks 6 to
  8; shapes `[N,1]`, `[N,4]`, `[N,10]`).
- **Embedder:** `w600k_r50` takes `[batch,3,112,112]` and returns 512 floats, the `arcface-112`
  contract (the model does not normalise: the contract's L2 normalisation does).
- **Why not the others:** `buffalo_sc` is a small-footprint fallback with lower recognition accuracy;
  `antelopev2` (ResNet100) is the quality-oriented alternative to compare in R4 if `w600k_r50` proves
  too weak, at about 2x the compute. Switching is a new representation space, by design.

## Verified so far (2026-10-07, CPU, this machine)

`scripts/install_reference_models.py` built and installed the package through the production store;
`scripts/smoke_real_models.py` ran the production perception client and supervisor with the real
worker on `CPUExecutionProvider` over four public-domain NASA photographs from Wikimedia Commons
(local files, not committed). Detection found the expected faces with scores 0.76 to 0.90, 512-d unit
vectors came back, and cosine similarity separated people: same person across photographs 0.59 to
0.69, different people 0.03 to 0.21. These are smoke results, not calibration (R4).

## Not yet verified

CUDA on the RTX 4070, CPU/CUDA agreement, and restart and catalog registration with the real package
are recorded in the implementation entries as they are done.
