"""The first durable processing command: snapshot, run and job are one transaction."""

import uuid
from copy import deepcopy
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from backend.app.jobs.models import Job
from backend.app.memory.models import RepresentationSpace
from backend.app.processing.configuration import ProcessingConfigurationError, ProcessingRequestV1
from backend.app.processing.models import ProcessingConfigurationSnapshot, ProcessingRun
from backend.app.processing.process_source import ProcessSourceError, ProcessSourceUseCase
from backend.app.runtime.models import (
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from tests.factories.models import ModelFactory
from tests.fixtures.processing_request import processing_request


def use_case(engine: Engine, build: ModelFactory, wakes: list[None]) -> ProcessSourceUseCase:
    return ProcessSourceUseCase(
        UnitOfWork(engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        new_id=build.new_id,
        clock=build.clock,
        wake_scheduler=lambda: wakes.append(None),
    )


def test_active_image_becomes_one_snapshot_run_and_queued_job(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    source = build.source()
    request = processing_request(build)
    build.session.commit()
    wakes: list[None] = []

    scheduled = use_case(sqlite_engine, build, wakes).process(
        source.id,
        processing_request=request,
        priority="INTERACTIVE",
        created_by_user_action="process-button",
    )

    with Session(sqlite_engine) as session:
        run = session.get(ProcessingRun, scheduled.processing_run_id)
        job = session.get(Job, scheduled.job_id)
        assert run is not None
        assert (run.source_id, run.state, run.requested_at) == (source.id, "PENDING", build.clock())
        snapshot = session.get(ProcessingConfigurationSnapshot, run.configuration_snapshot_id)
        assert snapshot is not None
        assert snapshot.canonical_json["runtime_policy"] == {
            "schema_version": 1,
            "providers": ["CPUExecutionProvider"],
            "allow_fallback": False,
        }
        assert (
            snapshot.canonical_json["detector"]["component_version"]["id"]
            == request["detector"]["component_version_id"]
        )
        assert snapshot.canonical_json["embedder"]["export"]["sha256"] == "65" * 32
        assert job is not None
        assert (job.type, job.state, job.priority, job.processing_run_id) == (
            "PROCESS_SOURCE",
            "QUEUED",
            "INTERACTIVE",
            run.id,
        )
    assert wakes == [None]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda request: request.pop("command_options"),
        lambda request: request.__setitem__("schema_version", 2),
        lambda request: request.__setitem__("schema_version", True),
        lambda request: request.__setitem__("schema_version", 1.0),
        lambda request: request["detector"].__setitem__("component_version_id", 1),
        lambda request: request["detector"].__setitem__("component_version_id", "not-a-uuid"),
        lambda request: request["calibration"].update(
            {"mode": "UNCALIBRATED", "profile_id": str(uuid.uuid4())}
        ),
        lambda request: request["calibration"].__setitem__("mode", "UNKNOWN"),
        lambda request: request["runtime_policy"].__setitem__("providers", []),
        lambda request: request["runtime_policy"].__setitem__("schema_version", 2),
        lambda request: request["runtime_policy"].__setitem__("schema_version", True),
        lambda request: request["runtime_policy"].__setitem__("allow_fallback", 1),
        lambda request: request["crop_policy"].__setitem__("schema_version", 2),
        lambda request: request["quality_policy"].__setitem__("schema_version", 1.0),
        lambda request: request["decision_policy"].__setitem__("min_detection_score", True),
        lambda request: request["decision_policy"].__setitem__("schema_version", 2),
        lambda request: request["command_options"].__setitem__("schema_version", True),
        lambda request: request["decision_policy"].__setitem__("match_threshold", 2.01),
        lambda request: request["decision_policy"].__setitem__("version", ""),
    ],
)
def test_processing_request_v1_is_strict_and_fails_closed(build: ModelFactory, mutate: Any) -> None:
    request = processing_request(build)
    invalid = deepcopy(request)
    replacement = mutate(invalid)

    with pytest.raises(ProcessingConfigurationError):
        ProcessingRequestV1.parse(invalid if replacement is None else replacement)


def test_a_decision_policy_may_turn_automatic_matching_off_with_an_unreachable_threshold(
    build: ModelFactory,
) -> None:
    request = processing_request(build)
    request["decision_policy"]["match_threshold"] = 2.0  # (above 1: no cosine reaches it)

    parsed = ProcessingRequestV1.parse(request)

    assert parsed.decision_policy["match_threshold"] == 2.0


def test_processing_request_v1_requires_an_object() -> None:
    with pytest.raises(ProcessingConfigurationError, match="must be an object"):
        ProcessingRequestV1.parse(None)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_kind",
        "wrong_export",
        "inactive_space",
        "unmapped_export",
        "missing_detector_variant",
        "unsupported_provider",
        "unusable_detector_variant",
        "unusable_variant",
    ],
)
def test_processing_request_rejects_incompatible_catalog_before_any_rows(
    sqlite_engine: Engine, build: ModelFactory, fault: str
) -> None:
    source = build.source()
    request = processing_request(build)
    if fault == "wrong_kind":
        request["detector"] = request["embedder"]
    elif fault == "wrong_export":
        request["detector"]["model_export_id"] = request["embedder"]["model_export_id"]
    elif fault == "inactive_space":
        space = build.session.get(
            RepresentationSpace, uuid.UUID(request["representation_space_id"])
        )
        assert space is not None
        space.state = "DEPRECATED"
    else:
        if fault == "unmapped_export":
            build.session.execute(delete(RuntimeVariantRepresentationSpace))
        elif fault == "missing_detector_variant":
            build.session.execute(
                delete(RuntimeVariant).where(
                    RuntimeVariant.model_export_id
                    == uuid.UUID(request["detector"]["model_export_id"])
                )
            )
        elif fault == "unsupported_provider":
            request["runtime_policy"]["providers"] = ["CUDAExecutionProvider"]
        elif fault == "unusable_detector_variant":
            detector_variant = build.session.scalar(
                select(RuntimeVariant).where(
                    RuntimeVariant.model_export_id
                    == uuid.UUID(request["detector"]["model_export_id"])
                )
            )
            assert detector_variant is not None
            detector_variant.state = "RETIRED"
        else:
            variant = build.session.scalar(
                select(RuntimeVariant).where(
                    RuntimeVariant.model_export_id
                    == uuid.UUID(request["embedder"]["model_export_id"])
                )
            )
            assert variant is not None
            variant.state = "RETIRED"
    build.session.commit()
    wakes: list[None] = []

    with pytest.raises(ProcessSourceError):
        use_case(sqlite_engine, build, wakes).process(
            source.id,
            processing_request=request,
            priority="NORMAL",
            created_by_user_action=None,
        )

    with Session(sqlite_engine) as session:
        assert session.query(ProcessingConfigurationSnapshot).count() == 0
        assert session.query(ProcessingRun).count() == 0
        assert session.query(Job).count() == 0
    assert wakes == []


def test_profile_calibration_is_rejected_until_m3_implements_it(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    source = build.source()
    request = processing_request(build)
    request["calibration"] = {
        "mode": "PROFILE",
        "interpretation": "COSINE_CALIBRATED",
        "profile_id": str(build.new_id()),
    }
    build.session.commit()

    with pytest.raises(ProcessSourceError, match="not supported"):
        use_case(sqlite_engine, build, []).process(
            source.id,
            processing_request=request,
            priority="NORMAL",
            created_by_user_action=None,
        )

    with Session(sqlite_engine) as session:
        assert session.query(ProcessingConfigurationSnapshot).count() == 0
        assert session.query(ProcessingRun).count() == 0
        assert session.query(Job).count() == 0


@pytest.mark.parametrize(
    ("source_state", "artifact_state"), [("RECYCLED", "AVAILABLE"), ("ACTIVE", "MISSING")]
)
def test_unprocessable_source_leaves_no_snapshot_run_or_job(
    sqlite_engine: Engine, build: ModelFactory, source_state: str, artifact_state: str
) -> None:
    artifact = build.artifact(state=artifact_state)
    source = build.source(state=source_state, original_artifact_id=artifact.id)
    build.session.commit()
    wakes: list[None] = []

    with pytest.raises(ProcessSourceError):
        use_case(sqlite_engine, build, wakes).process(
            source.id,
            processing_request={},
            priority="NORMAL",
            created_by_user_action=None,
        )

    with Session(sqlite_engine) as session:
        assert session.query(ProcessingConfigurationSnapshot).count() == 0
        assert session.query(ProcessingRun).count() == 0
        assert session.query(Job).count() == 0
    assert wakes == []


@pytest.mark.parametrize(
    ("source_kind", "expected"), [(None, "does not exist"), ("VIDEO", "not an image")]
)
def test_missing_or_non_image_source_leaves_no_processing_rows(
    sqlite_engine: Engine, build: ModelFactory, source_kind: str | None, expected: str
) -> None:
    source_id = uuid.uuid4() if source_kind is None else build.source(kind=source_kind).id
    build.session.commit()
    wakes: list[None] = []

    with pytest.raises(ProcessSourceError, match=expected):
        use_case(sqlite_engine, build, wakes).process(
            source_id,
            processing_request={},
            priority="NORMAL",
            created_by_user_action=None,
        )

    with Session(sqlite_engine) as session:
        assert session.query(ProcessingConfigurationSnapshot).count() == 0
        assert session.query(ProcessingRun).count() == 0
        assert session.query(Job).count() == 0
    assert wakes == []


@pytest.mark.parametrize(
    ("request_version", "priority", "expected"),
    [(0, "NORMAL", "schema_version"), (1, "URGENT", "not a job priority")],
)
def test_invalid_request_metadata_leaves_no_processing_rows(
    sqlite_engine: Engine,
    build: ModelFactory,
    request_version: int,
    priority: str,
    expected: str,
) -> None:
    source = build.source()
    request = processing_request(build)
    request["schema_version"] = request_version
    build.session.commit()
    wakes: list[None] = []

    with pytest.raises(ProcessSourceError, match=expected):
        use_case(sqlite_engine, build, wakes).process(
            source.id,
            processing_request=request,
            priority=priority,
            created_by_user_action=None,
        )

    with Session(sqlite_engine) as session:
        assert session.query(ProcessingConfigurationSnapshot).count() == 0
        assert session.query(ProcessingRun).count() == 0
        assert session.query(Job).count() == 0
    assert wakes == []


def test_a_lost_scheduler_wake_does_not_lose_the_committed_job(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    source = build.source()
    request = processing_request(build)
    build.session.commit()

    def unavailable() -> None:
        raise RuntimeError("scheduler unavailable")

    scheduled = ProcessSourceUseCase(
        UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        new_id=build.new_id,
        clock=build.clock,
        wake_scheduler=unavailable,
    ).process(
        source.id,
        processing_request=request,
        priority="NORMAL",
        created_by_user_action=None,
    )

    with Session(sqlite_engine) as session:
        assert session.get(Job, scheduled.job_id) is not None
