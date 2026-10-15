# M5: hard-negative strangers chosen inside the gate (issue 177)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`); issue 177
- **Status:** done (measurement only); **automatic acceptance stays off**; no threshold, policy or model changed
- **Commits:** PR to be recorded when merged (`feat(evaluation): choose hard-negative strangers inside the gate`)

## What changed

- `evaluation/assisted_recognition_gate.py` gains `--hard-negatives N --hard-negative-pool <dataset>`.
  After enrolment, each person of the pool (a second dataset under `evaluation/datasets/`, read through
  its `manifest.json` with the same `choose_people` checks) offers one **selection photograph** (the first
  in sorted order), searched against the enrolled library through the real `POST /search/face`. The N
  people whose selection photograph came closest to an enrolled person become never-enrolled strangers,
  and **only their other photographs are scored**, so the photograph that chose a person never counts
  for them. Ties are broken by a hash of the name, so the pool's listing order never matters.
- Left out of the pool: anyone whose name (underscores as spaces, case and spacing ignored) matches
  anyone in the main dataset, **anyone with a picture byte-identical to one of the main dataset's**
  (the whole person: one shared picture suggests the same person under another name), and anyone with
  fewer than two pictures. "The main dataset" is everything its `manifest.json` lists, not only what
  a verified export keeps.
- The report carries a `hard_negative_caveat`: the pool's labels are its creators' and the main
  dataset's verification does not extend to them.
- The selection queries run **inside** the before/after library-count check.
- The report gains `log.hard_negatives` (candidates, their selection-similarity spread, the chosen people
  with their selection photograph, nearest enrolled person and score, and what was left out of the pool)
  and `log.open_set_hard_negatives`, a cut-off table of its own (known people and hard negatives only);
  `log.open_set` stays random strangers only. The configuration records the pool manifest's SHA-256.
- Tests (`tests/unit/test_assisted_gate.py`): ranking order, unrankable candidates and listing-order
  independence; the name, shared-picture and too-few-pictures exclusions; selection photograph never
  among the scored ones.

## Why, and why not PR 196

Issue 177 and the 2026-10-14 decision: random strangers rarely resemble anyone enrolled, so the open-set
table said nothing about look-alikes. PR 196 (another agent's, kept open for reference at the owner's
request) took a different route: a selection mode in the LFW/CelebA importer driven by an embedding-map
JSON that nothing in the repository produces, which also could not be used with the verified celebrity
set, and which selected and scored on the same photographs. Ranking inside the gate reuses the gate's own
embeddings through the real application, needs no new file format, and separates selection from scoring.
PR 196's CI also failed (a 77-character header, formatting, ruff and mypy).

## Runs (2026-10-15)

Both on the 48-identity verified export (`verified-20261015T073439095195Z.json`), 40 enrolled, 8 random
strangers, 15 hard negatives; reports in `evaluation/datasets/reports/` (Git-ignored).

### Pool: the earlier LFW import (150 people), `gate-celebs-commons-hard.json`

| Measure | Value |
|---|---|
| Closed set, workflow, restart, counts | as before: Recall@1 0.983, Recall@5 0.992, MRR 0.986 (118 queries), 10 of 10 workflow checks, same rankings after a restart, counts unchanged (453 / 40 / 453) including the selection queries |
| Pool left out by name | 4: Denzel Washington, Jake Gyllenhaal, Jennifer Lopez, Tom Hanks (enrolled people who are also in LFW; without this check they would have been scored as "strangers" matching themselves) |
| Candidates ranked / without a score | 146 / 10 |
| Candidate selection similarity | min 0.115, median 0.166, max 0.279 |
| Hard-negative queries evaluated | 90 of 106 (16 without a clear subject face) |
| Accepted by the real policy | 0 |
| Hard-negative top-1 similarity | min 0.141, median 0.214, max 0.309 (Arnold Schwarzenegger against Tom Hanks) |
| Cut-off read-out | 0.30: 1 accepted; 0.35 and above: none (known accepted correctly 97.5% at 0.35) |
| Random strangers, for comparison | 115 queries, median 0.204, max 0.309 |

**Reading:** the mechanism works, but this pool is barely harder than random strangers (median 0.214
against 0.204): 150 news-photo people hold no close look-alike of the 40 enrolled celebrities. A wider
pool was imported for the second run.

### Pool: all of LFW with two or more pictures (1,680 people, up to 4 each), `gate-celebs-commons-hard-wide.json`

First attempt (2026-10-15, on battery, before the review fixes): it finished enrolment, selection,
queries and the workflow, then was killed with the application during the restart phase, so its report
is partial (`gate-celebs-commons-hard-wide-partial.json`). **A full re-run (2026-10-15, 16:35 to 18:43,
plugged in, started detached from the application, with the review fixes) completed** with exit code 0:
it chose the same 15 people, both open-set tables are identical to the first attempt's, no pool person
shared a picture with the main dataset, **10 of 10 workflow checks** passed and **the same rankings came
back after a restart** (all queries, the hard negatives included). Recall@1 after the workflow and
restart 0.958 (the forgotten person's queries no longer match, by design). The figures below are the
completed run's.

| Measure | Value |
|---|---|
| Closed set and counts | Recall@1 0.983, Recall@5 0.992, MRR 0.986 (118 queries); counts unchanged (453 / 40 / 453) including 1,662 selection queries |
| Pool left out by name | 18 enrolled people who are also in LFW (Tom Hanks, Angelina Jolie, Matt Damon, Nicole Kidman, Meryl Streep and 13 more) |
| Candidates ranked / without a score | 1,662 / 131 |
| Candidate selection similarity | min 0.099, median 0.166, max 0.305 |
| Chosen (selection photograph's nearest enrolled person) | Emma Thompson (Cate Blanchett, 0.305), Keira Knightley (Natalie Portman), Jada Pinkett Smith (Zoe Saldana), Ethan Hawke (Benedict Cumberbatch), Michael Winterbottom, Naomi Watts (Nicole Kidman), Arnold Schwarzenegger (Tom Hanks), Daisy Fuentes, Daniel Radcliffe (Jake Gyllenhaal), Brian Heidik, Ian McKellen, Natalie Coughlin (Scarlett Johansson), Vivica Fox, Azra Akin (Gal Gadot), Bruce Springsteen |
| Hard-negative queries evaluated | 31 of 34 (the pool keeps up to 4 pictures a person, one of them selects) |
| Accepted by the real policy | 0 |
| Hard-negative top-1 similarity | min 0.130, median 0.215, max 0.320 (Azra Akin against Gal Gadot) |
| Cut-off read-out | 0.30: 3 accepted (Azra Akin 0.320 to Gal Gadot; Natalie Coughlin 0.305 and 0.301 to Scarlett Johansson); 0.35 and above: none (Wilson 95% 0 to 0.11), known accepted correctly 97.5% at 0.35 |
| Time (completed run, plugged in, CPU shared with other sessions) | enrolment 613 s, selection 4,574 s, queries 888 s, workflow 8 s, queries after the workflow 837 s, restart and queries 785 s: 2.1 hours (the first attempt, on battery: selection alone 5,815 s) |

**Reading:** the wide pool does find recognisable look-alikes (several pairs a person would also call
similar), and they come closer than random strangers at the top (0.320 against 0.309), but **none
reaches 0.35**, the lowest cut-off at which no stranger was accepted on this verified set (random or
look-alike); at 0.30 three would be. Earlier unverified runs had strangers higher (LFW 0.402, CelebA
0.383), so 0.35 is not a safe cut-off in general. The sample is small (31 queries from 15 people, not independent), so this narrows
nothing to a rate: it says the best look-alikes LFW offers for these 40 people stay below 0.33.

## Limits

- The pool's labels are the LFW creators', not verified here; the same person under another name, or a
  near-duplicate picture that is not byte-identical, is still possible. Any hard negative scoring close
  to the cut-offs should be looked at by eye before it is read as a model error.
- Hard negatives are chosen to be hard: their table is a deliberately pessimistic read, not a rate for
  random strangers. Their queries come from 15 people and are not independent trials.
- Similarity to *one* selection photograph is a proxy for resemblance; a person whose other photographs
  look closer may be missed.
- LFW photographs are news crops (250 x 250) and many have several faces, so some queries have no clear
  subject face and are not evaluated.

## Verification

- `uv run pytest -q tests/unit/test_assisted_gate.py`: 18 passed; ruff, mypy (Windows and Linux) clean.
- Full backend gate before the PR: results in the PR description.
- The first real run finished with all workflow checks true and `queries_wrote_nothing` true. It ran
  the code before the review fixes (whole-person exclusion on a shared picture, digests from the full
  manifest, the pool caveat); checked afterwards, no picture in either LFW pool (150 or 1,680 people) is byte-identical to any of the 716 pictures the celebrity set lists, so neither run's selection changes. A second review found that the pool loader removed duplicate pictures across pool people before the shared-picture check, so an alias could keep two other pictures and stay eligible; the pool is now read person by person (`load_pool`) and two pool people sharing a picture are both left out. The 1,680-person pool has no picture shared between people, so the completed run is unaffected.
  The wide-pool run completed on the fixed code (exit code 0, 10 of 10 workflow checks, the same
  rankings after a restart, counts unchanged including the 1,662 selection queries).
