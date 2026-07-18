"""test_sdk.py — the public authoring surface (dreamlayer.sdk).

Pins that the facade re-exports (not re-defines) the real extension points, that
its surface is complete and versioned, that importing it stays lightweight, and
that a plugin written against *only* dreamlayer.sdk passes the gate and loads
into a live orchestrator.
"""
from __future__ import annotations

import re
import subprocess
import sys

import dreamlayer.sdk as sdk
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.glance import GlanceReading
from dreamlayer.plugins import PluginStore
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def test_all_exports_resolve():
    missing = [n for n in sdk.__all__ if not hasattr(sdk, n)]
    assert not missing, f"missing exports: {missing}"


def test_version_is_semver_and_api_is_latest():
    assert re.match(r"^\d+\.\d+\.\d+$", sdk.__version__)
    assert sdk.API in sdk.SUPPORTED_API
    assert sdk.API == max(sdk.SUPPORTED_API, key=int)


def test_facade_reexports_identity_not_copies():
    # the SDK must hand back the *same* classes the host uses, or a plugin's
    # PanelProvider/AudioPercept wouldn't be recognised by the host registries.
    from dreamlayer.object_lens.providers import PanelProvider
    from dreamlayer.object_lens.schema import PanelRow, ObjectSighting
    from dreamlayer.orchestrator.glance import LensCandidate, LensBid
    from dreamlayer.ai_brain.perception import AudioPercept
    assert sdk.PanelProvider is PanelProvider
    assert sdk.PanelRow is PanelRow and sdk.ObjectSighting is ObjectSighting
    assert sdk.LensCandidate is LensCandidate and sdk.LensBid is LensBid
    assert sdk.AudioPercept is AudioPercept


def test_first_party_plugins_import_via_the_sdk():
    # dogfood: the shipped plugins depend on the facade, not host internals.
    import inspect
    import dreamlayer.plugins.currency as currency
    import dreamlayer.plugins.filler as filler
    assert "from dreamlayer.sdk import" in inspect.getsource(currency)
    assert "from dreamlayer.sdk import" in inspect.getsource(filler)
    assert "object_lens.providers" not in inspect.getsource(currency)  # no deep import
    # functional proof: they still construct
    assert currency.currency_plugin().requires == ("object_lens", "network")
    assert filler.filler_plugin().requires == ("perception", "cards")


def test_sdk_import_is_lightweight():
    # a plugin author shouldn't drag torch/fastapi/etc. in just to import the SDK
    code = ("import sys, dreamlayer.sdk;"
            "print(','.join(m for m in "
            "('torch','fastapi','uvicorn','ultralytics','moondream','open_clip') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"sdk import pulled heavy modules: {out.stdout!r}"


# a complete plugin written against ONLY the SDK surface -----------------------
SDK_ONLY_SRC = '''
from dreamlayer.sdk import make_plugin, LensCandidate, LensBid

class WidgetCandidate(LensCandidate):
    lens, label = "widget", "Widget"
    def bid(self, reading, ctx):
        if reading.scene == "object":
            return LensBid(self.lens, self.label, 0.99, "widget", reason="widget")
        return None

def plugin():
    return make_plugin("widget", lambda c: c.add_glance_candidate(WidgetCandidate()),
                       requires=("glance",))
'''


def test_context_protocol_and_manifest_typeddict():
    from dreamlayer.sdk import PluginContextProtocol
    from dreamlayer.plugins.base import PluginContext
    assert isinstance(PluginContext(), PluginContextProtocol)   # structural conformance
    m: sdk.ManifestDict = {"name": "x", "version": "1.0.0", "entry": "p:f"}
    assert sdk.PluginManifest.from_dict(m).name == "x"


def test_min_sdk_gate():
    from dreamlayer.sdk import sdk_supports, SDK_VERSION
    assert sdk_supports("") and sdk_supports("1.0.0") and sdk_supports(SDK_VERSION)
    assert not sdk_supports("99.0.0")
    pkg = sdk.PluginPackage.build(name="future", version="1.0.0",
                                  entry="plugin:plugin", source=SDK_ONLY_SRC,
                                  requires=("glance",))
    pkg.manifest.min_sdk = "99.0.0"             # needs a newer SDK than the host
    r = sdk.validate(pkg, host_capabilities=frozenset({"glance"}))
    assert not r.ok and any("SDK >=" in e for e in r.errors)


def test_discover_returns_a_list():
    # no dreamlayer.plugins entry points are declared in the test env → []
    assert isinstance(sdk.discover(), list)


def test_render_card_through_the_real_device_renderer():
    import numpy as np
    from dreamlayer.plugins.filler import filler_plugin
    img = sdk.render_card(filler_plugin(), {"type": "FillerCard", "count": 3})
    assert img.size == (256, 256)
    # the card actually drew text (not a blank frame): bright pixels + the
    # antialiasing that a real font render produces
    rgb = np.asarray(img.convert("RGB"))
    assert int((rgb.sum(axis=-1) > 60).sum()) > 50
    assert len(set(map(tuple, rgb.reshape(-1, 3)))) > 10


def test_render_card_is_deterministic_and_data_sensitive():
    # deterministic render = snapshot/visual-regression testable; and the card
    # data actually changes the pixels.
    from dreamlayer.plugins.filler import filler_plugin
    a = sdk.render_card(filler_plugin(), {"type": "FillerCard", "count": 3}).tobytes()
    b = sdk.render_card(filler_plugin(), {"type": "FillerCard", "count": 3}).tobytes()
    c = sdk.render_card(filler_plugin(), {"type": "FillerCard", "count": 9}).tobytes()
    assert a == b and a != c


def test_render_card_provider_only_raises_and_types():
    import pytest
    from dreamlayer.plugins.currency import currency_plugin
    from dreamlayer.plugins.filler import filler_plugin
    assert sdk.registered_card_types(filler_plugin()) == ["FillerCard"]
    assert sdk.registered_card_types(currency_plugin()) == []
    with pytest.raises(ValueError):
        sdk.render_card(currency_plugin())


def test_preview_grants_only_declared_capabilities_not_everything():
    """REVERT-FAILING: the author-only preview harness EXECUTES an untrusted
    package's register(), so it must run it with the plugin's DECLARED caps
    only (plus the always-open object_lens/glance/cards surfaces smoke_load
    grants) — never all of KNOWN_CAPABILITIES. Before the fix the preview built
    a PluginContext over the full KNOWN set, a second ungated full-capability
    grant outside the device's fail-closed load path: a "what does this plugin
    do" call would hand register() network/vision/memory/… it never asked for.
    """
    from dreamlayer.sdk import make_plugin
    from dreamlayer.plugins.package import KNOWN_CAPABILITIES

    seen: dict = {}

    def spy(ctx):
        seen["caps"] = ctx.capabilities
        seen["network"] = ctx.has("network")

    # requires=() → declares NOTHING; reaching for an undeclared cap (network)
    # must be refused. The preview context must equal the always-open set only.
    sdk.contributions(make_plugin("greedy", spy, requires=()))
    assert seen["caps"] == frozenset({"object_lens", "glance", "cards"})
    assert seen["network"] is False
    assert "network" not in seen["caps"]
    # the exact bug this guards against: the old harness granted the full set
    assert seen["caps"] != frozenset(KNOWN_CAPABILITIES)

    # and a DECLARED capability IS granted (well-behaved plugins are unchanged)
    sdk.contributions(make_plugin("net", spy, requires=("network",)))
    assert seen["network"] is True
    assert seen["caps"] == frozenset({"network", "object_lens", "glance", "cards"})


def test_resolve_hardens_malformed_requires():
    """``_resolve`` must survive the ugly shapes a plugin's ``.requires`` can
    take — ``None`` (crashed ``frozenset(None)``) and a bare ``str`` (splatted
    ``frozenset("network")`` → per-character garbage caps) — without crashing
    or granting bogus caps, while still returning exactly
    ``declared | _ALWAYS_AVAILABLE`` (never an escalation).

    The returned caps ARE the PluginContext capabilities the preview hands to a
    plugin's ``register()`` (see ``registered_card_types``/``contributions``),
    so this pins the context grant directly."""
    from dreamlayer.sdk import make_plugin
    from dreamlayer.sdk.preview import _resolve, _as_caps, _ALWAYS_AVAILABLE
    from dreamlayer.plugins.base import SimplePlugin

    def _plugin_with_requires(requires):
        # bypass make_plugin's tuple() coercion to plant a raw .requires value
        p = SimplePlugin(name="raw", register_fn=lambda ctx: None)
        p.requires = requires
        return p

    # 1. requires=None → no crash; caps are exactly the always-open set
    _obj, caps = _resolve(_plugin_with_requires(None))
    assert caps == _ALWAYS_AVAILABLE

    # 2. requires="network" (a bare STRING) → the single capability "network",
    #    NOT the splatted characters {'n','e','t','w','o','r','k'}
    _obj, caps = _resolve(_plugin_with_requires("network"))
    assert "network" in caps
    assert caps == frozenset({"network"}) | _ALWAYS_AVAILABLE
    for ch in ("n", "e", "t", "w", "o", "r", "k"):
        assert ch not in caps

    # 3. a normal tuple still works
    _obj, caps = _resolve(make_plugin("mem", lambda ctx: None, requires=("memory",)))
    assert caps == frozenset({"memory"}) | _ALWAYS_AVAILABLE

    # 4. an unknown shape (e.g. an int) → nothing declared, no crash
    _obj, caps = _resolve(_plugin_with_requires(12345))
    assert caps == _ALWAYS_AVAILABLE

    # helper unit checks: coercion never invents a cap, never splats a string
    assert _as_caps(None) == frozenset()
    assert _as_caps("network") == frozenset({"network"})
    assert _as_caps(("a", "b")) == frozenset({"a", "b"})
    assert _as_caps(["a"]) == frozenset({"a"})
    assert _as_caps(frozenset({"a"})) == frozenset({"a"})
    assert _as_caps(object()) == frozenset()


def test_package_from_dir_builds_a_valid_package(tmp_path):
    # the helper the CLI and every scaffold test use
    (tmp_path / "plugin.py").write_text(SDK_ONLY_SRC, encoding="utf-8")
    (tmp_path / "plugin.json").write_text(
        '{"name":"widget","version":"1.0.0","entry":"plugin:plugin",'
        '"requires":["glance"]}', encoding="utf-8")
    pkg = sdk.package_from_dir(tmp_path)
    assert pkg.manifest.name == "widget" and pkg.checksum_ok()
    assert sdk.validate(pkg, host_capabilities=frozenset({"glance"})).ok
    import pytest
    with pytest.raises(FileNotFoundError):
        sdk.package_from_dir(tmp_path / "nope")


def test_sdk_only_plugin_validates_and_loads(tmp_path):
    pkg = sdk.PluginPackage.build(name="widget", version="1.0.0",
                                  entry="plugin:plugin", source=SDK_ONLY_SRC,
                                  author="tester", requires=("glance",))
    assert sdk.validate(pkg, host_capabilities=frozenset({"glance"})).ok
    store = PluginStore(tmp_path, host_capabilities=frozenset({"glance"}))
    assert store.install_package(pkg).ok
    orc = Orchestrator(FakeBridge())
    # isolate="trusted": load this reviewed package in-process (the secure
    # default jails unsigned code — covered in test_plugin_store.py).
    assert store.load_installed(orc, isolate="trusted").loaded == ["widget"]
    decision = orc.glance_arbiter.arbitrate(GlanceReading("object", 0.8, {}))
    assert decision.winner is not None and decision.winner.lens == "widget"
