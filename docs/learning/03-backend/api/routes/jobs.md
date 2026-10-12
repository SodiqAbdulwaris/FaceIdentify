# Routes: jobs (`backend/api/routes/jobs.py`)

## 1. What this is and why it exists

A **Job** is the scheduling side of a unit of work: "this is queued / running / done, at this priority, claimed
by this worker until this time, on this attempt". A **ProcessingRun** ([processing](processing.md)) is its history.
This module exposes jobs read-only, plus one command, cancel, which is a convenience: it cancels the run the job
belongs to. Screens mostly use the run routes; the job routes exist for the scheduler's view (and for
maintenance work that will have jobs without a run).

## 2. Where it lives

| Route | Notes |
|---|---|
| `GET /api/v1/jobs` | filters `state`, `type`; newest first; a job whose run belongs to a deleted source is hidden |
| `GET /api/v1/jobs/{id}` | `404 JOB_NOT_FOUND` |
| `POST /api/v1/jobs/{id}/cancel` (202) | finds the job's run and calls the same `cancel_command` as `POST /processing-runs/{id}/cancel`; a job with no run is `409 JOB_NOT_CANCELLABLE` |

Models and repository: `backend/app/jobs/models.py` (`Job`, `JobState`, `JobType`, `JobPriority`), `repository.py`
(`JobRepository`). Tests: `tests/integration/test_api_jobs.py`, `test_job_repository.py`, `test_processing_scheduler.py`.

## 3. How it works

`JobDetail` extends the `JobBrief` that a run embeds:

```json
{"id": "c1b8e26f-...", "state": "COMPLETED", "priority": "INTERACTIVE", "attempt_number": 1, "progress": null,
 "type": "PROCESS_SOURCE", "processing_run_id": "ddd2bbe0-...", "previous_job_id": null, "failure_code": null,
 "created_at": "...", "started_at": "...", "ended_at": "..."}
```

- **Priority** is one of `INTERACTIVE`, `HIGH`, `NORMAL`, `LOW`, `MAINTENANCE`, stored with an integer **rank** (0 is most
  urgent) because the text sorts alphabetically (`HIGH` before `INTERACTIVE`): `JobRepository.claim_next` orders by
  `priority_rank`, then `created_at`, then `id` (revision `0007`).
- **Lease**: a worker that claims a job holds it until an expiry and heartbeats; a stale lease is cleared at startup.
  (Not shown in this API.)
- **Paging**: the same cursor rules as everywhere; the cursor context is `jobs:<state>:<type>`.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
curl -s -H "$H" "$B/api/v1/jobs?limit=2" | j "[(i['type'], i['state'], i['priority']) for i in d['items']], d['page']['has_more']"
JOB=$(curl -s -H "$H" "$B/api/v1/jobs?limit=1" | j "d['items'][0]['id']")
curl -s -H "$H" $B/api/v1/jobs/$JOB | python3 -m json.tool
curl -s -H "$H" "$B/api/v1/jobs?state=QUEUED"
curl -s -X POST -H "$H" $B/api/v1/jobs/$JOB/cancel
```

Observed: `[('PROCESS_SOURCE', 'COMPLETED', 'INTERACTIVE'), ('PROCESS_SOURCE', 'COMPLETED', 'INTERACTIVE')]` then `True`
(more pages), the JSON above, an empty `items` list for `QUEUED` once the work is done, and for the cancel of a
finished job `409 RUN_NOT_CANCELLABLE` with `"reason": "run ... is COMPLETED, which cannot be cancelled"`. An unknown id is
`404 JOB_NOT_FOUND`; an unknown `state` value is `422`.

## 5. Change it

Run on 2026-10-12: change `@router.post("/jobs/{job_id}/cancel", status_code=202)` to `status_code=200` and run
`uv run pytest tests/integration/test_api_jobs.py -q`: it fails at `test_a_queued_run_is_cancelled_through_its_job`
(the assertion prints the cancelled run, showing the route worked but the code was wrong). Restore the file. To add a
filter (say `priority`), follow `state`/`type`: add the `Query` parameter, extend the cursor `context` string so a
cursor cannot cross filters, add the `.where`, and add a case to the listing test; then `npm run generate:api`.

## 6. Break it on purpose

Cancel a job whose `processing_run_id` is `null` (a future maintenance job): `409 JOB_NOT_CANCELLABLE` ("The job has no
processing run to cancel"). Page with a cursor from `/sources` on `/jobs`: `400 INVALID_CURSOR`. Neither is a bug; both
are the API refusing a request it cannot honour.

## 7. Exercises

1. Why does a job carry both `priority` and an integer rank?
2. What does cancelling a job actually cancel?
3. Why are some jobs not listed?
4. What is the cursor `context` for?

**Answers**

1. Text priorities sort alphabetically; the rank is the scheduling semantics.
2. The processing run it belongs to; the job follows.
3. Jobs whose run belongs to a source being or already permanently deleted are hidden.
4. It binds a cursor to the query that made it, so a cursor cannot be reused across filters or collections.

## 8. Related files

- Previous: [processing](processing.md) · Next: [memory](memory.md) · [Routes index](README.md)
- [Jobs and runs](../../processing/01-jobs-and-runs.md), [scheduler and runner](../../architecture/05-scheduler-and-runner.md)
- [`backend/api/routes/jobs.py`](../../../../../backend/api/routes/jobs.py)
