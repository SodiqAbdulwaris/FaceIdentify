# 03 The backend

The backend is the real application: it owns the database, the files, the rules and the memory. These
folders split it by what you want to know.

| Folder | Read it when | Lessons |
|---|---|---|
| [architecture/](architecture/README.md) | you want to know how the pieces and processes fit | layers, HTTP and FastAPI, the host and startup, profiles, the scheduler and runner, recovery, events, security |
| [api/](api/README.md) | you want to call, add or change a route | conventions, calling the API, adding a route, the OpenAPI contract, and [one lesson per route module](api/routes/README.md) |
| [domain/](domain/README.md) | you want the product's vocabulary | sources, artifacts, observations, representations, identities, people, occurrences, evidence, states and revisions |
| [processing/](processing/README.md) | you want to know how a photograph is processed | jobs and runs, snapshots, executing an image, checkpoints and acceptance, cancel and retry |
| [recognition/](recognition/README.md) | you want to know how a face becomes a decision | retrieval, assessment, the decision policy, decisions in memory, the face query |
| [runtime-and-worker/](runtime-and-worker/README.md) | you want to know about the models and the separate worker process | messages, supervisor, perception client and providers, packages and the catalog |
| [lifecycle/](lifecycle/README.md) | you want to know what delete really means | recycle and restore, permanent delete, forget |

Suggested order for a first pass: [layers](architecture/01-layers-and-rules.md) → [domain vocabulary](domain/01-vocabulary.md)
→ [jobs and runs](processing/01-jobs-and-runs.md) → [the decision policy](recognition/03-decision-policy.md) →
[the API conventions](api/README.md).

Back to the [guide index](../README.md).
