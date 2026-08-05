"""test_plugins.py — the supported extension surface.

Pins the narrow PluginContext (each add_* wires the real registry), capability
gating, failure isolation, idempotent load, the renderer card hook, and the
end-to-end path where a plugin loaded through the orchestrator adds a glance
candidate the arbiter then routes to.
"""
from __future__ import annotations


from dreamlayer.plugins import make_plugin, PluginContext, PluginRegistry
from dreamlayer.object_lens import ProviderRegistry, ObjectSighting
from dreamlayer.object_lens.providers import PanelProvider
from dreamlayer.object_lens.schema import PanelRow
from dreamlayer.orchestrator.glance import (
    GlanceArbiter, GlanceReading, LensCandidate, LensBid,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.hud.renderer import CardRenderer
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- fixtures: a tiny provider + candidate a plugin might ship ----------------

class StampProvider(PanelProvider):
    name = "stamp"
    def matches(self, sighting): return True
    def build(self, sighting, now=None):
        return [PanelRow(label="stamped", kind="info", source=self.name)]


class WidgetCandidate(LensCandidate):
    lens, label = "widget", "Widget"
    def bid(self, reading, ctx):
        if reading.scene == "object":
            return LensBid(self.lens, self.label, 0.99, "widget",
                           reason="a widget plugin claims objects")
        return None


# -- the context wires the real registries -----------------------------------

def test_context_add_object_provider_registers_it():
    reg = ProviderRegistry()
    # object_lens is the declared capability for a panel provider; it is now
    # enforced at the add_* call site (audit 2026-07-14), so grant it here.
    ctx = PluginContext(object_registry=reg,
                        capabilities=frozenset({"object_lens"}))
    ctx.add_object_provider(StampProvider())
    panel = reg.build_panel(ObjectSighting("mug", 0.9))
    assert any(r.label == "stamped" for r in panel.rows)


def test_context_add_glance_candidate_appends_it():
    arb = GlanceArbiter()
    ctx = PluginContext(glance_arbiter=arb)
    ctx.add_glance_candidate(WidgetCandidate())
    d = arb.arbitrate(GlanceReading("object", 0.8, {}))
    assert d.kind == "fire" and d.winner.lens == "widget"


def test_context_no_ops_without_a_target():
    ctx = PluginContext(capabilities=frozenset({"object_lens"}))  # cap, no target
    ctx.add_object_provider(StampProvider())  # must not raise
    assert ctx.added["object_provider"]       # still recorded


# -- capability gating + failure isolation -----------------------------------

def test_a_plugin_requiring_an_absent_capability_is_skipped():
    ctx = PluginContext(capabilities=frozenset({"glance"}))
    reg = PluginRegistry(ctx)
    p = make_plugin("needs-vision", lambda c: c.add_glance_candidate(WidgetCandidate()),
                    requires=("vision",))
    reg.load(p)
    assert reg.result.loaded == [] and reg.result.skipped
    assert "vision" in reg.result.skipped[0][1]


def test_a_throwing_plugin_is_isolated():
    ctx = PluginContext(glance_arbiter=GlanceArbiter())
    reg = PluginRegistry(ctx)
    def boom(c): raise RuntimeError("bad plugin")
    reg.load(make_plugin("boom", boom))
    reg.load(make_plugin("good", lambda c: c.add_glance_candidate(WidgetCandidate())))
    assert reg.result.failed and reg.result.failed[0][0] == "boom"
    assert reg.result.loaded == ["good"]      # the good one still loaded


def test_load_is_idempotent_per_name():
    ctx = PluginContext(glance_arbiter=GlanceArbiter())
    reg = PluginRegistry(ctx)
    p = make_plugin("once", lambda c: c.add_glance_candidate(WidgetCandidate()))
    assert reg.load(p) is True
    assert reg.load(p) is False               # same name, not loaded twice
    assert len(ctx.added["glance_candidate"]) == 1


# -- the renderer card hook ---------------------------------------------------

def test_plugin_card_renderer_is_dispatched():
    r = CardRenderer()
    seen = {}
    r.register("WidgetCard", lambda draw, card: seen.setdefault("hit", card.get("v")))
    r.render({"type": "WidgetCard", "v": 7})
    assert seen.get("hit") == 7


# -- end to end through the orchestrator -------------------------------------

def test_orchestrator_load_plugins_wires_a_candidate():
    orc = Orchestrator(FakeBridge())
    res = orc.load_plugins([make_plugin(
        "widget-lens", lambda c: c.add_glance_candidate(WidgetCandidate()))])
    assert res.loaded == ["widget-lens"]
    # the arbiter now routes an object look to the plugin's lens
    d = orc.glance_arbiter.arbitrate(GlanceReading("object", 0.8, {}))
    assert d.winner is not None and d.winner.lens == "widget"


def test_orchestrator_capability_gate_reflects_state():
    orc = Orchestrator(FakeBridge())
    caps = orc._plugin_capabilities()
    assert "object_lens" in caps and "glance" in caps and "perception" in caps
    # a mesh-requiring plugin is skipped until a mesh is attached
    res = orc.load_plugins([make_plugin(
        "needs-mesh", lambda c: None, requires=("mesh",))])
    assert res.skipped and res.skipped[0][0] == "needs-mesh"


class TestAPartialVeilIsNotConsent:
    """`PluginContext` takes whatever veil it is handed, including from a
    third-party embedder. The two questions answer differently on purpose, and
    the asymmetry is easy to misread as a bug later — so it is pinned.

    CAPTURE fails closed: a gate that cannot say "yes" must not be read as
    having said it. RECALL does not, because recall is unrestricted
    (decisions/0009) — incognito stops keeping, not asking — so an unanswerable
    recall question lands on the same answer the Brain's own gate gives.
    """

    class _NoCapture:
        """A gate that answers recall and not capture. Not hypothetical: two of
        the Brain's twelve hand-written gates lacked `allow_recall` before they
        were unified, so the mirror-image shape really did ship."""

        def allow_recall(self) -> bool:
            return True

    class _Raises:
        def allow_capture(self):
            raise RuntimeError("trust store unreadable")

        def allow_recall(self):
            raise RuntimeError("trust store unreadable")

    def test_no_veil_at_all_is_permissive_and_that_is_deliberate(self):
        """The SDK / preview / unit shape. The plugin is not next to a wearer,
        and refusing here would make every example refuse."""
        assert PluginContext().veiled() is False

    def test_a_gate_that_cannot_answer_capture_reads_as_veiled(self):
        ctx = PluginContext(veil=self._NoCapture())
        assert ctx.veiled() is True, (
            "a supplied gate with no allow_capture silently disabled the "
            "shield — a missing method is not consent")

    def test_a_gate_that_raises_reads_as_veiled(self):
        assert PluginContext(veil=self._Raises()).veiled() is True

    @staticmethod
    def _facade(veil):
        """The recall half lives on `MemoryFacade`, which is what a plugin
        actually touches — `ctx.memory`. Driven through `memories()` rather
        than the private predicate, so this asserts what a plugin experiences.
        """
        from dreamlayer.memory.db import MemoryDB
        from dreamlayer.plugins.base import MemoryFacade
        db = MemoryDB(":memory:")
        db.add_memory("note", "the lease is due Friday", confidence=1.0)
        return MemoryFacade(db, caps=frozenset({"memory"}), veil=veil)

    def test_recall_stays_open_where_capture_closes(self):
        """The asymmetry itself, asserted in one place so the next reader sees
        it is a decision rather than an oversight."""
        gate = self._NoCapture()
        assert PluginContext(veil=gate).veiled() is True
        assert self._facade(gate).memories(), (
            "recall is unrestricted (decisions/0009) — a plugin should still "
            "read what the wearer already knows")

    def test_but_a_broken_gate_still_refuses_recall(self):
        """An exception is a broken gate, not a gate saying yes."""
        assert self._facade(self._Raises()).memories() == []
