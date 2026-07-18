"""WASM Component Model contract (WIT) — the plugin capability surface, formalised
(D8).

wasm_component_host runs a plugin in-process with zero ambient authority: it may
call only the host functions of the capabilities its manifest declares. That
surface was an ad-hoc ptr/len catalog in Python with no formal contract (refute
2026-07-18). dreamlayer.wit now states it as a real Component Model `world`;
these pin that the shipped WIT parses, that its interfaces match the runtime
catalog exactly (so contract and binding can't drift), and that the world grants
every capability the host knows how to link.

The full component-model *instantiation* (wasmtime's component API) is a
toolchain follow-up; the WIT is the source of truth today and the cross-check
below is what keeps the interim core-ABI binding honest against it.
"""
from __future__ import annotations

import os

from dreamlayer.plugins import wasm_component_host as wch


def test_wit_file_ships_and_parses():
    assert os.path.exists(wch.wit_path())
    text = wch.wit_world()
    assert "world plugin" in text
    assert "package dreamlayer:host" in text


def test_wit_interfaces_match_the_runtime_catalog():
    """The formal contract and the host's intended function surface must be
    identical — this is the anti-drift check the WIT exists to enable."""
    assert wch.wit_interface_functions() == wch.capability_function_names()


def test_world_imports_every_known_capability():
    """A plugin's grantable surface (the world's imports) is exactly the set of
    capabilities the host can link — no interface is declared but ungrantable, or
    grantable but undeclared."""
    assert wch.wit_world_imports() == set(wch.capability_function_names())


def test_each_interface_declares_at_least_one_func():
    for iface, funcs in wch.wit_interface_functions().items():
        assert funcs, f"interface {iface} declares no functions"


def test_catalog_matches_wit_when_wasmtime_present():
    """When wasmtime is installed, the live `_catalog` (with ValType sigs) must
    expose exactly the WIT function names — closes the loop from contract →
    pure-data names → runtime catalog."""
    import pytest
    pytest.importorskip("wasmtime")
    catalog = wch._catalog()
    live = {cap: set(funcs) for cap, funcs in catalog.items()}
    assert live == wch.wit_interface_functions()
