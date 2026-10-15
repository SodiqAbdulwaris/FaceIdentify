# M6 plan draft: movies and scheduling

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M6 (TST-060 to TST-070); issues #180, #175
- **Status:** draft written; **not approved** (documentation only)
- **Commits:** PR (number recorded when merged): `docs(plans): draft the M6 movies and scheduling plan`

## What changed

- `docs/plans/M6_PLAN.md` (new): where things stand for video, the constraints that fix the order,
  seven steps (reprocessing images under #180's locked design, worker arbitration under #175's,
  video import and probe, decode and chunk, detect/track/select, recognition and occurrences over
  time, pause/resume/cancel and the end-to-end workflow), dependencies, the definition of done, risks,
  and ten open decisions with recommendations.
- `.agents/CONTEXT.md`, `docs/plans/PROJECT_STATUS.md` (the M6 row links the draft), this entry and
  its README row.

## Why

The overnight run of 2026-10-16 asked for an M6 plan draft from the Roadmap (sections 66 to 70), the
processing spec (sections 8, 13, 15, 23, 24, 26), the tracker's M6 rows and the locked stack, so the
owner can approve M6's scope and order after M5 closes.

## Decisions

- **Reprocessing is step 1, before any video work,** because the Roadmap puts Phase G before video and
  #180's locked decision defers it to M6; it is proven on images first, where the rest of the
  pipeline already works.
- **Worker arbitration (#175) is step 2,** before long videos, because without it a movie blocks face
  search for its whole duration.
- **No spec, dependency, threshold or model change is made here.** The plan names where each step will
  need one (FFmpeg/PyAV, the generation pointer, new routes) and lists them as owner decisions.
- The plan's recommendations in section 7 are proposals, not decisions; none is marked as a delegated
  decision.

## Verification

- Every "already in place" claim was checked against the code: `SourceKind.VIDEO`
  (`backend/app/sources/models.py`), the video frame/time note on observations
  (`backend/app/memory/models.py`), `JobType.REPROCESS_SOURCE` and the job states
  (`backend/app/jobs/models.py`), checkpoint kinds (`backend/app/processing/models.py`), and the
  absence of a video decoder (no FFmpeg or PyAV dependency in `pyproject.toml`).
- The constraints were checked against the Roadmap (sections 66 to 70), the processing spec (sections
  8 and 13), the tech-stack decision of 2026-10-02 (OpenCV not a baseline) and the locked decisions on
  #180 and #175.

## Open issues / follow-ups

- The owner's decisions D1 to D10 in `M6_PLAN.md` section 7.
