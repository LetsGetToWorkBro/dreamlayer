"""The Veil as a type invariant on the ring — `typed_models`, reachable.

`models_pydantic.MemoryEvent` cannot be constructed with `allowed=False`, and
`MemoryDB` has taken a `privacy=` gate that builds one before every write since
the day it was written. Nothing ever passed the gate, so the invariant never
ran — and it could not have helped if it did: the shipped Brain calls no
`db.add_*` method at all. Every `add_memory` caller in the tree is
Orchestrator-only, the simulator, or the ember burn tombstone, and blocking
THAT would be actively wrong (the burn has already happened by then; the
tombstone is the wearer's deletion receipt, which is why `ceremony.burn`
swallows its failures rather than leaving a half-burn).

Where the Brain actually keeps things is the ring. `world_lens` and
`lens_hosts` append `MemoryEvent`s to a `SemanticRingBuffer`, each site
checking `allow_capture()` first — `_remember_sighting` even re-checks for the
TOCTOU case — and the ring itself checking nothing. That is the
`person_guard`/`voice_guard` shape before centralisation: a rule enforced at N
call sites is a rule that holds until the N+1th.

So the ring takes the same `privacy=` opt-in the store already had, and the
Brain passes its gate. These tests pin the invariant, the recall/capture split
that keeps seeding working under the Veil, and the promotion being earned.
"""
from __future__ import annotations

import pytest

from dreamlayer.memory.models_pydantic import PrivacyViolation
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent


class _Gate:
    def __init__(self, allow=True, boom=False):
        self.allow, self.boom = allow, boom

    def allow_capture(self):
        if self.boom:
            raise RuntimeError("unreadable posture")
        return self.allow

    def allow_recall(self):
        return self.allow_capture()


def _ev(kind="object", summary="a mug"):
    return MemoryEvent(kind=kind, summary=summary, confidence=0.9)


class TestTheFloor:
    def test_no_gate_behaves_exactly_as_before(self):
        r = SemanticRingBuffer(8)
        r.append(_ev())
        assert len(r.latest()) == 1
        assert r.veil_checks == 0, "an unguarded ring must not claim a check"

    def test_an_open_veil_keeps_normally(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=True))
        r.append(_ev())
        assert len(r.latest()) == 1
        assert r.veil_checks == 1


class TestTheInvariant:
    def test_a_veiled_keep_cannot_be_constructed(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=False))
        with pytest.raises(PrivacyViolation):
            r.append(_ev())
        assert not r.latest(), "the event landed in the ring anyway"

    def test_it_fails_closed_on_an_unreadable_posture(self):
        # Opposite to the attention gate, and the asymmetry is the point: this
        # is about the RECORD, so an unreadable signal must not resolve to
        # "keep it".
        r = SemanticRingBuffer(8, privacy=_Gate(boom=True))
        with pytest.raises(PrivacyViolation):
            r.append(_ev())
        assert not r.latest()

    def test_extend_is_guarded_too(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=False))
        with pytest.raises(PrivacyViolation):
            r.extend([_ev(), _ev()])
        assert not r.latest()

    def test_the_gate_can_be_attached_after_construction(self):
        r = SemanticRingBuffer(8)
        r.append(_ev())                       # unguarded: fine
        r.set_privacy(_Gate(allow=False))
        with pytest.raises(PrivacyViolation):
            r.append(_ev())
        assert len(r.latest()) == 1

    def test_the_veiled_summary_is_not_copied_into_the_check(self):
        # The typed record exists only to be refused. Copying the wearer's
        # words into a validation object buys nothing and puts captured content
        # somewhere nobody audits.
        import dreamlayer.memory.models_pydantic as M
        seen = {}
        real = M.MemoryEvent

        class _Spy(real):                      # type: ignore[misc,valid-type]
            def __init__(self, **data):
                seen.update(data)
                super().__init__(**data)
        M.MemoryEvent = _Spy
        try:
            r = SemanticRingBuffer(8, privacy=_Gate(allow=True))
            r.append(_ev(summary="my card number is 4111 1111 1111 1111"))
        finally:
            M.MemoryEvent = real
        assert "summary" not in seen, seen
        assert seen.get("kind") == "object"


class TestSeedingIsRecallNotCapture:
    """The half that would have broken the product if it were gated wrong."""

    def test_restore_works_under_the_veil(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=False))
        r.restore(_ev(), ts=1.0)
        assert len(r.latest()) == 1, (
            "a veiled session left the ring empty, so every ring lens would "
            "answer 'nothing to report' about a timeline that exists")

    def test_restore_does_not_count_as_a_veil_check(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=True))
        r.restore(_ev(), ts=1.0)
        assert r.veil_checks == 0

    def test_restore_keeps_the_timestamp_it_is_given(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=False))
        r.restore(_ev(), ts=123.5)
        assert r.latest()[0].ts == 123.5

    def test_the_seed_uses_restore_and_not_append(self):
        # Read the source rather than the behaviour: this is the one call whose
        # WRONGNESS would only show on a device that happened to be veiled at
        # boot, which no unit test naturally reaches.
        import inspect

        from dreamlayer.ai_brain.server import lens_hosts
        seed = inspect.getsource(lens_hosts.BrainLenses._seed)
        assert "_ring.restore(" in seed
        assert "_ring.append(" not in seed, (
            "seeding through append() means a Brain that boots under the Veil "
            "gets an empty ring and lenses that lie by omission")


class TestTheBrainWiresIt:
    def test_the_lens_ring_carries_the_gate(self):
        import inspect

        from dreamlayer.ai_brain.server import lens_hosts
        src = inspect.getsource(lens_hosts.BrainLenses)
        assert "SemanticRingBuffer(RING_CAPACITY," in src
        assert "privacy=_LensGate(self.brain)" in src

    def test_the_world_lens_ring_carries_the_gate(self):
        import inspect

        from dreamlayer.ai_brain.server import world_lens
        src = inspect.getsource(world_lens)
        assert "SemanticRingBuffer(64, privacy=self.privacy)" in src

    def test_a_veiled_sighting_still_does_not_raise_out_of_look(self):
        # `_remember_sighting` is best-effort and wraps its own body; the new
        # invariant must not turn a veiled look into an exception the caller
        # sees. Belt and braces: the site's own gate returns first anyway.
        from dreamlayer.ai_brain.server.world_lens import WorldLensHost
        host = WorldLensHost.__new__(WorldLensHost)
        host.privacy = _Gate(allow=False)
        host.ring = SemanticRingBuffer(8, privacy=host.privacy)
        host._remember_sighting("mug")        # must not raise
        assert not host.ring.latest()


class TestThePromotionIsEarned:
    def test_an_unused_ring_does_not_promote(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=True))
        assert r.veil_checks == 0, (
            "a tripwire nobody has crossed is not a live guarantee")

    def test_a_real_keep_promotes(self):
        r = SemanticRingBuffer(8, privacy=_Gate(allow=True))
        r.append(_ev())
        assert r.veil_checks == 1

    def test_the_report_follows_a_vetted_append(self):
        import inspect

        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert "DL_WIRED_TYPED_MODELS" in src
        assert "veil_checks" in src, (
            "promotion must follow an append the invariant actually vetted, "
            "not a gate having been handed over")


class TestTheDependencyIsHonest:
    def test_the_invariant_holds_without_pydantic(self):
        # The floor: the fallback dataclass raises the same way, so uninstalling
        # the dependency must never turn a refusal into a keep.
        import dreamlayer.memory.models_pydantic as M
        if not M.available:                          # pragma: no cover
            pytest.skip("pydantic absent; the fallback is what already ran")
        assert M.available is True
        r = SemanticRingBuffer(8, privacy=_Gate(allow=False))
        with pytest.raises(PrivacyViolation):
            r.append(_ev())

    def test_the_typed_event_refuses_directly(self):
        from dreamlayer.memory.models_pydantic import MemoryEvent as Typed
        with pytest.raises(PrivacyViolation):
            Typed(kind="object", allowed=False)
        assert Typed(kind="object", allowed=True).kind == "object"
