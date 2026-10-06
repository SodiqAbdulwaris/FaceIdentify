"""The scheduler loop (M4 W2.3): idle waits, wakes, bounded failures, a stop that waits.

The runner is a stand-in here, so each test names exactly what the loop does with an outcome. The
real runner through the real library is exercised in `test_api_processing.py`. Waiting is on thread
events with a bound, never on a clock for correctness (the long idle interval proves a wake, not a
timeout, ended the wait).
"""

import asyncio
import threading
from collections.abc import Callable

import anyio.to_thread

from backend.api.scheduler import SchedulerService
from backend.app.processing.runner import RunOutcome, RunOutcomeKind

LONG = 60.0  # an idle interval no test waits out
IDLE = RunOutcome(RunOutcomeKind.IDLE)
ACCEPTED = RunOutcome(RunOutcomeKind.ACCEPTED)


class Script:
    """A `run_once` that returns scripted outcomes (or raises them) and counts its calls."""

    def __init__(self, *steps: RunOutcome | Exception, then: RunOutcome | Exception = IDLE) -> None:
        self.steps = list(steps)
        self.then = then
        self.calls = 0
        self.called = threading.Condition()
        self.before: Callable[[], None] | None = None

    def __call__(self) -> RunOutcome:
        if self.before is not None:
            self.before()
        with self.called:
            self.calls += 1
            self.called.notify_all()
        step = self.steps.pop(0) if self.steps else self.then
        if isinstance(step, Exception):
            raise step
        return step

    def wait_for_calls(self, count: int) -> bool:
        with self.called:
            return self.called.wait_for(lambda: self.calls >= count, timeout=30)


async def reached(script: Script, count: int) -> bool:
    return await anyio.to_thread.run_sync(script.wait_for_calls, count)


async def test_idle_waits_for_a_wake_not_for_the_interval() -> None:
    script = Script()
    service = SchedulerService(script, idle_seconds=LONG)
    service.start()
    assert await reached(script, 1)
    assert service.running

    service.wake()  # a new job was queued

    assert await reached(script, 2)  # the long interval was cut short
    await service.stop()
    assert not service.running


async def test_found_work_is_followed_at_once_by_another_look() -> None:
    script = Script(ACCEPTED, ACCEPTED, IDLE)
    service = SchedulerService(script, idle_seconds=LONG)
    service.start()

    assert await reached(script, 3)  # no wake, no interval: it kept going while work was found

    await service.stop()
    assert script.calls == 3


async def test_a_wake_during_a_call_is_not_lost() -> None:
    script = Script()
    service = SchedulerService(script, idle_seconds=LONG)
    script.before = lambda: service.wake() if script.calls == 0 else None
    service.start()

    assert await reached(script, 2)  # the wake arrived mid-call and still ended the next wait

    await service.stop()


async def test_an_error_does_not_stop_the_loop_and_a_later_success_clears_it() -> None:
    script = Script(RuntimeError("boom"), then=IDLE)
    service = SchedulerService(script, idle_seconds=0.01)
    service.start()

    assert await reached(script, 3)  # failed, waited one interval, then looked again, repeatedly
    await service.stop()

    assert service.last_error is None


async def test_the_recorded_error_is_a_class_name_never_a_message() -> None:
    script = Script(RuntimeError("secret path C:/Users/x"), then=RuntimeError("again"))
    service = SchedulerService(script, idle_seconds=LONG)
    service.start()
    assert await reached(script, 1)
    for _ in range(300):  # the loop records the error just after the call returns
        if service.last_error is not None:
            break
        await asyncio.sleep(0.01)

    assert service.last_error == "RuntimeError"
    assert "secret" not in str(service.last_error)
    await service.stop()


async def test_stop_waits_for_the_call_in_flight_and_claims_nothing_more() -> None:
    release = threading.Event()
    entered = threading.Event()
    calls = 0

    def blocking() -> RunOutcome:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(30)
        return ACCEPTED  # (work was found: without a stop it would look again at once)

    service = SchedulerService(blocking, idle_seconds=LONG)
    service.start()
    assert await anyio.to_thread.run_sync(entered.wait, 30)

    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0)  # let stop() begin and block on the call in flight
    assert not stopping.done()
    release.set()
    await stopping

    assert calls == 1
    assert not service.running


async def test_stopping_a_service_that_never_started_is_harmless() -> None:
    service = SchedulerService(Script(), idle_seconds=LONG)

    await service.stop()

    assert not service.running


def test_a_wake_before_start_or_after_the_loop_closed_is_harmless() -> None:
    script = Script()
    service = SchedulerService(script, idle_seconds=LONG)
    service.wake()  # never started: nothing to wake

    async def lifecycle() -> None:
        service.start()
        assert await reached(script, 1)
        await service.stop()

    asyncio.run(lifecycle())
    service.wake()  # the event loop is closed now: ignored, never an error
