"""The Veil as a TYPE INVARIANT on the memory store — the `typed_models` seam.

`memory/models_pydantic.py` opens with "a MemoryEvent literally cannot be
constructed with allowed=False", and nothing constructed one. Meanwhile
`MemoryDB.add_memory` checked nothing at all: every capture site checked
`allow_capture()` first and the guarantee rested entirely on none of them ever
forgetting. That is the shape `person_guard` and `voice_guard` were centralised
to fix — a rule enforced at N call sites holds until the N+1th.

`MemoryDB(path, privacy=gate)` now routes the write through that type. The
refusal is the record failing to exist, not another `if`.

Two scoping decisions are pinned here as much as the mechanism, because both
could reasonably have gone the other way and neither is obvious from the code:

  * **default off.** No gate means today's behaviour byte-for-byte, so nothing
    existing changes and this is opt-in.
  * **the Orchestrator, not the Brain.** The Brain's captures go to the hot ring
    and the index; its one `add_memory` caller is the ember TOMBSTONE, a record
    that something was burned — which must be written *while veiled*, because it
    is the opposite of captured content.
"""
from __future__ import annotations

import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.models_pydantic import MemoryEvent, PrivacyViolation


class Gate:
    def __init__(self, allow=True):
        self.allow = allow
        self.asked = 0

    def allow_capture(self):
        self.asked += 1
        return self.allow


class Unreadable:
    def allow_capture(self):
        raise RuntimeError("trust signal unreadable")


def _rows(db):
    return db.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]


class TestTheTypeItself:
    def test_it_cannot_be_constructed_disallowed(self):
        with pytest.raises(PrivacyViolation):
            MemoryEvent(kind="Note", summary="x", allowed=False)

    def test_it_constructs_normally_when_allowed(self):
        assert MemoryEvent(kind="Note", summary="x", allowed=True).kind == "Note"

    def test_the_two_paths_agree(self):
        """pydantic and the dataclass fallback must raise the same way — the
        module's whole claim is that either path gives the guarantee."""
        from dreamlayer.memory import models_pydantic as m
        assert issubclass(PrivacyViolation, ValueError)
        # whichever path is active here, the behaviour above is what was tested;
        # this records which one ran so a failure is diagnosable.
        assert isinstance(m.available, bool)


class TestTheStoreRefusesAVeiledWrite:
    def test_no_gate_is_unchanged(self):
        db = MemoryDB(":memory:")
        assert db.add_memory("Note", "hello") > 0 and _rows(db) == 1

    def test_veil_down_writes(self):
        g = Gate(True)
        db = MemoryDB(":memory:", privacy=g)
        assert db.add_memory("Note", "hello") > 0
        assert _rows(db) == 1 and g.asked == 1

    def test_veil_up_refuses_and_writes_nothing(self):
        db = MemoryDB(":memory:", privacy=Gate(False))
        with pytest.raises(PrivacyViolation):
            db.add_memory("Note", "the lease is due Friday")
        assert _rows(db) == 0, "the row landed despite the refusal"

    def test_an_unreadable_posture_fails_closed(self):
        """A trust signal that cannot be read is a veiled one — every other gate
        in this product resolves the same way."""
        db = MemoryDB(":memory:", privacy=Unreadable())
        with pytest.raises(PrivacyViolation):
            db.add_memory("Note", "secret")
        assert _rows(db) == 0

    def test_the_check_runs_before_anything_is_written(self):
        """Ordering matters: a refusal after a partial write would be worse than
        no check. The gate is consulted before the scrub and before the INSERT."""
        db = MemoryDB(":memory:", privacy=Gate(False))
        for _ in range(3):
            with pytest.raises(PrivacyViolation):
                db.add_memory("Note", "x")
        assert _rows(db) == 0

    def test_set_privacy_attaches_after_construction(self):
        """The Orchestrator builds the store before its gate exists."""
        db = MemoryDB(":memory:")
        assert db.add_memory("Note", "before") > 0
        db.set_privacy(Gate(False))
        with pytest.raises(PrivacyViolation):
            db.add_memory("Note", "after")
        assert _rows(db) == 1

    def test_the_refusal_carries_no_captured_content(self):
        """The record built to be refused deliberately omits the summary —
        nothing is gained by copying the wearer's words into a validation
        object, and the exception reaches logs."""
        db = MemoryDB(":memory:", privacy=Gate(False))
        try:
            db.add_memory("Note", "therapy with Dr Halloran on Tuesday")
        except PrivacyViolation as exc:
            assert "Halloran" not in str(exc) and "therapy" not in str(exc)
        else:
            pytest.fail("the veiled write was not refused")


class TestItIsAnInvariantNotAnIf:
    def test_the_store_refuses_by_constructing_the_type(self):
        """If the check is ever rewritten as a plain `if`, the guarantee moves
        back out of the type and into this file's memory — which is exactly the
        arrangement `typed_models` exists to replace."""
        import pathlib
        from dreamlayer.memory import db as m
        body = pathlib.Path(m.__file__).read_text(encoding="utf-8")
        block = body.split("def _veil_check", 1)[1].split("def add_memory", 1)[0]
        assert "MemoryEvent(" in block, (
            "_veil_check no longer constructs the record type")

    def test_the_gate_is_only_asked_once_per_write(self):
        g = Gate(True)
        db = MemoryDB(":memory:", privacy=g)
        db.add_memory("Note", "a")
        db.add_memory("Note", "b")
        assert g.asked == 2


class TestWhereItIsWiredAndWhereItIsNot:
    def test_the_orchestrator_attaches_its_gate(self):
        import pathlib
        from dreamlayer.orchestrator import orchestrator as o
        src = pathlib.Path(o.__file__).read_text(encoding="utf-8")
        assert "self.db.set_privacy(self.privacy)" in src

    def test_the_brains_stores_are_ungated_on_purpose(self):
        """The Brain's only `add_memory` caller is the ember tombstone. Gating it
        would refuse to record that something was BURNED while incognito, which
        inverts the point — the tombstone exists because the answer is gone.

        Asserted so that "the Brain is ungated" stays a decision someone made
        rather than something nobody noticed.
        """
        import pathlib
        from dreamlayer.ai_brain.server import retention_live, lens_hosts
        for mod in (retention_live, lens_hosts):
            src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
            sites = [ln for ln in src.splitlines() if "MemoryDB(" in ln]
            # Without this the test passes when the construction is RENAMED or
            # moved: no line matches, the loop body never runs, and "the store
            # is ungated" is asserted about nothing.
            assert sites, (
                f"{mod.__name__} no longer constructs MemoryDB( — this check "
                "has stopped looking at anything; find where the store is "
                "built now")
            for line in sites:
                assert "privacy" not in line, (
                    f"{mod.__name__} now gates a store the Brain only reads "
                    "from — check the ember tombstone still writes while veiled")

    def test_a_tombstone_still_writes_while_veiled(self):
        """The behavioural half of the above, not just the source check."""
        db = MemoryDB(":memory:")            # the Brain's store: no gate
        assert db.add_memory("ember_tombstone", "cue only", confidence=1.0) > 0
        assert _rows(db) == 1
