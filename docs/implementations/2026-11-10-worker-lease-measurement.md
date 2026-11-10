# Worker lease measurement and the fairness benchmark (M6 step 2, D5)

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 2 (D5); issue #175; TST-069 (first half: worker arbitration)
- **Status:** done
- **Commits:** PR (number recorded when merged): `perf(ml): measure worker turns and stress the
  lease`, `docs: record the worker lease measurement`

## What changed

- `backend/ml/supervisor/lease.py`: every turn on the worker is measured. A `TurnRecord` holds its
  class (interactive or background), how long it waited for the worker, how long it held it (the
  inference and its output protocol), how many requests of each class were still waiting when it was
  granted (the queue depth), and its outcome (`RAN`, `FAILED`, `CANCELLED`). It goes to the lease's
  `observe` callback, which by default logs one debug line per turn; the benchmark collects them.
  The lease's default clock is now `time.perf_counter` (monotonic, and fine-grained on Windows,
  where `time.monotonic` ticks every 15.6 ms and the first benchmark run showed every short wait as
  0, 15.6 or 31.2 ms).
- `benchmarks/worker_lease_stress.py` (new): a background thread processes images one job at a time,
  as the scheduler does (a fresh client per job, a detection then a representation, each its own
  turn), while face searches arrive at random (exponential gaps, seeded) with at most three in
  flight (the route's `face_search_slots`). It is run once per fairness value and reports, per class,
  the wait for the worker (p50, p95, max), the mean inference time and the queue depth, plus the
  background throughput and the searches' end-to-end time. `--real` runs the installed models through
  the real `ClientPool` and worker process (and reports the provider that actually ran); the default
  holds the real lease for simulated inference times.
- Tests in `tests/concurrency/test_worker_lease.py`: a measured turn's wait, hold and outcome for a
  request that ran, failed and was cancelled (a deterministic clock); the queue depth recorded at
  each grant; the default debug line.

## Why

Owner decision 2026-10-14 on #175, point 8 (instrument per-class wait, execution time, queue depth,
cancellations and fairness; choose thresholds only after measuring) and its last acceptance test (a
stress run logging p50/p95 queue wait and throughput); M6 decision D5 (the fairness parameter starts
at 3 consecutive interactive grants and changes only on measured evidence).

## Measurements

Windows 11, 2026-11-10, 200 background images per run, a search every 400 ms on average (seed 7),
burst = the consecutive interactive grants allowed before a waiting background request goes first.
One run per value: the differences between neighbouring values are of the order of the run-to-run
noise, so read trends, not single digits. Other sessions were using the machine at the same time.

**Real models** (`buffalo_l` through the real pool and worker, DirectML preferred with the CPU as
fallback; one LFW photograph with one face as every request's picture, read locally, nothing about
it printed or kept; two runs):

| burst | search wait p50 / p95 / max (ms) | job wait p50 / p95 / max (ms) | images/s | search end-to-end p50 / p95 (ms) |
|---|---|---|---|---|
| 1 | 49.4 / 190.3 / 289.9 · 27.1 / 134.4 / 186.0 | 0.0 / 62.2 / 78.7 · 0.0 / 44.1 / 57.4 | 8.33 · 12.16 | 178.7 / 414.4 · 133.5 / 319.0 |
| 2 | 43.8 / 145.6 / 200.0 · 29.7 / 106.1 / 158.4 | 0.0 / 90.6 / 134.0 · 0.0 / 64.4 / 108.4 | 8.13 · 10.72 | 183.9 / 336.9 · 138.8 / 267.8 |
| **3** | **34.5 / 116.3 / 160.7 · 32.5 / 80.0 / 115.3** | 0.0 / 82.9 / 165.9 · 0.0 / 59.3 / 147.8 | **8.32 · 11.60** | 171.1 / 276.1 · 134.3 / 211.4 |
| 5 | 35.0 / 106.5 / 152.4 · 28.1 / 69.5 / 95.8 | 0.0 / 72.3 / 271.3 · 0.0 / 61.1 / 224.3 | 7.43 · 10.73 | 174.4 / 273.3 · 135.4 / 194.2 |

Each cell gives the first run, then the second (`first · second`). The first run's report predates
the provider field; the second records `execution_provider` `DmlExecutionProvider`,
`provider_fallback` `NONE`. Mean inference was about 45 ms in both (detection and representation
together average out over 400 background and 130 to 145 search requests per run); the second run
had less competition from other sessions' test runs, hence the higher throughput.

**Simulated** (the real lease held for 40 ms per detection and 25 ms per representation, jitter
±10%):

| burst | search wait p50 / p95 / max (ms) | job wait p50 / p95 / max (ms) | images/s | search end-to-end p50 / p95 (ms) |
|---|---|---|---|---|
| 1 | 37.7 / 159.3 / 186.2 | 0.0 / 42.4 / 46.5 | 11.58 | 133.5 / 309.3 |
| 2 | 19.8 / 84.0 / 137.6 | 0.0 / 71.5 / 87.2 | 11.57 | 105.7 / 207.1 |
| 3 | 22.9 / 97.8 / 108.4 | 0.0 / 70.8 / 133.6 | 11.54 | 106.6 / 202.8 |
| 5 | 20.5 / 62.8 / 90.8 | 0.0 / 69.3 / 177.9 | 11.55 | 97.4 / 180.5 |

## Decisions

> **Decision 2026-11-10 (delegated decision, D5; the owner: "accept all 11 and i'll leave the rest
> of the decisions entirely to you"):** the fairness parameter stays at **3** consecutive interactive
> grants. On the real models in both runs, 1 and 2 make a search wait longer at p95 (134 to 190 ms)
> than 3 (80 to 116 ms); 5 shortens the search p95 by only 10 ms or so while the worst wait of
> background work grows (224 to 271 ms against 148 to 166 ms at 3) and throughput was lower in both
> runs (7.43 and 10.73 images/s against 8.32 and 11.60). 3 keeps throughput within about 5% of the
> setting most favourable to background work (1) while cutting the search p95 by about 40%. The
> measurements
> confirm the starting value; nothing argues for a change. No latency target is set: the owner's
> decision says to choose thresholds only after measuring representative workloads, and video work
> (steps 4 and 5) is the representative long-run load still to come.

> **Decision 2026-11-10 (delegated decision):** the per-turn measurement is logged at debug level
> and kept nowhere else (no metrics store, no readiness field): it is diagnosis and benchmark input,
> and two lines per image at info level would flood the log during an import.

## Verification

Filled in from the actual runs before the PR is reported ready.

## Open issues / follow-ups

- #175: batch yields for long runs come with the video path (M6 steps 4 and 5), where a frame batch
  will take one turn; the benchmark can then be re-run with video work as the background class.
