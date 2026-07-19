"""test_first_party_pins.py — the keyless first-party trust anchor.

The reviewed first-party catalogue earns in-process execution by a CONTENT-HASH
pin (plugins/first_party.json), not a signing key. This is what lets the bundled
connector plugins actually run on Windows/Mac, where no kernel sandbox
(bwrap/nsjail) exists and an unpinned plugin fails closed.

These pin: (1) the pins never drift from the registry sources they mirror,
(2) the pin grants in-process trust ONLY on an exact source-byte match — a
look-alike that borrows a first-party name but ships different code is refused
and fails closed, and (3) the Brain actually wires the pins in.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dreamlayer.plugins import (PluginManifest, PluginPackage, PluginStore,
                                sha256_of)
from dreamlayer.plugins.store import (load_first_party_pins,
                                      _FIRST_PARTY_PUBLISHER)
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge
from dreamlayer.tests.test_plugin_store import _jailable_package

# repo-root/registry/packages — present in a source checkout (how CI runs).
_REGISTRY = Path(__file__).resolve().parents[4] / "registry" / "packages"
_needs_registry = pytest.mark.skipif(
    not _REGISTRY.is_dir(), reason="registry/ is only present in a source checkout")


def _no_kernel_sandbox(monkeypatch):
    """Force the 'no OS/WASM sandbox available' posture — i.e. Windows/Mac, and
    CI. Without this the host might actually have bwrap and mask the point."""
    import dreamlayer.plugins.os_sandbox as osb
    import dreamlayer.plugins.wasm_host as wh
    monkeypatch.setattr(osb, "available", lambda: None)
    monkeypatch.setattr(wh, "available", lambda: False)


def _registry_packages():
    for p in sorted(_REGISTRY.glob("*.json")):
        d = json.loads(p.read_text())
        yield p.name, d["manifest"], d["source"]


# -- 1. the pins never drift from the registry -------------------------------

@_needs_registry
def test_pins_match_every_official_registry_source():
    """Each pin must equal sha256(the exact registry source), which must equal
    that package's advertised checksum. If a first-party plugin's code changes
    without first_party.json being regenerated, this fails loudly — the pin
    would otherwise silently miss and drop the plugin back into the jail."""
    pins = load_first_party_pins()
    seen = set()
    for fname, manifest, source in _registry_packages():
        h = sha256_of(source)
        assert h == manifest["checksum"], f"{fname}: checksum != sha256(source)"
        if manifest.get("official"):
            name = manifest["name"]
            seen.add(name)
            assert name in pins, f"official plugin {name} is not pinned"
            assert pins[name] == h, f"{name}: first_party.json pin != source hash"
    # and no stray pins that don't correspond to an official registry plugin
    assert set(pins) == seen, f"pins without an official package: {set(pins) - seen}"


@_needs_registry
def test_load_first_party_pins_ships_the_catalogue():
    pins = load_first_party_pins()
    assert len(pins) == 8
    assert all(v.startswith("sha256:") for v in pins.values())


# -- 2. the pin grants trust only on an exact source-byte match --------------

@_needs_registry
def test_real_first_party_source_is_recognized(tmp_path):
    d = json.loads((_REGISTRY / "open-library-0.1.0.json").read_text())
    pkg = PluginPackage(manifest=PluginManifest.from_dict(d["manifest"]),
                        source=d["source"])
    store = PluginStore(tmp_path, first_party=load_first_party_pins())
    assert store._first_party_publisher(pkg) == _FIRST_PARTY_PUBLISHER


@_needs_registry
def test_tampered_first_party_source_is_rejected(tmp_path):
    """Same name, one byte of extra source → pin misses → not first-party."""
    d = json.loads((_REGISTRY / "open-library-0.1.0.json").read_text())
    pkg = PluginPackage(manifest=PluginManifest.from_dict(d["manifest"]),
                        source=d["source"] + "\n# sneaked in\n")
    store = PluginStore(tmp_path, first_party=load_first_party_pins())
    assert store._first_party_publisher(pkg) == ""


def test_no_pins_means_no_first_party_trust(tmp_path):
    """A bare store (default) trusts no one first-party — the grant must be
    explicit at the wiring site, never implicit."""
    pkg = _jailable_package()
    assert PluginStore(tmp_path)._first_party_publisher(pkg) == ""


# -- 3. end-to-end: a pinned plugin runs in-process where others fail closed --

def test_pinned_plugin_runs_in_process_without_a_kernel_sandbox(tmp_path, monkeypatch):
    """The whole point: with no bwrap/nsjail/WASM and require_sandbox=True (the
    world-lens posture), an UNPINNED plugin fails closed — but a first-party
    PINNED plugin still loads in-process. Mirrors
    test_registered_publisher_runs_in_process, but trust comes from the content
    pin, not a signing key."""
    _no_kernel_sandbox(monkeypatch)
    pkg = _jailable_package()
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}),
                        first_party={pkg.manifest.name: sha256_of(pkg.source)})
    assert store.install_package(pkg).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc, require_sandbox=True)
    try:
        assert len(result.loaded) == 1     # pinned → in-process, not jailed
        assert store.isolated == []        # not routed to an isolation host
    finally:
        for h in store.isolated:
            h.stop()


def test_lookalike_first_party_name_fails_closed(tmp_path, monkeypatch):
    """A plugin that claims a pinned NAME but ships different bytes must miss the
    pin and hit the ordinary fail-closed path — never in-process, never jailed
    without a boundary."""
    _no_kernel_sandbox(monkeypatch)
    pkg = _jailable_package()
    store = PluginStore(tmp_path, host_capabilities=frozenset({"object_lens"}),
                        # pin the right name to the WRONG hash → no match
                        first_party={pkg.manifest.name: "sha256:" + "0" * 64})
    assert store.install_package(pkg).ok
    orc = Orchestrator(FakeBridge())
    result = store.load_installed(orc, require_sandbox=True)
    assert result.loaded == []             # not trusted → not run in-process
    assert store.isolated == []            # and fail-closed → not jailed either
    assert any("no OS/WASM sandbox" in n for n in store.isolation_notices)


# -- 4. the Brain wires the pins in ------------------------------------------

def test_brain_wires_the_first_party_pins(tmp_path):
    from dreamlayer.ai_brain.server import Brain
    b = Brain(tmp_path)
    assert len(b.plugins.first_party) == 8
    assert all(v.startswith("sha256:") for v in b.plugins.first_party.values())
