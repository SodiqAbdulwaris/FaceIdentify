"""The live class of the worker lease (M7 step 3; plan C6; TST-072, TST-077 contention half).

A camera session's inference is `live`: after interactive face searches, before background
processing, and the burst rule counts grants to either higher class, so a movie keeps moving under a
running camera. Real threads on a real lease, lined up behind a held worker (`Line`), as in
`test_worker_lease.py`: nothing depends on how long anything takes.
"""

import threading

from backend.ml.supervisor.lease import (
    ServiceClass,
    TurnRecord,
    WorkerLease,
    interactive,
    is_interactive,
    live,
    service_class,
)
from tests.concurrency.test_worker_lease import Line, finish

INTERACTIVE, LIVE, BACKGROUND = ServiceClass


class Classes(Line):
    """A `Line` whose requests may be of any class."""

    def join_as(self, name: str, service: ServiceClass) -> None:
        def request() -> None:
            scope = {INTERACTIVE: interactive, LIVE: live}.get(service)
            if scope is None:
                with self.lease.held():
                    self.served.append(name)
            else:
                with scope(), self.lease.held():
                    self.served.append(name)

        thread = threading.Thread(target=request)
        thread.start()
        self.threads.append(thread)
        self.condition.queued_one()


def test_live_work_goes_after_searches_and_before_background_work() -> None:
    line = Classes(WorkerLease(burst=10))
    line.join_as("movie", BACKGROUND)
    line.join_as("camera", LIVE)
    line.join_as("search", INTERACTIVE)

    assert line.let_go() == ["search", "camera", "movie"]


def test_a_running_camera_cannot_stop_a_movie() -> None:
    """Live requests arriving faster than the worker serves them still let a waiting background
    request through after every `burst` higher-class grants."""
    line = Classes(WorkerLease(burst=2))
    line.join_as("movie 1", BACKGROUND)
    line.join_as("movie 2", BACKGROUND)
    for n in range(1, 6):
        line.join_as(f"frame {n}", LIVE)

    assert line.let_go() == [
        "frame 1", "frame 2", "movie 1", "frame 3", "frame 4", "movie 2", "frame 5",
    ]  # fmt: skip


def test_searches_and_frames_share_one_burst() -> None:
    line = Classes(WorkerLease(burst=2))
    line.join_as("movie", BACKGROUND)
    line.join_as("frame", LIVE)
    line.join_as("search", INTERACTIVE)
    line.join_as("search 2", INTERACTIVE)

    assert line.let_go() == ["search", "search 2", "movie", "frame"]


def test_a_live_request_is_recorded_as_live() -> None:
    records: list[TurnRecord] = []
    line = Classes(WorkerLease(observe=records.append))
    line.join_as("movie", BACKGROUND)
    line.join_as("frame", LIVE)

    assert line.let_go() == ["frame", "movie"]
    services = [(r.service, r.queued_live, r.queued_background) for r in records]
    assert services == [(BACKGROUND, 0, 0), (LIVE, 0, 1), (BACKGROUND, 0, 0)]
    assert records[1].live
    assert not records[1].interactive


def test_the_queue_of_each_class_is_counted() -> None:
    line = Classes(WorkerLease())
    line.join_as("frame", LIVE)
    line.join_as("movie", BACKGROUND)

    assert [line.lease.queued(service) for service in ServiceClass] == [0, 1, 1]
    line.let_go()
    assert [line.lease.queued(service) for service in ServiceClass] == [0, 0, 0]


def test_the_innermost_scope_names_the_class() -> None:
    assert service_class() is BACKGROUND
    with live():
        assert service_class() is LIVE
        assert not is_interactive()
        with interactive():  # a search made from a camera session (step 6) is interactive
            assert service_class() is INTERACTIVE
        assert service_class() is LIVE
    assert service_class() is BACKGROUND

    seen: list[ServiceClass] = []
    with live():
        thread = threading.Thread(target=lambda: seen.append(service_class()))
        thread.start()
        finish([thread])
    assert seen == [BACKGROUND]  # (a new thread starts in the default class)
