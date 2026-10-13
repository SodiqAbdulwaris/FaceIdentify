# 07 Run it and see it work

## 1. What this is and why it exists

This is the lesson where the application runs on your screen. You will start the backend by hand on
the **development profile**, import three pictures, process them, and watch two of them become one
person and the third become another. You do it with `curl` (or a few lines of Python), so you see
every request and every answer that the window normally hides.

The **development profile** (`--development-profile`) replaces the neural networks with fakes so
that this works on any machine with no model files: its "perception" finds one face in the middle of
every image and embeds it as a vector derived from the picture's pixels. **Identical pictures
therefore become the same identity and different pictures do not.** It is a way to exercise the whole
application, not a way to recognise real faces. Everything it produces is labelled uncalibrated.

## 2. Where it lives

| Piece | File |
|---|---|
| The host you start | `backend/api/host.py` |
| The development profile | `backend/api/development.py` |
| The routes you call | `backend/api/routes/*.py` |
| The interactive description of every route | `frontend/src/api/openapi.json` (generated) |

## 3. How it works

You are doing by hand what the shell and the front end do: the shell starts the host with a token
and reads the handshake; the front end sends the token with every request. The host opens the
library (lock, migrations, storage, index, startup recovery), starts the scheduler loop, and then
answers requests. The profile is recorded inside the library (`app_state`): a library created under
the development profile is refused by the real profile and the reverse
(`backend/api/library_profile.py`), so you cannot accidentally mix fake and real data.

## 4. Try it

**Works with no models. Verified 2026-10-12 on Linux** (bash and `curl`); the PowerShell forms are
*unverified here*. You need `uv sync` done ([lesson 06](06-set-up-your-machine.md)) and two terminals
in the repository folder.

### Terminal A: prepare and start the backend

1. **Make a scratch area and three synthetic pictures** (coloured rectangles with noise; no real
   photographs). This Python works in any shell:

   ```bash
   uv run python - <<'EOF'
   import pathlib, random, shutil
   from PIL import Image

   play = pathlib.Path.home() / "faceidentify-play"
   (play / "lib").mkdir(parents=True, exist_ok=True)
   (play / "state").mkdir(parents=True, exist_ok=True)
   pics = play / "pics"
   pics.mkdir(exist_ok=True)

   def make(name, colour, seed):
       image = Image.new("RGB", (320, 240), colour)
       pixels = image.load()
       rnd = random.Random(seed)
       for _ in range(2000):
           pixels[rnd.randrange(320), rnd.randrange(240)] = (rnd.randrange(256),) * 3
       image.save(pics / name)

   make("red.png", (200, 50, 50), 1)
   make("green.png", (50, 200, 50), 2)
   shutil.copy(pics / "red.png", pics / "red-copy.png")
   print("pictures in", pics)
   EOF
   ```

   Expected: `pictures in /home/<you>/faceidentify-play/pics` (on Windows `C:\Users\<you>\...`). On
   Windows PowerShell, paste the same Python through `uv run python -` is awkward; save it as
   `make_pics.py` in the scratch folder and run `uv run python make_pics.py` instead (*unverified here*).
2. **Make a token** (bash; PowerShell below):

   ```bash
   export FACEIDENTIFY_LAUNCH_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   ```

   ```powershell
   $env:FACEIDENTIFY_LAUNCH_TOKEN = uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **Start the backend** and leave the terminal open:

   ```bash
   uv run python -m backend.api.host --library-root ~/faceidentify-play/lib \
     --local-state-root ~/faceidentify-play/state --development-profile
   ```

   Expected: one JSON line, for example
   `{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":48937,"pid":2981}`.
   **Write down the port.** The first start also creates the library: `lib/database/library.db`,
   `lib/originals/`, `lib/staging/` and the other folders, and `state/` for the index.

### Terminal B: talk to it

4. Set two variables (use your port, and the same token as terminal A):

   ```bash
   export FACEIDENTIFY_LAUNCH_TOKEN="<the token from terminal A>"
   B=http://127.0.0.1:PORT
   H="Authorization: Bearer $FACEIDENTIFY_LAUNCH_TOKEN"
   curl -s -H "$H" $B/readiness
   ```

   Expected: `{"state":"READY","capabilities":{"database":"READY","storage":"READY","index":"READY","recovery":"READY","ml_worker":"NOT_CONFIGURED","scheduler":"READY"}}`.
   If `state` is `INITIALIZING`, wait a second and ask again: the library opens after the server
   starts serving.

5. **Import the red picture** (a path on this machine, absolute):

   ```bash
   curl -s -X POST -H "$H" -H "Content-Type: application/json" \
     -d "{\"path\":\"$HOME/faceidentify-play/pics/red.png\"}" $B/api/v1/sources/import
   ```

   Expected: `201`-style JSON starting `{"id":"<uuid>","type":"IMAGE","display_name":"red", "availability":"AVAILABLE","processing_status":"NOT_PROCESSED",...,"state":"ACTIVE","storage_mode":"MANAGED",...,"width":320,"height":240,"mime_type":"image/png"}`.
   Copy the `id` into `RED=<uuid>`. The file was **copied** into `lib/originals/`; `NOT_PROCESSED` means
   nothing has been recognised yet.

6. **Process it** and watch the run finish:

   ```bash
   curl -s -X POST -H "$H" $B/api/v1/sources/$RED/process
   ```

   Expected: HTTP 202 and a run with `"state":"PENDING"`, `"policy":{"calibration_mode":"UNCALIBRATED",
   "decision_policy_version":"development-uncalibrated-v1","calibrated":false,"automatic_matching":true}`
   and `"job":{"state":"QUEUED","priority":"INTERACTIVE",...}`. Copy the run `id` into `RUN=<uuid>` and ask
   twice, a second apart:

   ```bash
   curl -s -H "$H" $B/api/v1/processing-runs/$RUN
   ```

   Expected: `"state":"COMPLETED"` and `"job":{"state":"COMPLETED",...}` (the fake perception is fast;
   the real models take about a second per image on CPU).

7. **See what it found:**

   ```bash
   curl -s -H "$H" $B/api/v1/sources/$RED/occurrences
   curl -s -H "$H" $B/api/v1/identities
   ```

   Expected: one *occurrence* (the face in this image, with `"bounding_box":{"x":0.2,"y":0.2,"width":0.6,
   "height":0.6}`, the middle of the picture, as the fake always says) and one *identity* with
   `"occurrence_count":1`, `"person":null` (nobody has named it) and `"revision":3`.

8. **Import and process the copy and the green picture** the same way (`red-copy.png`, then
   `green.png`), then list identities again:

   ```bash
   curl -s -H "$H" $B/api/v1/identities
   ```

   Expected: **two** identities: one with `"occurrence_count":2,"source_count":2` (red and its identical
   copy were recognised as the same subject) and one with `1,1` (green).

9. **Name the first identity** (put its `id` in `ID`), then search by name:

   ```bash
   curl -s -X POST -H "$H" -H "Content-Type: application/json" \
     -d "{\"display_name\":\"Ada Example\",\"identity_id\":\"$ID\"}" $B/api/v1/people
   curl -s -H "$H" "$B/api/v1/search?q=ada"
   ```

   Expected: a person `{"display_name":"Ada Example","revision":1,"identity_count":1,...}`, then a
   search result whose `people` list has `Ada Example` with `"match":"PREFIX"`, `"occurrence_count":2`,
   `"source_count":2`, and `"coverage":{"sources":3,"processed":3,"not_processed":0}`.

10. **Search by a picture** (the picture is read and forgotten; nothing is stored):

    ```bash
    curl -s -X POST -H "$H" -H "Content-Type: image/png" \
      --data-binary @$HOME/faceidentify-play/pics/red.png $B/api/v1/search/face
    ```

    Expected: one face with `"status":"IDENTITY_ANSWER","reason":"MATCHED"`, the person `Ada Example`, and
    in `possible_people` the same identity with `"similarity":1.0` (cosine similarity 1.0: identical) next
    to the other identity at about `0.208`. Search with `green.png` and the answer is the other identity.

11. **Stop and restart.** Stop terminal A (Ctrl+C), start it again with the same command, ask
    `/readiness`, then list identities again. Expected: the same two identities and the person's name.
    The memory lives in the library on disk, not in the running program.

### The same thing in Python (works in every shell)

`httpx` is installed with the project. Start an interactive prompt with `uv run python` and type:

```python
import os, time, httpx
api = httpx.Client(base_url="http://127.0.0.1:PORT",
                   headers={"Authorization": "Bearer " + os.environ["FACEIDENTIFY_LAUNCH_TOKEN"]},
                   timeout=30)
print(api.get("/readiness").json()["state"])          # READY
src = api.post("/api/v1/sources/import", json={"path": "/home/you/faceidentify-play/pics/red.png"})
print(src.status_code, src.json()["processing_status"])  # 201 NOT_PROCESSED
run = api.post(f"/api/v1/sources/{src.json()['id']}/process").json()
print(run["state"], run["job"]["state"])               # PENDING QUEUED
time.sleep(1)
print(api.get(f"/api/v1/processing-runs/{run['id']}").json()["state"])   # COMPLETED
```

(This exact sequence, with the base URL of a live host, printed `READY`, `201 NOT_PROCESSED`,
`PENDING QUEUED`, `COMPLETED` on 2026-10-12.)

### What the window does differently

In the real app the shell starts the backend for you and the page replaces `curl`. Open the page with
`npm run tauri dev` (*unverified here: no display*). The behaviour it shows is exactly the sequence
above; `npm run test:e2e` drives the same workflow against the real backend without a window
(*1 passed, as recorded in the restructure's implementation entry; not re-run by the reviewer*; CI's "Desktop shell" job runs it).

## 5. Change it

Change the decision rather than the code: process the *same* picture a second time, then count the
occurrences on the first identity:

```bash
curl -s -X POST -H "$H" $B/api/v1/sources/$RED/process
curl -s -H "$H" $B/api/v1/identities
```

Expected (observed 2026-10-12): the run completes again and the identity's `occurrence_count` rises:
processing a source again is a new run with its own occurrences. (Re-processing is outside M5's scope;
see [`docs/plans/M5_PLAN.md`](../../plans/M5_PLAN.md).) The tests that pin the normal single-process
behaviour:

```bash
uv run pytest tests/integration/test_api_processing.py tests/integration/test_api_development_profile.py -q
```

Expected: pass.

## 6. Break it on purpose

1. Import a path that is not absolute: `-d '{"path":"red.png"}'`. Expected: `422` with
   `"code":"VALIDATION_ERROR"` and `"fields":[{"location":["body","path"],"type":"value_error"}]`: the error
   names the field but never echoes what you sent.
2. Call without the token or with a wrong one: `401 UNAUTHORIZED`.
3. Start a second backend on the same library folders while the first runs. Expected (observed
   2026-10-12): the second one still prints a handshake line and serves, but asking it
   `/readiness` answers `{"state":"FAILED","failure":"LibraryLockedError"}`. The library lock
   `lib/database/.lock` is held by the first; the second refuses to open the library rather than
   opening it a second time, and `failure` names only the error class, never a path. Stop the second
   one with Ctrl+C. The tests behind this: `tests/integration/test_library_lock.py` and
   `tests/integration/test_api_lifespan.py`.

## 7. Exercises

1. After step 8, how many rows would `select count(*) from representations` return? (Three faces.)
2. Which request created the person's name, and which table holds it?
3. What does `similarity: 0.208` mean, and would you call it a 20.8% chance?
4. Why does the face search not change `occurrence_count`?

**Answers**

1. Three (one vector per face, whatever the identity).
2. `POST /api/v1/people`; the `people` table (with an `identity_person_associations` row linking it).
3. The cosine similarity between the picture's vector and the nearest remembered face of that identity.
   It is a raw score, never a probability.
4. Face search is a query, not an ingest: it reads the picture, looks faces up, and writes nothing.

## 8. Related files

- Previous: [06 Set up your machine](06-set-up-your-machine.md)
- [Call the API](../03-backend/api/01-call-the-api.md) (all the routes)
- [Profiles](../03-backend/architecture/04-profiles.md), [host and startup](../03-backend/architecture/03-host-and-startup.md)
- [Read a database and a log](../02-data-and-storage/09-read-a-database-and-a-log.md)
