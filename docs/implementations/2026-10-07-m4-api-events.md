# M4 W4: the event connection

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W4 · TST-049 (server side; the client reconnect behaviour is W7)
- **Status:** done for the server; the frontend client is W7
- **Commits:** PR (this change): `feat(api): publish events on the event connection`

## What changed

- `backend/api/events.py` (new): `EventHub`. `publish(type, resource_type, resource_id, data)` numbers
  an event from one process-wide counter, wraps it in the documented envelope (`version` 1,
  `event_id`, `sequence`, `type`, `occurred_at`, `resource`, `data`) and offers it to every
  connection. It is safe from any thread (the scheduler loop and the route threads publish); each
  connection is fed on its own event loop through a bounded queue (256). A full queue drops the new
  event *for that client*: its sequence has a gap, which tells it to refetch. Nothing is buffered
  without limit and nothing is replayed.
- `WS /api/v1/events` (`backend/api/app.py`): after the existing capability check and `accept`, a
  connection is subscribed, greeted with `system.hello` (the current sequence, consuming none, so
  the first real event can be checked against it) and then sent every event. A client that vanishes
  mid-send, or leaves, is unsubscribed and its tasks cancelled. Without a hub the endpoint behaves
  as before.
- What is announced (all best effort: `Backend.announce` swallows failures, because the change is
  already committed and a notification must never fail a request or the work): `source.created`
  (import), `processing_run.created` (process, retry), `processing_run.updated` (cancel, but not a
  repeat that changed nothing; the run claimed by the scheduler (`RUNNING`); the run's outcome).
  Each run event carries `data.state` and `data.source_id`. The runner gained an optional
  `on_started(run_id)` hook for the claim notification; a failing hook is suppressed.
- The hub uses the application's clock and id source (`Backend.events`).

## Why

W4 of the completion plan: REST stays authoritative, but a screen needs to know *when* to refetch
while a run goes from queued to completed, without polling.

## Decisions

None new. There are no `job.*` events: the run carries the job's state for the M4 screens, and the
resource appears when something other than runs needs it. Events are not ordered with respect to
the command that caused them: a fast scheduler can announce `RUNNING` before the route announces
`created`; the sequence is the order of publication, and a client refetches either way.

## Verification

- `tests/integration/test_api_events.py` (16): the envelope and numbering; ordered delivery and
  unsubscribing; publication from other threads; a slow client's drops and the sequence gap; the
  greeting consuming no sequence; a subscriber whose loop has closed; a connection greeted and then
  fed (`tests/fixtures/ws.py` drives the ASGI app directly); the capability still required; a
  client vanishing mid-greeting and mid-event; import, process and completion announced in order;
  `RUNNING` announced while work is in progress; a cancel announced once and a repeat silent; a
  retry announced as a new run; a broken hub failing neither a request nor the work; the
  application clock. `test_processing_runner.py` covers the claim hook and a failing hook.
- Mutation probes (22 on the hub, the endpoint, the announcements and the hook): all killed except
  one equivalent mutant (a full queue re-raising inside the loop callback, which is only logged).
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; see the pull request for
  the pytest total.
