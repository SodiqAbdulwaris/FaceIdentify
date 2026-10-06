"""The scheduler loop: repeat `ProcessingRunner.run_once` until told to stop (M4 W2.3).

The loop is the only thing that claims queued work in the API process. It is created by the
backend only after the library has opened, which includes startup recovery, so recovery and normal
scheduling never race over the same job or run (plan constraint, 2026-10-06).

* `run_once` blocks (decoding, inference, SQLite), so each call runs in a worker thread and the
  event loop stays free to answer requests.
* Work found means another call at once; `IDLE` waits for a `wake()` (a new job was queued) or a
  poll interval, whichever comes first. A wake that arrives while a job runs is not lost: the
  event is cleared *before* each call.
* An error out of `run_once` (a defect, or the database unavailable) is recorded by class name and
  the loop waits one interval before trying again, so a persistent failure never spins.
* `stop()` lets the call in flight finish (it cannot be interrupted) and claims nothing more.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress

import anyio.to_thread

from backend.app.processing.runner import RunOutcome, RunOutcomeKind


class SchedulerService:
    def __init__(self, run_once: Callable[[], RunOutcome], *, idle_seconds: float) -> None:
        self._run_once = run_once
        self._idle_seconds = idle_seconds
        self._stopping = False
        self._wakeup: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self.last_error: str | None = None  # an exception class name, never a message
        self.last_outcome: RunOutcome | None = None  # what the latest look found (None: errored)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the loop on the running event loop."""
        self._loop = asyncio.get_running_loop()
        self._wakeup = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    def wake(self) -> None:
        """Ask for a prompt look at the queue. Safe from any thread."""
        loop, wakeup = self._loop, self._wakeup
        if loop is not None and wakeup is not None:
            with suppress(RuntimeError):  # the event loop is already closed: nothing to wake
                loop.call_soon_threadsafe(wakeup.set)

    async def stop(self) -> None:
        """Claim nothing more and wait for the call in flight to finish."""
        self._stopping = True
        self.wake()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        assert self._wakeup is not None
        while not self._stopping:
            self._wakeup.clear()  # before the call: a wake that arrives meanwhile is kept
            try:
                outcome: RunOutcome | None = await anyio.to_thread.run_sync(self._run_once)
            except Exception as error:  # noqa: BLE001 - recorded; the loop must survive it
                self.last_error = type(error).__name__
                outcome = None
            else:
                self.last_error = None
            self.last_outcome = outcome
            if outcome is not None and outcome.kind is not RunOutcomeKind.IDLE:
                continue  # there may be more queued
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), self._idle_seconds)
