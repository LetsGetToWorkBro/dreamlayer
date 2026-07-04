"""test_plugin_store.py — the marketplace: package, gate, and store client.

Pins the package format + integrity, the validation gate (manifest, checksum,
static scan of dangerous ops vs declared capabilities, smoke load), and the
store client (index search/rank, install refuses on a failed gate, remove,
sideload, load-installed into the orchestrator).
"""
from __future__ import annotations

import json

from dreamlayer.plugins import (
    PluginManifest, PluginPackage, sha256_of, validate, scan_source,
    ValidationReport, RegistryIndex, StoreEntry, PluginStore,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.glance import GlanceReading
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# a clean, well-behaved plugin: adds a glance candidate, nothing dangerous
GOOD_SRC = '''
from dreamlayer.plugins import make_plugin
from dreamlayer.orchestrator.glance import LensCandidate, LensBid

class GadgetCandidate(LensCandidate):
    lens, label = "gadget", "Gadget"
    def bid(self, reading, ctx):
        if reading.scene == "object":
            return LensBid(self.lens, self.label, 0.99, "gadget", reason="gadget")
        return None

def gadget_plugin():
    return make_plugin("gadget", lambda c: c.add_glance_candidate(GadgetCandidate()))
'''


def good_package():
    return PluginPackage.build(name="gadget", version="1.0.0",
                               entry="plugin:gadget_plugin", source=GOOD_SRC,
                               author="tester", description="a test gadget")


# -- package format + integrity ----------------------------------------------

def test_manifest_shape_is_validated():
    m = PluginManifest(name="Bad Name", version="1", entry="nope", api="9")
    probs = " ".join(m.problems())
    assert "bad name" in probs and "bad version" in probs and "bad entry" in probs
    assert "unsupported api" in probs


def test_build_stamps_a_matching_checksum():
    pkg = good_package()
    assert pkg.checksum_ok()
    pkg.source += "\n# tampered\n"
    assert not pkg.checksum_ok()               # integrity catches the edit


def test_package_disk_round_trip(tmp_path):
    good_package().write(tmp_path / "gadget")
    back = PluginPackage.load(tmp_path / "gadget")
    assert back.manifest.name == "gadget" and back.checksum_ok()


# -- the static scan ----------------------------------------------------------

def test_scan_flags_dangerous_ops_without_capability():
    issues = scan_source("import os\nos.system('rm -rf /')", allowed_capabilities=())
    assert any("os.system" in i for i in issues)
    issues2 = scan_source("eval('2+2')", allowed_capabilities=())
    assert any("eval()" in i for i in issues2)


def test_scan_allows_declared_capability():
    src = "import socket\ns = socket.socket()"
    assert scan_source(src, allowed_capabilities=()) != []       # undeclared → flagged
    assert scan_source(src, allowed_capabilities=("network",)) == []  # declared → ok


def test_scan_reports_syntax_errors():
    assert any("syntax error" in i for i in scan_source("def (:", ()))


# -- the whole gate -----------------------------------------------------------

def test_validate_passes_a_clean_plugin():
    r = validate(good_package(), host_capabilities=frozenset({"glance"}))
    assert r.ok and not r.errors


def test_validate_fails_a_tampered_checksum():
    pkg = good_package()
    pkg.source += "\n# sneaky\n"               # checksum no longer matches
    r = validate(pkg, host_capabilities=frozenset({"glance"}))
    assert not r.ok and any("checksum" in e for e in r.errors)


def test_validate_fails_dangerous_undeclared_code():
    bad = PluginPackage.build(name="sneaky", version="1.0.0",
                              entry="plugin:p",
                              source="import subprocess\ndef p():\n return None")
    r = validate(bad, host_capabilities=frozenset())
    assert not r.ok and any("subprocess" in e for e in r.errors)


def test_validate_fails_a_plugin_the_device_cannot_grant():
    needs = PluginPackage.build(name="needs-midi", version="1.0.0",
                                entry="plugin:p", requires=("midi",),
                                source="from dreamlayer.plugins import make_plugin\n"
                                       "def p():\n return make_plugin('needs-midi', lambda c: None, requires=('midi',))")
    # host has no midi → hard error (can't run here safely)
    r = validate(needs, host_capabilities=frozenset({"glance"}))
    assert not r.ok and any("midi" in e for e in r.errors)


def test_validate_catches_a_plugin_that_throws_on_register():
    boom = PluginPackage.build(name="boom", version="1.0.0", entry="plugin:p",
                               source="from dreamlayer.plugins import make_plugin\n"
                                      "def _r(c):\n raise RuntimeError('boom')\n"
                                      "def p():\n return make_plugin('boom', _r)")
    r = validate(boom, host_capabilities=frozenset())
    assert not r.ok and any("register()" in e for e in r.errors)


# -- the registry index -------------------------------------------------------

def sample_index():
    return RegistryIndex.from_dict({"plugins": [
        {"name": "gadget", "version": "1.0.0", "url": "u/gadget",
         "checksum": good_package().manifest.checksum, "requires": ["glance"],
         "downloads": 500, "rating": 4.8, "ratings_count": 40, "tags": ["fun"]},
        {"name": "widget", "version": "2.0.0", "url": "u/widget",
         "downloads": 1500, "rating": 4.2, "tags": ["util"]},
    ]})


def test_index_search_and_rank():
    idx = sample_index()
    assert {e.name for e in idx.search("fun")} == {"gadget"}
    assert idx.top(by="downloads", n=1)[0].name == "widget"
    assert idx.top(by="rating", n=1)[0].name == "gadget"


# -- the store client: install / remove / load -------------------------------

def _fetch_for(pkg):
    def fetch(url):
        return json.dumps({"manifest": pkg.manifest.to_dict(), "source": pkg.source})
    return fetch


def test_install_refuses_a_plugin_that_fails_the_gate(tmp_path):
    pkg = good_package()
    pkg.source += "\nimport os\nos.system('bad')\n"
    pkg.manifest.checksum = sha256_of(pkg.source)   # honest checksum, still dangerous
    store = PluginStore(tmp_path, index=sample_index(), fetch_fn=_fetch_for(pkg),
                        host_capabilities=frozenset({"glance"}))
    # index still advertises the clean checksum → mismatch OR scan will fail
    report = store.install("gadget")
    assert not report.ok
    assert store.installed() == []                  # nothing written


def test_install_then_remove(tmp_path):
    pkg = good_package()
    store = PluginStore(tmp_path, index=sample_index(), fetch_fn=_fetch_for(pkg),
                        host_capabilities=frozenset({"glance"}))
    report = store.install("gadget")
    assert report.ok and store.installed() == ["gadget"]
    assert store.is_installed("gadget")
    assert store.remove("gadget") and store.installed() == []


def test_sideload_and_load_into_orchestrator(tmp_path):
    store = PluginStore(tmp_path, host_capabilities=frozenset({"glance"}))
    assert store.install_package(good_package()).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc)
    assert result.loaded == ["gadget"]
    # the installed plugin's lens is now live in the arbiter
    d = orc.glance_arbiter.arbitrate(GlanceReading("object", 0.8, {}))
    assert d.winner is not None and d.winner.lens == "gadget"
