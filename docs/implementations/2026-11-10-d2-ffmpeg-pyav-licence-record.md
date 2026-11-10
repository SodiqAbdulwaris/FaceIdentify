# D2: the FFmpeg and PyAV licence record

- **Date:** 2026-11-09 (inspection), 2026-11-10 (record)
- **Milestone / tracker IDs:** M6 step 3 prerequisite (D2); M7 and M8 inputs
- **Status:** done; documentation only (no code, dependency, spec or `tech-stack.md` change)
- **Commits:** PR #233: `docs: record the FFmpeg and PyAV licences for M6 D2`

## What changed

`docs/research/licensing-and-commercialization.md`: new section 4.1 and two rows in section 4, blocker row 5,
section 7 and the section 11 checklist updated. `.agents/CONTEXT.md`: Known conflicts 33.
`docs/plans/PROJECT_STATUS.md`: the last-updated line.

## Why

M6 D2 requires the exact FFmpeg builds' licences, PyAV's bundled FFmpeg included, to be inspected and recorded
before step 3 merges.

## Decisions

Delegated (owner, 2026-11-09), recommendation pending the orchestrating session's confirmation: do not use
the PyAV wheel; use the pinned LGPL ffmpeg and ffprobe over pipes. Options checked and reasons are in section
4.1. Not decided here: whether `tech-stack.md` section 6 and the M6 step wording are amended (left to the M6
step 3 PR).

## Verification

Everything in 4.1 marked "verified" was read or run on 2026-11-09 in scratch folders outside the repository: the
wheel's file list, metadata, `DELVEWHEEL` and `av.libs`, the configuration strings of the DLLs, `ctypes` calls to
`*_license()`, an import-table name search, PyAV opening, probing and decoding a clip; the FFmpeg zip's SHA-256,
its `LICENSE.txt`, `ffmpeg -version`, `-L`, `-encoders`, `-decoders`, `-devices`, `ffprobe` JSON and per-frame
times, a rawvideo pipe decode, seeking, a truncated file. Marked "assumed" or "not verified": the upstream
licences of x264 and x265, the licences of libraries inside the FFmpeg DLLs, older PyAV wheels, a source-built
PyAV.

## Open issues / follow-ups

Confirm or reverse the recommendation. M6 step 3 mirrors the zip into the local runtime store by hash, adds a CI
arrangement for it, and amends the M6 wording. The inventory of third-party libraries inside the FFmpeg build is
an M8 task.
