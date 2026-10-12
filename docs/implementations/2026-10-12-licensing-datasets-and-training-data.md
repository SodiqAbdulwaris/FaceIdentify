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

## Not changed

No code and no behaviour. The WIDER FACE row comes from the SCRFD paper, not from reading the dataset's terms.
