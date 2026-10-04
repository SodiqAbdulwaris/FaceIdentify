# M4: authenticated local API bootstrap

- **Date:** 2026-10-04
- **Milestone / tracker IDs:** M4 first slice · TST-045, TST-048, TST-051, SEC-003
- **Status:** partial
- **Commits:** pending PR

## What changed

Added FastAPI and an in-memory application factory. Every HTTP route, including health/readiness,
requires this launch's canonical 256-bit `Authorization: Bearer` capability. `/api/v1/events`
requires the same capability via an offered `fi.<token>` WebSocket protocol, but selects only the
stable `faceidentify.v1` protocol. Tokens are never stored, logged, returned, or put in URLs.

## Why

This implements the approved SEC-003 local-process boundary. The future Tauri host creates and
passes the token and binds the server to loopback; the factory cannot bind an ASGI server itself.

## Verification

- Focused contract suite: 9 passed; 100% line/branch coverage.
- Clean full suite: 2,156 passed in 311.32 seconds; 100% coverage.
- Clean-baseline mutations of HTTP authorization, token length, and WebSocket conjunction all
  failed; source restored byte-identically, SHA-256 `672D6E7B9A596853A6680DDF18F85A7B5081157BDE5EA2EF5D8483CD625B527C`.

## Open issues / follow-ups

- Implement loopback sidecar launch, FastAPI lifespan/library-worker-scheduler startup, routes,
  generated client contracts, and desktop readiness tests in later M4 slices.
