# Licensing record: datasets and training data

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** documentation (owner request); supports the commercialisation record
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

`docs/research/licensing-and-commercialization.md` section 10 is now "Datasets and training data":

- It states plainly that FaceIdentify **trains and fine-tunes nothing**: the detector and recogniser are
  third-party pretrained weights used unmodified, so the project has no training set of its own.
- 10.1 lists the data the pretrained weights were trained on (WebFace600K behind the `buffalo_l` recogniser,
  WIDER FACE for the SCRFD detector as published, Glint360K and MS1M-derived data for the packages that are
  not used), each marked *terms not verified*.
- 10.2 lists the data we use to evaluate and calibrate: the Wikimedia Commons public-domain set (44 people,
  662 photographs, local and never committed, labels under human review), the NASA test pictures and the
  owner's private photographs.
- It corrects an overstatement: the manifest on disk holds only file, title, thumbnail URL and licence name
  per photograph. The builder script is written to also record author, credit, source page, acquisition time
  and SHA-256, so those must be re-collected before any decision to share the set.

## Verification and its limits

- **Checked directly on this machine:** no training or fine-tuning code exists in the repository (inference and
  calibration only); the local Commons manifest has 44 categories and 662 entries, each with exactly `file`,
  `title`, `url` and `licence`, every licence `public domain`; the builder script writes more fields than the
  manifest holds; the review decision log supports "review in progress".
- **Taken from the existing records, not re-checked:** which dataset is behind which weights (the model-selection
  record and section 2); the MS1M and Apache-2.0 statement for the zoo model (search results only).
- **Not verified at all:** the terms of WebFace600K/WebFace260M, WIDER FACE, Glint360K and MS1M; whether the
  SCRFD paper's training data is exactly what the model-zoo `det_10g.onnx` was trained on. Live upstream checks
  need network access and were not made.
- Pull request: #165.

## Not changed

No code and no behaviour. The WIDER FACE row comes from the SCRFD paper, not from reading the dataset's terms.
