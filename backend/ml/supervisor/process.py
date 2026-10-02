"""Starting and stopping the real worker process.

On Windows the interpreter a virtual environment starts may itself start the real one, so a worker
is killed with its whole process tree (the lesson of the library-lock tests); elsewhere killing the
process is enough.
"""

import multiprocessing
import subprocess
import sys
from typing import Any, Protocol

from backend.ml.worker.main import worker_entry


class WorkerConnection(Protocol):
    """The parent's end of the pipe (a `multiprocessing` Connection is one; its class differs
    between Windows and POSIX)."""

    def send(self, obj: Any, /) -> None: ...

    def recv(self) -> Any: ...

    def poll(self, timeout: float | None = 0.0, /) -> bool: ...

    def close(self) -> None: ...


class WorkerHandle(Protocol):
    """What the supervisor needs of a worker process, however it was made."""

    @property
    def connection(self) -> WorkerConnection: ...

    def is_alive(self) -> bool: ...

    def kill(self) -> None: ...


def kill_process_tree(pid: int) -> None:
    """End a process and everything it started; a process that is already gone is fine."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:  # pragma: no cover - the suite runs on Windows
        import os
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class ProcessWorker:
    """A worker running in its own process, reached over a pipe."""

    def __init__(self, factory_path: str, config: str | None = None) -> None:
        context = multiprocessing.get_context("spawn")
        self.connection, child_end = context.Pipe()
        self._process = context.Process(
            target=worker_entry, args=(child_end, factory_path, config), daemon=True
        )
        self._process.start()
        # The child holds its own copy; keeping this one would hide the child's death from the
        # parent on POSIX (the pipe would never read as closed). Windows pipes break either way, so
        # no test here can tell.
        child_end.close()

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def kill(self) -> None:
        pid = self._process.pid
        assert pid is not None  # (the process is started in __init__)
        kill_process_tree(pid)  # (taskkill returns when the process is gone: nothing to wait for)
        self.connection.close()
