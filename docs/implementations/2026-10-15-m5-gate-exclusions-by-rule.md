# M5: gate reports list exclusions by rule, including the enrolment cascade

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 evaluation, issue #182
- **Status:** done (pure functions unit-tested; not yet run on a real dataset)
- **Commits:** PR for #182: `feat(evaluation): list gate exclusions by rule, with the cascade`,
  `docs: record the gate exclusions by rule`

## What changed

- `evaluation/assisted_recognition_gate.py`:
  - `EXCLUSION_RULES`: one sentence per rule (`processing_failed`, `no_face`, `no_subject`,
    `too_few_enrolled_faces`). The no-subject rule reads "not evaluated (ambiguous subject)".
  - `skip_reason(faces, run_state)`: why an enrolment photograph places no face. A run that did not
    complete is now `processing_failed`. Before this change it was counted as `no_face`.
  - `query_exclusion(result)`: why a query is not evaluated. The cascade comes first (a known
    person with fewer than `MINIMUM_ENROLLED` = 2 enrolled faces), then no face, then no subject.
    A stranger is never enrolled, so only their faces count.
  - `exclusions(...)` builds the report's new `log.exclusions`: the rules, the enrolment
    photographs per rule, the people left with too few enrolled faces (with how many they kept),
    the known and stranger queries not evaluated per rule (hard negatives flagged), and the counts.
  - `enrol` records each excluded photograph (person, file, rule) in
    `log.enrolment.excluded_photographs`. `skipped_photographs` gains a `processing_failed` count.
    `run_queries` records how many faces each query photograph had, which separates no face from
    an ambiguous subject.
  - `MINIMUM_ENROLLED` names the existing `>= 2` eligibility rule. Its value is unchanged.
- `tests/unit/test_assisted_gate.py`: four tests. They cover the enrolment rule order, the query
  rule order (cascade first; strangers judged by their faces only), the full by-rule listing on
  fake inputs, and the empty case. One test checks that the listed known queries add up to
  `metrics()["ineligible_or_no_subject"]`.

## Why

Issue #182. The report gave one total, `ineligible_or_no_subject`, which mixed three different
things: photographs with no face, photographs with several faces and no dominant one, and the
cascade (`2026-10-13-m5-lfw-exclusion-analysis.md`: on LFW, one person and one query). Separating
them stops an ambiguous subject from reading as pipeline loss.

## Decisions

- **Each photograph is listed once, under the first rule it meets.** That keeps the counts equal
  to the existing totals. A known query that is both in the cascade and without a subject is
  listed under the cascade.
- **No threshold, policy, model or metric changed.** `metrics()`, `open_set()` and
  `per_identity()` are untouched. The retrieval totals, and `ineligible_or_no_subject`, are as
  before. Only `skipped_photographs` splits out `processing_failed`, which was hidden in
  `no_face` before.
- The selection step (`choose_people`, people with fewer than `--minimum-photographs`) happens
  before the gate and is not an exclusion of the pipeline. It is recorded in the configuration
  as before and is not listed again.

## Verification

- `uv run pytest -q tests/unit/test_assisted_gate.py`: 25 passed (4 new).
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`,
  `uv run mypy --platform linux`: clean.
- Full `uv run pytest -q`: see the PR description (this container runs as root, so tests that
  simulate a permission error do not raise, and one test needs Windows `cmd`).
- **Not verified:** a real gate run with the new report. No model weights or datasets exist in the
  cloud environment, so the change is tested only through its pure functions with fake inputs.
  The next local gate run on the owner's machine will show it.

## Open issues / follow-ups

- On the next local gate run, check that `log.exclusions` matches the LFW exclusion analysis of
  2026-10-13 (one person and one query in the cascade).
