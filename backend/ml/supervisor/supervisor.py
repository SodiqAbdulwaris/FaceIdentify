"""The ML supervisor: owns the worker process, its handshake, its restarts (API and Contracts.md
sections 47 to 50).

A request can fail in three different ways, and they are kept apart. The worker answers an ERROR
response (an operation failure: the caller gets the response and nothing changes). The worker
answers but cannot run a component (a component or runtime failure: the response says so and the
backend decides about fallback). Or the worker stops answering: it died, it timed out, it spoke
nonsense. That is a worker failure, the only one this class handles: the process is killed, the
state becomes UNAVAILABLE, and the caller gets `WorkerFailedError`.

The next call after a worker failure starts a new worker, a bounded number of times: more than
`max_restarts` failures inside `restart_window` seconds is a crash loop, and the capability becomes
FAILED rather than restarting for ever; it stays so until `reset()`. A request that was in flight
when the worker failed is never retried here (the caller decides); a request is sent only to a
worker that has just been seen to be alive.

Segments: the caller owns the segments it passed in and releases them after the response (or when
this raises, because a dead worker cannot be reading them). The worker owns the segments of its
results, which the operating system frees if it dies and which `release_output` frees otherwise.
No limit of time, count or window has a default: they are the caller's measured choices.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.ml.contracts.control import frame, parse_frame
from backend.ml.contracts.messages import MLRequest, MLResponse
from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    ControlType,
    MLErrorCode,
    WorkerState,
)
from backend.ml.supervisor.process import WorkerHandle


class MLUnavailableError(RuntimeError):
    """The machine-learning capability cannot be used right now."""


class WorkerFailedError(MLUnavailableError):
    """The worker died, timed out or broke the protocol; it has been killed."""


@dataclass(frozen=True, slots=True)
class SupervisorPolicy:
    handshake_timeout: float  # seconds to say HELLO and become READY
    request_timeout: float  # seconds an EXECUTE may take
    ping_timeout: float
    shutdown_timeout: float  # seconds to acknowledge SHUTDOWN before being killed
    max_restarts: int  # failures tolerated inside the window; one more is a crash loop
    restart_window: float  # seconds

    def __post_init__(self) -> None:
        if min(self.handshake_timeout, self.request_timeout, self.ping_timeout) <= 0:
            raise ValueError("timeouts must be positive")
        if self.shutdown_timeout < 0 or self.max_restarts < 0:
            raise ValueError("the shutdown timeout and the restart limit must not be negative")
        if self.restart_window <= 0:
            raise ValueError("the restart window must be positive")


class MLSupervisor:
    def __init__(
        self,
        spawn: Callable[[], WorkerHandle],
        policy: SupervisorPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spawn = spawn
        self._policy = policy
        self._clock = clock
        self._lock = threading.RLock()  # one request at a time; start/stop/ping wait their turn
        self._state = WorkerState.STOPPED
        self._worker: WorkerHandle | None = None
        self._failures: deque[float] = deque()
        self._pings = 0
        self.worker_instance_id: str | None = None
        self.capabilities: list[str] = []
        self.last_failure: str | None = None

    @property
    def state(self) -> WorkerState:
        return self._state

    # --- starting and stopping -----------------------------------------------------------------

    def start(self) -> None:
        """Make the worker READY, starting it if it is not running. Raises `WorkerFailedError` if
        it cannot be started, `MLUnavailableError` if the capability has FAILED."""
        with self._lock:
            self._ensure_ready()

    def stop(self) -> None:
        """Ask the worker to shut down; kill it if it does not acknowledge in time. Idempotent."""
        with self._lock:
            worker = self._worker
            if worker is None:
                if self._state is not WorkerState.FAILED:
                    self._state = WorkerState.STOPPED
                return
            if self._state is WorkerState.READY and worker.is_alive():
                self._state = WorkerState.STOPPING
                self._shut_down(worker)
            self._discard_worker()
            self._state = WorkerState.STOPPED

    def reset(self) -> None:
        """Forget past failures so a FAILED capability may be tried again (a deliberate act)."""
        with self._lock:
            self._failures.clear()
            if self._state is WorkerState.FAILED:
                self._state = WorkerState.STOPPED

    # --- using the worker ----------------------------------------------------------------------

    def execute(self, request: MLRequest) -> MLResponse:
        """Run one request. The response may be an ERROR response (returned, not raised). A
        failure of the worker itself raises `WorkerFailedError`."""
        with self._lock:
            worker = self._ensure_ready()
            self._state = WorkerState.BUSY
            try:
                worker.connection.send(frame(ControlType.EXECUTE, request=request.to_wire()))
                body = self._receive(worker, ControlType.RESPONSE, self._policy.request_timeout)
                response = MLResponse.from_wire(body["response"], request)
            except TimeoutError as error:  # (first: TimeoutError is an OSError)
                raise self._fail(
                    f"the worker did not answer within {self._policy.request_timeout}s"
                ) from error
            except (OSError, EOFError) as error:
                raise self._fail(
                    f"the worker died during a request ({type(error).__name__})"
                ) from error
            except ContractError as error:
                raise self._fail(f"the worker's answer is not valid ({error})") from error
            self._state = WorkerState.READY
            return response

    def release_output(self, request_id: str) -> None:
        """Tell the worker it may free the segments of a request's result. Never raises: a worker
        that is gone has already had them freed by the operating system."""
        with self._lock:
            worker = self._worker
            if worker is None or self._state is not WorkerState.READY:
                return
            try:
                worker.connection.send(frame(ControlType.RELEASE_OUTPUT, request_id=request_id))
            except (OSError, EOFError):
                self._record_failure("the worker is gone (while releasing an output)")

    def ping(self) -> bool:
        """Whether the worker answers. A worker that does not is killed."""
        with self._lock:
            if self._state is not WorkerState.READY or self._worker is None:
                return False
            worker = self._worker
            self._pings += 1
            nonce = f"ping-{self._pings}"
            try:
                worker.connection.send(frame(ControlType.PING, nonce=nonce))
                body = self._receive(worker, ControlType.PONG, self._policy.ping_timeout)
                if body["nonce"] != nonce:
                    raise ContractError(MLErrorCode.INVALID_REQUEST, "a PONG for another PING")
            except (OSError, EOFError, TimeoutError, ContractError):
                self._record_failure("the worker did not answer a ping")
                return False
            return True

    # --- internals -----------------------------------------------------------------------------

    def _ensure_ready(self) -> WorkerHandle:
        if self._state is WorkerState.FAILED:
            raise MLUnavailableError(f"the ML capability has failed: {self.last_failure}")
        worker = self._worker
        if worker is not None and self._state is WorkerState.READY:
            if worker.is_alive():
                return worker
            self._record_failure("the worker had died between requests")
            if self.state is WorkerState.FAILED:  # (read through the property: the call changed it)
                raise MLUnavailableError(f"the ML capability has failed: {self.last_failure}")
        return self._launch()

    def _launch(self) -> WorkerHandle:
        self._state = WorkerState.STARTING
        try:
            worker = self._spawn()
        except OSError as error:
            raise self._fail(f"the worker could not be started ({error})") from error
        self._worker = worker
        try:
            body = self._receive(worker, ControlType.HELLO, self._policy.handshake_timeout)
            worker.connection.send(frame(ControlType.INITIALIZE, protocol_version=PROTOCOL_VERSION))
            self._receive(worker, ControlType.READY, self._policy.handshake_timeout)
        except TimeoutError as error:  # (first: TimeoutError is an OSError)
            raise self._fail("the worker did not become ready in time") from error
        except (OSError, EOFError) as error:
            raise self._fail(
                f"the worker went away while starting ({type(error).__name__})"
            ) from error
        except ContractError as error:
            raise self._fail(f"the worker's handshake is not valid ({error})") from error
        self.worker_instance_id = body["worker_instance_id"]
        self.capabilities = list(body["capabilities"])
        self._state = WorkerState.READY
        return worker

    def _receive(
        self, worker: WorkerHandle, expected: ControlType, timeout: float
    ) -> dict[str, Any]:
        """The next frame, which must be `expected`, within `timeout` seconds. A worker that dies
        closes its end of the pipe, which shows up here as readable and then as EOF."""
        if not worker.connection.poll(timeout):
            raise TimeoutError
        kind, body = parse_frame(worker.connection.recv())
        if kind is not expected:
            raise ContractError(MLErrorCode.INVALID_REQUEST, f"expected {expected}, got {kind}")
        return body

    def _fail(self, reason: str) -> WorkerFailedError:
        """Kill the worker, record why, and return the error to raise."""
        self._record_failure(reason)
        return WorkerFailedError(reason)

    def _record_failure(self, reason: str) -> None:
        self.last_failure = reason
        self._discard_worker()
        now = self._clock()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._policy.restart_window:
            self._failures.popleft()
        crash_loop = len(self._failures) > self._policy.max_restarts
        self._state = WorkerState.FAILED if crash_loop else WorkerState.UNAVAILABLE

    def _discard_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.kill()

    def _shut_down(self, worker: WorkerHandle) -> None:
        try:
            worker.connection.send(frame(ControlType.SHUTDOWN))
            self._receive(worker, ControlType.SHUTDOWN_ACK, self._policy.shutdown_timeout)
        except (OSError, EOFError, TimeoutError, ContractError):
            pass  # killed by the caller either way
