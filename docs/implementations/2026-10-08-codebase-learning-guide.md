# A learning guide for the whole codebase

- **Date:** 2026-10-08
- **Milestone / tracker IDs:** documentation (owner request); no tracker row
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- `docs/research/StackResearch.md` (a bare, unexplained list of topics to research) is renamed to
  `docs/research/codebase-learning-guide.md` and rewritten as a twelve-part guide: the big picture;
  Python from zero (values, conditionals, loops, functions, classes, exceptions, types, concurrency),
  using code from this repository; the tools (uv, pytest, ruff, mypy, git, CI); vectors, models and
  thresholds; the old research list with an answer for every topic; databases, transactions and
  storage; the backend; the domain model; the front end (HTML, CSS, JavaScript, TypeScript, React,
  TanStack Query); the Rust and Tauri shell; the project's working rules; a walkthrough of one
  photograph with file names, a reading path, exercises, a glossary and further reading.
- Every topic of the old list is kept (Part 5 keeps its checklist and states whether each topic is
  built, designed, or only researched).
- No code, test, schema or specification changed.

## Why

The owner asked, after the CUDA and conservative-policy work, to pause implementation and write down
everything needed to understand the codebase, including Python basics, organised and renamed.

## Verification

- Every claim about this repository was checked against the code, the specs or the configuration on
  `main` at the time of writing (for example: the CI job list against `.github/workflows/ci.yml`,
  the tables against revision `0001`, the routes against `backend/api/routes/`, the storage layout
  against `docs/research/tech-stack.md` section 15, dependency lists against `pyproject.toml` and the
  front-end `package.json`). Markers show what is built, designed or only researched.
- An independent fact-check review (Codex, read-only) found seven major and seven moderate
  inaccuracies, all fixed in a follow-up commit: the real ML worker is not yet wired into the host
  (the debug shell runs the development profile; `backend/api/real.py` is not on `main`), the
  abstain-only policy is evaluated but not active, 100% coverage is a working rule and not a CI
  threshold, the identity-page controls exist, events carry small metadata, PyTorch is not a
  dependency, not every status column has a CHECK, only collection routes paginate, a stylesheet
  exists, the tracker has a `COMPLETE` status, and three language-precision points (tuples as keys,
  namespace packages, Rust `panic!`).
- `CONTEXT.md`'s front-end line was stale for the same reason (the M5 identity controls exist) and
  is corrected.

## Open issues / follow-ups

- The guide describes `main` on 2026-10-08 and must be updated when a milestone lands (Part 12.6).
- It is long on purpose; the table at the top says which part to read for which question.
