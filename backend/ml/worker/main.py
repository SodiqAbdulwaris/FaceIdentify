"""The worker process's entry point: build the handlers named by a factory, then serve.

The factory is a dotted `module:function` path that returns the handlers (given the worker's
configuration text, if it has one: the supervising process passes it as an argument, not through
the environment), so the process that
supervises the worker never imports a model library: loading models is the worker's business and
its crash if it goes wrong. This runs only inside the child process, which coverage does not
measure; everything it calls is tested in-process.
"""

import importlib
import sys
import uuid
from multiprocessing.connection import Connection

from backend.ml.contracts.protocol import MLOperation
from backend.ml.worker.loop import Handler, serve


def load_handlers(factory_path: str, config: str | None = None) -> dict[MLOperation, Handler]:
    """Call the factory, with the configuration text if there is one."""
    module_name, _, function_name = factory_path.partition(":")
    factory = getattr(importlib.import_module(module_name), function_name)
    handlers: dict[MLOperation, Handler] = factory() if config is None else factory(config)
    return handlers


def worker_entry(
    connection: Connection, factory_path: str, config: str | None = None
) -> None:  # pragma: no cover
    try:
        handlers = load_handlers(factory_path, config)
    except Exception as error:
        print(
            f"ml-worker: could not load handlers: {type(error).__name__}: {error}", file=sys.stderr
        )
        raise SystemExit(2) from error
    serve(connection, handlers, instance_id=uuid.uuid4().hex, new_id=uuid.uuid4)
