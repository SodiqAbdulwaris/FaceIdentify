# M5: the owner's close-up photographs (issue 173) and the finished CelebA gate run

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R; issue 173; TST-057A, TST-057B (no status changed by this entry)
- **Status:** measurements recorded; no threshold, policy or model changed
- **Commits:** PR to be recorded when merged

## What changed

Documentation only. Two evaluation runs on the main checkout's Git-ignored data, recorded here:

1. Issue 173: how many very large or close-up faces in the owner's own photographs (`MyFaces/`) SCRFD
   loses to the 0.5 detection floor or to the gate's subject rule.
2. The CelebA gate run of 2026-10-14 stopped before its workflow and restart phases
   ([entry](2026-10-14-m5-celeba-gate-and-acceptance-decision.md)); it was re-run to completion into a
   fresh workdir.

No code, threshold, policy or model changed. The reports name files and stay under the Git-ignored
`evaluation/datasets/reports/`; no picture, face crop or derived image was copied, saved or committed.

## 1. The owner's photographs (issue 173)

### Method

`evaluation/analyse_exclusions.py` selects photographs through the gate's manifest (people and
partitions), and `MyFaces/` has no manifest: it is a flat folder of 29 pictures of the owner, with no
identity or category labels. Rather than write a new tool, a throwaway driver (in the session's
scratchpad, not committed) imported the tool's own functions and ran them on every file:
`pixels_of` (the application's decoder, EXIF orientation applied), `look` (every candidate down to
0.05, split into kept / below the floor / dropped by the border rule, with the tool's assertion that
its kept faces equal `detection.decode`), `describe` (the gate's subject rule, `DOMINANCE` 2.5),
`counterfactuals`, and the tool's half-size black padding check, run on every picture this time, not
only on losses. Same installed `buffalo_l` SCRFD export, CPU. Report:
`evaluation/datasets/reports/exclusions-myfaces.json` (Git-ignored).

### Result

| Measure | `MyFaces/` |
|---|---|
| Files / decoded by the application's decoder | 29 / 29 (`18.avif` now decodes: issue 188 fixed) |
| Kept (one subject) / no subject / no face | **29 / 0 / 0** |
| Kept faces per picture | exactly 1 in every picture |
| Score of the kept face | 0.66 to 0.93 |
| Area of the kept face (fraction of the frame) | 0.6% to 43.5%, median 19.5% |
| Faces at 30% of the frame or more | 3: 31.0% (0.86), 31.6% (0.87), 43.5% (0.66; 0.82 padded) |
| Kept faces under 0.7 | 1 (`9.jpg`, the 43.5% face) |
| Below-floor candidates | in 12 pictures, all scored 0.31 or less; none changes a verdict |
| Counterfactuals (floor 0.3 or 0.1; ratio 2.0 or 1.5; largest face wins) | no picture moves |
| Border rule | one confident face dropped (`11.jpg`, 0.61, 9% of the frame, a second face cut by the edge); the subject was kept |

**Losses to the 0.5 floor: 0 of 29. Losses to the subject rule: 0 of 29.** The scale effect seen on LFW
shows again in its mild form: the largest face (43.5%, larger than any LFW loss at 34% to 40%) is the
lowest score of the set (0.66) and rises to 0.82 when padded, but it stays above the floor. The faces
between 29% and 32% score 0.79 to 0.87.

### What this does and does not answer

- It answers the issue's direct question for the photographs the owner has supplied: **none is lost.**
- It is 29 pictures of one person, possibly with duplicates (`18.avif` and `18.jpg`,
  `19.jpg` and `19.webp`, `10-1.jpg` and `10-2.jpg` look like pairs by name only; not checked), uncategorised
  (selfie, ID-style or phone crop is not recorded), with no negatives and no multi-face controls. Only
  three faces exceed 30% of the frame. The owner's locked plan on the issue (2026-10-14) asks for a
  categorised set with negatives and controls, a comparison against a padded fallback and a separate
  holdout before any decision; this run does not provide those, so **issue 173 stays open**.
- Combined with LFW (5 of 1,244 lost, all faces at 34% to 40%) and CelebA (0 large-face losses of
  1,736), the evidence so far says the weakness is real but rare, and does not support building the
  padded fallback yet; that remains the owner's decision.

## 2. The CelebA gate run, finished

The same command as on 2026-10-14, into a fresh workdir, started fully detached (a Git-ignored
`run-celeba-rerun.cmd` launched by a copy of `launch_detached.py`: `DETACHED_PROCESS` and a new
process group) and on mains power:

`PYTHONPATH=. uv run python -u evaluation/assisted_recognition_gate.py --dataset evaluation/datasets/celeba
--local-state-root local-models/state --workdir evaluation/datasets/gate-celeba-rerun --report
evaluation/datasets/reports/gate-celeba-rerun.json --people 100 --minimum-photographs 5 --unknown 50
--run-timeout 3600`

It ran from 19:17 to 21:57 UTC on 2026-10-15 (2 h 40 min on CPU, `CPUExecutionProvider`, provider
fallback `NONE`; other sessions ran test suites at times, so the timing is not a benchmark) and exited 0.
The report is complete (no `partial` flag). The 2026-10-14 partial report `gate-celeba.json` is kept
as it was.

| Measure | 2026-10-14 (partial) | 2026-10-15 re-run |
|---|---|---|
| Enrolled people / photographs placed | 100 / 872 | 100 / 872 (none lost) |
| Closed-set queries / Recall@1 (Wilson 95%) / Recall@5 / MRR | 283 / 0.979 (0.955 to 0.990) / 0.979 / 0.980 | identical |
| Stranger queries / accepted by the real policy | 580 / 0 | 580 / 0 (all offered as possible people) |
| Strangers' best similarity: min / median / max | 0.138 / 0.198 / 0.383 | identical |
| Library counts unchanged by the queries (images / identities / runs) | yes (872 / 100 / 872) | yes (872 / 100 / 872) |
| Workflow checks | not reached | **10 of 10 passed** |
| Same rankings after a restart | not reached | **yes** |
| Recall@1 after the workflow and restart | not reached | 0.968 (0.941 to 0.983), MRR 0.970 |

The 10 checks: name search finds the person; a recycled image is left out of the default search but
still recognises the person; restoring returns it to normal search; split then merge restores the person;
a permanently deleted image is gone; a forgotten person is not recognised but stays findable by name;
after a restart, name search still works and the rankings are the same as before the restart.

The drop from 0.979 to 0.968 after the workflow (277 to 274 correct of 283) is consistent with the
workflow forgetting one enrolled person (`identity 1358`, chosen by the gate) whose 3 held-out queries
can then no longer rank that person first. That attribution was not verified: the per-query rankings
after the workflow are not stored in the report, so it was not checked query by query.
The rankings after the restart equal the rankings just before it, which is what the restart check
measures.

So the CelebA run now has what the LFW run had: the workflow checks and the restart comparison all
pass. This run used the abstain-only policy of 2026-10-14 and changes no TST-057B status or
acceptance setting (automatic acceptance was built separately on 2026-10-15); the CelebA labels are
the creators', unverified here.

## Verification

- MyFaces: the driver ran the tool's functions on 29 of 29 files with the tool's own production
  cross-check assertion on every picture (and every padded picture); no assertion fired. Run from the main
  checkout at `32e45de` (`main`).
- The CelebA run: see section 2.
- **Not verified:** whether the name-paired MyFaces files are the same picture; the photo categories;
  behaviour on the GPU path; any label.

## Open issues / follow-ups

- Issue 173 stays open: a categorised close-up set with negatives and multi-face controls, and the
  padded-fallback comparison, per the owner's locked plan, if the owner wants to pursue it.
