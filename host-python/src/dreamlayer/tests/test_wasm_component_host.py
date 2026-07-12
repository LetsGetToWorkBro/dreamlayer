"""In-process capability-enforced WASM host: a plugin can call only the host
functions its declared capabilities link, and a module importing an undeclared
capability cannot instantiate. Real wasmtime execution (importorskip)."""
import pytest

wasmtime = pytest.importorskip("wasmtime")

from dreamlayer.plugins.wasm_component_host import (   # noqa: E402
    WasmCapabilityHost, CapabilityError, available,
)

# a module that imports dreamlayer.log and calls it from run()
WAT_LOG = ('(module (import "dreamlayer" "log" (func $log (param i32 i32))) '
           '(func (export "run") i32.const 3 i32.const 7 call $log))')
# imports dreamlayer.net_get — belongs to the `net` capability
WAT_NET = ('(module (import "dreamlayer" "net_get" (func $n (param i32) '
           '(result i32))) (func (export "run") (result i32) i32.const 1 '
           'call $n))')
# imports a host function that no capability grants
WAT_BOGUS = ('(module (import "dreamlayer" "bogus" (func $b)) '
             '(func (export "run") call $b))')
# imports from outside the host namespace entirely
WAT_ESCAPE = ('(module (import "env" "sneaky" (func $s)) '
              '(func (export "run") call $s))')
# no imports at all — pure computation
WAT_PURE = '(module (func (export "run") (result i32) i32.const 42))'


def test_available_reflects_wasmtime():
    assert available() is True


class TestCapabilityEnforcement:
    def test_granted_capability_links_and_calls(self):
        seen = []
        host = WasmCapabilityHost.from_wat(
            WAT_LOG, granted=["log"], impls={"log": lambda p, n: seen.append((p, n))})
        host.call("run")
        assert seen == [(3, 7)]                      # the host fn actually ran
        assert host.calls == [("log", "log", (3, 7))]  # audit trail

    def test_undeclared_capability_is_refused(self):
        host = WasmCapabilityHost.from_wat(WAT_NET, granted=["log"])  # not net
        with pytest.raises(CapabilityError) as ei:
            host.instantiate()
        assert "requires:[net]" in str(ei.value)

    def test_granting_the_capability_lets_it_load(self):
        host = WasmCapabilityHost.from_wat(
            WAT_NET, granted=["net"], impls={"net_get": lambda rid: 200})
        assert host.call("run") == 200

    def test_unknown_host_function_is_refused(self):
        host = WasmCapabilityHost.from_wat(WAT_BOGUS, granted=["log", "net"])
        with pytest.raises(CapabilityError) as ei:
            host.instantiate()
        assert "unknown host function" in str(ei.value)

    def test_import_outside_namespace_is_refused(self):
        host = WasmCapabilityHost.from_wat(WAT_ESCAPE, granted=["log", "net"])
        with pytest.raises(CapabilityError) as ei:
            host.instantiate()
        assert "outside the host surface" in str(ei.value)

    def test_no_imports_runs_under_zero_capabilities(self):
        host = WasmCapabilityHost.from_wat(WAT_PURE, granted=[])
        assert host.call("run") == 42

    def test_granted_but_unimpl_func_is_a_safe_stub(self):
        # `net` granted, module calls net_get, no impl provided → 0 stub, no error
        host = WasmCapabilityHost.from_wat(WAT_NET, granted=["net"])
        assert host.call("run") == 0
        assert host.calls == [("net", "net_get", (1,))]
