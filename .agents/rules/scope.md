# Scope rules

## Locked stack

Tauri · React + TypeScript + Vite + Tailwind CSS + shadcn/ui · Python + FastAPI ·
SQLAlchemy 2 + Alembic · SQLite WAL · USearch · ONNX Runtime · one persistent ML worker.

Do not introduce PostgreSQL, FAISS, TensorRT, a second inference worker, a distributed
transaction framework, another frontend framework, or a second package manager (Python: `uv`;
JavaScript: `npm`). Replacing a locked component needs the user's decision, backed by evidence
(see the migration triggers in `docs/research/tech-stack.md`).

## Stay inside the task

- Implement what the current milestone and task require: nothing speculative, and no
  "for later" scaffolding unless asked.
- Do not invent production tables, domain models or API contracts that the specs do not define.
- Do not add a dependency when the standard library or an existing dependency does the job.
  Every new dependency is recorded in the implementation entry, with the reason.
- Do not reorganise unrelated code. If you notice something worth fixing outside scope, write it
  down under *Follow-ups* in your implementation entry instead of fixing it.
- Keep the process boundaries: the ML worker never touches SQLite. USearch never decides identity
  truth. Routes stay thin.

## When unsure

Ask. This applies especially to product behaviour, spec conflicts, data deletion, security and
anything hard to reverse.
