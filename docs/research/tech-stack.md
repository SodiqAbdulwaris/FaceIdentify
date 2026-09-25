# Tech Stack

**Status:** Implementation Stack v1 — Locked Baseline  
**Platform:** Windows Desktop

> **Decision rule:** Use the primary technology unless a documented bottleneck actually appears. Alternatives are migration paths, not technologies to implement in parallel.

## Architecture Tree

```text
WINDOWS DESKTOP APPLICATION
│
├── Desktop shell
│   └── Tauri                              ← LOCKED
│
├── UI
│   ├── React                              ← LOCKED
│   ├── TypeScript                         ← LOCKED
│   ├── Vite                               ← LOCKED
│   ├── Tailwind CSS                       ← LOCKED
│   └── shadcn/ui                          ← LOCKED
│
├── Python application sidecar
│   ├── FastAPI                            ← LOCKED
│   ├── SQLAlchemy 2                       ← LOCKED
│   ├── Alembic                            ← LOCKED
│   ├── Domain services
│   ├── Identity & Memory services
│   ├── Universal Search
│   ├── Scheduler
│   ├── Storage Manager
│   ├── Runtime Package Manager
│   └── Model / Component Manager
│
├── Primary DB
│   └── SQLite + WAL                       ← LOCKED
│       ├── Alt: libSQL
│       │   └── trigger: replication / sync requirement
│       └── Alt: PostgreSQL
│           └── trigger: demonstrated sustained write-concurrency bottleneck
│
├── ML worker
│   ├── separate Python process            ← LOCKED
│   └── ONNX Runtime                       ← LOCKED
│       ├── CUDA                           ← NVIDIA
│       ├── DirectML                       ← Windows GPU
│       └── CPUExecutionProvider           ← universal fallback
│
├── Development / training
│   └── PyTorch                            ← LOCKED
│       └── NOT shipped by default
│
├── Optional NVIDIA optimization
│   └── TensorRT                           ← FUTURE / OPTIONAL
│       └── locally generated machine-specific derived artifact
│
├── Vector ANN
│   └── USearch                            ← LOCKED
│       ├── Alt: FAISS
│       │   └── trigger: advanced ANN / GPU ANN / scale
│       └── Alt: Voyager
│           └── trigger: USearch integration / packaging problems
│
├── Media
│   ├── FFmpeg                             ← LOCKED
│   ├── ffprobe                            ← LOCKED
│   ├── PyAV                               ← LOCKED direction
│   └── OpenCV                             ← CV/image utilities
│
├── Packaging
│   ├── PyInstaller                        ← LOCKED baseline
│   ├── Alt: Nuitka
│   │   └── trigger: measurable packaging benefit
│   └── Alt: self-contained Python env
│       └── trigger: native dependency freezing is unreliable
│
├── Distribution
│   ├── hardware-aware online bootstrapper ← LOCKED
│   └── offline full bundle                ← OPTIONAL
│
├── Updates
│   ├── Application updater
│   ├── Runtime Package Manager
│   └── ComponentVersion / Model updater
│
└── Storage
    ├── User-selected Library root
    │   ├── database/                       ← authoritative
    │   ├── originals/
    │   ├── crops/
    │   ├── thumbnails/
    │   ├── models/
    │   ├── derived/
    │   ├── backups/
    │   └── recovery/
    │
    ├── %LOCALAPPDATA%/<App>/
    │   ├── indexes/                        ← rebuildable
    │   ├── cache/
    │   ├── temp/
    │   ├── logs/
    │   ├── runtime/
    │   └── installation/
    │
    └── Program Files/<App>/
        ├── desktop/
        ├── backend/
        └── baseline-assets/
```

## 1. Desktop and UI

The V1 frontend is **Tauri + React + TypeScript + Vite + Tailwind CSS + shadcn/ui**.

Tauri owns the native Windows shell and process lifecycle. React owns presentation. shadcn/ui is a source of editable primitives, not the application's visual identity. Domain-specific components such as `PersonCard`, `FaceGallery`, `AppearanceTimeline`, `MatchComparison`, `EvidenceInspector`, `PipelineProgress`, `UniversalSearchBar`, and video/face overlays should be built on top.

There is no planned alternate frontend framework. If a particular UI workload becomes expensive, optimize that feature through memoization, virtualization, Web Workers, Canvas/WebGL, or a targeted Tauri/Rust implementation rather than replacing React.

## 2. Tauri ↔ Python

Python runs as a **Tauri-managed sidecar**, not in-process FFI.

```text
Tauri / React
      │ localhost HTTP / WebSocket
      ▼
FastAPI Application
      │
      ├── Domain / Identity / Search
      ├── Scheduler
      ├── Storage
      └── Component / Runtime management
      │
      ▼
Dedicated ML Worker
```

FastAPI binds only to loopback and should use an available dynamic port rather than assuming port 8000. At startup, the backend reports its port and protocol/session information to Tauri.

There is no user authentication. However, use an ephemeral per-launch local secret/nonce so unrelated local processes cannot casually invoke destructive endpoints. This is process isolation, not account authentication.

The shell must handle graceful shutdown, worker shutdown, safe checkpoints, timeout/forced termination, parent-PID monitoring, stale-process cleanup, crash recovery, and single-instance behavior.

## 3. Python Application

Locked technologies:

- Python
- FastAPI
- SQLAlchemy 2
- Alembic

The application owns domain services, Source/Artifact management, Person/Identity/Memory logic, Universal Search, jobs, scheduling, persistence coordination, Storage Manager, Runtime Package Manager, Component Manager, and ML-worker orchestration.

FastAPI is an application boundary, not a transport for raw movies or large frame streams. Managed media should be processed directly from storage.

## 4. Database — SQLite WAL

SQLite is the authoritative V1 relational database.

Use SQLite WAL with SQLAlchemy 2 and Alembic. The processing architecture's **COMPUTED != COMMITTED** rule should be used deliberately: heavy compute may be concurrent while persistence uses short transactions, bounded queues, batching where appropriate, and explicit commit boundaries.

### Alternative: libSQL

Move toward libSQL if replication, synchronization, local-first remote replicas, or another libSQL-specific capability becomes an actual product requirement.

### Alternative: PostgreSQL

Move to PostgreSQL only if sustained measured writer contention materially affects live, interactive, or batch workloads after reasonable SQLite mitigations such as WAL tuning, short transactions, batching, and controlled persistence.

If PostgreSQL is ever adopted for production, it should be application-managed/native. **Docker is development infrastructure only and is not an end-user dependency.**

## 5. Vector ANN — USearch

USearch is the V1 ANN engine.

```text
SQLite     = authoritative metadata and identity truth
USearch    = derived nearest-neighbor acceleration
Filesystem = durable artifacts
```

The ANN index must be rebuildable. Losing USearch must never mean losing identity memory.

### Alternative: FAISS

Use FAISS if advanced index types, GPU ANN, substantially larger scale, or demonstrated USearch performance limits require it.

### Alternative: Voyager

Use Voyager if USearch itself causes significant Windows packaging, integration, or stability problems while the required ANN workload remains straightforward.

Do not maintain multiple ANN engines in parallel without a demonstrated reason.

## 6. Media

**FFmpeg + ffprobe** are the canonical media foundation. Use them for probing, codec/container support, transcoding where necessary, robust media handling, and hardware decoding where appropriate.

**PyAV** provides programmatic frame/timestamp access for the processing pipeline.

**OpenCV** is used for CV/image utilities and preprocessing/postprocessing where appropriate. OpenCV VideoCapture is not the canonical media architecture.

If PyAV becomes problematic for a particular flow, that flow may use direct FFmpeg subprocess/pipe processing.

## 7. ML Development and Production

### Development / training

**PyTorch** is used for experimentation, training, fine-tuning, research, and export preparation.

PyTorch is **not shipped to normal end users by default**. A production component that genuinely cannot leave PyTorch is an explicitly documented exception.

### Production inference

**ONNX Runtime** is the standard production runtime.

```text
ONNX Component
      │
      ▼
Hardware / capability detection
      │
      ├── NVIDIA → CUDA EP
      ├── supported Windows GPU → DirectML
      └── fallback → CPUExecutionProvider
```

CPU is the universal fallback. Provider combinations must be supported and validated for the relevant ComponentVersion rather than assumed numerically identical.

Fallback to a PyTorch runtime is permitted only when a required component cannot be faithfully exported/executed through ONNX Runtime without unacceptable semantic or functional degradation.

## 8. ML Export Provenance

Export is a first-class provenanced operation:

```text
TrainingRun
    ↓
Source ComponentVersion
    ↓
Export ProcessingJob
    ↓
Export WorkUnit
    ↓
ONNX Artifact
    ↓
Deployable ComponentVersion / Artifact relationship
    ↓
Evaluation
    ↓
VersionDecision
    ↓
ComponentActivation
```

The exported ONNX file is an `Artifact`, linked through `ComponentVersionArtifact` with an appropriate role such as `ONNX_EXPORT`. The export should retain `produced_by_work_unit_id` provenance where supported.

Runtime, precision, quantization, opset, conversion provenance, and representation-space compatibility are semantically relevant when they can change output behavior.

Variants such as PyTorch FP32, ONNX FP32, ONNX FP16, and ONNX INT8 must not silently masquerade as interchangeable artifacts if their behavior differs. Deployable variants must be identifiable, evaluated, and provenanced.

## 9. TensorRT

TensorRT is not required for V1.

If later justified by a measured NVIDIA inference bottleneck, a portable ONNX artifact may be compiled locally into a TensorRT engine. The resulting engine is machine-specific, derived, rebuildable, hardware/runtime dependent, and not assumed portable between installations.

## 10. ML Process Isolation

Heavy inference runs in **one dedicated Python ML worker process**.

This isolates GPU OOM and native inference failures, gives models/VRAM a clear owner, and allows the application/database to survive worker restart.

The worker may execute DETECT → TRACK → SELECT → REPRESENT → RECOGNIZE internally. These are capabilities, not separate OS processes.

Only move to multiple specialized workers if the single worker becomes a demonstrated scheduling or fault-isolation bottleneck, such as live camera work being unable to coexist acceptably with long movie processing.

## 11. Packaging

**PyInstaller** is the V1 baseline for the Python application and worker.

**Nuitka** is the first alternative only if it provides a demonstrated practical advantage in reliability, startup, distribution, output size, or build behavior.

If native dependency freezing remains fundamentally unreliable, the Plan C is a managed self-contained Python environment/runtime.

Native dependency handling is more important than loyalty to a particular bundler.

## 12. Distribution — Hardware-aware Bootstrapper

The normal distribution is an online bootstrap installer.

```text
Setup
  ↓
Detect Windows / CPU / RAM / GPU / VRAM / drivers / disk
  ↓
Resolve installation plan
  ↓
Download required runtime packages and components
  ↓
Verify checksums / signatures
  ↓
Install
  ↓
Initialize
  ↓
Run application + inference smoke test
  ↓
Launch
```

NVIDIA systems receive the appropriate CUDA path; supported AMD/Intel Windows GPUs may receive DirectML; unsupported/CPU-only systems retain ORT CPU fallback.

An optional **offline full bundle** may package baseline dependencies and models for installations without internet.

## 13. Runtime Packages

Infrastructure dependencies are distinct from ML `ComponentVersion`s.

Examples include ONNX Runtime, execution-provider packages, FFmpeg, USearch/native ANN support, and Windows native prerequisites.

The Runtime Package concept should carry enough information for dependency resolution:

- package ID and name
- version
- platform and architecture
- download source
- checksum and signature
- size
- dependencies/conflicts
- hardware requirements
- compatibility constraints
- install strategy
- installation state

The exact persistence schema can be finalized during implementation; the architectural concept is locked.

## 14. Component Management and Updates

ML/application capabilities retain the existing lifecycle:

```text
Component
    ↓
ComponentVersion
    ↓
Artifact
    ↓
Evaluation
    ↓
VersionDecision
    ↓
ComponentActivation
```

Maintain three independent update domains:

1. **Application updater** — Tauri shell, React UI, Python application, migrations, protocols.
2. **Runtime Package Manager** — ORT, execution providers, FFmpeg, native infrastructure.
3. **Component Manager** — detectors, trackers, representation models, recognizers, calibration, and other independently versioned components.

A model-only update must not require a complete application reinstall.

## 15. Storage Layout

### User-selected Library root

```text
<Library Root>/
├── database/
│   └── library.db
├── originals/
├── crops/
├── thumbnails/
├── models/
├── derived/
├── backups/
├── recovery/
└── staging/
```

The authoritative database lives with the library so the user's library can be backed up or moved coherently.

> **Decision 2026-09-25:** this is the authoritative storage layout (persistence §1 and architecture §16.3 were aligned to it). `staging/` holds managed writes in flight; it sits inside the library root, not in machine-local `temp/`, because the final rename must stay on one volume to be atomic. (Owner decision, M2 PR #14.)

### Machine-local state

```text
%LOCALAPPDATA%/<App>/
├── indexes/
├── cache/
├── temp/
├── logs/
├── runtime/
└── installation/
```

ANN/search indexes belong here because they are derived and rebuildable.

### Installed application

```text
Program Files/<App>/
├── desktop/
├── backend/
└── baseline-assets/
```

User media must never be stored under Program Files.

Baseline models may ship with baseline assets, while independently installed/upgraded ComponentVersions belong in managed model storage.

## 16. Docker Policy

Docker may be used for development, CI, reproducible developer environments, and experiments.

**Docker is not a production/end-user dependency.** Users should not need Docker Desktop, WSL2, or a container runtime to run the application.

## 17. Pressure Points and Migration Paths

| Primary | Pressure point | Mitigation first | Alternative | Migration trigger |
|---|---|---|---|---|
| SQLite WAL | serialized writes | short transactions, batching, persistence queues | PostgreSQL | sustained measured write contention affects real workloads |
| SQLite WAL | future sync/replication | preserve DB abstraction boundaries | libSQL | sync/replication becomes a real product requirement |
| USearch | advanced/large ANN | tune index/rebuild strategy | FAISS | scale, advanced ANN, or GPU ANN is actually required |
| USearch | native integration | packaging/runtime fixes | Voyager | USearch integration itself becomes materially problematic |
| ONNX Runtime | unsupported/unfaithful model | export fixes and validated variants | PyTorch runtime | faithful ONNX execution cannot be achieved |
| One ML worker | workload contention | scheduling, priorities, batching | multiple workers | live/interactive and batch workloads cannot coexist acceptably |
| PyInstaller | packaging limitations | hooks/explicit native collection | Nuitka | measurable practical advantage |
| Frozen Python | native dependency failure | runtime-package separation | self-contained environment | freezing remains unreliable |
| Online bootstrap | no network | caching/manifests | offline bundle | offline installation is required |
| React | isolated render bottleneck | virtualization/workers/Canvas/WebGL | targeted native Rust | specific UI workload cannot meet requirements in web layer |
| ONNX CUDA | NVIDIA performance ceiling | batching/optimization | TensorRT | measured bottleneck justifies machine-local acceleration |

Alternatives are **not parallel implementations**. They are pre-considered escape routes.

## 18. Release Validation

A release pipeline should eventually perform:

```text
dependency lock
  ↓
dependency/security checks
  ↓
build Python sidecar + ML worker
  ↓
build Tauri app
  ↓
construct bootstrap package/manifests
  ↓
install on clean Windows environment
  ↓
launch
  ↓
hardware/provider detection
  ↓
open/create library
  ↓
inference smoke test
  ↓
process sample image
  ↓
search smoke test
  ↓
close/reopen
  ↓
uninstall
  ↓
verify user library survived
```

Clean-machine validation is required because developer machines can hide missing native DLL/runtime dependencies.

## 19. Authoritative vs Derived Boundary

### Authoritative

- SQLite relational state
- retained managed source media
- identity corrections and feedback
- deletion/forget state
- component/version provenance
- critical backups

### Derived / rebuildable

- USearch ANN indexes
- search indexes
- caches
- reconstructible recognition artifacts
- TensorRT engines
- regenerable thumbnails/crops
- temporary processing artifacts

### Operational

- jobs
- tasks
- work units/attempts
- checkpoints
- runtime state
- installation state

No derived technology may override authoritative state.

> **USearch, ONNX outputs, TensorRT engines, caches, stale indexes, old runtime state, or other derived structures cannot override current authoritative identity, correction, deletion, or forget state.**

## 20. Final V1 Stack

| Area | Choice | Status |
|---|---|---|
| Platform | Windows | LOCKED |
| Desktop shell | Tauri | LOCKED |
| Frontend | React + TypeScript | LOCKED |
| Frontend build | Vite | LOCKED |
| Styling | Tailwind CSS | LOCKED |
| UI primitives | shadcn/ui | LOCKED |
| Backend | Python + FastAPI | LOCKED |
| ORM | SQLAlchemy 2 | LOCKED |
| Migrations | Alembic | LOCKED |
| Database | SQLite WAL | LOCKED |
| ANN | USearch | LOCKED |
| Media | FFmpeg + ffprobe + PyAV | LOCKED |
| CV utilities | OpenCV | LOCKED direction |
| Training | PyTorch | LOCKED |
| Production inference | ONNX Runtime | LOCKED |
| NVIDIA inference | CUDA EP | LOCKED direction |
| Windows GPU inference | DirectML | LOCKED direction |
| CPU fallback | ORT CPU | LOCKED |
| ML isolation | Dedicated Python worker | LOCKED |
| Optional NVIDIA optimization | TensorRT | FUTURE |
| Python packaging | PyInstaller | LOCKED baseline |
| Distribution | Hardware-aware online bootstrapper | LOCKED |
| Offline distribution | Full bundle | OPTIONAL |
| Runtime management | Runtime Package Manager | LOCKED concept |
| Model management | Component Manager | LOCKED concept |
| Large-file storage | Managed filesystem | LOCKED |
| End-user Docker | None | LOCKED |

## 21. Implementation Rule

1. Implement the primary V1 technology.
2. Do not implement alternatives preemptively.
3. Preserve boundaries that make the documented migration path possible.
4. Measure an actual bottleneck before changing the stack.
5. If migration becomes necessary, document the bottleneck, evidence, attempted mitigations, migration impact, and rollback strategy.
6. Never allow a technology choice to override the locked Product, Identity/Memory, Processing, Search, or deletion/privacy invariants.

The alternatives in this document represent **planned escape routes, not indecision**.
