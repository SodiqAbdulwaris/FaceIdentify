"""Forgetting an identity on a real library: SQLite, USearch, files and restarts (M5 step 4c;
TST-059, SEC-006; identity-and-memory-model-v1.md §46-§49; API and Contracts.md §8.3 and §116).

The story, with unit-length 4-d vectors: image 1 shows face A (identity I1), image 2 a different
face C (identity I2). Forgetting I2 removes its vectors from the row, every index file and the log,
ends its Person link and stops its faces from resolving to anyone; the media, the other identity and
the Person's name stay, and nothing reconnects a later image of C to the forgotten identity.
"""

import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.identities.forget import (
    ForgetIdentityUseCase,
    IdentityNotFoundError,
    PersonNotFoundError,
)
from backend.app.identities.models import Evidence, Identity
from backend.app.identities.use_cases import StaleRevisionError
from backend.app.memory.models import IndexOperation, Observation, Occurrence, Representation
from backend.app.people.models import AssociationState, IdentityPersonAssociation, Person
from backend.app.people.use_cases import assign_identity_to_person, name_identity
from backend.app.sources.models import Artifact, Source
from tests.factories.models import ModelFactory
from tests.fixtures.pipeline import Pipeline, unit
from tests.fixtures.story import (
    A,
    C,
    SimulatedCrash,
    add_face_crop,
    files_containing,
    only,
    process,
)


def forgetting(lib: Pipeline) -> ForgetIdentityUseCase:
    return ForgetIdentityUseCase(
        lib.lib.unit_of_work,
        lib.lib.eraser,
        lib.lib.store,
        clock=lib.clock,
        new_id=lib.new_id,
    )


def identity_of(lib: Pipeline, source_id: uuid.UUID) -> uuid.UUID:
    [identity_id] = only(
        lib, select(Occurrence.identity_id).where(Occurrence.source_id == source_id)
    )
    return uuid.UUID(str(identity_id))


def named(lib: Pipeline, identity_id: uuid.UUID, name: str = "Ada") -> uuid.UUID:
    person, _ = lib.lib.unit_of_work.write(
        lambda s: name_identity(s, identity_id, name, new_id=lib.new_id, clock=lib.clock)
    )
    return person.id


def state_of(lib: Pipeline, identity_id: uuid.UUID) -> str:
    return str(only(lib, select(Identity.state).where(Identity.id == identity_id))[0])


# --- what forgetting removes -------------------------------------------------------------------


def test_forgetting_removes_the_vectors_from_every_place_and_keeps_the_rest(opened: Any) -> None:
    with opened() as lib:
        keep_source, _ = process(lib, A)
        gone_source, _ = process(lib, C)
        keep, gone = identity_of(lib, keep_source), identity_of(lib, gone_source)
        assert files_containing(lib, C)
        space = lib.space_id

        report = forgetting(lib).forget(gone)

        assert (report.complete, report.changed) == (True, True)
        assert state_of(lib, gone) == "FORGOTTEN"
        [forgotten] = only(lib, select(Identity).where(Identity.id == gone))
        assert forgotten.forgotten_at is not None
        assert forgotten.representative_observation_id is None
        # the vectors: not in a row, not in the log, not in any index file
        assert {
            r.state
            for r in only(lib, select(Representation).where(Representation.identity_id == gone))
        } == {"ERASED"}
        assert files_containing(lib, C) == []
        assert len(lib.global_index(space)) == 1
        assert files_containing(lib, A)  # the other identity is untouched
        assert state_of(lib, keep) == "ACTIVE"
        # the media stays: the source, the face's box, but no occurrence resolves to anyone
        assert only(lib, select(Source.state).where(Source.id == gone_source)) == ["ACTIVE"]
        assert len(only(lib, select(Observation).where(Observation.source_id == gone_source))) == 1
        assert {
            o.state
            for o in only(lib, select(Occurrence).where(Occurrence.source_id == gone_source))
        } == {"DELETED"}
        # history keeps that it happened, with ids only
        [entry] = only(lib, select(Evidence).where(Evidence.kind == "IDENTITY_FORGOTTEN"))
        assert entry.subject_identity_id == gone
        assert set(entry.payload_json) == {"representation_ids", "occurrence_ids"}


def test_a_named_person_keeps_their_name_but_loses_the_link_and_the_faces(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        person = named(lib, identity)

        assert forgetting(lib).forget(identity).complete

        [kept] = only(lib, select(Person))
        assert (kept.id, kept.display_name, kept.state) == (person, "Ada", "ACTIVE")
        [link] = only(lib, select(IdentityPersonAssociation))
        assert link.state == AssociationState.REMOVED
        kinds = sorted(only(lib, select(Evidence.kind)))
        assert "IDENTITY_REMOVED_FROM_PERSON" in kinds
        [forgotten] = only(lib, select(Evidence).where(Evidence.kind == "IDENTITY_FORGOTTEN"))
        assert forgotten.subject_person_id == person
        assert files_containing(lib, C) == []


def test_forgetting_a_person_forgets_each_of_their_identities_and_nothing_else(
    opened: Any,
) -> None:
    with opened() as lib:
        first_source, _ = process(lib, C)
        second_source, _ = process(lib, unit(0, 0, 1, 0))
        other_source, _ = process(lib, A)
        first, second, other = (
            identity_of(lib, s) for s in (first_source, second_source, other_source)
        )
        person = named(lib, first)
        lib.lib.unit_of_work.write(
            lambda s: assign_identity_to_person(
                s, second, person, new_id=lib.new_id, clock=lib.clock
            )
        )

        report = forgetting(lib).forget_person(person)

        assert sorted(map(str, report.identity_ids)) == sorted([str(first), str(second)])
        assert report.complete
        assert (state_of(lib, first), state_of(lib, second), state_of(lib, other)) == (
            "FORGOTTEN",
            "FORGOTTEN",
            "ACTIVE",
        )
        [kept] = only(lib, select(Person))
        assert (kept.display_name, kept.state) == ("Ada", "ACTIVE")
        assert files_containing(lib, C) == []
        assert files_containing(lib, A)
        again = forgetting(lib).forget_person(person)  # nothing left to forget
        assert (again.complete, again.changed) == (True, False)


def test_a_person_that_does_not_exist_cannot_be_forgotten(opened: Any) -> None:
    with opened() as lib:
        with pytest.raises(PersonNotFoundError):
            forgetting(lib).forget_person(uuid.uuid4())


# --- refusals and repeats ----------------------------------------------------------------------


def test_a_repeat_changes_nothing_and_a_stale_view_is_refused(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        [row] = only(lib, select(Identity))
        use_case = forgetting(lib)

        with pytest.raises(StaleRevisionError):
            use_case.forget(identity, expected_revision=row.revision + 5)
        assert state_of(lib, identity) == "ACTIVE"  # refused, nothing happened
        assert files_containing(lib, C)

        first = use_case.forget(identity, expected_revision=row.revision)
        again = use_case.forget(
            identity, expected_revision=row.revision + 99
        )  # (a repeat ignores it)

        assert (first.complete, first.changed) == (True, True)
        assert (again.complete, again.changed) == (True, False)
        assert len(only(lib, select(Evidence).where(Evidence.kind == "IDENTITY_FORGOTTEN"))) == 1


def test_only_an_active_identity_can_be_forgotten(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        with Session(lib.lib.engine) as session:
            session.execute(update(Identity).values(state="DELETED"))
            session.commit()

        with pytest.raises(IdentityNotFoundError, match="DELETED"):
            forgetting(lib).forget(identity)
        with pytest.raises(IdentityNotFoundError, match="does not exist"):
            forgetting(lib).forget(uuid.uuid4())
        assert files_containing(lib, C)  # nothing was erased


# --- no resurrection -----------------------------------------------------------------------------


def test_nothing_reconnects_a_later_image_to_the_forgotten_identity(opened: Any) -> None:
    with opened() as lib:
        process(lib, A)
        source, _ = process(lib, C)
        gone = identity_of(lib, source)
        assert forgetting(lib).forget(gone).complete

        later, _ = process(lib, C)  # the same face again, after forgetting

        new = identity_of(lib, later)
        assert new != gone
        assert state_of(lib, gone) == "FORGOTTEN"
        assert state_of(lib, new) == "ACTIVE"
        kinds = {
            e.kind for e in only(lib, select(Evidence).where(Evidence.subject_identity_id == new))
        }
        assert "IDENTITY_MATCHED" not in kinds  # it was not recognised as the forgotten one


def test_a_rebuilt_index_and_a_restart_do_not_bring_it_back(opened: Any) -> None:
    import shutil

    with opened() as lib:
        process(lib, A)
        source, _ = process(lib, C)
        gone = identity_of(lib, source)
        assert forgetting(lib).forget(gone).complete
        space = lib.space_id
        index_directory = lib.lib.coordinator.index_directory(space)

    shutil.rmtree(index_directory)  # the index is lost; SQLite still holds what it holds

    with opened() as lib:  # --- restart with no index
        assert lib.lib.startup.indexes_rebuilt == [space]
        assert len(lib.global_index(space)) == 1  # only A is in the rebuilt index
        assert state_of(lib, gone) == "FORGOTTEN"
        assert files_containing(lib, C) == []
        assert forgetting(lib).forget(gone).changed is False


# --- crashes -------------------------------------------------------------------------------------


def crashed_after_the_forget(opened: Any, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    """A library whose forget committed and whose erasure never ran: the vectors are ERASING."""
    with opened() as lib:
        source, _ = process(lib, C)
        gone = identity_of(lib, source)
        use_case = forgetting(lib)

        def die(_ids: Any) -> Any:
            raise SimulatedCrash

        monkeypatch.setattr(lib.lib.eraser, "erase", die)
        with pytest.raises(SimulatedCrash):
            use_case.forget(gone)
        monkeypatch.undo()
    return gone


def test_an_interrupted_erasure_is_already_unrecognizable_and_a_repeat_finishes_it(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        gone = identity_of(lib, source)

        def die(_ids: Any) -> Any:
            raise SimulatedCrash

        monkeypatch.setattr(lib.lib.eraser, "erase", die)
        with pytest.raises(SimulatedCrash):
            forgetting(lib).forget(gone)
        monkeypatch.undo()
        assert state_of(lib, gone) == "FORGOTTEN"
        assert {r.state for r in only(lib, select(Representation))} == {"ERASING"}

        process(lib, C)  # before any cleanup: the same face must not be recognised as the forgotten
        kinds = {e.kind for e in only(lib, select(Evidence))}
        assert "IDENTITY_MATCHED" not in kinds

        finishing = forgetting(lib).forget(gone)  # a repeat finishes the erasure that was owed
        assert (finishing.complete, finishing.changed) == (True, True)
        assert not any(
            r.state == "ERASING" and r.identity_id == gone
            for r in only(lib, select(Representation))
        )


def test_the_next_start_finishes_an_interrupted_erasure_by_itself(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = crashed_after_the_forget(opened, monkeypatch)

    with opened() as lib:  # --- restart: no repeat of the request, only startup recovery
        assert {
            r.state
            for r in only(lib, select(Representation).where(Representation.identity_id == gone))
        } == {"ERASED"}
        assert files_containing(lib, C) == []


def test_a_log_that_cannot_be_truncated_is_reported_and_settled_by_a_repeat(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        gone = identity_of(lib, source)
        monkeypatch.setattr("backend.app.memory.erasure.truncate_wal", lambda *_a, **_k: False)

        owed = forgetting(lib).forget(gone)

        assert not owed.complete
        assert any("write-ahead log" in item for item in owed.outstanding)
        assert state_of(lib, gone) == "FORGOTTEN"  # unrecognizable already
        monkeypatch.undo()

        again = forgetting(lib).forget(gone)

        assert again.complete
        assert files_containing(lib, C) == []


def test_a_representation_marked_deleted_loses_its_vector_too(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        gone = identity_of(lib, source)
        with Session(lib.lib.engine) as session:
            [representation] = session.scalars(select(Representation))
            representation.state = "DELETED"
            ModelFactory(session, lib.clock, lib.new_id).index_operation(
                representation, operation="REMOVE", state="APPLIED", applied_at=lib.clock()
            )
            session.commit()
        assert files_containing(lib, C)

        assert forgetting(lib).forget(gone).complete

        assert files_containing(lib, C) == []
        assert not only(lib, select(IndexOperation).where(IndexOperation.state == "PENDING"))


# --- what the review of the pull request found ---------------------------------------------------


def test_vectors_left_on_an_identity_that_was_merged_into_the_forgotten_one_go_too(
    opened: Any,
) -> None:
    from backend.app.identities.use_cases import merge_identities

    with opened() as lib:
        survivor_source, _ = process(lib, A)
        loser_source, _ = process(lib, C)
        survivor, loser = identity_of(lib, survivor_source), identity_of(lib, loser_source)
        with Session(lib.lib.engine) as session:  # a merge moves only the active vectors
            session.execute(
                update(Representation)
                .where(Representation.identity_id == loser)
                .values(state="SUPERSEDED")
            )
            session.commit()
        revision = only(lib, select(Identity.revision).where(Identity.id == loser))[0]
        lib.lib.unit_of_work.write(
            lambda s: merge_identities(
                s, loser, survivor, expected_revision=revision, new_id=lib.new_id, clock=lib.clock
            )
        )
        assert files_containing(
            lib, C
        )  # the superseded vector is still on the merged-away identity

        assert forgetting(lib).forget(survivor).complete

        assert files_containing(lib, C) == []
        assert files_containing(lib, A) == []
        assert state_of(lib, loser) == "MERGED"  # the lineage tombstone stays
        assert {r.state for r in only(lib, select(Representation))} == {"ERASED"}


def test_forgetting_a_person_forgets_only_identities_that_are_theirs_now(opened: Any) -> None:
    with opened() as lib:
        mine_source, _ = process(lib, C)
        moved_source, _ = process(lib, unit(0, 0, 1, 0))
        mine, moved = identity_of(lib, mine_source), identity_of(lib, moved_source)
        ada = named(lib, mine)
        lib.lib.unit_of_work.write(
            lambda s: assign_identity_to_person(s, moved, ada, new_id=lib.new_id, clock=lib.clock)
        )
        bob = named(lib, identity_of(lib, process(lib, A)[0]), "Bob")
        lib.lib.unit_of_work.write(  # the second identity is corrected to belong to Bob instead
            lambda s: assign_identity_to_person(s, moved, bob, new_id=lib.new_id, clock=lib.clock)
        )

        report = forgetting(lib).forget_person(ada)

        assert report.identity_ids == [mine]
        assert (state_of(lib, mine), state_of(lib, moved)) == ("FORGOTTEN", "ACTIVE")


@pytest.mark.parametrize("state", ["RECYCLED", "DELETED"])
def test_a_person_that_is_not_active_cannot_be_forgotten(opened: Any, state: str) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        person = named(lib, identity)
        with Session(lib.lib.engine) as session:
            session.execute(update(Person).values(state=state))
            session.commit()

        with pytest.raises(PersonNotFoundError):
            forgetting(lib).forget_person(person)

        assert state_of(lib, identity) == "ACTIVE"
        assert files_containing(lib, C)


def test_a_person_forget_cleans_up_once_for_all_their_identities(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        first, _ = process(lib, C)
        second, _ = process(lib, unit(0, 0, 1, 0))
        person = named(lib, identity_of(lib, first))
        lib.lib.unit_of_work.write(
            lambda s: assign_identity_to_person(
                s, identity_of(lib, second), person, new_id=lib.new_id, clock=lib.clock
            )
        )
        real, calls = lib.lib.eraser.erase, []

        def counting(ids: Any) -> Any:
            calls.append(list(ids))
            return real(ids)

        monkeypatch.setattr(lib.lib.eraser, "erase", counting)

        assert forgetting(lib).forget_person(person).complete

        assert len(calls) == 1  # one consolidated erasure (one rebuild per space), not one each
        assert len(calls[0]) == 2


def test_retrying_a_person_forget_finishes_what_is_owed_and_never_pretends_it_is_done(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        person = named(lib, identity)
        monkeypatch.setattr("backend.app.memory.erasure.truncate_wal", lambda *_a, **_k: False)

        owed = forgetting(lib).forget_person(person)  # the links end, the cleanup cannot finish
        still_owed = forgetting(lib).forget_person(person)  # the person has no link left now

        assert not owed.complete
        assert not still_owed.complete  # a retry must not report `done` while cleanup is owed
        assert still_owed.identity_ids == [identity]
        monkeypatch.undo()

        finished = forgetting(lib).forget_person(person)

        assert (finished.complete, finished.changed) == (True, False)
        assert files_containing(lib, C) == []


def test_a_stale_view_of_an_identity_is_refused_after_what_it_owns_changed(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, A)
        identity = identity_of(lib, source)
        [seen] = only(lib, select(Identity.revision).where(Identity.id == identity))
        process(lib, unit(0.95, 0.1, 0, 0))  # a second face is matched to the same identity

        with pytest.raises(StaleRevisionError):
            forgetting(lib).forget(identity, expected_revision=seen)

        assert state_of(lib, identity) == "ACTIVE"


def test_a_stale_view_is_refused_after_the_identity_changed_person(opened: Any) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        [seen] = only(lib, select(Identity.revision).where(Identity.id == identity))
        named(lib, identity)  # a Person is attached after the caller looked

        with pytest.raises(StaleRevisionError):
            forgetting(lib).forget(identity, expected_revision=seen)


def test_the_face_crops_of_a_forgotten_identity_are_deleted_and_the_image_is_not(
    opened: Any,
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        crop = add_face_crop(lib, source)
        [crop_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == crop))
        [original] = only(lib, select(Source.original_artifact_id).where(Source.id == source))
        [original_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == original))

        assert forgetting(lib).forget(identity_of(lib, source)).complete

        assert lib.lib.store.digest(crop_key) is None  # the face crop is gone
        assert lib.lib.store.digest(original_key) is not None  # the photograph stays
        states = {a.id: a.state for a in only(lib, select(Artifact))}
        assert (states[crop], states[original]) == ("DELETED", "AVAILABLE")


def test_a_crop_that_cannot_be_removed_is_reported_and_a_repeat_finishes_it(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        crop = add_face_crop(lib, source)
        gone = identity_of(lib, source)

        def locked(_key: str) -> None:
            raise PermissionError("in use")

        monkeypatch.setattr(lib.lib.store, "delete", locked)
        owed = forgetting(lib).forget(gone)

        assert not owed.complete
        assert any("crop" in item for item in owed.outstanding)
        assert state_of(lib, gone) == "FORGOTTEN"
        monkeypatch.undo()

        again = forgetting(lib).forget(gone)

        assert again.complete
        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "DELETED"


def test_a_stale_view_is_refused_after_the_person_link_was_removed(opened: Any) -> None:
    from backend.app.people.use_cases import remove_identity_from_person

    with opened() as lib:
        source, _ = process(lib, C)
        identity = identity_of(lib, source)
        named(lib, identity)
        [seen] = only(lib, select(Identity.revision).where(Identity.id == identity))
        lib.lib.unit_of_work.write(
            lambda s: remove_identity_from_person(s, identity, new_id=lib.new_id, clock=lib.clock)
        )

        with pytest.raises(StaleRevisionError):
            forgetting(lib).forget(identity, expected_revision=seen)


# --- what the second review of the pull request found ---------------------------------------------


def only_crop(lib: Pipeline, source: uuid.UUID, state: str) -> tuple[uuid.UUID, str]:
    crop = add_face_crop(lib, source)
    with Session(lib.lib.engine) as session:
        session.execute(update(Artifact).where(Artifact.id == crop).values(state=state))
        session.commit()
    [key] = only(lib, select(Artifact.storage_key).where(Artifact.id == crop))
    return crop, key


@pytest.mark.parametrize("state", ["PENDING", "DELETING"])
def test_a_crop_whose_write_or_deletion_was_unfinished_is_finished_too(
    opened: Any, state: str
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        crop, key = only_crop(lib, source, state)
        staged = lib.lib.store.staging_path(key)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"half a crop")

        report = forgetting(lib).forget(identity_of(lib, source))

        assert report.complete
        assert lib.lib.store.digest(key) is None
        assert not staged.exists()  # the half-written copy goes with it
        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "DELETED"


def test_a_leftover_staged_copy_of_an_available_crop_is_removed_and_a_locked_one_reported(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source, _ = process(lib, C)
        _crop, key = only_crop(lib, source, "AVAILABLE")
        staged = lib.lib.store.staging_path(key)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"half a crop")
        real = Path.unlink

        def locked(self: Path, *args: Any, **kwargs: Any) -> None:
            if self.suffix == ".part":
                raise PermissionError("in use")
            real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", locked)
        owed = forgetting(lib).forget(identity_of(lib, source))

        assert not owed.complete
        assert any("PermissionError" in item for item in owed.outstanding)
        monkeypatch.undo()

        assert forgetting(lib).forget(identity_of(lib, source)).complete
        assert not staged.exists()


def test_a_crop_that_another_identity_still_shows_is_kept(opened: Any) -> None:
    with opened() as lib:
        first, _ = process(lib, C)
        second, _ = process(lib, A)
        crop, key = only_crop(lib, first, "AVAILABLE")
        with Session(lib.lib.engine) as session:  # the other identity's face shows the same crop
            session.execute(
                update(Observation)
                .where(Observation.source_id == second)
                .values(face_crop_artifact_id=crop)
            )
            session.commit()

        assert forgetting(lib).forget(identity_of(lib, first)).complete

        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "AVAILABLE"
        assert lib.lib.store.digest(key) is not None
        assert forgetting(lib).forget(identity_of(lib, second)).complete  # now nobody needs it
        assert lib.lib.store.digest(key) is None


def test_a_very_large_family_is_forgotten_in_bounded_statements(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import event

    from backend.app.identities import forget as forgetting_module

    with opened() as lib:
        source, _ = process(lib, C)
        survivor = identity_of(lib, source)
        with Session(lib.lib.engine) as session:
            build = ModelFactory(session, lib.clock, lib.new_id)
            for _ in range(80):  # eighty identities merged into the survivor, none with a face
                build.identity(state="MERGED", merged_into_identity_id=survivor)
            session.commit()
        monkeypatch.setattr(forgetting_module, "CHUNK", 10)

        @event.listens_for(lib.lib.engine, "connect")
        def lower_the_limit(connection: sqlite3.Connection, _record: object) -> None:
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 40)

        lib.lib.engine.dispose()  # new connections get the lower limit
        try:
            report = forgetting(lib).forget(survivor)
        finally:
            event.remove(lib.lib.engine, "connect", lower_the_limit)
            lib.lib.engine.dispose()

        assert report.complete
        assert state_of(lib, survivor) == "FORGOTTEN"
