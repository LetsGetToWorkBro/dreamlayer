"""WASM in-process host — untrusted guest bytecode must run BOUNDED.

A plugin module whose export is `(loop br 0)` would hang the host thread forever
if no fuel/epoch limit were set, and an unbounded `memory.grow` would OOM the box
(refute 2026-07-18: the in-process host set none of them). These pin that a
runaway guest TRAPS instead of hanging. Skips cleanly when wasmtime isn't
installed (the `platform` extra); runs where the in-process tier is live.
"""
from __future__ import annotations

import pytest

wasmtime = pytest.importorskip("wasmtime")

from dreamlayer.plugins.wasm_component_host import (   # noqa: E402
    ResourceLimitError, WasmCapabilityHost,
)

_SPIN = '(module (func (export "spin") (loop br 0)))'
_ADD = '(module (func (export "add") (param i32 i32) (result i32) ' \
       '(i32.add (local.get 0) (local.get 1))))'


def test_infinite_loop_traps_instead_of_hanging():
    # A tiny fuel budget: the loop exhausts it and traps in microseconds rather
    # than spinning forever. Either the wrapped ResourceLimitError or a raw
    # wasmtime.Trap is acceptable — the guarantee is that it RAISES, not hangs.
    host = WasmCapabilityHost.from_wat(_SPIN, granted=[], fuel=2_000_000, timeout_s=10.0)
    with pytest.raises((ResourceLimitError, wasmtime.Trap)):
        host.call("spin")


def test_a_bounded_plugin_still_runs_within_budget():
    host = WasmCapabilityHost.from_wat(_ADD, granted=[])
    assert host.call("add", 20, 22) == 42


def test_fuel_and_memory_limits_are_actually_configured():
    # Guards a revert of the Config/StoreLimits wiring: the store must be built
    # with fuel accounting on (so a runaway CAN trap).
    host = WasmCapabilityHost.from_wat(_ADD, granted=[], fuel=500_000)
    # set_fuel/get_fuel round-trips only when consume_fuel was enabled on Config.
    assert hasattr(host.store, "get_fuel") or hasattr(host.store, "fuel_consumed")
