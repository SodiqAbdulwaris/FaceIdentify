"""TST-036: importing an image as a Source (API and Contracts.md sections 5.1, 55 and 57).

Managed or referenced, an import makes a Source and an artifact and nothing else; a file that is
not a usable image leaves no trace; and a crash at any step is settled by the startup recovery that
already exists, never into a half-made Source.
"""

import hashlib
import io
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.jobs.models import Job
from backend.app.processing.models import ProcessingRun
from backend.app.sources import import_source
from backend.app.sources.artifact_storage import recover_artifacts
from backend.app.sources.import_source import (
    ImportedSource,
    ImportFileError,
    ImportFileTooLargeError,
    ImportSourceUseCase,
)
from backend.app.sources.models import (
    Artifact,
    ArtifactKind,
    ArtifactState,
    Source,
    SourceKind,
    SourceState,
    StorageMode,
)
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.media.image import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedImageError,
)
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.referenced import ReferencedFileError
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

MAX_PIXELS = 10_000
MAX_BYTES = 100_000
WIDTH, HEIGHT = 40, 30


def picture() -> np.ndarray[Any, Any]:
    rng = np.random.default_rng(3)
    return rng.integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8)


def png_bytes() -> bytes:
    out = io.BytesIO()
    Image.fromarray(picture()).save(out, "PNG")
    return out.getvalue()


def rotated_jpeg_bytes() -> bytes:
    """A 40 by 30 picture whose camera says it is on its side: shown, it is 30 by 40."""
    exif = Image.Exif()
    exif[0x0112] = 6
    out = io.BytesIO()
    Image.fromarray(picture()).save(out, "JPEG", exif=exif)
    return out.getvalue()


class Crash(BaseException):
    """The process was killed here (not an Exception, so nothing cleans up after it)."""


class World:
    def __init__(
        self,
        engine: Engine,
        roots: StorageRoots,
        store: ManagedFileStore,
        new_id: SeededUUIDs,
        clock: FrozenClock,
        photos: Path,
    ) -> None:
        self.engine = engine
        self.roots = roots
        self.store = store
        self.new_id = new_id
        self.clock = clock
        self.photos = photos
        self.factory: sessionmaker[Session] = create_session_factory(engine)

    def importer(
        self,
        *,
        max_pixels: int = MAX_PIXELS,
        max_bytes: int = MAX_BYTES,
        crash_at: str | None = None,
    ) -> ImportSourceUseCase:
        def checkpoint(step: str) -> None:
            if step == crash_at:
                raise Crash(step)

        return ImportSourceUseCase(
            UnitOfWork(self.engine, retry=TransactionRetry(3, lambda n: 0.01 * n)),
            self.store,
            new_id=self.new_id,
            clock=self.clock,
            max_pixels=max_pixels,
            max_bytes=max_bytes,
            checkpoint=checkpoint,
        )

    def file(self, name: str, data: bytes) -> Path:
        self.photos.mkdir(exist_ok=True)
        path = self.photos / name
        path.write_bytes(data)
        return path

    def count(self, model: Any) -> int:
        with self.factory() as session:
            return int(session.scalar(select(func.count()).select_from(model)) or 0)

    def source(self, source_id: Any) -> Source:
        with self.factory() as session:
            row = session.get(Source, source_id)
            assert row is not None
            return row

    def artifact(self, artifact_id: Any) -> Artifact:
        with self.factory() as session:
            row = session.get(Artifact, artifact_id)
            assert row is not None
            return row

    def nothing_was_written(self) -> bool:
        return (
            self.count(Source) == 0
            and self.count(Artifact) == 0
            and list(self.store.managed_files()) == []
            and self.store.staging_files() == []
        )


@pytest.fixture
def world(
    sqlite_engine: Engine,
    storage_roots: StorageRoots,
    file_store: ManagedFileStore,
    new_id: SeededUUIDs,
    clock: FrozenClock,
    tmp_path: Path,
) -> World:
    return World(sqlite_engine, storage_roots, file_store, new_id, clock, tmp_path / "photos")


# --- a managed import -------------------------------------------------------------------------


def test_a_managed_import_copies_the_image_and_makes_a_source(world: World) -> None:
    data = png_bytes()
    path = world.file("Holiday.png", data)

    imported = world.importer().import_managed(path)

    source = world.source(imported.source_id)
    artifact = world.artifact(imported.artifact_id)
    assert (source.kind, source.state) == (SourceKind.IMAGE, SourceState.ACTIVE)
    assert source.display_name == "Holiday"
    assert source.original_artifact_id == imported.artifact_id
    assert (source.width, source.height) == (WIDTH, HEIGHT)
    assert source.thumbnail_artifact_id is None
    assert source.current_processing_run_id is None
    assert source.revision == 1
    assert source.created_at == world.clock() == source.updated_at
    assert (artifact.kind, artifact.storage_mode) == (
        ArtifactKind.SOURCE_ORIGINAL,
        StorageMode.MANAGED,
    )
    assert artifact.state == ArtifactState.AVAILABLE
    assert artifact.sha256 == hashlib.sha256(data).digest()
    assert artifact.size_bytes == len(data)
    assert artifact.mime_type == "image/png"
    assert artifact.original_filename == "Holiday.png"
    assert artifact.storage_key is not None
    assert artifact.storage_key.startswith("originals/")
    with world.store.open(artifact.storage_key) as stored:
        assert stored.read() == data
    assert path.read_bytes() == data  # the user's file is untouched


def test_importing_is_not_processing(world: World) -> None:
    world.importer().import_managed(world.file("a.png", png_bytes()))

    assert world.count(Job) == 0
    assert world.count(ProcessingRun) == 0


def test_the_size_recorded_is_the_one_shown_after_the_orientation_is_applied(world: World) -> None:
    imported = world.importer().import_managed(world.file("rotated.jpg", rotated_jpeg_bytes()))

    source = world.source(imported.source_id)

    assert (source.width, source.height) == (HEIGHT, WIDTH)  # turned on its side
    assert world.artifact(imported.artifact_id).mime_type == "image/jpeg"


def test_the_name_may_be_chosen_and_is_trimmed(world: World) -> None:
    path = world.file("IMG_0001.png", png_bytes())

    imported = world.importer().import_managed(path, display_name="  Anna's birthday ")

    assert world.source(imported.source_id).display_name == "Anna's birthday"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_a_source_without_a_name_is_refused_before_anything_happens(
    world: World, name: str
) -> None:
    path = world.file("a.png", png_bytes())

    with pytest.raises(ValueError, match="needs a name"):
        world.importer().import_managed(path, display_name=name)
    with pytest.raises(ValueError, match="needs a name"):
        world.importer().import_referenced(path, display_name=name)

    assert world.nothing_was_written()


def test_the_name_is_checked_before_the_file_is_looked_at(world: World) -> None:
    missing = world.photos / "not-there.png"

    with pytest.raises(ValueError, match="needs a name"):  # not ImportFileError
        world.importer().import_managed(missing, display_name=" ")
    with pytest.raises(ValueError, match="needs a name"):
        world.importer().import_referenced(missing, display_name=" ")


def test_a_source_is_created_and_updated_at_one_instant(world: World) -> None:
    ticks = iter(range(1, 1000))

    def ticking() -> Any:
        return world.clock.advance(seconds=next(ticks))

    importer = world.importer()
    importer._clock = ticking  # (every call to the clock now gives a later time)

    imported = importer.import_managed(world.file("a.png", png_bytes()))

    source = world.source(imported.source_id)
    assert source.created_at == source.updated_at


def test_importing_the_same_file_twice_makes_two_sources(world: World) -> None:
    path = world.file("a.png", png_bytes())

    first = world.importer().import_managed(path)
    second = world.importer().import_managed(path)

    assert first.source_id != second.source_id
    assert first.artifact_id != second.artifact_id
    assert world.count(Source) == 2
    assert world.count(Artifact) == 2


def test_imports_made_at_the_same_time_all_succeed(world: World) -> None:
    paths = [world.file(f"p{n}.png", png_bytes()) for n in range(4)]
    done: list[ImportedSource] = []
    failures: list[BaseException] = []

    def run(path: Path) -> None:
        try:
            done.append(world.importer().import_managed(path))
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=run, args=(p,)) for p in paths]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert failures == []
    assert len({d.source_id for d in done}) == 4
    assert world.count(Source) == 4


# --- a file that is not a usable image --------------------------------------------------------

SMALL = (WIDTH * HEIGHT) - 1


@pytest.mark.parametrize(
    ("name", "data", "error"),
    [
        ("notes.txt", b"just some text", UnsupportedImageError),
        ("empty.png", b"", UnsupportedImageError),
        ("cut.png", png_bytes()[:50], CorruptImageError),
    ],
    ids=["text", "empty", "cut-short"],
)
def test_a_file_that_is_not_a_usable_image_leaves_nothing_behind(
    world: World, name: str, data: bytes, error: type[Exception]
) -> None:
    path = world.file(name, data)

    with pytest.raises(error):
        world.importer().import_managed(path)
    with pytest.raises(error):
        world.importer().import_referenced(path)

    assert world.nothing_was_written()


def test_an_image_with_too_many_pixels_is_refused(world: World) -> None:
    path = world.file("big.png", png_bytes())

    with pytest.raises(ImageTooLargeError):
        world.importer(max_pixels=SMALL).import_managed(path)
    with pytest.raises(ImageTooLargeError):
        world.importer(max_pixels=SMALL).import_referenced(path)

    assert world.nothing_was_written()


def test_exactly_the_pixel_limit_is_allowed(world: World) -> None:
    path = world.file("fits.png", png_bytes())

    imported = world.importer(max_pixels=WIDTH * HEIGHT).import_managed(path)

    assert world.source(imported.source_id).width == WIDTH


def test_a_file_with_too_many_bytes_is_refused_without_reading_all_of_it(world: World) -> None:
    data = png_bytes()
    path = world.file("heavy.png", data)

    with pytest.raises(ImportFileTooLargeError, match=f"larger than the {len(data) - 1} allowed"):
        world.importer(max_bytes=len(data) - 1).import_managed(path)
    with pytest.raises(ImportFileTooLargeError):
        world.importer(max_bytes=len(data) - 1).import_referenced(path)
    imported = world.importer(max_bytes=len(data)).import_managed(path)  # (exactly enough)

    assert world.source(imported.source_id).display_name == "heavy"


def test_a_referenced_file_that_is_too_big_is_refused_before_it_is_hashed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = world.file("huge.png", png_bytes())

    def never(*args: object) -> object:
        raise AssertionError("the file was inspected, which hashes all of it")

    monkeypatch.setattr(import_source, "inspect_referenced_file", never)

    with pytest.raises(ImportFileTooLargeError):
        world.importer(max_bytes=10).import_referenced(path)


def test_a_referenced_file_that_cannot_be_looked_at_is_an_error(world: World) -> None:
    with pytest.raises(ImportFileError, match="cannot read nothing.png"):
        world.importer().import_referenced(world.photos / "nothing.png")


@pytest.mark.parametrize("what", ["missing", "directory"])
def test_a_file_that_cannot_be_read_is_an_error_and_leaves_nothing(world: World, what: str) -> None:
    world.photos.mkdir(exist_ok=True)
    path = world.photos / "gone.png"
    if what == "directory":
        path.mkdir()

    with pytest.raises(ImportFileError, match="cannot read gone.png"):
        world.importer().import_managed(path)

    assert world.nothing_was_written()


# --- a failure while writing ------------------------------------------------------------------


def test_a_write_that_fails_is_recorded_and_leaves_no_source(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = world.file("a.png", png_bytes())

    def fail(key: str, source: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(world.store, "store", fail)

    with pytest.raises(OSError, match="disk full"):
        world.importer().import_managed(path)

    assert world.count(Source) == 0
    with world.factory() as session:
        (artifact,) = session.scalars(select(Artifact)).all()
    assert artifact.state == ArtifactState.MISSING
    assert artifact.failure_code == "WRITE_NOT_COMPLETED"
    assert "disk full" in (artifact.failure_detail or "")
    assert list(world.store.managed_files()) == []


# --- a crash at each step ---------------------------------------------------------------------


def settle(world: World) -> None:
    recover_artifacts(world.factory, world.store, clock=world.clock)


def test_a_crash_after_the_reservation_leaves_a_missing_artifact_and_no_source(
    world: World,
) -> None:
    path = world.file("a.png", png_bytes())

    with pytest.raises(Crash):
        world.importer(crash_at="reserved").import_managed(path)
    settle(world)

    assert world.count(Source) == 0
    with world.factory() as session:
        (artifact,) = session.scalars(select(Artifact)).all()
    assert (artifact.state, artifact.failure_code) == (ArtifactState.MISSING, "WRITE_NOT_COMPLETED")
    assert list(world.store.managed_files()) == []


def test_a_crash_after_the_write_leaves_an_unreferenced_artifact_and_no_source(
    world: World,
) -> None:
    data = png_bytes()
    path = world.file("a.png", data)

    with pytest.raises(Crash):
        world.importer(crash_at="stored").import_managed(path)
    settle(world)

    assert world.count(Source) == 0  # never a half-made Source
    with world.factory() as session:
        (artifact,) = session.scalars(select(Artifact)).all()
    assert artifact.state == ArtifactState.AVAILABLE  # the bytes are whole: recovery finishes it
    assert artifact.sha256 == hashlib.sha256(data).digest()
    assert artifact.storage_key is not None
    assert world.store.digest(artifact.storage_key) is not None


def test_a_crash_after_the_commit_changes_nothing(world: World) -> None:
    path = world.file("a.png", png_bytes())

    with pytest.raises(Crash):
        world.importer(crash_at="committed").import_managed(path)
    settle(world)

    assert world.count(Source) == 1
    with world.factory() as session:
        (artifact,) = session.scalars(select(Artifact)).all()
    assert artifact.state == ArtifactState.AVAILABLE


def test_recovery_is_idempotent_after_an_interrupted_import(world: World) -> None:
    path = world.file("a.png", png_bytes())
    with pytest.raises(Crash):
        world.importer(crash_at="stored").import_managed(path)
    settle(world)

    again = recover_artifacts(world.factory, world.store, clock=world.clock)

    assert (again.finalized, again.write_not_completed, again.staging_removed) == ([], [], [])


# --- a referenced import ----------------------------------------------------------------------


def test_a_referenced_import_records_the_file_and_copies_nothing(world: World) -> None:
    data = png_bytes()
    path = world.file("Mine.png", data)

    imported = world.importer().import_referenced(path)

    source = world.source(imported.source_id)
    artifact = world.artifact(imported.artifact_id)
    assert (source.kind, source.display_name) == (SourceKind.IMAGE, "Mine")
    assert (source.width, source.height) == (WIDTH, HEIGHT)
    assert (artifact.kind, artifact.storage_mode) == (
        ArtifactKind.SOURCE_ORIGINAL,
        StorageMode.REFERENCED,
    )
    assert artifact.state == ArtifactState.AVAILABLE
    assert artifact.external_path == str(path.resolve())
    assert artifact.storage_key is None
    assert artifact.sha256 == hashlib.sha256(data).digest()
    assert artifact.mime_type == "image/png"
    assert list(world.store.managed_files()) == []  # nothing was copied
    assert path.read_bytes() == data  # and the user's file was not touched


def test_a_referenced_path_must_be_absolute_and_outside_the_applications_storage(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = world.roots.library_root / "originals" / "x.png"
    inside.write_bytes(png_bytes())
    world.file("relative.png", png_bytes())
    monkeypatch.chdir(world.photos)  # so that a relative path names a file that exists

    with pytest.raises(ReferencedFileError, match="absolute"):
        world.importer().import_referenced(Path("relative.png"))
    with pytest.raises(ReferencedFileError, match="own storage"):
        world.importer().import_referenced(inside)

    assert world.count(Source) == 0
    assert world.count(Artifact) == 0


def test_a_referenced_file_that_changes_while_it_is_read_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = world.file("moving.png", png_bytes())
    real = ImportSourceUseCase._read

    def read_after_a_change(self: ImportSourceUseCase, target: Path) -> bytes:
        path.write_bytes(bytes(reversed(png_bytes())))  # same length, other bytes
        return real(self, target)

    monkeypatch.setattr(ImportSourceUseCase, "_read", read_after_a_change)

    with pytest.raises(ReferencedFileError, match="changed while it was being read"):
        world.importer().import_referenced(path)

    assert world.count(Source) == 0
    assert world.count(Artifact) == 0


def test_the_bytes_that_are_decoded_are_the_bytes_that_are_stored(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = png_bytes()
    path = world.file("swap.png", good)
    real = ImportSourceUseCase._read

    def read_then_swap(self: ImportSourceUseCase, target: Path) -> bytes:
        data = real(self, target)
        target.write_bytes(b"replaced by something that is not an image")  # after it was read
        return data

    monkeypatch.setattr(ImportSourceUseCase, "_read", read_then_swap)

    imported = world.importer().import_managed(path)

    artifact = world.artifact(imported.artifact_id)
    assert artifact.sha256 == hashlib.sha256(good).digest()  # what was validated, not the swap
    assert artifact.storage_key is not None
    with world.store.open(artifact.storage_key) as stored:
        assert stored.read() == good
