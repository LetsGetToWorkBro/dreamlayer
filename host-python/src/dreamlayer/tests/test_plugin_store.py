"""test_plugin_store.py — the marketplace: package, gate, and store client.

Pins the package format + integrity, the validation gate (manifest, checksum,
static scan of dangerous ops vs declared capabilities, smoke load), and the
store client (index search/rank, install refuses on a failed gate, remove,
sideload, load-installed into the orchestrator).
"""
from __future__ import annotations

import json

import pytest

from dreamlayer.reality_compiler import sign_crypto
from dreamlayer.plugins import (
    PluginManifest, PluginPackage, sha256_of, validate, scan_source,
    RegistryIndex, StoreEntry, PluginStore,
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


# -- author-shipped store detail (long/forwho/screenshot) --------------------

def test_manifest_carries_store_detail_and_it_survives_round_trip(tmp_path):
    pkg = PluginPackage.build(
        name="gadget", version="1.0.0", entry="plugin:gadget_plugin",
        source=GOOD_SRC, author="tester", description="a test gadget",
        long=("first line", "second line"), forwho="for testers",
        screenshot="https://example.test/shot.png")
    m = pkg.manifest
    assert m.long == ("first line", "second line")
    assert m.forwho == "for testers"
    assert m.screenshot == "https://example.test/shot.png"
    # and it round-trips through disk (manifest.json)
    pkg.write(tmp_path / "gadget")
    back = PluginPackage.load(tmp_path / "gadget")
    assert back.manifest.long == ("first line", "second line")
    assert back.manifest.forwho == "for testers"
    assert back.manifest.screenshot == "https://example.test/shot.png"


def test_store_detail_does_not_change_the_checksum():
    # the checksum covers the code payload only, so an author can revise their
    # write-up or screenshot without re-signing the code.
    plain = PluginPackage.build(name="gadget", version="1.0.0",
                                entry="plugin:gadget_plugin", source=GOOD_SRC)
    rich = PluginPackage.build(name="gadget", version="1.0.0",
                               entry="plugin:gadget_plugin", source=GOOD_SRC,
                               long=("a", "b"), forwho="w", screenshot="s")
    assert plain.manifest.checksum == rich.manifest.checksum
    assert rich.checksum_ok()


def test_store_entry_carries_detail_through_json():
    e = StoreEntry.from_dict({
        "name": "gadget", "version": "1.0.0",
        "long": ["p1", "p2"], "forwho": "for you",
        "screenshot": "https://example.test/s.png"})
    assert e.long == ("p1", "p2") and e.forwho == "for you"
    d = e.to_dict()
    assert d["long"] == ["p1", "p2"]
    assert d["screenshot"] == "https://example.test/s.png"


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


def test_scan_closes_egress_and_dynamic_import_gaps():
    """Audit 2026-07-14: smtplib/ftplib and importlib.import_module were exfil
    channels the scanner missed — a plugin could ship data out or dynamically
    import socket without declaring 'network'."""
    for mod in ("smtplib", "ftplib", "telnetlib", "httpx", "aiohttp"):
        src = f"import {mod}"
        assert scan_source(src, allowed_capabilities=()) != [], mod
        assert scan_source(src, allowed_capabilities=("network",)) == [], mod
    # dynamic import is forbidden outright — it launders any import past the table
    assert any("import_module" in i or "forbidden" in i
               for i in scan_source(
                   "import importlib\nimportlib.import_module('socket')",
                   allowed_capabilities=("network",)))


def test_add_knowledge_brain_requires_the_knowledge_capability():
    """Audit 2026-07-14: a knowledge tier is fed the wearer's recall query in
    every mode, so registering one must require a declared capability — a plugin
    with no grant can no longer wire a brain into the router."""
    from dreamlayer.plugins.base import PluginContext

    class Brain:
        is_cloud = is_remote = False
        def ask(self, q): return None

    class FakeRouter:
        def __init__(self): self.knowledge = []
        def add_knowledge(self, b): self.knowledge.append(b)
        def add_vision(self, b): pass

    router = FakeRouter()
    ungranted = PluginContext(brain=router, capabilities=frozenset())
    ungranted.add_knowledge_brain(Brain())
    assert router.knowledge == []                       # refused
    assert ungranted.added["knowledge_brain"] == []
    granted = PluginContext(brain=router, capabilities=frozenset({"knowledge"}))
    granted.add_knowledge_brain(Brain())
    assert len(router.knowledge) == 1                   # declared → wired


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
    # smoke load is opt-in (it runs plugin code); the author-facing gate turns
    # it on. Without run_smoke the register() break wouldn't be exercised.
    r = validate(boom, host_capabilities=frozenset(), run_smoke=True)
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
    # isolate="trusted": the curated in-process path (this package was reviewed).
    # The secure default (isolate="untrusted") routes unsigned code to the jail
    # instead — see test_default_isolates_unsigned_installed_plugin below.
    result = store.load_installed(orc, isolate="trusted")
    assert result.loaded == ["gadget"]
    # the installed plugin's lens is now live in the arbiter
    d = orc.glance_arbiter.arbitrate(GlanceReading("object", 0.8, {}))
    assert d.winner is not None and d.winner.lens == "gadget"


# an unsigned object-provider plugin — a pure-data extension point the jail can
# proxy (matches/build → panel rows), so it demonstrably crosses into isolation.
JAILABLE_SRC = '''
from dreamlayer.plugins import make_plugin
from dreamlayer.object_lens.schema import PanelRow

class MugProvider:
    facet, name = "own", "jailed-mug"
    def matches(self, s):
        return getattr(s, "label", "") == "mug"
    def build(self, s, now=None):
        return [PanelRow(label="from the jail", detail="ok", kind="note",
                         value=None, source="jailed-mug")]

def obj_plugin():
    return make_plugin("jailed-mug",
                       lambda c: c.add_object_provider(MugProvider()),
                       requires=("object_lens",))
'''


def _jailable_package():
    return PluginPackage.build(name="jailed-mug", version="1.0.0",
                               entry="plugin:obj_plugin", source=JAILABLE_SRC,
                               requires=("object_lens",))


def test_default_isolates_unsigned_installed_plugin(tmp_path):
    # P1-10: an installed, unsigned third-party package must NOT get in-process
    # authority just for being installed. The default routes it to the jail, so
    # it never appears in the in-process LoadResult — it lives in store.isolated,
    # and only its pure-data rows cross back.
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}))
    assert store.install_package(_jailable_package()).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc)              # default = "untrusted"
    try:
        assert result.loaded == []                  # never ran in-process
        assert len(store.isolated) == 1             # jailed instead
        # the provider's rows still reach the panel — through the jail, not in-process
        from dreamlayer.object_lens.schema import ObjectSighting
        panel = orc.object_lens.registry.build_panel(
            ObjectSighting(label="mug", confidence=0.9, attributes={}))
        assert "from the jail" in [r.label for r in panel.rows]
    finally:
        for h in store.isolated:
            h.stop()


@pytest.mark.skipif(not sign_crypto._HAS_CRYPTO,
                    reason="author signing needs the cryptography (privacy) extra")
def test_self_signed_plugin_is_jailed_not_run_in_process(tmp_path):
    """Audit 2026-07-14 CRITICAL: a self-signature (the attacker's own key) must
    NOT buy in-process host authority. With trusted_keys=None (the production
    default) a validly self-signed package must still go to the jail, never the
    host — only a REGISTERED publisher key earns in-process execution."""
    from dreamlayer.reality_compiler.sign_crypto import Signer
    signed_pkg = _jailable_package().sign_with(Signer(b"\x21" * 32))
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}))
    assert store.install_package(signed_pkg).ok
    # sanity: the package really is self-signed (valid signature, no registry)
    from dreamlayer.plugins.validate import validate
    rep = validate(signed_pkg, frozenset({"object_lens"}))
    assert rep.signed is True and rep.publisher == ""
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc)              # default = "untrusted", no keys
    try:
        assert result.loaded == []                  # never ran in-process
        assert len(store.isolated) == 1             # jailed instead
    finally:
        for h in store.isolated:
            h.stop()


@pytest.mark.skipif(not sign_crypto._HAS_CRYPTO,
                    reason="author signing needs the cryptography (privacy) extra")
def test_registered_publisher_runs_in_process(tmp_path):
    """The counterpart: a package signed by a key in trusted_keys IS trusted to
    run in-process, so the registry model still works for vetted publishers."""
    from dreamlayer.reality_compiler.sign_crypto import Signer
    s = Signer(b"\x33" * 32)
    signed_pkg = _jailable_package().sign_with(s)
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}),
                        trusted_keys={"vetted": s.public_key_hex})
    assert store.install_package(signed_pkg).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc)
    try:
        assert len(result.loaded) == 1              # trusted → in-process
        assert store.isolated == []
    finally:
        for h in store.isolated:
            h.stop()


# -- honest isolation posture (re-audit 2026-07) -----------------------------
# In CI there is no bwrap/nsjail and no WASM runtime, so the untrusted jail is a
# plain subprocess: process isolation, but no kernel boundary. That degradation
# used to be silent; these pin that it is now loud, and fail-closable.

def _no_kernel_sandbox(monkeypatch):
    """Force the 'no OS/WASM sandbox available' posture regardless of host."""
    import dreamlayer.plugins.os_sandbox as osb
    import dreamlayer.plugins.wasm_host as wh
    monkeypatch.setattr(osb, "available", lambda: None)
    monkeypatch.setattr(wh, "available", lambda: False)


def test_degraded_isolation_is_recorded_not_silent(tmp_path, monkeypatch):
    _no_kernel_sandbox(monkeypatch)
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}))
    assert store.install_package(_jailable_package()).ok
    orc = Orchestrator(FakeBridge())
    store.load_installed(orc)                       # permissive default
    try:
        # still loaded (permissive), but the degraded posture is on the record
        assert len(store.isolated) == 1
        assert store.isolation_notices, "degraded load must be surfaced"
        assert any("no OS/WASM sandbox" in n for n in store.isolation_notices)
    finally:
        for h in store.isolated:
            h.stop()


def test_require_sandbox_fails_closed_without_kernel_boundary(tmp_path, monkeypatch):
    _no_kernel_sandbox(monkeypatch)
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}))
    assert store.install_package(_jailable_package()).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc, require_sandbox=True)
    # fail closed: the plugin is NOT run at all without a real kernel boundary
    assert result.loaded == []
    assert store.isolated == []
    assert any("no OS/WASM sandbox" in n for n in store.isolation_notices)
    # and its rows never reached the panel
    from dreamlayer.object_lens.schema import ObjectSighting
    panel = orc.object_lens.registry.build_panel(
        ObjectSighting(label="mug", confidence=0.9, attributes={}))
    assert "from the jail" not in [r.label for r in panel.rows]


def test_require_sandbox_honors_env(tmp_path, monkeypatch):
    _no_kernel_sandbox(monkeypatch)
    monkeypatch.setenv("DL_REQUIRE_SANDBOX", "1")
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}))
    assert store.install_package(_jailable_package()).ok
    orc = Orchestrator(FakeBridge())
    store.load_installed(orc)                        # env drives fail-closed
    assert store.isolated == []


# -- capability enforcement at the ctx.add_* call sites (audit 2026-07-14) ----
# The extension-point capabilities used to be advisory (declared in docs, never
# checked where the plugin actually reaches). These pin that the grant is now
# enforced at the call site, so an undeclared reach is refused — reverting the
# guard makes these fail.

def test_add_object_provider_requires_the_object_lens_capability():
    from dreamlayer.plugins.base import PluginContext
    from dreamlayer.object_lens.providers import ProviderRegistry

    class Prov:
        facet, name = "own", "p"
        def matches(self, s): return True
        def build(self, s, now=None): return []

    reg = ProviderRegistry()
    ungranted = PluginContext(object_registry=reg, capabilities=frozenset())
    ungranted.add_object_provider(Prov())
    assert ungranted.added["object_provider"] == []          # refused
    assert ("object_provider", "object_lens") in ungranted.added.get("rejected", [])
    assert reg.providers == [] if hasattr(reg, "providers") else True

    granted = PluginContext(object_registry=reg,
                            capabilities=frozenset({"object_lens"}))
    granted.add_object_provider(Prov())
    assert len(granted.added["object_provider"]) == 1        # declared → wired


def test_add_shop_provider_requires_shop_or_network():
    from dreamlayer.plugins.base import PluginContext
    reg: list = []
    ungranted = PluginContext(shop_registry=reg, capabilities=frozenset())
    ungranted.add_shop_provider(lambda label, attrs: {"rating": 5.0})
    assert reg == [] and ungranted.added["shop_provider"] == []   # refused
    # either the commerce entitlement OR its egress channel satisfies it
    for cap in ("shop", "network"):
        r2: list = []
        ok = PluginContext(shop_registry=r2, capabilities=frozenset({cap}))
        ok.add_shop_provider(lambda label, attrs: {"rating": 5.0})
        assert len(r2) == 1, cap


def test_scan_flags_smtplib_ftplib_telnetlib_without_network():
    # audit 2026-07-14: the old _DANGER_IMPORTS omitted these egress modules, so
    # a plugin could exfiltrate over SMTP/FTP/telnet without declaring 'network'.
    for mod in ("smtplib", "ftplib", "telnetlib"):
        assert scan_source(f"import {mod}\n", ()), f"{mod} not flagged"
        # declaring network mediates it (a real capability gate, not a ban)
        assert scan_source(f"import {mod}\n", {"network"}) == [], mod
    # importlib.import_module is a forbidden dynamic-import laundering channel
    assert scan_source("import importlib\nimportlib.import_module('socket')\n",
                       {"network"}), "importlib.import_module not flagged"


# -- the memory facade: capability + veil gated (audit 2026-07-14 CRITICAL) ---
# The raw MemoryDB used to be reachable in-process; now the ONLY supported
# memory surface is ctx.memory, which refuses a plugin lacking the 'memory'
# capability and returns nothing while the Veil is up. Reverting either gate
# makes these fail.

def test_plugin_memory_facade_denies_without_the_memory_capability():
    from dreamlayer.plugins.base import PluginContext
    from dreamlayer.memory.db import MemoryDB

    db = MemoryDB()
    db.add_memory("fact", "the wearer's private secret")

    no_cap = PluginContext(db=db, capabilities=frozenset())
    with pytest.raises(PermissionError):
        no_cap.memory.memories()                 # undeclared reach → refused
    with pytest.raises(PermissionError):
        no_cap.memory.commitments()
    with pytest.raises(PermissionError):
        no_cap.memory.places()

    granted = PluginContext(db=db, capabilities=frozenset({"memory"}))
    got = granted.memory.memories()
    assert any("private secret" in m.get("summary", "") for m in got)


def test_plugin_memory_facade_is_veil_gated():
    from dreamlayer.plugins.base import PluginContext
    from dreamlayer.memory.db import MemoryDB
    from dreamlayer.memory.privacy import PrivacyGate

    db = MemoryDB()
    db.add_memory("fact", "recallable while unveiled")
    gate = PrivacyGate()
    ctx = PluginContext(db=db, capabilities=frozenset({"memory"}), veil=gate)

    assert ctx.memory.memories()                 # unveiled → readable
    gate.pause()                                 # Veil up → recall blocked
    assert ctx.memory.memories() == []           # nothing crosses the Veil
    gate.resume()
    assert ctx.memory.memories()                 # readable again
