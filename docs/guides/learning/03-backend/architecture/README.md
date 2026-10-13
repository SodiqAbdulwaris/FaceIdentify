# Backend architecture

How the backend is put together and how it lives: its layers, the web layer, how it starts and stops, the two profiles,
the scheduler that does the work, how it survives being killed, how it tells the screen what changed, and how it protects
itself.

| # | Lesson | You will learn |
|---|---|---|
| 01 | [Layers and rules](01-layers-and-rules.md) | the dependency direction and the hard rules (thin routes, the worker never touches SQLite, the index never decides truth) |
| 02 | [HTTP and FastAPI](02-http-and-fastapi.md) | requests, status codes, validation, `Depends`, ASGI, uvicorn, with a tiny app you run |
| 03 | [The host and startup](03-host-and-startup.md) | the sidecar host, the handshake, the lifespan, readiness states, shutdown |
| 04 | [Profiles](04-profiles.md) | the development and real profiles, the library-profile guard, what "real" needs |
| 05 | [The scheduler and runner](05-scheduler-and-runner.md) | the loop that claims and executes work |
| 06 | [Recovery](06-recovery.md) | what happens when the program is killed, and how startup repairs it |
| 07 | [Events](07-events.md) | the WebSocket hub, sequence numbers, why events are only hints |
| 08 | [Security](08-security.md) | the token, loopback, trusted input, hashes, what is deliberately not protected |

Back to [03 The backend](../README.md).
