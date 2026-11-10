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
  Every granted turn gets its record; a clock reading that fails after the grant leaves that time
  `None`.
  The lease's default clock is now `time.perf_counter` (monotonic, and fine-grained on Windows,
  where `time.monotonic` ticks every 15.6 ms and the first benchmark run showed every short wait as
  0, 15.6 or 31.2 ms).
- `benchmarks/worker_lease_stress.py` (new): a background thread processes images one job at a time,
  as the scheduler does (a fresh client per job, a detection then a representation, each its own
  turn), while face searches arrive at random (exponential gaps, seeded) with at most three in
  flight (the route's `face_search_slots`). It is run once per fairness value and reports, per class,
  the wait for the worker (nearest-rank p50, p95, and the max), the mean inference time, the queue
  depth and the outcomes (ran, failed, cancelled, printed per class), plus the fairness grants (background grants made
  while searches waited), the background throughput and the searches' end-to-end time. `--real` runs the installed models through
  the real `ClientPool` and worker process (and reports the provider that actually ran); the default
  holds the real lease for simulated inference times.
- Tests in `tests/concurrency/test_worker_lease.py`: a measured turn's wait, hold and outcome for a
  request that ran, failed and was cancelled (a deterministic clock); the queue depth recorded at
  each grant; the default debug line; a clock failing at the release or at the grant still records
  the turn with the time unknown; a failing cancellation check is recorded `FAILED`.
  `tests/unit/test_worker_lease_stress.py`: the benchmark's nearest-rank percentile, and its
  per-class outcomes, kept and reported when the workload raises (the benchmark then exits with an
  error after printing what it measured).

## Why

Owner decision 2026-10-14 on #175, point 8 (instrument per-class wait, execution time, queue depth,
cancellations and fairness; choose thresholds only after measuring) and its last acceptance test (a
stress run logging p50/p95 queue wait and throughput); M6 decision D5 (the fairness parameter starts
at 3 consecutive interactive grants and changes only on measured evidence).

## Measurements

Windows 11, 2026-11-10, 200 background images per run, a search every 400 ms on average (seed 7),
burst = the consecutive interactive grants allowed before a waiting background request goes first.
Percentiles are nearest-rank. A *fairness grant* is a background grant made while searches were
waiting (the burst had run out). Other sessions were using the machine at the same time, so read
trends across runs, not single digits.

**Real models, final run** (`buffalo_l` through the real pool and worker; the report records
`execution_provider` `DmlExecutionProvider`, `provider_fallback` `NONE`; one LFW photograph with
one face as every request's picture, read locally, nothing about it printed or kept; mean inference
about 45 ms; no request was cancelled or failed):

| burst | search wait p50 / p95 / max (ms) | job wait p50 / p95 / max (ms) | images/s | search end-to-end p50 / p95 (ms) | fairness grants |
|---|---|---|---|---|---|
| 1 | 27.9 / 134.2 / 167.0 | 0.0 / 41.7 / 55.6 | 12.17 | 131.0 / 284.3 | 40 |
| 2 | 29.4 / 114.6 / 166.4 | 0.0 / 71.1 / 124.6 | 10.07 | 141.3 / 284.8 | 17 |
| **3** | **30.3 / 93.2 / 150.2** | 0.0 / 80.3 / 176.9 | 9.75 | 145.0 / 234.9 | 11 |
| 5 | 28.4 / 88.1 / 130.0 | 0.0 / 80.6 / 249.2 | 10.04 | 142.9 / 251.8 | 4 |

Two earlier real runs (before the review fixes: a rounded rather than nearest-rank percentile, no
provider, grant or outcome fields; the second recorded DirectML with no fallback afterwards) showed
the same shape: search wait p95 190 / 146 / 116 / 107 ms and 134 / 106 / 80 / 70 ms for bursts
1 / 2 / 3 / 5, with the worst background wait 79 / 134 / 166 / 271 ms and 57 / 108 / 148 / 224 ms.
Throughput moved between 7.4 and 12.2 images/s across runs without a consistent order by burst: at
this search rate it is dominated by the machine's other load, not by the fairness parameter.

**Simulated, final run** (the real lease held for 40 ms per detection and 25 ms per representation,
jitter ±10%):

| burst | search wait p50 / p95 / max (ms) | job wait p50 / p95 / max (ms) | images/s | search end-to-end p50 / p95 (ms) | fairness grants |
|---|---|---|---|---|---|
| 1 | 37.1 / 160.7 / 185.4 | 0.0 / 42.9 / 53.2 | 11.56 | 143.0 / 338.4 | 70 |
| 2 | 18.2 / 92.9 / 162.0 | 0.0 / 71.7 / 95.8 | 11.32 | 106.6 / 235.5 | 17 |
| 3 | 21.0 / 75.6 / 118.8 | 0.0 / 80.6 / 132.2 | 11.00 | 115.3 / 201.6 | 13 |
| 5 | 17.6 / 67.1 / 91.8 | 0.0 / 72.5 / 194.7 | 11.01 | 95.9 / 193.8 | 3 |

## Decisions

> **Decision 2026-11-10 (delegated decision, D5; the owner: "accept all 11 and i'll leave the rest
> of the decisions entirely to you"):** the fairness parameter stays at **3** consecutive interactive
> grants. In all three real runs and the simulated one, 1 and 2 make a search wait longer at p95
> than 3, while 5 shortens the search p95 by only 5 to 10 ms and lengthens the worst wait of
> background work by about 50% (249 against 177 ms in the final run). Throughput does not separate
> the values at this load. The measurements confirm the starting value; nothing argues for a change.
> No latency target is set: the owner's decision says to choose thresholds only after measuring
> representative workloads, and video work (steps 4 and 5) is the representative long-run load
> still to come.

> **Decision 2026-11-10 (delegated decision):** the per-turn measurement is logged at debug level
> and kept nowhere else (no metrics store, no readiness field): it is diagnosis and benchmark input,
> and two lines per image at info level would flood the log during an import. Every turn that is
> granted gets its record: a clock failing at the release leaves the hold unknown (`None`) and the
> turn as it was; a clock failing at the grant fails that request as before (released, the error
> raised) and its record shows both times unknown. A clock failing before the request is queued
> fails it before it is a turn at all, with nothing to record. The clock is `time.perf_counter`,
> which does not fail in practice; these paths exist so a fault never loses a record or a turn
> (found by the Codex review).

## Verification

Filled in from the actual runs before the PR is reported ready.

## Open issues / follow-ups

- #175: batch yields for long runs come with the video path (M6 steps 4 and 5), where a frame batch
  will take one turn; the benchmark can then be re-run with video work as the background class.
