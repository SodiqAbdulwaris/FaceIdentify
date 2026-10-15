# AVIF pictures are accepted (issue 188)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 follow-up · TST-037, TST-056 · issue
  [#188](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/188)
- **Status:** built; the spec notes await the owner's approval
- **Commits:** PR (this branch, `feat/avif-image-support`): `feat(media): accept AVIF images`,
  `feat(ui): offer AVIF in the pickers and face search`, `docs: record AVIF support (#188)`

## What changed

- `backend/infrastructure/media/image.py`: AVIF is a fifth accepted format (`image/avif`). Its
  signature (an ISO-BMFF `ftyp` box naming the `avif` or `avis` brand at byte 8) makes a damaged
  AVIF `CorruptImageError`, not `UnsupportedImageError`. libavif reports a failed pixel decode as
  `RuntimeError`, which Pillow's other readers never raise; it is now caught with the others and
  becomes `CorruptImageError` (without this, a damaged AVIF would have been a 500 on every route).
- One decoder serves import (`ImportSourceUseCase`), processing (`ExecuteProcessingJob`) and face
  search (`FaceQuery`), so all three accept AVIF under the same byte limit (the caller's), pixel
  limit (header-checked before any pixel exists), Pillow ceiling and error mapping.
- The two `MEDIA_FORMAT_UNSUPPORTED` messages (`sources.py`, `face_search.py`) name AVIF.
- `desktop/src-tauri/src/config.rs`: the native picker offers `.avif`.
- `frontend/src/features/search/FaceSearch.tsx`: a chosen, dropped or pasted `image/avif` is sent;
  the refusal message names AVIF.

## Why

The owner's photographs folder held a `.avif` that was refused (issue 188, 2026-10-14). AVIF is
common on the web.

## Decisions

- **No new dependency.** The pinned `pillow` 12.3.0 decodes AVIF from its own wheel: libavif 1.4.2
  with the dav1d 1.5.3 decoder (both BSD-2-Clause; aom 3.14.1 is bundled for encoding only, which
  the application never does). Recorded under `pillow` in
  `docs/research/licensing-and-commercialization.md`.
- **HEIF stays refused.** Pillow's AVIF reader also tries the generic `mif1`/`msf1` brands; such a
  file that is not an AVIF is still "not ours" (`UnsupportedImageError`), so HEIC photographs keep
  their old answer. A genuine AVIF whose major brand is `mif1` decodes; only if it is also damaged
  is it called unsupported rather than corrupt.
- **The spec.** `API and Contracts.md` lists the accepted formats in two decision notes (import,
  2026-10-02; face search, 2026-10-10). Editing a spec needs the owner's approval; the supervising
  session asked the owner on 2026-10-15. Until the answer, the notes are unchanged and the
  conflict is recorded in `.agents/CONTEXT.md` (item 32).
- An AVIF's orientation (EXIF orientation, carried by libavif as `irot`/`imir`) is applied exactly
  once: all eight orientations come out upright (tested).

## Verification

- `uv run pytest tests/unit/test_image_decode.py`: 88 passed (73 before). New: an AVIF identified
  and close to its source (lossy), all eight orientations, an animated AVIF's first frame, a header
  read decodes nothing, an AVIF over the limit refused before decoding, cut short and
  signature-only AVIFs corrupt, damaged pixels corrupt, a `mif1` HEIF unsupported.
- `tests/integration/test_api_face_search.py`: an AVIF imported, processed, indexed and found by a
  face search with an AVIF (by path and by bytes); a damaged AVIF `422 MEDIA_CORRUPT` from face
  search (path and bytes) and from import, writing nothing.
- Both damaged-AVIF tests were run without the `RuntimeError` mapping and failed; they pass with it.
- `FaceSearch.test.tsx`: a dropped `image/avif` is sent; the refusal names AVIF.
- `cargo test config` (desktop): 9 passed.
- Full gate: see the PR description for the final results.

## Open issues / follow-ups

- The two spec notes, once the owner answers.
- Writing AVIF (thumbnails, exports) is not needed and not done.
