"""TST-035: worker supervision (API and Contracts.md sections 47 to 50).

Real worker processes: a worker that fails does not corrupt the backend, the next call starts a new
worker a bounded number of times, a crash loop ends in FAILED instead of restarting for ever, and a
worker whose parent has gone ends itself and frees what it made.
"""

import threading
import time
from collections.abc import Callable, Iterator
from multiprocessing import Pipe
from typing import Any

import pytest

from backend.infrastructure.resources.shared_memory import AttachedSegment, OwnedSegment
from backend.ml.contracts.control import frame, hello, parse_frame
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    FaceGeometry,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    MLResponse,
)
from backend.ml.contracts.protocol import (
    PROTOCOL_VERSION,
    ContractError,
    ControlType,
    MLErrorCode,
    MLOperation,
    MLStatus,
    WorkerState,
)
from backend.ml.contracts.shared_memory import SharedMemoryDescriptor
from backend.ml.supervisor.process import ProcessWorker
from backend.ml.supervisor.supervisor import (
    MLSupervisor,
    MLUnavailableError,
    SupervisorPolicy,
    WorkerFailedError,
)
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.processes import close_streams, kill_tree, start_until, wait_until_gone

HANDLERS = "tests.fixtures.ml_handlers:build_handlers"
BROKEN = "tests.fixtures.ml_handlers:build_broken"
HANGING = "tests.fixtures.ml_handlers:build_hanging"

POLICY = SupervisorPolicy(
    handshake_timeout=60,
    request_timeout=60,
    ping_timeout=10,
    shutdown_timeout=10,
    max_restarts=2,
    restart_window=600,
)


class Ticks:
    """A clock that moves only when told to."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Supervised:
    """A supervisor over real worker processes, remembering every one it started."""

    def __init__(
        self, factory: str, policy: SupervisorPolicy = POLICY, clock: Ticks | None = None
    ) -> None:
        self.workers: list[ProcessWorker] = []
        self.supervisor = MLSupervisor(self._spawn(factory), policy, clock=clock or Ticks())

    def _spawn(self, factory: str) -> Callable[[], ProcessWorker]:
        def spawn() -> ProcessWorker:
            worker = ProcessWorker(factory)
            self.workers.append(worker)
            return worker

        return spawn

    @property
    def last_pid(self) -> int:
        pid = self.workers[-1].pid
        assert pid is not None
        return pid


@pytest.fixture
def supervised() -> Iterator[Callable[..., Supervised]]:
    made: list[Supervised] = []

    def make(factory: str = HANDLERS, **kwargs: Any) -> Supervised:
        made.append(Supervised(factory, **kwargs))
        return made[-1]

    yield make
    for each in made:
        each.supervisor.stop()
        for worker in each.workers:
            worker.kill()  # (whatever a test left behind)


@pytest.fixture
def lit(new_id: SeededUUIDs) -> Iterator[OwnedSegment]:
    segment = OwnedSegment("uint8", (4, 4, 3), new_id=new_id)
    segment.write(200)
    yield segment
    segment.release()


def detect(segment: OwnedSegment, request_id: str = "r-1", **options: Any) -> MLRequest:
    return MLRequest(
        request_id=request_id,
        operation=MLOperation.DETECT_FACES,
        component="cv-fake",
        input=DetectFacesInput((segment.descriptor,)),
        options=options,
    )


def represent(segment: OwnedSegment, request_id: str = "r-2") -> MLRequest:
    return MLRequest(
        request_id=request_id,
        operation=MLOperation.GENERATE_REPRESENTATIONS,
        component="cv-fake",
        input=GenerateRepresentationsInput(
            (segment.descriptor,), (FaceGeometry(0, 0, (0.1, 0.1, 0.5, 0.6)),)
        ),
    )


def state_of(supervisor: MLSupervisor) -> WorkerState:
    """The state, read fresh (so a type checker does not remember an earlier assertion)."""
    return supervisor.state


def gone(descriptor: SharedMemoryDescriptor) -> bool:
    try:
        AttachedSegment(descriptor).close()
    except ContractError as error:
        return error.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE
    return False


# --- a worker that works ----------------------------------------------------------------------


def test_starting_makes_the_worker_ready_and_stopping_ends_its_process(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised()
    assert state_of(s.supervisor) is WorkerState.STOPPED

    s.supervisor.start()

    assert state_of(s.supervisor) is WorkerState.READY
    assert s.supervisor.worker_instance_id
    assert s.supervisor.capabilities == ["DETECT_FACES", "GENERATE_REPRESENTATIONS"]
    pid = s.last_pid
    s.supervisor.stop()
    assert state_of(s.supervisor) is WorkerState.STOPPED
    assert wait_until_gone(pid)
    s.supervisor.stop()  # idempotent
    assert state_of(s.supervisor) is WorkerState.STOPPED


def test_a_request_starts_the_worker_and_the_same_worker_serves_the_next(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()

    first = s.supervisor.execute(detect(lit))
    second = s.supervisor.execute(detect(lit, "r-3"))

    assert first.status is MLStatus.SUCCESS
    assert isinstance(first.output, DetectFacesOutput)
    assert len(first.output.detections) == 1
    assert second.status is MLStatus.SUCCESS
    assert len(s.workers) == 1
    assert state_of(s.supervisor) is WorkerState.READY
    assert s.supervisor.ping() is True


def test_a_result_segment_is_read_and_then_released_through_the_supervisor(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    response = s.supervisor.execute(represent(lit))
    assert isinstance(response.output, GenerateRepresentationsOutput)
    embedding = response.output.representations[0].embedding
    with AttachedSegment(embedding) as attached:
        assert attached.copy().tolist() == [200.0, 0.0, 0.0, 1.0]

    s.supervisor.release_output("r-2")

    assert s.supervisor.ping()  # (no acknowledgement: a ping after it is the barrier)
    assert gone(embedding)


def test_an_error_response_is_returned_not_raised_and_the_worker_carries_on(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    s.supervisor.start()
    pid = s.last_pid

    response = s.supervisor.execute(detect(lit, mode="raise"))

    assert response.status is MLStatus.ERROR
    assert response.error is not None
    assert response.error.code is MLErrorCode.INFERENCE_FAILED
    assert state_of(s.supervisor) is WorkerState.READY
    assert s.supervisor.execute(detect(lit)).status is MLStatus.SUCCESS
    assert s.last_pid == pid
    assert len(s.workers) == 1


def test_releasing_an_output_with_no_worker_running_does_nothing(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised()

    s.supervisor.release_output("never-made")

    assert state_of(s.supervisor) is WorkerState.STOPPED
    assert s.workers == []


def test_two_threads_asking_at_once_are_served_one_after_the_other(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    results: list[MLResponse] = []

    def ask(request_id: str) -> None:
        results.append(s.supervisor.execute(detect(lit, request_id)))

    threads = [threading.Thread(target=ask, args=(f"r-{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)

    assert sorted(r.request_id for r in results) == ["r-0", "r-1", "r-2", "r-3"]
    assert len(s.workers) == 1


# --- a worker that fails ----------------------------------------------------------------------


def test_a_worker_that_died_between_requests_is_replaced_by_the_next_call(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    s.supervisor.start()
    first = s.last_pid
    kill_tree_of(s.workers[0])
    assert wait_until_gone(first)

    response = s.supervisor.execute(detect(lit))

    assert response.status is MLStatus.SUCCESS
    assert len(s.workers) == 2
    assert s.last_pid != first
    assert state_of(s.supervisor) is WorkerState.READY


def test_a_worker_that_dies_during_a_request_fails_it_and_corrupts_nothing(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    s.supervisor.start()
    pid = s.last_pid

    with pytest.raises(WorkerFailedError, match="died during a request"):
        s.supervisor.execute(detect(lit, mode="exit"))

    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE
    assert wait_until_gone(pid)
    assert lit.copy().tolist()[0][0] == [200, 200, 200]  # the caller's own segment is intact
    # ...and the next call starts a new worker that works.
    assert s.supervisor.execute(detect(lit)).status is MLStatus.SUCCESS
    assert state_of(s.supervisor) is WorkerState.READY
    assert len(s.workers) == 2


def test_a_worker_that_does_not_answer_in_time_is_killed(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    quick = SupervisorPolicy(60, 2.0, 10, 10, 2, 600)
    s = supervised(policy=quick)
    s.supervisor.start()
    pid = s.last_pid

    with pytest.raises(WorkerFailedError, match="did not answer within 2.0s"):
        s.supervisor.execute(detect(lit, mode="sleep:600"))

    assert wait_until_gone(pid)  # killed, not left running
    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE
    assert s.supervisor.last_failure is not None
    assert s.supervisor.execute(detect(lit)).status is MLStatus.SUCCESS


def test_a_worker_that_cannot_load_its_models_fails_every_start_until_a_crash_loop(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised(BROKEN)

    for expected in (WorkerState.UNAVAILABLE, WorkerState.UNAVAILABLE, WorkerState.FAILED):
        with pytest.raises(WorkerFailedError, match="went away while starting"):
            s.supervisor.start()
        assert state_of(s.supervisor) is expected
    spawned = len(s.workers)

    with pytest.raises(MLUnavailableError, match="has failed") as raised:
        s.supervisor.start()

    assert not isinstance(raised.value, WorkerFailedError)  # refused, not another attempt
    assert len(s.workers) == spawned  # nothing more was started


def test_a_crash_loop_ends_only_a_reset_lets_it_try_again(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised(BROKEN)
    for _ in range(3):
        with pytest.raises(WorkerFailedError):
            s.supervisor.start()
    assert state_of(s.supervisor) is WorkerState.FAILED
    with pytest.raises(MLUnavailableError):
        s.supervisor.execute(detect(lit))
    s.supervisor.stop()
    assert state_of(s.supervisor) is WorkerState.FAILED  # stopping does not forgive it

    s.supervisor.reset()

    assert state_of(s.supervisor) is WorkerState.STOPPED
    with pytest.raises(WorkerFailedError):
        s.supervisor.start()  # tries again (and fails again, once)
    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE


def test_resetting_when_nothing_has_failed_changes_nothing(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised()
    s.supervisor.start()

    s.supervisor.reset()

    assert state_of(s.supervisor) is WorkerState.READY


def test_a_worker_found_dead_that_makes_a_crash_loop_is_refused_not_restarted(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    no_restarts = SupervisorPolicy(60, 60, 10, 10, 0, 600)
    s = supervised(policy=no_restarts)
    s.supervisor.start()
    kill_tree_of(s.workers[0])
    assert wait_until_gone(s.last_pid)

    with pytest.raises(MLUnavailableError, match="has failed") as raised:
        s.supervisor.execute(detect(lit))

    assert not isinstance(raised.value, WorkerFailedError)
    assert state_of(s.supervisor) is WorkerState.FAILED
    assert len(s.workers) == 1  # no new worker was started


def test_failures_far_apart_are_not_a_crash_loop(
    supervised: Callable[..., Supervised],
) -> None:
    clock = Ticks()
    s = supervised(BROKEN, clock=clock)

    for _ in range(6):
        with pytest.raises(WorkerFailedError):
            s.supervisor.start()
        clock.now += 601  # longer than the window: the earlier failures no longer count

    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE


def test_a_worker_that_never_becomes_ready_is_killed(
    supervised: Callable[..., Supervised],
) -> None:
    impatient = SupervisorPolicy(2.0, 60, 10, 10, 2, 600)
    s = supervised(HANGING, policy=impatient)

    with pytest.raises(WorkerFailedError, match="did not become ready"):
        s.supervisor.start()

    assert wait_until_gone(s.last_pid)
    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE


def test_a_worker_that_does_not_answer_a_ping_is_killed(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised()
    s.supervisor.start()
    kill_tree_of(s.workers[0])
    assert wait_until_gone(s.last_pid)

    assert s.supervisor.ping() is False

    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE


def test_a_ping_with_no_worker_ready_is_false(supervised: Callable[..., Supervised]) -> None:
    assert supervised().supervisor.ping() is False


def test_releasing_an_output_after_the_worker_died_costs_nothing(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    s.supervisor.start()
    kill_tree_of(s.workers[0])
    assert wait_until_gone(s.last_pid)

    s.supervisor.release_output("r-1")  # the segments went with the process

    assert state_of(s.supervisor) is WorkerState.UNAVAILABLE


def test_stopping_a_worker_that_is_already_dead_just_stops(
    supervised: Callable[..., Supervised],
) -> None:
    s = supervised()
    s.supervisor.start()
    kill_tree_of(s.workers[0])
    assert wait_until_gone(s.last_pid)

    s.supervisor.stop()

    assert state_of(s.supervisor) is WorkerState.STOPPED


def kill_tree_of(worker: ProcessWorker) -> None:
    """Kill a worker from outside, as a crash would (the supervisor is not told)."""
    assert worker.pid is not None
    from backend.ml.supervisor.process import kill_process_tree

    kill_process_tree(worker.pid)


# --- a worker whose parent has gone -----------------------------------------------------------

PARENT = """
import os, sys
from backend.ml.supervisor.process import ProcessWorker
worker = ProcessWorker("tests.fixtures.ml_handlers:build_handlers")
print("READY", flush=True)
print(os.getpid(), worker.pid, flush=True)
sys.stdin.readline()
"""


def test_a_worker_whose_parent_is_killed_ends_itself(tmp_path: Any) -> None:
    parent = start_until(PARENT, ready="READY")
    try:
        assert parent.stdout is not None
        parent_pid, worker_pid = (int(n) for n in parent.stdout.readline().split())
        import subprocess

        subprocess.run(
            ["taskkill", "/F", "/PID", str(parent_pid)], capture_output=True, check=False
        )
        assert wait_until_gone(parent_pid)

        assert wait_until_gone(worker_pid, seconds=60)  # it noticed the pipe close and left
    finally:
        kill_tree(parent)
        close_streams(parent)


# --- a worker that breaks the protocol --------------------------------------------------------


class Scripted:
    """A worker handle whose behaviour is a function of the frames it is sent. Not a process."""

    def __init__(self, behaviour: Callable[[Any, Any], None]) -> None:
        self.connection, self._worker_end = Pipe()
        self.killed = False
        self.alive = True
        self.seen: list[ControlType] = []
        self.nonces: list[str] = []
        self._thread = threading.Thread(
            target=behaviour, args=(self._worker_end, self), daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        return self.alive

    def kill(self) -> None:
        self.killed = True
        self.alive = False
        self._worker_end.close()
        self.connection.close()


def well_behaved_until(break_at: str, then: Callable[[Any], None]) -> Callable[[Any, Any], None]:
    """A worker that completes the handshake, then misbehaves at `break_at` (EXECUTE or PING)."""

    def behave(end: Any, handle: Scripted) -> None:
        try:
            end.send(hello("scripted", ["DETECT_FACES"]))
            end.recv()
            end.send(frame(ControlType.READY))
            while True:
                kind, body = parse_frame(end.recv())
                if kind.value == break_at:
                    then(end)
                    continue
                if kind is ControlType.SHUTDOWN:
                    return  # (and never acknowledges)
        except (EOFError, OSError):
            return

    return behave


def scripted_supervisor(
    behaviour: Callable[[Any, Any], None], policy: SupervisorPolicy = POLICY
) -> tuple[MLSupervisor, list[Scripted]]:
    handles: list[Scripted] = []

    def spawn() -> Scripted:
        handles.append(Scripted(behaviour))
        return handles[-1]

    return MLSupervisor(spawn, policy, clock=Ticks()), handles


def test_a_response_to_another_request_is_a_protocol_failure(lit: OwnedSegment) -> None:
    def wrong_id(end: Any) -> None:
        wire = MLResponse(
            request_id="someone-else",
            status=MLStatus.SUCCESS,
            operation=MLOperation.DETECT_FACES,
            execution=__import__("tests.fixtures.ml_handlers", fromlist=["x"]).PROVENANCE,
            output=DetectFacesOutput(()),
        ).to_wire()
        end.send(frame(ControlType.RESPONSE, response=wire))

    supervisor, handles = scripted_supervisor(well_behaved_until("EXECUTE", wrong_id))

    with pytest.raises(WorkerFailedError, match="not valid"):
        supervisor.execute(detect(lit))

    assert handles[0].killed
    assert state_of(supervisor) is WorkerState.UNAVAILABLE


@pytest.mark.parametrize(
    "garbage",
    ["garbage", {"type": "NOPE"}, frame(ControlType.PONG, nonce="n")],
)
def test_a_worker_that_answers_with_something_else_is_killed(
    lit: OwnedSegment, garbage: Any
) -> None:
    supervisor, handles = scripted_supervisor(
        well_behaved_until("EXECUTE", lambda end: end.send(garbage))
    )

    with pytest.raises(WorkerFailedError, match="not valid"):
        supervisor.execute(detect(lit))

    assert handles[0].killed


def test_a_pong_for_another_ping_is_a_failure() -> None:
    supervisor, handles = scripted_supervisor(
        well_behaved_until("PING", lambda end: end.send(frame(ControlType.PONG, nonce="other")))
    )
    supervisor.start()

    assert supervisor.ping() is False

    assert handles[0].killed


def test_a_handshake_that_is_not_a_hello_is_refused() -> None:
    def not_a_hello(end: Any, handle: Scripted) -> None:
        end.send(frame(ControlType.READY))

    supervisor, handles = scripted_supervisor(not_a_hello)

    with pytest.raises(WorkerFailedError, match="handshake is not valid"):
        supervisor.start()

    assert handles[0].killed


def polite(end: Any, handle: Scripted) -> None:
    """A worker that completes the handshake, answers pings and acknowledges SHUTDOWN, and
    remembers every frame it was sent."""
    try:
        end.send(hello("polite", ["DETECT_FACES"]))
        end.recv()
        end.send(frame(ControlType.READY))
        while True:
            kind, body = parse_frame(end.recv())
            handle.seen.append(kind)
            if kind is ControlType.PING:
                handle.nonces.append(body["nonce"])
                end.send(frame(ControlType.PONG, nonce=body["nonce"]))
            elif kind is ControlType.SHUTDOWN:
                end.send(frame(ControlType.SHUTDOWN_ACK))
                return
    except (EOFError, OSError):
        return


def test_stopping_asks_the_worker_to_shut_down_first_and_then_lets_go_of_it() -> None:
    supervisor, handles = scripted_supervisor(polite)
    supervisor.start()
    assert supervisor.ping() is True
    assert supervisor.ping() is True  # (each ping has its own nonce)

    supervisor.stop()

    assert len(set(handles[0].nonces)) == 2  # a ping that is answered by an old pong proves nothing
    assert handles[0].seen == [ControlType.PING, ControlType.PING, ControlType.SHUTDOWN]
    assert handles[0].killed  # the handle is released once the worker has acknowledged
    assert state_of(supervisor) is WorkerState.STOPPED
    supervisor.release_output("r-1")  # and releasing into a stopped supervisor is harmless
    assert handles[0].seen == [ControlType.PING, ControlType.PING, ControlType.SHUTDOWN]


def test_the_state_is_busy_while_a_request_is_running(
    supervised: Callable[..., Supervised], lit: OwnedSegment
) -> None:
    s = supervised()
    s.supervisor.start()
    result: list[MLResponse] = []
    thread = threading.Thread(
        target=lambda: result.append(s.supervisor.execute(detect(lit, mode="sleep:3")))
    )
    thread.start()
    deadline = time.monotonic() + 30
    while state_of(s.supervisor) is not WorkerState.BUSY and time.monotonic() < deadline:
        time.sleep(0.05)

    assert state_of(s.supervisor) is WorkerState.BUSY
    thread.join(60)
    assert result[0].status is MLStatus.SUCCESS
    assert state_of(s.supervisor) is WorkerState.READY


def test_a_worker_that_will_not_acknowledge_shutdown_is_killed() -> None:
    impatient = SupervisorPolicy(60, 60, 10, 0.5, 2, 600)
    supervisor, handles = scripted_supervisor(
        well_behaved_until("NEVER", lambda end: None), impatient
    )
    supervisor.start()

    supervisor.stop()

    assert handles[0].killed
    assert state_of(supervisor) is WorkerState.STOPPED


def test_a_worker_that_cannot_be_started_at_all_is_a_failure() -> None:
    def cannot_spawn() -> Scripted:
        raise OSError("no more processes")

    supervisor = MLSupervisor(cannot_spawn, POLICY, clock=Ticks())

    with pytest.raises(WorkerFailedError, match="could not be started"):
        supervisor.start()

    assert state_of(supervisor) is WorkerState.UNAVAILABLE


def test_killing_a_worker_ends_its_process_and_closes_the_pipe_to_it() -> None:
    worker = ProcessWorker(HANDLERS)
    pid = worker.pid
    assert pid is not None
    assert worker.is_alive()

    worker.kill()

    assert wait_until_gone(pid)
    assert not worker.is_alive()
    assert worker.connection.closed


def test_a_release_that_cannot_be_written_marks_the_worker_gone() -> None:
    supervisor, handles = scripted_supervisor(well_behaved_until("NEVER", lambda end: None))
    supervisor.start()
    handles[0].connection.close()  # the pipe breaks under it

    supervisor.release_output("r-1")

    assert state_of(supervisor) is WorkerState.UNAVAILABLE


def test_the_policy_refuses_limits_that_make_no_sense() -> None:
    for kwargs in (
        {"handshake_timeout": 0},
        {"request_timeout": -1},
        {"ping_timeout": 0},
        {"shutdown_timeout": -1},
        {"max_restarts": -1},
        {"restart_window": 0},
    ):
        values = {
            "handshake_timeout": 1,
            "request_timeout": 1,
            "ping_timeout": 1,
            "shutdown_timeout": 1,
            "max_restarts": 1,
            "restart_window": 1,
        }
        values.update(kwargs)
        with pytest.raises(ValueError, match="must"):
            SupervisorPolicy(**values)
    assert PROTOCOL_VERSION == 1
