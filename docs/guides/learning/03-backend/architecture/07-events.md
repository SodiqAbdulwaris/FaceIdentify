# Architecture 07 Events: telling the screen something changed

## 1. What this is and why it exists

When a processing run finishes, the screen should update by itself. The backend therefore keeps one **event connection**
(`WS /api/v1/events`, a WebSocket) and **pushes a small notice** whenever something changes. The central design decision:
**an event is only a hint to refetch.** REST is the truth; the change was already committed before the event was sent, so a
lost, repeated, late or dropped event can never make the screen show wrong data, only briefly stale data. This is why events
carry ids and a little metadata (a run's state and source id) and never names or other data.

## 2. Where it lives

| Thing | Where |
|---|---|
| The hub (sequence numbers, subscribers, bounded queues) | `EventHub`, `Subscription` in `backend/api/events.py` |
| The WebSocket endpoint and its authentication | `event_stream` in `backend/api/app.py` |
| Publishing | `Backend.announce` and `Backend.announce_run` in `backend/api/startup.py`; called by routes after a commit and by the runner |
| The browser side | `frontend/src/api/events.ts` (connect, reconnect, gap detection), `invalidation.ts` (what an event makes stale), `frontend/src/app/EventsBridge.tsx` |
| Tests | `tests/integration/test_api_events.py` (18), `frontend/src/api/events.test.ts`, `invalidation.test.ts` |

## 3. How it works

**The envelope** (every event):

```json
{"version": 1, "event_id": "<uuid>", "sequence": 3, "type": "processing_run.updated",
 "occurred_at": "2026-10-12T17:52:14.1+00:00", "resource": {"type": "processing_run", "id": "<uuid>"},
 "data": {"state": "COMPLETED", "source_id": "<uuid>"}}
```

**Event types published** (checked 2026-10-12 against `announce` calls): `source.created`, `source.updated`,
`processing_run.created`, `processing_run.updated` (data: `state`, `source_id`), `person.updated` (data: `revision`, never the
name), `occurrence.updated`, `identity.updated`, and the greeting `system.hello`.

**Best effort, honestly stated**:

- Every event has a **`sequence`** from one counter for the process, assigned when published.
- Each connection has a **bounded queue** (256). If a slow client's queue is full, the new event is *dropped for that client*,
  which sees the gap in `sequence` and simply refetches. Nothing is buffered without limit.
- A new connection is greeted with **`system.hello`**, carrying the current sequence (it consumes none), so the first real
  event can be checked against it.
- **Nothing is replayed after a reconnect**: the client refetches through REST.
- `publish` is thread-safe: the scheduler thread and the route worker threads publish; each subscriber is fed on its own
  event loop. `announce` swallows any failure (`contextlib.suppress`): a failing notification must never fail the work.

**Authentication**: a browser cannot set an `Authorization` header on a WebSocket, so the client offers two **sub-protocols**,
`faceidentify.v1` and `fi.<token>`; the server checks the token (constant time), accepts with only `faceidentify.v1` selected
(the token is never echoed), and otherwise closes with code 1008.

**On the screen**: `events.ts` reconnects after a drop and detects gaps (`sequence > last + 1`) or repeats; `staleBecauseOf`
maps an event type to the query keys it makes stale, and TanStack Query refetches them ([events and routing](../../04-frontend/06-events-and-routing.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.** The Python script in [call the API](../api/01-call-the-api.md) ("Listen to
events") connects with the two sub-protocols, prints the greeting, triggers a `process`, and prints the next three events.
Observed output:

```text
subprotocol: faceidentify.v1
system.hello
1 processing_run.created processing_run {'state': 'PENDING', 'source_id': '...'}
2 processing_run.updated processing_run {'state': 'RUNNING', 'source_id': '...'}
3 processing_run.updated processing_run {'state': 'COMPLETED', 'source_id': '...'}
```

Then:

1. **Prove the authentication.** Connect without the token sub-protocol (`subprotocols=["faceidentify.v1"]`): the server
   closes the connection (code 1008). (By reading `event_stream`; the tests `test_api_events.py` cover a missing or wrong
   token.)
2. **Make a gap.** Not by hand; `uv run pytest tests/integration/test_api_events.py -q` (`18 passed`) includes a slow
   client whose queue fills, a full queue dropping the new event, hello carrying the baseline, and publishing from threads.
3. **Cause every type once** with the corrections and people routes ([routes](../api/routes/README.md)) while the listener
   runs, and watch `person.updated` carry only `{'revision': N}`.

## 5. Change it

A new event type is three small edits and a test: call `backend.announce("thing.updated", "thing", str(id))` after the commit
in the route; map the type in `frontend/src/api/invalidation.ts` (`staleBecauseOf`) to the query keys it makes stale (a type
with no mapping makes nothing stale: the screen would not refresh, silently); and add tests on both sides
(`test_api_events.py` for the publish, `invalidation.test.ts` for the mapping). Never put data a screen would *trust* in an
event: it must refetch.

## 6. Break it on purpose

Remove `person.` from the prefixes in `staleBecauseOf` (a scratch edit) and rename a person in two windows: the second window
does not update until reloaded. The browser tests (`npm test`, `invalidation.test.ts`) fail first. Restore with `git restore`.

## 7. Exercises

1. Why does `person.updated` carry the revision and not the name?
2. A client's queue is full when an event is published. What happens, and how does the client recover?
3. What does `system.hello` do?
4. Why are events published after the commit and not inside the transaction?

**Answers**

1. Events are hints; the name could be stale or private, and REST is the authority (owner decision 2026-10-08).
2. The event is dropped for that client; it sees the sequence gap and refetches.
3. It greets a new connection with the current sequence so the first real event can be checked for a gap; it consumes none.
4. A transaction may be retried or rolled back; announcing from inside would claim a change that might not happen.

## 8. Related files

- Previous: [06 Recovery](06-recovery.md) · Next: [08 Security](08-security.md)
- [`backend/api/events.py`](../../../../../backend/api/events.py), [`frontend/src/api/events.ts`](../../../../../frontend/src/api/events.ts)
- [Events and routing (front end)](../../04-frontend/06-events-and-routing.md)
