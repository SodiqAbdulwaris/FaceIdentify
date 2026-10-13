# Walkthrough 02 A reading path

## 1. What this is and why it exists

You can read this guide front to back, but eventually you will want to read the *code*. This is the order that works: small and central
first, wide and mechanical last. Each step names a file, what to look for, and the lesson that prepares you.

## 2. Where it lives

Files named in the table; the [guide index](../README.md) has the lesson-by-lesson reading paths.

## 3. How it works

| # | Read | Look for | Prepare with |
|---|---|---|---|
| 1 | `AGENTS.md`, then skim `.agents/CONTEXT.md`, then `docs/plans/PROJECT_STATUS.md` | the rules and where the project stands | [milestones and decisions](../06-evaluation-and-operations/07-milestones-tracker-decisions.md) |
| 2 | `docs/research/tech-stack.md` (sections 1 to 5, 15, 19) | why each technology | [the four programs](../00-start-here/02-the-four-programs.md) |
| 3 | `backend/app/recognition/reasoner.py` (188 lines) | the three outcomes and the first-match-wins rules | [decision policy](../03-backend/recognition/03-decision-policy.md) |
| 4 | `backend/infrastructure/db/unit_of_work.py` and `backend/app/people/use_cases.py` | a transaction, and a small use case that uses it | [transactions](../02-data-and-storage/03-transactions-and-unit-of-work.md) |
| 5 | `backend/app/sources/models.py` and `backend/app/memory/models.py` | tables as classes, with their check constraints | [domain](../03-backend/domain/README.md) |
| 6 | `backend/app/processing/execute_job.py` top to bottom, then `accept_run.py` | the straight line, then the one atomic moment | [processing](../03-backend/processing/README.md) |
| 7 | `backend/ml/worker/loop.py`, `backend/ml/supervisor/supervisor.py` | one response per request; three kinds of failure | [runtime and worker](../03-backend/runtime-and-worker/README.md) |
| 8 | `tests/unit/test_recognition_reasoner.py`, then `tests/integration/test_migration_0009.py` | how a unit test and a migration test read | [pytest](../01-basics/tools/03-pytest.md), [migrations](../02-data-and-storage/04-migrations-alembic.md) |
| 9 | `frontend/src/app/routes.tsx`, `BackendGate.tsx`, then one feature folder | the gate, the routes, a screen | [front end](../04-frontend/README.md) |
| 10 | `docs/specs/identity-and-memory-model-v1.md` | the concept sections, not all of it | [domain vocabulary](../03-backend/domain/01-vocabulary.md) |
| 11 | `docs/research/measured-operating-point.md`, `reference-model-selection.md` | why automatic matching is off | [evaluation](../06-evaluation-and-operations/README.md) |

## 4. Try it

**Works with no models. Verified 2026-10-12.** Do step 3 as a live exercise: run `uv run pytest tests/unit/test_recognition_reasoner.py -q`
(`59 passed`), then read the test names top to bottom; they are the rules of `reasoner.py` in sentences. Time yourself: the whole of step 3 should
take under half an hour.

## 5. Change it

After each step, write three sentences in your own words in a private note. Where you cannot, go back to the lesson, not forward.

## 6. Break it on purpose

Skip step 3 and read `accept_run.py` first: you will meet `MATCH_EXISTING` and `ABSTAIN` before you know what they decide, and the 884 lines will not make sense. The order is
the lesson.

## 7. Exercises

1. Which step introduces the first tests you read?
2. Why is `reasoner.py` before `execute_job.py`?

**Answers**

1. Step 8 (but step 3 can be done with its tests open).
2. `execute_job.py` calls it; knowing what it decides first makes the call site obvious.

## 8. Related files

- Previous: [01](01-one-photograph.md) · Next: [03 Exercises](03-exercises.md)
