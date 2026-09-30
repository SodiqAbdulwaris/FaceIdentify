"""The per-space USearch index on real USearch and real files (M2: TST-027; persistence §23).

One index per RepresentationSpace, a manifest, atomic generations, and quarantine plus rebuild of
anything missing, corrupt, mismatched or unsupported. USearch only ever yields candidate keys;
nothing here decides identity.
"""

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from backend.infrastructure.indexing.representation_index import (
    INDEX_FORMAT_VERSION,
    MANIFEST_NAME,
    Candidate,
    IndexManifest,
    IndexUnusableError,
    RepresentationIndex,
    open_or_rebuild,
    quarantine,
)
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.persistence import AppDirs

NDIM = 8
METRIC = "cos"


@pytest.fixture
def space() -> uuid.UUID:
    return uuid.UUID(int=1)


@pytest.fixture
def directory(app_dirs: AppDirs, space: uuid.UUID) -> Path:
    return app_dirs.indexes / space.hex


@pytest.fixture
def vectors(np_rng: np.random.Generator) -> dict[int, NDArray[np.float32]]:
    """Unit vectors under explicit keys, including ones larger than 32 bits."""
    raw = np_rng.standard_normal((6, NDIM)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return dict(zip([1, 2, 3, 40, 2**40, 2**63 + 5], raw, strict=True))


def build(
    directory: Path, space: uuid.UUID, entries: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> RepresentationIndex:  # fmt: skip
    return RepresentationIndex.build(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
        entries=entries.items(), clock=clock, new_id=new_id,
    )  # fmt: skip


def reopen(directory: Path, space: uuid.UUID) -> RepresentationIndex:
    return RepresentationIndex.open(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC
    )


def unusable(directory: Path, space: uuid.UUID, **overrides: object) -> str:
    """Open and return the reason it is unusable."""
    arguments: dict[str, object] = dict(representation_space_id=space, ndim=NDIM, metric=METRIC)
    with pytest.raises(IndexUnusableError) as caught:
        RepresentationIndex.open(directory, **(arguments | overrides))  # type: ignore[arg-type]
    return str(caught.value)


def rewrite_manifest(directory: Path, **changes: object) -> None:
    path = directory / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(manifest | changes), encoding="utf-8")


# --- operations on real USearch --------------------------------------------------------------


def test_search_returns_the_nearest_keys_first(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)

    for key, vector in vectors.items():
        hits = index.search(vector, 3)
        assert hits[0].key == key
        assert hits[0].distance == pytest.approx(0.0, abs=1e-5)
        assert [hit.distance for hit in hits] == sorted(hit.distance for hit in hits)
        assert all(isinstance(hit, Candidate) for hit in hits)
    assert len(index) == len(vectors)


def test_asking_for_more_than_exists_returns_what_exists(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)

    assert len(index.search(vectors[1], 100)) == len(vectors)


def test_an_empty_index_finds_nothing_and_can_be_persisted(
    directory: Path, space: uuid.UUID, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    index = build(directory, space, {}, clock, new_id)

    assert index.search(np.ones(NDIM, dtype=np.float32), 5) == []
    assert len(reopen(directory, space)) == 0


def test_adding_and_removing_are_idempotent(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]]
) -> None:
    index = RepresentationIndex.empty(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC
    )

    assert index.add(7, vectors[1]) is True
    assert index.add(7, vectors[1]) is False  # a replayed durable operation changes nothing
    assert (len(index), index.contains(7)) == (1, True)
    assert index.remove(7) is True
    assert index.remove(7) is False
    assert index.remove(12345) is False  # never present
    assert (len(index), index.contains(7)) == (0, False)


def test_a_removed_key_is_no_longer_a_candidate(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)

    index.remove(3)

    assert 3 not in [hit.key for hit in index.search(vectors[3], len(vectors))]


@pytest.mark.parametrize("key", [-1, 2**64, True])
def test_a_key_must_be_an_unsigned_64_bit_integer(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]], key: int
) -> None:
    index = RepresentationIndex.empty(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC
    )
    operations: list[Callable[[], object]] = [
        lambda: index.add(key, vectors[1]),
        lambda: index.remove(key),
        lambda: index.contains(key),
    ]
    for operation in operations:
        with pytest.raises(ValueError, match="unsigned 64-bit"):
            operation()


@pytest.mark.parametrize(
    ("vector", "message"),
    [
        (np.ones(NDIM + 1, dtype=np.float32), "dimensions"),
        (np.ones((2, NDIM), dtype=np.float32), "dimensions"),
        (np.ones((1, NDIM), dtype=np.float32), "dimensions"),  # the right size, the wrong shape
        (np.array([np.nan] + [0.0] * (NDIM - 1), dtype=np.float32), "finite"),
        (np.array([np.inf] + [0.0] * (NDIM - 1), dtype=np.float32), "finite"),
    ],
    ids=["too-long", "matrix", "row-matrix", "nan", "infinity"],
)
def test_a_vector_must_have_the_spaces_dimension_and_be_finite(
    directory: Path, space: uuid.UUID, vector: NDArray[np.float32], message: str
) -> None:
    index = RepresentationIndex.empty(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC
    )
    index.add(1, np.ones(NDIM, dtype=np.float32))

    with pytest.raises(ValueError, match=message):
        index.add(2, vector)
    with pytest.raises(ValueError, match=message):
        index.search(vector, 1)
    assert len(index) == 1


def test_k_must_be_positive(directory: Path, space: uuid.UUID) -> None:
    index = RepresentationIndex.empty(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC
    )
    with pytest.raises(ValueError, match="at least 1"):
        index.search(np.ones(NDIM, dtype=np.float32), 0)


def test_building_from_duplicate_keys_is_refused(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    with pytest.raises(ValueError, match="appears twice"):
        RepresentationIndex.build(
            directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
            entries=[(1, vectors[1]), (1, vectors[2])], clock=clock, new_id=new_id,
        )  # fmt: skip


# --- persistence -----------------------------------------------------------------------------


def test_a_persisted_index_reopens_with_the_same_content_and_manifest(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    built = build(directory, space, vectors, clock, new_id)
    manifest = built.manifest
    assert manifest is not None

    opened = reopen(directory, space)

    assert opened.manifest == manifest
    assert (manifest.index_format_version, manifest.representation_space_id) == (
        INDEX_FORMAT_VERSION, space,
    )  # fmt: skip
    assert (manifest.ndim, manifest.metric, manifest.count) == (NDIM, METRIC, len(vectors))
    assert manifest.built_at == clock()
    assert manifest.index_file == f"index.{manifest.generation_id.hex}.usearch"
    assert manifest.size_bytes == (directory / manifest.index_file).stat().st_size
    for key, vector in vectors.items():
        assert opened.contains(key)
        assert opened.search(vector, 1)[0].key == key


def test_the_manifest_is_the_documented_json(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)

    raw = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))

    assert {"index_format_version", "representation_space_id", "generation_id", "built_at"} <= set(
        raw
    )
    assert IndexManifest.from_json(json.dumps(raw)).to_json() == json.dumps(raw, indent=2)


def test_each_persist_is_a_new_generation_and_removes_the_old_file(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    first = index.manifest
    assert first is not None
    index.remove(1)
    clock.advance(hours=1)

    second = index.persist(clock=clock, new_id=new_id)

    assert second.generation_id != first.generation_id
    assert second.built_at > first.built_at
    assert second.count == len(vectors) - 1
    assert sorted(p.name for p in directory.iterdir()) == sorted([MANIFEST_NAME, second.index_file])
    assert not reopen(directory, space).contains(1)


def test_a_crash_before_the_manifest_is_replaced_leaves_the_old_generation_live(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    live = index.manifest
    assert live is not None
    index.remove(1)

    def crash(*_: object, **__: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="power cut"):
        index.persist(clock=clock, new_id=new_id)
    monkeypatch.undo()

    # The half-finished generation's file and staged manifest are on disk, but nothing names them.
    leftovers = {p.name for p in directory.iterdir()} - {MANIFEST_NAME, live.index_file}
    assert len(leftovers) == 2
    opened = reopen(directory, space)
    assert opened.manifest == live
    assert opened.contains(1)  # the removal was never persisted: the old generation is intact
    assert {p.name for p in directory.iterdir()} == {MANIFEST_NAME, live.index_file}


def test_opening_removes_only_files_it_owns_that_no_manifest_names(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    stale = directory / f"index.{uuid.uuid4().hex}.usearch"
    stale.write_bytes(b"a superseded generation")
    foreign = directory / "notes.txt"
    foreign.write_text("not ours")
    lookalike = directory / "index.not-a-generation.usearch"
    lookalike.write_bytes(b"not ours either")

    reopen(directory, space)

    assert not stale.exists()
    assert foreign.read_text() == "not ours"
    assert lookalike.read_bytes() == b"not ours either"


# --- what makes a persisted index unusable ---------------------------------------------------


def test_no_manifest(directory: Path, space: uuid.UUID) -> None:
    directory.mkdir(parents=True)
    assert unusable(directory, space) == "no manifest"


def test_no_directory_at_all(directory: Path, space: uuid.UUID) -> None:
    assert unusable(directory, space) == "no manifest"


@pytest.mark.parametrize(
    "content",
    [b"", b"{not json", b'["a list"]', b"\xff\xfe\x00 not utf-8", b"{}"],
    ids=["empty", "not-json", "wrong-shape", "not-utf8", "no-fields"],
)
def test_an_unreadable_manifest(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, content: bytes,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    (directory / MANIFEST_NAME).write_bytes(content)

    assert "manifest" in unusable(directory, space)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("representation_space_id", "not-a-uuid"),
        ("generation_id", 12),
        ("built_at", "yesterday"),
        ("ndim", "8"),
        ("ndim", True),
        ("count", None),
        ("index_file", 5),
        ("metric", ["cos"]),
    ],
)
def test_a_manifest_with_a_badly_typed_field(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, field: str, value: object,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    rewrite_manifest(directory, **{field: value})

    assert "manifest is not readable" in unusable(directory, space)


def test_an_unsupported_format_version(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    rewrite_manifest(directory, index_format_version=INDEX_FORMAT_VERSION + 1)

    assert "unsupported index format" in unusable(directory, space)


def test_another_spaces_index_is_never_used(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)

    assert "belongs to space" in unusable(directory, uuid.UUID(int=2))


@pytest.mark.parametrize(("ndim", "metric"), [(NDIM + 1, METRIC), (NDIM, "l2sq")])
def test_a_different_dimension_or_metric(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, ndim: int, metric: str,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)

    reason = unusable(directory, space, ndim=ndim, metric=metric)
    assert reason == f"index is {NDIM}-dimensional {METRIC}, expected {ndim}-dimensional {metric}"


@pytest.mark.parametrize("name", ["../escape.usearch", "index.usearch", "C:/index.usearch", ""])
def test_a_manifest_naming_an_unexpected_file(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, name: str,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    rewrite_manifest(directory, index_file=name)

    assert "unexpected file" in unusable(directory, space)


def test_a_missing_index_file(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    (directory / index.manifest.index_file).unlink()

    assert "is missing" in unusable(directory, space)


def test_an_index_file_of_the_wrong_size(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    path = directory / index.manifest.index_file
    path.write_bytes(path.read_bytes()[:-10])

    assert "bytes, the manifest recorded" in unusable(directory, space)


def test_an_index_file_that_is_garbage_of_the_right_size(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    path = directory / index.manifest.index_file
    path.write_bytes(b"\x00" * index.manifest.size_bytes)

    assert "cannot be loaded" in unusable(directory, space)


def test_an_index_file_from_another_generation_does_not_match_the_manifest(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    """A file that loads fine but holds a different number of entries than the manifest recorded."""
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    rewrite_manifest(directory, count=index.manifest.count + 1)

    assert "entries, the manifest recorded" in unusable(directory, space)


def test_a_file_of_another_dimension_is_caught_even_though_usearch_adopts_it(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    """`Index.load` silently adopts the file's own dimension: the manifest cannot be trusted."""
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    other = RepresentationIndex.empty(
        directory / "other", representation_space_id=space, ndim=4, metric=METRIC
    )
    for key in vectors:
        other.add(key, np.ones(4, dtype=np.float32))
    other.persist(clock=clock, new_id=new_id)
    assert other.manifest is not None
    wrong = (directory / "other" / other.manifest.index_file).read_bytes()
    path = directory / index.manifest.index_file
    path.write_bytes(wrong)
    rewrite_manifest(directory, size_bytes=len(wrong))

    assert "4-dimensional, expected 8" in unusable(directory, space)


def test_a_manifest_file_that_cannot_be_read(directory: Path, space: uuid.UUID) -> None:
    directory.mkdir(parents=True)
    (directory / MANIFEST_NAME).mkdir()  # a directory where the file should be

    assert "cannot be read" in unusable(directory, space)


# --- quarantine and rebuild ------------------------------------------------------------------


def test_quarantine_moves_only_the_indexs_own_files_and_keeps_them(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    index = build(directory, space, vectors, clock, new_id)
    assert index.manifest is not None
    (directory / "notes.txt").write_text("not ours")

    first = quarantine(directory)
    assert first == directory / "quarantine" / "1"
    assert sorted(p.name for p in first.iterdir()) == sorted(
        [MANIFEST_NAME, index.manifest.index_file]
    )
    assert [p.name for p in directory.iterdir() if p.name != "quarantine"] == ["notes.txt"]

    build(directory, space, vectors, clock, new_id)
    assert (
        quarantine(directory) == directory / "quarantine" / "2"
    )  # never overwrites an earlier one


def test_quarantining_nothing_is_a_no_op(directory: Path, tmp_path: Path) -> None:
    assert quarantine(directory) is None  # no directory
    directory.mkdir(parents=True)
    (directory / "notes.txt").write_text("x")
    assert quarantine(directory) is None  # nothing of the index's
    assert not (directory / "quarantine").exists()


def entries_of(
    vectors: dict[int, NDArray[np.float32]],
) -> Callable[[], list[tuple[int, NDArray[np.float32]]]]:
    return lambda: list(vectors.items())


def test_a_sound_index_is_used_without_touching_sqlite(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)

    def forbidden() -> list[tuple[int, NDArray[np.float32]]]:
        raise AssertionError("entries are only streamed when a rebuild is needed")

    result = open_or_rebuild(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
        entries=forbidden, clock=clock, new_id=new_id,
    )  # fmt: skip

    assert (result.rebuilt, result.reason) == (False, None)
    assert len(result.index) == len(vectors)


def test_the_first_build_is_not_a_failure_and_quarantines_nothing(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    result = open_or_rebuild(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
        entries=entries_of(vectors), clock=clock, new_id=new_id,
    )  # fmt: skip

    assert (result.rebuilt, result.reason) == (True, None)
    assert len(result.index) == len(vectors)
    assert not (directory / "quarantine").exists()
    assert len(reopen(directory, space)) == len(vectors)


@pytest.mark.parametrize("damage", ["garbage-file", "missing-file", "manifest-gone", "other-space"])
def test_an_unusable_index_is_quarantined_and_rebuilt_from_the_entries(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs, damage: str,
) -> None:  # fmt: skip
    old = build(directory, space, {1: vectors[1]}, clock, new_id)  # stale: holds one entry
    assert old.manifest is not None
    if damage == "garbage-file":
        (directory / old.manifest.index_file).write_bytes(b"\x00" * old.manifest.size_bytes)
    elif damage == "missing-file":
        (directory / old.manifest.index_file).unlink()
    elif damage == "manifest-gone":
        (directory / MANIFEST_NAME).unlink()
    else:
        rewrite_manifest(directory, representation_space_id=str(uuid.UUID(int=99)))
    clock.advance(hours=1)

    result = open_or_rebuild(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
        entries=entries_of(vectors), clock=clock, new_id=new_id,
    )  # fmt: skip

    assert result.rebuilt is True
    assert result.reason is not None
    assert len(result.index) == len(vectors)
    assert result.index.manifest is not None
    assert result.index.manifest.generation_id != old.manifest.generation_id
    assert result.index.manifest.built_at == clock()
    assert (directory / "quarantine" / "1").is_dir()
    for key, vector in vectors.items():
        assert result.index.search(vector, 1)[0].key == key
    assert len(reopen(directory, space)) == len(vectors)  # and the rebuilt one persisted


def test_rebuilding_from_no_entries_gives_a_usable_empty_index(
    directory: Path, space: uuid.UUID, vectors: dict[int, NDArray[np.float32]],
    clock: FrozenClock, new_id: SeededUUIDs,
) -> None:  # fmt: skip
    build(directory, space, vectors, clock, new_id)
    (directory / MANIFEST_NAME).write_text("{broken")

    result = open_or_rebuild(
        directory, representation_space_id=space, ndim=NDIM, metric=METRIC,
        entries=lambda: [], clock=clock, new_id=new_id,
    )  # fmt: skip

    assert (result.rebuilt, len(result.index)) == (True, 0)
