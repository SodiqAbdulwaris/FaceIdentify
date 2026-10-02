"""The worker's two operations, DETECT_FACES and GENERATE_REPRESENTATIONS, run on ONNX models.

The worker is started with a JSON configuration naming the model variants it may run (written by
the backend from what is installed; see `parse_config`). Nothing is loaded at start: a variant is
loaded, verified and cached the first time a request names it, so a variant that cannot run (a
missing file, a changed digest, an unavailable provider) is a coded error answer the backend can
act on, which includes choosing another variant, rather than a worker that never becomes ready.
A request names the component version it wants in `component`, and the variant in
`options["runtime_variant_id"]` (needed only when the component has more than one).

This module knows the contracts of the two reference models (`scrfd-letterbox-v1`,
`arcface-112-similarity-v1`) and nothing about any other model; a different model is a different
module and a different contract version. It never touches the database.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import onnxruntime as ort

from backend.infrastructure.resources.shared_memory import AttachedSegment
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    Detection,
    ExecutionProvenance,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    RepresentationResult,
)
from backend.ml.contracts.protocol import ContractError, MLErrorCode, MLOperation
from backend.ml.perception import alignment, detection
from backend.ml.worker.loop import Handler, HandlerContext, HandlerResult, WorkerError
from backend.ml.worker.onnx_session import load_session

DETECTOR = "FACE_DETECTOR"
EMBEDDER = "FACE_REPRESENTATION"
_KINDS = {DETECTOR, EMBEDDER}
_FIELDS = {
    "component_version_id",
    "kind",
    "runtime_variant_id",
    "model_path",
    "sha256",
    "provider",
    "device",
}


class ConfigError(ValueError):
    """The worker's configuration is not acceptable."""


@dataclass(frozen=True, slots=True)
class VariantConfig:
    component_version_id: str
    kind: str
    runtime_variant_id: str
    model_path: Path
    sha256: bytes
    provider: str
    device: str
    dimension: int | None  # an embedder's output length; None for a detector


def parse_config(text: str) -> tuple[VariantConfig, ...]:
    """`{"variants": [{component_version_id, kind, runtime_variant_id, model_path, sha256,
    provider, device, [dimension]}]}`: exact keys, a variant id only once, an embedder with a
    dimension and a detector without one."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(f"not valid JSON: {error.msg}") from error
    if (
        not isinstance(raw, dict)
        or set(raw) != {"variants"}
        or not isinstance(raw["variants"], list)
    ):
        raise ConfigError('expected {"variants": [...]}')
    variants: list[VariantConfig] = []
    for entry in raw["variants"]:
        if not isinstance(entry, dict) or not _FIELDS <= set(entry) <= _FIELDS | {"dimension"}:
            raise ConfigError("a variant has the wrong keys")
        strings = {name: entry[name] for name in _FIELDS}
        if not all(isinstance(v, str) and v for v in strings.values()):
            raise ConfigError("a variant's fields are non-empty strings")
        if strings["kind"] not in _KINDS:
            raise ConfigError(f"unknown component kind {strings['kind']!r}")
        try:
            digest = bytes.fromhex(strings["sha256"])
        except ValueError:
            digest = b""
        if len(digest) != 32:
            raise ConfigError("sha256 must be 64 hexadecimal characters")
        dimension = entry.get("dimension")
        if strings["kind"] == EMBEDDER:
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
                raise ConfigError("an embedder needs a positive integer dimension")
        elif dimension is not None:
            raise ConfigError("a detector has no dimension")
        variants.append(
            VariantConfig(
                component_version_id=strings["component_version_id"],
                kind=strings["kind"],
                runtime_variant_id=strings["runtime_variant_id"],
                model_path=Path(strings["model_path"]),
                sha256=digest,
                provider=strings["provider"],
                device=strings["device"],
                dimension=dimension,
            )
        )
    ids = [v.runtime_variant_id for v in variants]
    if len(set(ids)) != len(ids):
        raise ConfigError("a runtime variant id is used twice")
    return tuple(variants)


class _Components:
    """The configured variants and the sessions loaded from them so far."""

    def __init__(
        self,
        variants: tuple[VariantConfig, ...],
        loader: Callable[[Path, bytes, str], ort.InferenceSession],
    ) -> None:
        self._variants = variants
        self._loader = loader
        self._sessions: dict[str, ort.InferenceSession] = {}

    def resolve(self, request: MLRequest, kind: str) -> tuple[VariantConfig, ort.InferenceSession]:
        candidates = [
            v
            for v in self._variants
            if v.component_version_id == request.component and v.kind == kind
        ]
        wanted = request.options.get("runtime_variant_id")
        if wanted is not None:
            candidates = [v for v in candidates if v.runtime_variant_id == wanted]
        elif len(candidates) > 1:
            raise WorkerError(
                MLErrorCode.INVALID_REQUEST,
                f"{request.component} has several variants: name one in runtime_variant_id",
            )
        if not candidates:
            raise WorkerError(
                MLErrorCode.COMPONENT_NOT_AVAILABLE,
                f"no {kind} variant for component {request.component!r}"
                + ("" if wanted is None else f" and variant {wanted!r}"),
            )
        (variant,) = candidates
        session = self._sessions.get(variant.runtime_variant_id)
        if session is None:
            session = self._loader(variant.model_path, variant.sha256, variant.provider)
            self._check_shape(variant, session)
            self._sessions[variant.runtime_variant_id] = session
        return variant, session

    @staticmethod
    def _check_shape(variant: VariantConfig, session: ort.InferenceSession) -> None:
        """A model that cannot be what the configuration says is refused when it is loaded."""
        if len(session.get_inputs()) != 1:
            raise WorkerError(MLErrorCode.COMPONENT_LOAD_FAILED, "the model must take one input")
        if variant.kind == EMBEDDER:
            shape = session.get_outputs()[0].shape
            last = shape[-1] if shape else None
            if isinstance(last, int) and last != variant.dimension:
                raise WorkerError(
                    MLErrorCode.COMPONENT_LOAD_FAILED,
                    f"the model's output has {last} values, the configuration says "
                    f"{variant.dimension}",
                )
        elif len(session.get_outputs()) != 3 * len(detection.STRIDES):
            raise WorkerError(
                MLErrorCode.COMPONENT_LOAD_FAILED,
                f"the detector has {len(session.get_outputs())} outputs, "
                f"expected {3 * len(detection.STRIDES)}",
            )


def _provenance(variant: VariantConfig) -> ExecutionProvenance:
    return ExecutionProvenance(
        variant.component_version_id,
        variant.runtime_variant_id,
        variant.provider,
        variant.device,
    )


def build_handlers(
    config_text: str,
    *,
    loader: Callable[[Path, bytes, str], ort.InferenceSession] = load_session,
    detector_contract: detection.DetectorContract | None = None,
    embedder_contract: alignment.EmbedderContract | None = None,
) -> dict[MLOperation, Handler]:
    """The worker factory: the operations the configuration has a variant for."""
    variants = parse_config(config_text)
    components = _Components(variants, loader)
    detector_rules = detector_contract or detection.DetectorContract()
    embedder_rules = embedder_contract or alignment.EmbedderContract()

    def detect(request: MLRequest, context: HandlerContext) -> HandlerResult:
        variant, session = components.resolve(request, DETECTOR)
        images = cast(DetectFacesInput, request.input).images
        input_name = session.get_inputs()[0].name
        found: list[Detection] = []
        for index, descriptor in enumerate(images):
            with AttachedSegment(descriptor) as segment:
                pixels = segment.copy()
            boxed = detection.letterbox(pixels, detector_rules)
            outputs = session.run(None, {input_name: boxed.tensor})
            faces = detection.decode(
                [np.asarray(o, dtype=np.float32) for o in outputs],
                detector_rules,
                boxed.scale,
                (pixels.shape[0], pixels.shape[1]),
            )
            found.extend(
                Detection(index, number, face.box, face.score, face.landmarks)
                for number, face in enumerate(faces)
            )
        return HandlerResult(DetectFacesOutput(tuple(found)), _provenance(variant))

    def represent(request: MLRequest, context: HandlerContext) -> HandlerResult:
        variant, session = components.resolve(request, EMBEDDER)
        asked = cast(GenerateRepresentationsInput, request.input)
        assert variant.dimension is not None  # (an embedder always has one)
        input_name = session.get_inputs()[0].name
        results: list[RepresentationResult] = []
        for face in asked.faces:
            if face.landmarks is None:
                raise ContractError(
                    MLErrorCode.INVALID_INPUT, "a representation needs the face's landmarks"
                )
            with AttachedSegment(asked.images[face.input_index]) as segment:
                pixels = segment.copy()
            crop = alignment.align(pixels, face.landmarks, embedder_rules)
            raw = session.run(None, {input_name: alignment.preprocess(crop, embedder_rules)})[0]
            vector = alignment.canonical_vector(raw, variant.dimension)
            output = context.ledger.create("float32", (variant.dimension,))
            output.write(vector)
            results.append(
                RepresentationResult(
                    face.input_index,
                    face.face_index,
                    variant.dimension,
                    "float32",
                    alignment.NORMALIZATION,
                    output.descriptor,
                )
            )
        return HandlerResult(GenerateRepresentationsOutput(tuple(results)), _provenance(variant))

    handlers: dict[MLOperation, Handler] = {}
    kinds = {v.kind for v in variants}
    if DETECTOR in kinds:
        handlers[MLOperation.DETECT_FACES] = detect
    if EMBEDDER in kinds:
        handlers[MLOperation.GENERATE_REPRESENTATIONS] = represent
    return handlers
