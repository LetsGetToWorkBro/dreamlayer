"""Plugin API v2: lifecycle, the veil-gated event bus, per-plugin settings, the
dogfood migrations, and the subprocess isolation jail (with a hostile plugin)."""
import json


from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.privacy import PrivacyGate
from dreamlayer.orchestrator.health import HealthLedger
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.plugins import PluginContext, PluginRegistry, make_plugin
from dreamlayer.plugins.events import PluginEventBus


# --- lifecycle -------------------------------------------------------------

class LifecyclePlugin:
    name = "lifecycle-probe"
    version = "0.1.0"
    requires = ()

    def __init__(self):
        self.log = []

    def register(self, ctx):
        self.log.append("register")

    def start(self, ctx):
        self.log.append("start")

    def stop(self):
        self.log.append("stop")

    def tick(self, now):
        self.log.append(("tick", now))
        return {"t": "probe", "now": now}

    def on_event(self, kind, payload):
        self.log.append(("event", kind))


class TestLifecycle:
    def _reg(self, plugin, caps=frozenset()):
        reg = PluginRegistry(PluginContext(capabilities=caps))
        reg.load(plugin)
        return reg

    def test_start_stop_tick_dispatch(self):
        p = LifecyclePlugin()
        reg = self._reg(p)
        reg.start_all()
        cmds = reg.tick_all(now=1.0)
        reg.dispatch_event("place", {"signature": "home"})
        reg.stop_all()
        kinds = [x if isinstance(x, str) else x[0] for x in p.log]
        assert kinds == ["register", "start", "tick", "event", "stop"]
        assert cmds == [{"t": "probe", "now": 1.0}]

    def test_missing_lifecycle_methods_are_fine(self):
        # a v1 register-only plugin has no start/tick — must not error
        loaded = []
        reg = self._reg(make_plugin("v1", lambda ctx: loaded.append(1)))
        reg.start_all(); reg.tick_all(0.0); reg.stop_all()
        assert loaded == [1]

    def test_a_throwing_tick_is_isolated_and_recorded(self):
        h = HealthLedger()

        class Bad:
            name = "bad"; version = "0"; requires = ()
            def register(self, ctx): pass
            def tick(self, now): raise RuntimeError("boom")

        reg = PluginRegistry(PluginContext(), health=h)
        reg.load(Bad())
        assert reg.tick_all(1.0) == []          # no crash
        assert h.failures("plugin:bad") == 1

    def test_reload_stops_old_and_loads_new(self):
        a, b = LifecyclePlugin(), LifecyclePlugin()
        reg = self._reg(a)
        reg.start_all()
        reg.reload(b)
        assert "stop" in a.log                  # old instance torn down
        assert reg.plugins["lifecycle-probe"] is b


# --- events (veil-gated) ---------------------------------------------------

class TestEventBus:
    def test_subscribe_requires_capability(self):
        seen = []
        ctx = PluginContext(capabilities=frozenset({"glance"}),
                            events=PluginEventBus())
        with ctx._as("p"):
            assert ctx.subscribe("glance", lambda k, d: seen.append(d)) is True
            assert ctx.subscribe("card_shown", lambda k, d: None) is False  # no 'cards'

    def test_veil_gates_all_but_veil_events(self):
        gate = PrivacyGate()
        bus = PluginEventBus(veil=gate)
        got = []
        bus.subscribe("glance", lambda k, d: got.append("g"))
        bus.subscribe("veil", lambda k, d: got.append("v"))
        gate.pause()                            # doors shut
        bus.publish("glance", {})               # blocked
        bus.publish("veil", {"paused": True})   # always flows
        assert got == ["v"]
        gate.resume()
        bus.publish("glance", {})
        assert got == ["v", "g"]

    def test_bad_subscriber_never_breaks_publish(self):
        h = HealthLedger()
        bus = PluginEventBus(health=h)
        ran = []
        bus.subscribe("glance", lambda k, d: (_ for _ in ()).throw(ValueError("x")),
                      plugin_name="rude")
        bus.subscribe("glance", lambda k, d: ran.append(1))
        bus.publish("glance", {})
        assert ran == [1]                       # the good one still ran
        assert h.failures("plugin:rude") == 1

    def test_orchestrator_publishes_at_moments(self):
        orch = Orchestrator(EmulatorBridge())
        seen = []
        orch.plugin_events.subscribe("veil", lambda k, d: seen.append(d["paused"]))
        orch.plugin_events.subscribe("dream_enter", lambda k, d: seen.append("dream"))
        orch.pause(); orch.resume()
        orch.enter_dream()
        assert True in seen and False in seen and "dream" in seen


# --- settings --------------------------------------------------------------

class TestSettings:
    def test_persisted_per_plugin(self):
        db = MemoryDB()
        ctx = PluginContext(db=db)
        with ctx._as("counter"):
            ctx.settings.set("threshold", 3)
            assert ctx.settings.get("threshold") == 3
        # a fresh context over the same db sees it (persisted)
        ctx2 = PluginContext(db=db)
        with ctx2._as("counter"):
            assert ctx2.settings.get("threshold") == 3
        # namespaced: another plugin doesn't see it
        with ctx2._as("other"):
            assert ctx2.settings.get("threshold") is None

    def test_in_memory_without_db(self):
        ctx = PluginContext()
        with ctx._as("p"):
            ctx.settings.set("k", "v")
            assert ctx.settings.get("k") == "v"


# --- dogfood migrations ----------------------------------------------------

class TestDogfood:
    def test_filler_persists_lifetime_total(self):
        from dreamlayer.plugins.filler import filler_plugin
        db = MemoryDB()
        reg = PluginRegistry(PluginContext(capabilities=frozenset(
            {"perception", "cards"}), db=db))
        p = filler_plugin()
        reg.load(p)
        reg.start_all()
        p.counter.listen("um, so, like, basically yeah")   # 3 fillers
        reg.stop_all()                                     # flushes total
        # a new instance resumes the tally from settings
        reg2 = PluginRegistry(PluginContext(capabilities=frozenset(
            {"perception", "cards"}), db=db))
        p2 = filler_plugin()
        reg2.load(p2); reg2.start_all()
        assert p2.counter.total == p.counter.total >= 3

    def test_reactions_folds_mesh_events(self):
        from dreamlayer.plugins.reactions import reactions_plugin, reaction_body

        class FakeMesh:
            def receive(self, wire): return "peer"
        ctx = PluginContext(capabilities=frozenset({"cards", "mesh"}),
                            mesh=FakeMesh())
        reg = PluginRegistry(ctx)
        p = reactions_plugin()
        reg.load(p); reg.start_all()
        reg.dispatch_event("mesh", {"body": reaction_body("fire")})
        assert p.pending and p.pending[0]["emoji"] == "🔥"


# --- subprocess isolation --------------------------------------------------

HELLO_SANDBOX = '''
from dreamlayer.object_lens.schema import PanelRow

class Prov:
    facet = "own"
    name = "sandbox-hello"
    def matches(self, s): return s.label == "mug"
    def build(self, s, now=None):
        return [PanelRow(label="from the jail", detail="ok", kind="note",
                         value=None, source="sandbox-hello")]

def make():
    class P:
        name="sandbox-hello"; version="0.1.0"; requires=("object_lens",)
        def register(self, ctx): ctx.add_object_provider(Prov())
    return P()
'''

HANGING_SANDBOX = '''
def make():
    class P:
        name="hang"; version="0.1.0"; requires=("object_lens",)
        def register(self, ctx):
            import time
            class Slow:
                facet="own"; name="hang"
                def matches(self, s): time.sleep(30); return True
                def build(self, s, now=None): return []
            ctx.add_object_provider(Slow())
    return P()
'''

CRASHING_SANDBOX = '''
def make():
    class P:
        name="crash"; version="0.1.0"; requires=("object_lens",)
        def register(self, ctx):
            class Boom:
                facet="own"; name="crash"
                def matches(self, s): raise RuntimeError("child boom")
                def build(self, s, now=None): return []
            ctx.add_object_provider(Boom())
    return P()
'''


def _pkg(tmp_path, name, source):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "name": name, "version": "0.1.0", "entry": "plugin:make",
        "api": "2", "requires": ["object_lens"]}))
    (d / "plugin.py").write_text(source)
    return d


class TestSubprocessIsolation:
    def _sighting(self, label="mug"):
        from dreamlayer.object_lens.schema import ObjectSighting
        return ObjectSighting(label=label, confidence=0.9, attributes={})

    def test_provider_runs_in_child_and_rows_cross_back(self, tmp_path):
        from dreamlayer.plugins.isolation import SubprocessPluginHost
        host = SubprocessPluginHost(_pkg(tmp_path, "hello", HELLO_SANDBOX),
                                    capabilities=["object_lens"])
        try:
            assert host.start()
            orch = Orchestrator(EmulatorBridge())
            host.register_into(orch)
            panel = orch.object_lens.registry.build_panel(self._sighting("mug"))
            labels = [r.label for r in panel.rows]
            assert "from the jail" in labels
        finally:
            host.stop()

    def test_hanging_child_is_killed_not_hung(self, tmp_path):
        from dreamlayer.plugins.isolation import SubprocessPluginHost
        h = HealthLedger()
        host = SubprocessPluginHost(_pkg(tmp_path, "hang", HANGING_SANDBOX),
                                    capabilities=["object_lens"], health=h,
                                    deadline_ms=300)
        try:
            assert host.start()
            # drive a build through the proxy; the 30s child sleep must hit the
            # 300ms deadline, get abandoned, and be recorded — never hang the host
            orch = Orchestrator(EmulatorBridge())
            host.register_into(orch)
            panel = orch.object_lens.registry.build_panel(self._sighting("mug"))
            assert panel.rows == []                 # provider abandoned
            assert h.failures("plugin:hang") >= 1   # recorded
        finally:
            host.stop()

    def test_crashing_child_is_isolated(self, tmp_path):
        from dreamlayer.plugins.isolation import SubprocessPluginHost
        host = SubprocessPluginHost(_pkg(tmp_path, "crash", CRASHING_SANDBOX),
                                    capabilities=["object_lens"])
        try:
            assert host.start()
            orch = Orchestrator(EmulatorBridge())
            host.register_into(orch)
            # the child raises inside matches → host proxy returns no rows, no crash
            panel = orch.object_lens.registry.build_panel(self._sighting("mug"))
            assert panel.rows == []
        finally:
            host.stop()

    def test_side_effecting_points_are_rejected(self, tmp_path):
        from dreamlayer.plugins.isolation import SubprocessPluginHost
        src = ('def make():\n'
               '    class P:\n'
               '        name="fx"; version="0.1.0"; requires=("cards",)\n'
               '        def register(self, ctx):\n'
               '            ctx.add_card_renderer("X", lambda d,c: None)\n'
               '    return P()\n')
        host = SubprocessPluginHost(_pkg(tmp_path, "fx", src),
                                    capabilities=["cards"])
        try:
            # nothing proxyable registered → start() reports False, rejection noted
            started = host.start()
            assert "card_renderer" in host.rejected
            assert started is False
        finally:
            host.stop()
