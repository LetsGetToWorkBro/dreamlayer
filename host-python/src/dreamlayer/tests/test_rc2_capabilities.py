"""The emit→capability contract: a lens must declare every host power it uses."""
from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END, SELF, verify,
    CAPABILITIES, capability_for, declared_requires, emitted_capabilities,
    require,
)


def _ask_lens() -> Figment:
    fig = Figment(name="Ask", initial="idle")
    idle = fig.add_scene(Scene(id="idle", lines=[TextLine("ask me", row=0)]))
    idle.on["double"] = Transition(target="hear", emit="ask")
    hear = fig.add_scene(Scene(id="hear", lines=[TextLine("{slot}", row=1)]))
    hear.on["double"] = Transition(target=END)
    return fig


class TestLookup:
    def test_known_tags_map_to_capabilities(self):
        assert capability_for("ask") == "ask"
        assert capability_for("look") == "look"
        assert capability_for("translate") == "translate"

    def test_free_tags_are_not_capabilities(self):
        for tag in ("rep", "round", "beat", "banished", "", None):
            assert capability_for(tag) is None

    def test_emitted_capabilities_inferred_from_tags(self):
        assert emitted_capabilities(_ask_lens()) == ["ask"]


class TestValidatorGate:
    def test_undeclared_capability_is_rejected(self):
        rep = verify(_ask_lens())
        assert not rep.ok
        assert any(v.code == "capability_undeclared" for v in rep.violations)

    def test_declaring_the_capability_passes(self):
        fig = require(_ask_lens(), "ask")
        assert declared_requires(fig) == ["ask"]
        assert verify(fig).ok

    def test_unknown_capability_is_rejected(self):
        fig = require(_ask_lens(), "ask")
        fig.meta["requires"].append("mind_control")
        rep = verify(fig)
        assert not rep.ok
        assert any(v.code == "capability_unknown" for v in rep.violations)

    def test_passive_capability_needs_no_emit(self):
        # a Rosetta-style lens: fed by the Brain into a slot, emits nothing,
        # yet legitimately declares the power it consumes
        fig = Figment(name="Rosetta", initial="a")
        a = fig.add_scene(Scene(id="a", lines=[TextLine("{slot:translation}", row=1)]))
        a.on["text"] = Transition(target=SELF)
        a.on["double"] = Transition(target=END)
        require(fig, "translate")
        assert verify(fig).ok
        assert emitted_capabilities(fig) == []      # nothing emitted
        assert declared_requires(fig) == ["translate"]

    def test_require_is_idempotent(self):
        fig = require(require(_ask_lens(), "ask"), "ask")
        assert fig.meta["requires"] == ["ask"]


class TestRegistrySummaries:
    def test_every_capability_has_a_summary(self):
        for name, cap in CAPABILITIES.items():
            assert cap.name == name
            assert cap.summary and isinstance(cap.summary, str)


class TestFigmentMigrationPilot:
    """The decision recorded in ADR 0002 + the Rosetta pilot's core invariant."""

    def test_rosetta_figment_declares_translate_and_verifies(self):
        from dreamlayer.reality_compiler.v2 import native
        fig = native.rosetta_figment()
        assert verify(fig).ok
        assert declared_requires(fig) == ["translate"]
        assert emitted_capabilities(fig) == []      # fed passively, emits nothing

    def test_decision_docs_exist(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[4]
        adr = root / "docs" / "adr" / "0002-figment-migration.md"
        guide = root / "docs" / "rc_v2" / "figment_migration.md"
        assert adr.is_file() and "output-shape" in adr.read_text()
        assert guide.is_file() and "requires" in guide.read_text()
