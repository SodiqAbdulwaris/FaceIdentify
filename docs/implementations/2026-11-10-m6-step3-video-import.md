# M6 step 3: video import and probe

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 3; TST-063 (metadata half); D1, D2
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(sources): import and probe videos with the pinned ffprobe`

## What changed

- `backend/infrastructure/media/video.py` (new): finds the installed tools (`FACEIDENTIFY_FFMPEG_DIR`, else
  `<local state>/runtime/ffmpeg`) and reads a video's facts with `ffprobe -show_format -show_streams` as JSON:
  the container family (MP4/QuickTime, Matroska/WebM, AVI) and its MIME type, the first real video stream (a
  cover picture is not one), the size as shown (a rotation of 90 or 270 degrees swaps width and height), the
  duration (the container's, else the stream's) and the average frame rate (else the real one, else none). A
  probe that fails or takes over 60 s is a corrupt video. No console window opens on Windows.
- `backend/app/sources/import_source.py`: a file whose name is a video's is probed first, then streamed into
  managed storage through the existing three-step protocol, or hashed where it is for a referenced import; it is
  never read into memory. It has its own byte limit (`VideoImport.max_bytes`). The Source is a `VIDEO` with
  `media_duration_ms` and `frame_rate_num`/`_den` filled. Images are unchanged.
- `backend/api/routes/sources.py`: the import route wires the probe lazily (a missing FFmpeg fails only a video
  import: `503 MEDIA_TOOLS_UNAVAILABLE`), maps `415`/`422` for videos, and Source detail gains `duration_ms`
  (generated OpenAPI and TypeScript types updated). `MediaLimits.max_video_bytes` (provisional 64 GiB: a
  streamed copy bounds no memory, only the disk).
- `scripts/install_ffmpeg.py` (new): verifies the pinned zip's SHA-256 and unpacks `bin` (ffmpeg, ffprobe,
  their DLLs; not ffplay) and `LICENSE.txt` into `<local state>/runtime/ffmpeg`, staged and renamed into place.
- CI (`backend-tests`, Windows): downloads the pinned zip once, caches it by its SHA-256, installs it with the
  same script and sets `FACEIDENTIFY_FFMPEG_DIR`.
- Tests: `tests/fixtures/media.py` makes clips from FFmpeg's own test patterns with the pinned build (no
  faces); `tests/unit/test_video_probe.py`; video tests in `tests/integration/test_import_source.py` and
  `tests/integration/test_api_sources.py`.
- Docs: delegated decisions in `docs/specs/API and Contracts.md` (5.1, 24) and `PERSISTENCE_IMPLEMENTATION.md`
  (4.1), the D2 confirmation and re-pin in `docs/research/licensing-and-commercialization.md` 4.1, notes in
  `docs/research/tech-stack.md` section 6 and `docs/plans/M6_PLAN.md` step 3, tracker TST-063, the testing
  guide, `PROJECT_STATUS.md`, `CONTEXT.md`.

## Why

M6 step 3: a movie must become a Source before it can be processed. D2 (no GPL components) rules out the PyAV
wheel (it links x264 and x265); the pinned LGPL ffmpeg over pipes meets it and adds no Python dependency.

## Decisions

All delegated (owner, 2026-11-09; the owner may reverse any of them):

1. **D2 confirmed, no PyAV** (orchestrating session, 2026-11-10): ffmpeg/ffprobe over pipes. Recorded in
   licensing 4.1, tech-stack section 6 and the M6 plan.
2. **Re-pin to a month-end build.** The build first read (`autobuild-2026-11-09-12-42`) is a daily build that
   BtbN prunes after about two weeks; the release list shows it keeps each month's last build back to 2024. The
   same version line from `autobuild-2026-10-31-12-59` (`n9.0.2-39-g7adfbe40dc`, SHA-256 `e907b01f...c4c0`) was
   downloaded, its hash matched GitHub's digest, and its licence and configuration were re-read (LGPL v3,
   `--enable-version3`, x264 and x265 disabled, no GPL or non-free). CI can fetch it for as long as the release
   exists, and caches it.
3. **A video is chosen by its file name** (`.mp4 .m4v .mov .mkv .webm .avi`), then its content must be one of
   those containers. Images keep content sniffing. A picture renamed `.mp4` is refused as unsupported.
4. **Probe before writing, stream the copy, and bind the facts to the bytes** (review of PR #243): the
   file's size and modification time are taken before the probe and must be unchanged after it; the
   managed copy stops at that size and checks them again at its end; a referenced import compares the
   hashed size with them. A file that grows, shrinks or is rewritten meanwhile is refused and leaves no
   Source (a managed copy leaves its reservation `MISSING`, as any failed write does). A probe whose
   executable cannot start is `MEDIA_TOOLS_UNAVAILABLE`; output that cannot be read is `MEDIA_CORRUPT`.
   `scripts/install_ffmpeg.py --replace` moves the old install aside and removes it only after the new one
   is in place.
5. **No thumbnails in step 3** (images have none either); the step 7 video screen shows the original.
6. **`MEDIA_TOOLS_UNAVAILABLE` (503)** is a new error code.
7. **No schema change:** the `sources` columns for duration and frame rate already exist (M2).

## Verification

- `uv run pytest -q tests/unit/test_video_probe.py tests/integration/test_import_source.py
  tests/integration/test_api_sources.py` with the pinned build installed: all pass; `video.py` and
  `import_source.py` 100% line and branch covered by these alone.
- Full backend gate: see the PR description (recorded there with the numbers).
- `npm run generate:api` then `npm run typecheck`: clean.

## Open issues / follow-ups

- The libraries linked inside the FFmpeg DLLs are still not inventoried (M8, licensing section 4.1).
- The desktop file picker offers images only (`desktop/src-tauri/src/config.rs`); videos are added in step 7
  with the video screen.
