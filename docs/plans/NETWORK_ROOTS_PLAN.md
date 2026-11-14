# Approved network roots for face search by path (issue #174)

_Status: PR A built (2026-11-14); B, C and D not started._

**Goal.** Under the owner's decision of 2026-10-14 (locked, on issue #174) and the direction of
2026-11-14: a picture named by path in face search may live on a network share the user approved by
name, and only there. Default deny stays. Scope: face search by path only. Out of scope: referenced
import from a share (#179), cameras, and any listener on a LAN interface.

**Steps** (each its own PR, one at a time):

| Step | Content | State |
|---|---|---|
| A | Approvals store (machine-local file `network-roots.json` under the local state root) and `GET`/`POST`/`DELETE /api/v1/settings/network-roots`; approving contacts nothing | built, [entry](../implementations/2026-11-14-approved-network-roots-store.md) |
| B | Policy in the path check: a UNC path, mapped drive, link or junction whose effective target is inside an approved root is allowed; the walk-to-open race closed | not started |
| C | Isolation and deadlines: network reads in a killable helper process with a deadline, retryable failure, no lease, transaction or lock held while waiting | not started |
| D | Settings screen to review, add and revoke approved locations | not started |

> **Decision 2026-11-14 (agent, delegated by the owner's brief):** the approvals live in a
> machine-local JSON file, not in the library database, so a library copied to another computer does
> not carry its owner's network approvals with it; the recognition policy file is the precedent.

**Serves:** issue #174's acceptance tests (listed in the issue); TST-056.
