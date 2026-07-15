"""plugins/wasm_component_host.py — in-process, capability-*enforced* WASM host.

The subprocess/WASI tier (wasm_host.py) confines a plugin from the *outside*
(no --dir, no network grant). This is the complementary, stronger idea the
research surfaced (Extism / the Wasmtime Component Model): run the plugin's WASM
**in-process** under wasmtime-py, where the guest has zero ambient authority and
can only call **host functions the host explicitly links** — so the capability
manifest is enforced by the runtime, not merely declared.

The mapping is exact: each declared capability materializes one or more host
functions the guest may import; a *denied* capability is a host function that is
simply never linked, so a module that imports it **cannot instantiate**. We
pre-scan the module's imports and refuse — with a precise "imports undeclared
capability X" error — before anything runs. This closes manifest-vs-reality
drift at the hardest layer: a forged plugin that calls a power it never declared
fails to load at all.

Lazy dependency (extras group ``plugins``): ``available()`` is False when
wasmtime-py isn't installed, and callers fall back to the subprocess/WASI tier.

    host = WasmCapabilityHost(wasm_bytes, granted=["log"], impls={"log": fn})
    inst = host.instantiate()           # raises CapabilityError on undeclared use
    host.call("run", 21)
"""
from __future__ import annotations

import logging

log = logging.getLogger("dreamlayer.wasm_component_host")

try:  # optional dep — extras group `plugins`
    import wasmtime  # type: ignore
    _HAS_WASMTIME = True
except Exception:
    wasmtime = None                     # type: ignore
    _HAS_WASMTIME = False

# The host-function surface, grouped by capability. The guest imports these from
# the "dreamlayer" module; only the functions of *granted* capabilities are
# linked. Each entry: import name -> (param ValTypes, result ValTypes) as a
# lazy factory (ValType objects need wasmtime present). Keep this small and
# auditable — it is the trusted boundary.
def _catalog():
    i32 = wasmtime.ValType.i32
    return {
        # a plugin that only wants to speak to the host log needs just this
        "log":  {"log": ([i32(), i32()], [])},          # (ptr, len) -> ()
        # read a byte from the granted package sandbox
        "fs":   {"fs_read": ([i32()], [i32()])},        # (offset) -> byte
        # a single mediated fetch handle (host decides what it means)
        "net":  {"net_get": ([i32()], [i32()])},        # (req_id) -> status
        # surface a card to the wearer
        "cards": {"show_card": ([i32(), i32()], [])},   # (ptr, len) -> ()
    }


def available() -> bool:
    return _HAS_WASMTIME


class CapabilityError(RuntimeError):
    """A plugin imports a host power its manifest never declared."""


class WasmCapabilityHost:
    """Instantiate a WASM plugin with only its declared capabilities linked.

    Parameters
    ----------
    wasm : bytes
        The compiled module (or WAT text via ``from_wat``).
    granted : list[str]
        Capability names the manifest declares (``requires``).
    impls : dict[str, callable] | None
        Optional host implementations keyed by import-func name; a granted
        function with no impl gets a safe no-op/zero stub.
    """

    def __init__(self, wasm: bytes, granted, impls=None):
        if not _HAS_WASMTIME:
            raise RuntimeError("wasmtime not installed")
        self.granted = set(granted or [])
        self.impls = impls or {}
        self.engine = wasmtime.Engine()
        self.store = wasmtime.Store(self.engine)
        self.module = wasmtime.Module(self.engine, wasm)
        self._inst = None
        self.calls: list = []            # audit: which host funcs the guest hit

    @classmethod
    def from_wat(cls, wat: str, granted, impls=None):
        return cls(wasmtime.wat2wasm(wat), granted, impls)

    # -- the enforcement ------------------------------------------------------
    def _granted_funcs(self) -> dict:
        """The set of host-function specs the granted capabilities expose."""
        cat = _catalog()
        out = {}
        for cap in self.granted:
            for fname, sig in cat.get(cap, {}).items():
                out[fname] = (cap, sig)
        return out

    def _refuse_undeclared(self, allowed: set) -> None:
        cat = _catalog()
        # reverse map: import func name -> capability that would grant it
        owner = {f: cap for cap, funcs in cat.items() for f in funcs}
        for imp in self.module.imports:
            mod = imp.module
            name = imp.name
            if mod != "dreamlayer":
                # anything outside our host namespace is not a capability the
                # host provides — refuse it outright (no ambient authority)
                raise CapabilityError(
                    f"plugin imports {mod}.{name}, outside the host surface")
            if name not in allowed:
                cap = owner.get(name)
                if cap is None:
                    raise CapabilityError(
                        f"plugin imports unknown host function {name!r}")
                raise CapabilityError(
                    f"plugin imports {name!r} but did not declare "
                    f"requires:[{cap}]")

    def instantiate(self):
        funcs = self._granted_funcs()
        self._refuse_undeclared(set(funcs))
        linker = wasmtime.Linker(self.engine)
        for fname, (cap, (params, results)) in funcs.items():
            linker.define_func(
                "dreamlayer", fname,
                wasmtime.FuncType([p for p in params], [r for r in results]),
                self._wrap(cap, fname))
        self._inst = linker.instantiate(self.store, self.module)
        return self._inst

    def _wrap(self, cap: str, fname: str):
        impl = self.impls.get(fname)

        def host_fn(*args):
            self.calls.append((cap, fname, args))
            if impl is not None:
                return impl(*args)
            return 0                     # safe default for i32-returning stubs

        return host_fn

    def call(self, export: str, *args):
        if self._inst is None:
            self.instantiate()
        assert self._inst is not None   # instantiate() sets it or raises
        fn = self._inst.exports(self.store).get(export)
        if fn is None:
            raise KeyError(f"no export {export!r}")
        return fn(self.store, *args)
