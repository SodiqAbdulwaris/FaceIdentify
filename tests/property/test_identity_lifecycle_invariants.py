"""Property-based invariants over generated Identity Manager operation sequences (M1 PR 7:
TST-020; TESTING_STRATEGY.md §6.3: "Use Hypothesis to generate valid operation sequences
involving identity creation, assignment, correction, merging and deletion. Verify critical
invariants after every operation.").

No `deletion`/`forget` use case exists yet (a later milestone; see `.agents/CONTEXT.md`), so this
machine's operations are the full set that does exist: create, activate, assign a representation,
assign/remove/rename a Person, merge, and split. A query (`resolve_recognition_candidates`) is
exercised as an invariant, run after every operation, rather than as a mutating rule — it must
never be one.

Each example gets its own real, file-backed SQLite database (production engine/pragmas), so this
is an integration-style stateful test, not an in-memory model check.
"""

import tempfile
import uuid
from pathlib import Path

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    precondition,
    rule,
)
from sqlalchemy import select

from backend.app.identities.models import Evidence, EvidenceKind, Identity, IdentityLineage
from backend.app.identities.use_cases import (
    IdentityManagerError,
    activate_identity,
    assign_representation_to_identity,
    create_pending_identity,
    merge_identities,
    resolve_recognition_candidates,
    split_identity,
)
from backend.app.memory.models import IndexOperation, Representation, RepresentationState
from backend.app.people.models import IdentityPersonAssociation, Person
from backend.app.people.use_cases import (
    assign_identity_to_person,
    remove_identity_from_person,
    rename_person,
)
from backend.infrastructure.db.engine import Base, create_session_factory, create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

PERSON_NAMES = st.text(min_size=1, max_size=20).map(str.strip).filter(bool)


class IdentityLifecycleMachine(RuleBasedStateMachine):
    pending_identities: Bundle = Bundle("pending_identities")
    active_identities: Bundle = Bundle("active_identities")
    pending_representations: Bundle = Bundle("pending_representations")
    people: Bundle = Bundle("people")

    def __init__(self) -> None:
        super().__init__()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_sqlite_engine(Path(self._tmpdir.name) / "state.db")
        Base.metadata.create_all(self.engine)
        self.session = create_session_factory(self.engine)()
        self.clock = FrozenClock()
        self.new_id = SeededUUIDs()
        self.build = ModelFactory(self.session, self.clock, self.new_id)
        self.space = self.build.representation_space()

        self.revision: dict[uuid.UUID, int] = {}
        self.has_creation_evidence: dict[uuid.UUID, bool] = {}
        self.active_reps_by_identity: dict[uuid.UUID, set[uuid.UUID]] = {}
        self.has_person: dict[uuid.UUID, bool] = {}
        self.person_revision: dict[uuid.UUID, int] = {}
        self._last_evidence_count = 0

    def teardown(self) -> None:
        self.session.rollback()
        self.session.close()
        self.engine.dispose()
        self._tmpdir.cleanup()

    # --- rules ---------------------------------------------------------------------------

    @rule(target=pending_identities)
    def create_identity(self) -> uuid.UUID:
        identity = create_pending_identity(
            self.session, new_id=self.new_id, clock=self.clock,
            created_by_processing_run_id=self.build.run().id,
        )  # fmt: skip
        self.revision[identity.id] = identity.revision
        return identity.id

    @rule(target=active_identities, pending_id=consumes(pending_identities))
    def activate(self, pending_id: uuid.UUID) -> uuid.UUID:
        # active_reps_by_identity/has_creation_evidence/has_person are keyed by currently-ACTIVE
        # identity, so they're only populated here and in split() — never for a PENDING identity,
        # which no rule may pick as a merge survivor or split source.
        activate_identity(
            self.session, pending_id, expected_revision=self.revision[pending_id], clock=self.clock
        )
        # Predicted independently of what the call returns, so a bug that skips the revision
        # bump (not just misreports it) is still visible to `revisions_match_the_database`.
        self.revision[pending_id] += 1
        self.has_creation_evidence[pending_id] = False
        self.active_reps_by_identity[pending_id] = set()
        self.has_person[pending_id] = False
        return pending_id

    @rule(target=pending_representations)
    def create_representation(self) -> uuid.UUID:
        representation = self.build.representation(
            representation_space_id=self.space.id, state="PENDING"
        )
        return representation.id

    @rule(rep_id=consumes(pending_representations), identity_id=active_identities)
    def assign_representation(self, rep_id: uuid.UUID, identity_id: uuid.UUID) -> None:
        kind = (
            EvidenceKind.IDENTITY_MATCHED
            if self.has_creation_evidence[identity_id]
            else EvidenceKind.IDENTITY_CREATED
        )
        assign_representation_to_identity(
            self.session, rep_id, identity_id,
            new_id=self.new_id, clock=self.clock, evidence_kind=kind,
        )  # fmt: skip
        self.has_creation_evidence[identity_id] = True
        self.active_reps_by_identity[identity_id].add(rep_id)

    @rule(target=people)
    def create_person(self) -> uuid.UUID:
        person = self.build.person(display_name=f"person-{self.build.new_id()}")
        self.person_revision[person.id] = person.revision
        return person.id

    @rule(identity_id=active_identities, person_id=people)
    def assign_person(self, identity_id: uuid.UUID, person_id: uuid.UUID) -> None:
        try:
            assign_identity_to_person(
                self.session, identity_id, person_id, new_id=self.new_id, clock=self.clock
            )
        except IdentityManagerError:
            return  # already linked to exactly this person: a documented no-op rejection
        self.has_person[identity_id] = True

    @rule(identity_id=active_identities)
    def remove_person(self, identity_id: uuid.UUID) -> None:
        try:
            remove_identity_from_person(
                self.session, identity_id, new_id=self.new_id, clock=self.clock
            )
        except IdentityManagerError:
            return  # no active association to remove
        self.has_person[identity_id] = False

    @rule(person_id=people, new_name=PERSON_NAMES)
    def rename(self, person_id: uuid.UUID, new_name: str) -> None:
        rename_person(
            self.session, person_id, new_name,
            expected_revision=self.person_revision[person_id], clock=self.clock,
        )  # fmt: skip
        self.person_revision[person_id] += 1

    @precondition(lambda self: len(self.active_reps_by_identity) >= 2)
    @rule(loser_id=consumes(active_identities), data=st.data())
    def merge(self, loser_id: uuid.UUID, data: st.DataObject) -> None:
        survivor_id = data.draw(
            st.sampled_from([i for i in self.active_reps_by_identity if i != loser_id])
        )
        merge_identities(
            self.session, loser_id, survivor_id,
            expected_revision=self.revision[loser_id], new_id=self.new_id, clock=self.clock,
        )  # fmt: skip
        self.active_reps_by_identity[survivor_id] |= self.active_reps_by_identity.pop(loser_id)
        if self.has_person.pop(loser_id):
            self.has_person[survivor_id] = True
        del self.revision[loser_id]
        del self.has_creation_evidence[loser_id]

    @precondition(lambda self: any(self.active_reps_by_identity.values()))
    @rule(target=active_identities, data=st.data())
    def split(self, data: st.DataObject) -> uuid.UUID:
        source_id = data.draw(
            st.sampled_from([i for i, reps in self.active_reps_by_identity.items() if reps])
        )
        available = sorted(self.active_reps_by_identity[source_id])
        to_move = data.draw(
            st.lists(st.sampled_from(available), min_size=1, max_size=len(available), unique=True)
        )
        new_identity = split_identity(
            self.session, source_id, to_move, new_id=self.new_id, clock=self.clock
        )
        self.active_reps_by_identity[source_id] -= set(to_move)
        self.active_reps_by_identity[new_identity.id] = set(to_move)
        self.revision[new_identity.id] = new_identity.revision
        self.has_creation_evidence[new_identity.id] = True
        self.has_person[new_identity.id] = False
        return new_identity.id

    # --- invariants ------------------------------------------------------------------------

    @invariant()
    def revisions_match_the_database(self) -> None:
        """ID-01 / PER-01: each identifier's authoritative revision is exactly what this
        machine's own count of successful revision-bumping operations on it predicts —
        independently of what any single operation call happened to report back."""
        for identity_id, expected in self.revision.items():
            row = self.session.get(Identity, identity_id, populate_existing=True)
            assert row is not None
            assert row.revision == expected
        for person_id, expected_person_revision in self.person_revision.items():
            person_row = self.session.get(Person, person_id, populate_existing=True)
            assert person_row is not None
            assert person_row.revision == expected_person_revision

    @invariant()
    def evidence_is_append_only(self) -> None:
        """OBS-03 / ID-03: the Evidence table only ever grows."""
        count = len(self.session.scalars(select(Evidence)).all())
        assert count >= self._last_evidence_count
        self._last_evidence_count = count

    @invariant()
    def active_representations_are_ann_eligible(self) -> None:
        """§20: an ACTIVE representation always has an identity and an ann_key."""
        ineligible = self.session.scalars(
            select(Representation).where(
                Representation.state == RepresentationState.ACTIVE,
                Representation.ann_key.is_(None),
            )
        ).all()
        assert ineligible == []

    @invariant()
    def a_query_creates_no_persistent_state(self) -> None:
        """SEARCH-01: resolving recognition candidates never writes anything, for any mix of
        known and unknown candidates, at any point in the generated operation sequence."""
        candidate_ids = [*self.revision.keys(), uuid.uuid4()]
        before = self._table_counts()
        resolve_recognition_candidates(self.session, candidate_ids)
        assert self._table_counts() == before

    def _table_counts(self) -> tuple[int, int, int, int, int, int]:
        return (
            len(self.session.scalars(select(Identity)).all()),
            len(self.session.scalars(select(Evidence)).all()),
            len(self.session.scalars(select(IdentityLineage)).all()),
            len(self.session.scalars(select(Representation)).all()),
            len(self.session.scalars(select(IndexOperation)).all()),
            len(self.session.scalars(select(IdentityPersonAssociation)).all()),
        )


TestIdentityLifecycle = IdentityLifecycleMachine.TestCase
TestIdentityLifecycle.settings = settings(max_examples=25, stateful_step_count=20, deadline=None)
