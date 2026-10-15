"""Hard-negative sampling is explicit, deterministic, and never leaks held-out identities into enrolment."""

import json
from pathlib import Path

import pytest

from evaluation import import_labelled_dataset as importer


def _dataset(tmp_path: Path) -> tuple[dict[str, list[Path]], Path]:
    people = {}
    for name in ("Known", "Lookalike", "Unrelated", "WithoutVector"):
        folder = tmp_path / name
        folder.mkdir()
        people[name] = []
        for i in range(2):
            p = folder / f"{i}.jpg"
            p.write_bytes(f"{name}:{i}".encode())
            people[name].append(p)
    return people, tmp_path


def test_hard_negatives_rank_nearest_stranger_and_keep_known_disjoint(tmp_path: Path) -> None:
    people, source = _dataset(tmp_path)
    vectors = {
        "Known/0.jpg": [1.0, 0.0], "Known/1.jpg": [1.0, 0.0],
        "Lookalike/0.jpg": [0.99, 0.1], "Lookalike/1.jpg": [0.98, 0.2],
        "Unrelated/0.jpg": [0.0, 1.0], "Unrelated/1.jpg": [0.1, 0.99],
    }
    embedding_file = tmp_path / "embeddings.json"
    embedding_file.write_text(json.dumps({"model_digest": "test-weights", "vectors": vectors}))
    # Known cohort follows hash order, so explicitly make the nearest pair name
    # according to whichever person happens to be chosen.
    from hashlib import sha256
    known_name = min(("Known", "Lookalike", "Unrelated", "WithoutVector"),
                     key=lambda n: sha256(n.encode()).hexdigest())
    if known_name == "WithoutVector":
        with pytest.raises(SystemExit, match="no usable embeddings"):
            importer.select_hard_negatives(people, minimum=2, count=2, maximum=2,
                                           known_count=1, embeddings_path=embedding_file, source=source)
        return
    chosen, known, unknown, metadata = importer.select_hard_negatives(
        people, minimum=2, count=2, maximum=2, known_count=1,
        embeddings_path=embedding_file, source=source,
    )
    assert known == [known_name]
    assert len(unknown) == 1
    assert set(known).isdisjoint(unknown)
    assert list(chosen) == known + unknown
    assert metadata["mode"] == "hard-negatives"
    assert metadata["embedding_map_sha256"]
    again = importer.select_hard_negatives(people, minimum=2, count=2, maximum=2,
                                           known_count=1, embeddings_path=embedding_file, source=source)
    assert again[1:3] == (known, unknown)


def test_hard_negative_input_requires_provenance_and_valid_vectors(tmp_path: Path) -> None:
    people, source = _dataset(tmp_path)
    file = tmp_path / "vectors.json"
    file.write_text(json.dumps({"vectors": {}}))
    with pytest.raises(SystemExit, match="model_digest"):
        importer.select_hard_negatives(people, minimum=2, count=2, maximum=2,
                                       known_count=1, embeddings_path=file, source=source)
    with pytest.raises(SystemExit, match="known-people"):
        importer.select_hard_negatives(people, minimum=2, count=2, maximum=2,
                                       known_count=2, embeddings_path=file, source=source)
