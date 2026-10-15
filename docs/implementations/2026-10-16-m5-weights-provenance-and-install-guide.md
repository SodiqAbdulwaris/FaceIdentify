# M5 close-out: the weights' provenance re-checked (issue #69) and a Windows install guide

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 track R (R1 close-out); issue #69
- **Status:** done; documentation only
- **Commits:** PR (number recorded when merged): `docs: record the weights' provenance check and
  install guide`

## What changed

- `docs/research/reference-model-selection.md`: a dated *Provenance re-checked* section. The exact
  files in use were hashed again and match the recorded SHA-256s; the installed manifest's source,
  licence and `redistributable: false` were read back.
- `docs/guides/INSTALLING_MODELS_WINDOWS.md` (new): from a fresh clone to the real models on the
  GPU: the ONNX Runtime build (`onnxruntime-windowsml`, DirectML then the CPU), downloading and
  checking `buffalo_l`, installing the runtime package into the right local state root (the desktop
  shell's `%LOCALAPPDATA%\io.github.sodiqabdulwaris.faceidentify\state`, or a developer root), the
  two admitted policy files, the provider settings (CUDA developer-only), and how to check which
  provider ran.
- `.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md`, this entry and its README row.

## Why

Issue #69 (ML spec 18.1, decision of 2026-10-02): the licence and provenance of the exact SCRFD and
ArcFace weights must be verified and recorded. The selection (2026-10-07) recorded the source, the
licence and every hash; this closes the loop by checking the files actually in use against that
record, and gives the owner one place that says how to reproduce the installation. The M5 close-out
asked for both.

## Decisions

- **Issue #69 closes as recorded and verified; the licence stays a release blocker.** Verifying
  provenance does not change the licence: the weights remain "non-commercial research purposes only",
  used under the owner-accepted risk of 2026-10-07, never redistributed. The release blocker lives in
  every manifest (`redistributable: false`) and in the licensing record, not in an open issue.
- **The guide warns against reinstalling under an existing library.** A package installed before
  2026-10-15 has no DirectML variant, but a library refuses a different manifest for a package it
  has registered, so a reinstall would make the package unavailable to that library. Moving an
  existing library to the new manifest is a separate decision (not taken here).
- **No new script.** The guide uses the existing `install_reference_models.py` and
  `smoke_real_models.py`.

## Verification

- On this machine, 2026-10-16: `sha256sum` of `local-models/_download/buffalo_l.zip`
  (`80ffe37d…ca2f`), `local-models/buffalo_l/det_10g.onnx` (`5838f7fe…5b91`),
  `local-models/buffalo_l/w600k_r50.onnx` (`4c06341c…9e43`) and the two installed copies under
  `local-models/state/runtime/packages/insightface-buffalo-l/models/`: all equal to the recorded
  values. The installed `manifest.json` carries the same hashes and sizes (16,923,827 and
  174,383,860 bytes), the v0.7 release source, the licence string and `redistributable: false`.
- The guide's commands and paths were checked against the code: the shell's state root
  (`desktop/src-tauri/src/lib.rs` `start_backend`, identifier in `tauri.conf.json`), the policy file
  name and admitted versions (`backend/api/real.py` `load_policy`, `APPROVED_MATCHING`), the
  abstain-only example (`tests/e2e/test_real_host.py` `ABSTAIN_ONLY`), `FACEIDENTIFY_PROVIDERS`,
  `FACEIDENTIFY_ORT_GPU_DIR`, `FACEIDENTIFY_DEVELOPMENT_PROFILE` (`desktop/src-tauri/src/config.rs`)
  and `/readiness`'s `execution_provider` / `provider_fallback`. The guide was not followed end to end
  on a fresh machine.

## Open issues / follow-ups

- The installed package in `local-models/state` still predates the DirectML variants (it runs on the
  CPU); moving the owner's library to the new manifest needs a decision.
- Observed 2026-10-16 (not changed: this work may not write to `local-models/`): in
  `local-models/state/policies/`, both `insightface-buffalo-l.json` and the backup
  `insightface-buffalo-l.abstain-only-v1.json` hold the **matching** policy
  (`buffalo-l-verified-match-v1`), so copying the backup over the live file would not return to
  abstain-only. The abstain-only content is in the guide, section 4.
- DirectML on AMD GPUs and on machines without DirectX 12 is unverified (2026-10-15 entry).
