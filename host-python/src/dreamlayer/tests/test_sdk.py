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


def test_sdk_only_plugin_validates_and_loads(tmp_path):
    pkg = sdk.PluginPackage.build(name="widget", version="1.0.0",
                                  entry="plugin:plugin", source=SDK_ONLY_SRC,
                                  author="tester", requires=("glance",))
    assert sdk.validate(pkg, host_capabilities=frozenset({"glance"})).ok
    store = PluginStore(tmp_path, host_capabilities=frozenset({"glance"}))
    assert store.install_package(pkg).ok
    orc = Orchestrator(FakeBridge())
    assert store.load_installed(orc).loaded == ["widget"]
    decision = orc.glance_arbiter.arbitrate(GlanceReading("object", 0.8, {}))
    assert decision.winner is not None and decision.winner.lens == "widget"
