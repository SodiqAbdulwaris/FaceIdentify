"""Running a perception plan against the ML worker: detect the faces of one image, then represent
them, trying the planned variants in the caller's order.

The worker never falls back (Architecture 9): it answers with a coded error and the backend decides.
This is where the backend decides, and it decides narrowly. Only the two codes that mean *this
execution provider cannot run here* move on to the next planned variant
(`RUNTIME_VARIANT_NOT_AVAILABLE`, `RUNTIME_INITIALIZATION_FAILED`); every other error is the
operation's own failure (a model that will not load, a broken input, an inference error) and is
raised, because trying a different variant would hide it. When every variant of a stage has been
ruled out the answer is `RuntimeUnavailableError` with a reason per variant, never a substitute.

A variant that was ruled out stays out for the life of this client (a provider that was missing a
moment ago does not come back mid-run), so one run does not bounce between providers. A worker that
fails (dies, times out) raises `WorkerFailedError` from the supervisor, unchanged: the supervisor
restarts it on the next call, and whether to retry the request is the caller's decision.

What comes back says which variant **actually ran** (`ran`): that is what the writer records as the
output's provenance (Persistence 5 and 6.2), not the variant that was preferred.

A client belongs to one thread (one processing run): the record of ruled-out variants is not
locked, and releasing a worker's output is a separate call from the request that made it.

Pixels travel to the worker in a shared-memory segment this client creates and releases around the
call; vectors come back in segments the worker made, which are copied out and then released.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.app.runtime.worker_config import (
    PerceptionPlan,
    PlannedVariant,
    RuntimeUnavailableError,
)
from backend.infrastructure.resources.shared_memory import AttachedSegment, SegmentLedger
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    Detection,
    ExecutionContext,
    FaceGeometry,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    MLResponse,
)
from backend.ml.contracts.protocol import MLErrorCode, MLOperation, MLStatus
from backend.ml.supervisor.process import ProcessWorker
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy

WORKER_FACTORY = "backend.ml.worker.perception_handlers:build_handlers"

# The only worker errors that mean "not this provider, ask for the next variant".
PROVIDER_UNAVAILABLE = frozenset(
    {MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE, MLErrorCode.RUNTIME_INITIALIZATION_FAILED}
)


class PerceptionError(Exception):
    """The worker could not do the operation, or answered something that cannot be right."""

    def __init__(self, code: MLErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ProviderUnavailable:
    """One provider-specific rejection while the backend selects a runtime variant."""

    variant: PlannedVariant
    code: MLErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ProviderFallback:
    """One transition to the variant that succeeded, retaining every unavailable attempt."""

    failed: tuple[ProviderUnavailable, ...]
    selected: PlannedVariant


@dataclass(frozen=True, slots=True)
class Detected:
    detections: tuple[Detection, ...]  # empty is a successful "no face"
    ran: PlannedVariant
    fallbacks: tuple[ProviderFallback, ...] = ()


@dataclass(frozen=True, slots=True)
class FaceVector:
    detection_index: int
    vector: NDArray[np.float32]  # the canonical vector, a copy that belongs to the caller
    normalization: str


@dataclass(frozen=True, slots=True)
class Represented:
    vectors: tuple[FaceVector, ...]  # one per detection, in the order asked
    ran: PlannedVariant | None  # None when there was nothing to represent (no worker call)
    fallbacks: tuple[ProviderFallback, ...] = ()


def supervisor_for(plan: PerceptionPlan, policy: SupervisorPolicy) -> MLSupervisor:
    """A supervisor whose worker is started with `plan`'s configuration (and so can run exactly
    the variants the plan offers)."""
    return MLSupervisor(lambda: ProcessWorker(WORKER_FACTORY, plan.worker_config()), policy)


class PerceptionClient:
    def __init__(
        self,
        supervisor: MLSupervisor,
        plan: PerceptionPlan,
        *,
        new_id: Callable[[], uuid.UUID],
    ) -> None:
        self._supervisor = supervisor
        self._plan = plan
        self._new_id = new_id
        # (stage, variant) -> why this provider cannot run; a stage never inherits another's
        self._ruled_out: dict[tuple[str, uuid.UUID], str] = {}

    def detect(
        self, pixels: NDArray[np.uint8], *, context: ExecutionContext | None = None
    ) -> Detected:
        with SegmentLedger(new_id=self._new_id) as ledger:
            image = _put(ledger, pixels)
            _, response, ran, fallbacks = self._attempt(
                "the face detector",
                self._plan.detector,
                lambda variant: self._request(
                    MLOperation.DETECT_FACES, variant, DetectFacesInput((image,)), context
                ),
            )
        assert isinstance(response.output, DetectFacesOutput)  # (the operation's own output)
        # (a detection makes no worker segments, so there is nothing to release_output here)
        return Detected(response.output.detections, ran, fallbacks)

    def represent(
        self,
        pixels: NDArray[np.uint8],
        detections: Sequence[Detection],
        *,
        context: ExecutionContext | None = None,
    ) -> Represented:
        if not detections:
            return Represented((), None)
        if len({d.detection_index for d in detections}) != len(detections):
            raise ValueError("each detection is represented once")
        asked = tuple(FaceGeometry(0, d.detection_index, d.box, d.landmarks) for d in detections)
        with SegmentLedger(new_id=self._new_id) as ledger:
            image = _put(ledger, pixels)
            request, response, ran, fallbacks = self._attempt(
                "the face embedder",
                self._plan.embedder,
                lambda variant: self._request(
                    MLOperation.GENERATE_REPRESENTATIONS,
                    variant,
                    GenerateRepresentationsInput((image,), asked),
                    context,
                ),
            )
            try:
                return Represented(self._read(response, asked), ran, fallbacks)
            finally:
                self._supervisor.release_output(request.request_id)

    # --- internals -------------------------------------------------------------------------

    def _request(
        self,
        operation: MLOperation,
        variant: PlannedVariant,
        body: Any,
        context: ExecutionContext | None,
    ) -> MLRequest:
        return MLRequest(
            request_id=str(self._new_id()),
            operation=operation,
            component=str(variant.component_version_id),
            input=body,
            options={"runtime_variant_id": str(variant.runtime_variant_id)},
            execution_context=context or ExecutionContext(),
        )

    def _attempt(
        self,
        what: str,
        variants: Sequence[PlannedVariant],
        build: Callable[[PlannedVariant], MLRequest],
    ) -> tuple[MLRequest, MLResponse, PlannedVariant, tuple[ProviderFallback, ...]]:
        """Ask each variant that is not ruled out, in order, until one runs."""
        failures: list[ProviderUnavailable] = []
        for variant in variants:
            if _key(variant) in self._ruled_out:
                continue
            request = build(variant)
            response = self._supervisor.execute(request)
            if response.status is MLStatus.SUCCESS:
                self._check_it_was_that_variant(request, response, variant)
                return (
                    request,
                    response,
                    variant,
                    (ProviderFallback(tuple(failures), variant),) if failures else (),
                )
            assert response.error is not None  # (an ERROR response always has its error)
            if response.error.code not in PROVIDER_UNAVAILABLE:
                raise PerceptionError(response.error.code, response.error.message)
            self._ruled_out[_key(variant)] = (
                f"{variant.provider} ({variant.package_key}): {response.error.message}"
            )
            failures.append(
                ProviderUnavailable(variant, response.error.code, response.error.message)
            )
        raise RuntimeUnavailableError(
            what,
            [self._ruled_out[_key(v)] for v in variants],  # (every one is, by now)
        )

    def _check_it_was_that_variant(
        self, request: MLRequest, response: MLResponse, variant: PlannedVariant
    ) -> None:
        """The provenance recorded for an output is what the worker says ran, so it must be what
        was asked for: an answer from another variant is refused, not recorded under this one."""
        execution = response.execution
        assert execution is not None  # (a SUCCESS response always has its execution)
        # (the worker's provenance is one configured entry chosen by exactly these two ids, so its
        # provider and device follow from them)
        if execution.runtime_variant_id != str(
            variant.runtime_variant_id
        ) or execution.component_version_id != str(variant.component_version_id):
            self._supervisor.release_output(request.request_id)
            raise PerceptionError(
                MLErrorCode.INTERNAL_WORKER_ERROR,
                f"asked for variant {variant.runtime_variant_id}, the worker says it ran "
                f"{execution.runtime_variant_id}",
            )

    def _read(
        self, response: MLResponse, asked: tuple[FaceGeometry, ...]
    ) -> tuple[FaceVector, ...]:
        output = response.output
        assert isinstance(output, GenerateRepresentationsOutput)
        results = {r.face_index: r for r in output.representations}
        if len(results) != len(output.representations) or set(results) != {
            face.face_index for face in asked
        }:
            raise PerceptionError(
                MLErrorCode.INTERNAL_WORKER_ERROR,
                "the worker did not answer for exactly the faces it was asked about",
            )
        vectors: list[FaceVector] = []
        for face in asked:
            result = results[face.face_index]
            if result.dimension != self._plan.dimension or result.dtype != "float32":
                raise PerceptionError(
                    MLErrorCode.INTERNAL_WORKER_ERROR,
                    f"a {result.dimension}-value {result.dtype} vector, expected "
                    f"{self._plan.dimension} float32 values",
                )
            with AttachedSegment(result.embedding) as segment:
                vector = segment.copy().astype("<f4", copy=False)
            vectors.append(FaceVector(face.face_index, vector, result.normalization))
        return tuple(vectors)


def _key(variant: PlannedVariant) -> tuple[str, uuid.UUID]:
    return variant.kind, variant.runtime_variant_id


def _put(ledger: SegmentLedger, pixels: NDArray[np.uint8]) -> Any:
    """The image in a segment the worker may read; returns its descriptor."""
    if pixels.dtype != np.uint8:
        raise ValueError("an image is uint8 pixels")
    segment = ledger.create("uint8", pixels.shape)
    segment.write(pixels)
    return segment.descriptor
