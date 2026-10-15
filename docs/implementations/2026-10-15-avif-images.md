# AVIF pictures are accepted (issue 188)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 follow-up · TST-037, TST-056 · issue
  [#188](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/188)
- **Status:** done (awaiting merge)
- **Commits:** PR (this branch, `feat/avif-image-support`): `feat(media): accept AVIF images`,
  `feat(ui): offer AVIF in the pickers and face search`, `docs: record AVIF support (#188)`,
  `docs(specs): accept AVIF images (owner decision)`, `docs: record the AVIF gate results`, and
  after the Codex review `fix(media): find the AVIF brand anywhere in the ftyp box`,
  `fix(media): decode each AVIF on one thread`, `test(ui): use the five-format message in the
  library test`, `docs: record the AVIF review fixes`

## What changed

- `backend/infrastructure/media/image.py`: AVIF is a fifth accepted format (`image/avif`). Its
  signature (an ISO-BMFF `ftyp` box listing the `avif` or `avis` brand, as its major brand or a
  compatible one, read within the box's own size and at most 4 KiB) makes a damaged AVIF
  `CorruptImageError`, not `UnsupportedImageError`. libavif decodes on one thread
  (`AvifImagePlugin.DEFAULT_MAX_THREADS = 1`), like every other decoder here; Pillow's default is
  one thread per CPU for every image. libavif reports a failed pixel decode as
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
  their old answer. A genuine AVIF whose major brand is `mif1` and lists `avif` among its
  compatible brands decodes, and when damaged is corrupt (the Codex review's finding 1).
- **One decoding thread per AVIF** (the Codex review's finding 2): Pillow's default asked libavif
  for 32 threads on a 32-CPU machine for each image, which would let concurrent imports go past
  the architecture's bounded CPU work.
- **The spec.** `API and Contracts.md` lists the accepted formats in two decision notes (import,
  2026-10-02; face search, 2026-10-10). Editing a spec needs the owner's approval; asked through the
  supervising session, the owner approved on 2026-10-15: "add AVIF to the accepted formats ...
  with dated Decision 2026-10-15 notes after the two existing format notes ..., keeping the
  original text. Pillow's built-in AVIF support, no new dependency." Both notes are added;
  `.agents/CONTEXT.md` item 32 is marked resolved.
- An AVIF's orientation (EXIF orientation, carried by libavif as `irot`/`imir`) is applied exactly
  once: all eight orientations come out upright (tested).

## Verification

- `uv run pytest tests/unit/test_image_decode.py`: 90 passed (73 before). New: an AVIF identified
  and close to its source (lossy), all eight orientations, an animated AVIF's first frame, a header
  read decodes nothing, an AVIF over the limit refused before decoding, cut short and
  signature-only AVIFs corrupt, damaged pixels corrupt, a `mif1` HEIF unsupported, an AVIF
  under the `mif1` brand read and (cut short) corrupt, the decoder asked for one thread. The last
  two failed before their fixes.
- `tests/integration/test_api_face_search.py`: an AVIF imported, processed, indexed and found by a
  face search with an AVIF (by path and by bytes); a damaged AVIF `422 MEDIA_CORRUPT` from face
  search (path and bytes) and from import, writing nothing.
- Both damaged-AVIF tests were run without the `RuntimeError` mapping and failed; they pass with it.
- `FaceSearch.test.tsx`: a dropped `image/avif` is sent; the refusal names AVIF.
- `cargo test config` (desktop): 9 passed.
- Full gate on the code commits, 2026-10-15: `ruff format --check`, `ruff check`, `mypy` and
  `mypy --platform linux` clean; `pytest -q` 3034 passed, 2 deselected; `npm test` 193 passed,
  `npm run typecheck`, `npm run lint -- --deny-warnings` and `npm run build` clean;
  `npx tauri build --debug --no-bundle` built.

## Open issues / follow-ups

- Writing AVIF (thumbnails, exports) is not needed and not done.
