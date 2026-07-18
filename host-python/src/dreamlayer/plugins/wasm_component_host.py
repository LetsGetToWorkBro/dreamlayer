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
import os
import re

log = logging.getLogger("dreamlayer.wasm_component_host")

# The formal Component Model contract (WIT) this host implements. It is the
# source of truth for the capability surface; `_catalog` below is its runtime
# (core-ABI) binding, kept honest against it by `wit_interface_functions()`.
WIT_FILENAME = "dreamlayer.wit"


def wit_path() -> str:
    return os.path.join(os.path.dirname(__file__), WIT_FILENAME)


def wit_world() -> str:
    """The WIT contract text (ships with the package)."""
    with open(wit_path(), encoding="utf-8") as f:
        return f.read()


def wit_interface_functions() -> dict:
    """Parse the WIT into ``{interface_name: {func_name}}`` with names normalised
    to the snake_case the core-ABI catalog uses (WIT is kebab-case). A tiny,
    dependency-free parser — enough to cross-check the runtime catalog against the
    formal contract, not a full WIT parser."""
    text = wit_world()
    out: dict = {}
    for m in re.finditer(r"interface\s+([a-z0-9\-]+)\s*\{([^}]*)\}", text):
        iface = m.group(1).replace("-", "_")
        funcs = {fm.group(1).replace("-", "_")
                 for fm in re.finditer(r"([a-z0-9\-]+)\s*:\s*func", m.group(2))}
        out[iface] = funcs
    return out


def wit_world_imports() -> set:
    """The interface names the `world plugin` imports — the full grantable
    capability surface a plugin may draw from."""
    text = wit_world()
    m = re.search(r"world\s+plugin\s*\{([^}]*)\}", text)
    if not m:
        return set()
    return {im.group(1).replace("-", "_")
            for im in re.finditer(r"import\s+([a-z0-9\-]+)\s*;", m.group(1))}


def capability_function_names() -> dict:
    """The host-function names each capability exposes, as PURE DATA (no wasmtime
    needed). The one place the WIT contract and the runtime `_catalog` are tied
    together: `_catalog` adds ValTypes to exactly these names, and
    `wit_interface_functions()` must equal this — otherwise contract and binding
    have drifted."""
    return {"log": {"log"}, "fs": {"fs_read"},
            "net": {"net_get"}, "cards": {"show_card"}}

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


class ResourceLimitError(RuntimeError):
    """A plugin exceeded its fuel / memory / wall-clock budget."""


# Untrusted guest bytecode MUST run bounded. Defaults are generous for a real
# card/logic plugin yet trap a `(loop br 0)` in well under the timeout: fuel
# caps executed instructions, StoreLimits caps linear-memory growth, and the
# epoch watchdog caps wall-clock even for a guest that avoids burning fuel.
DEFAULT_FUEL = 1_000_000_000
DEFAULT_MEMORY_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT_S = 2.0


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

    def __init__(self, wasm: bytes, granted, impls=None, *,
                 fuel: int = DEFAULT_FUEL,
                 memory_bytes: int = DEFAULT_MEMORY_BYTES,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        if not _HAS_WASMTIME:
            raise RuntimeError("wasmtime not installed")
        self.granted = set(granted or [])
        self.impls = impls or {}
        self._timeout_s = timeout_s
        # Bound the untrusted guest: without this a `(loop br 0)` hangs the host
        # thread forever, and an unbounded memory.grow OOMs the box (refute
        # 2026-07-18: the in-process host set NO fuel/epoch/memory limits).
        config = wasmtime.Config()
        config.consume_fuel = True          # fuel is charged per instruction
        config.epoch_interruption = True    # lets the watchdog trap wall-clock
        self.engine = wasmtime.Engine(config)
        self.store = wasmtime.Store(self.engine)
        if hasattr(self.store, "set_fuel"):
            self.store.set_fuel(fuel)       # wasmtime-py >= 14
        else:                               # pragma: no cover - old wasmtime
            self.store.add_fuel(fuel)
        self.store.set_limits(memory_size=memory_bytes)   # StoreLimits: memory cap
        self.module = wasmtime.Module(self.engine, wasm)
        self._inst = None
        self.calls: list = []            # audit: which host funcs the guest hit

    @classmethod
    def from_wat(cls, wat: str, granted, impls=None, **limits):
        return cls(wasmtime.wat2wasm(wat), granted, impls, **limits)

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
        # Wall-clock backstop: arm the epoch deadline and a daemon watchdog that
        # ticks it once the budget elapses, so a guest that somehow avoids
        # burning fuel (or a host call that stalls) still cannot run unbounded.
        import threading
        self.store.set_epoch_deadline(1)
        tripped = threading.Event()

        def _tick():
            tripped.set()
            try:
                self.engine.increment_epoch()
            except Exception:               # pragma: no cover
                pass

        timer = threading.Timer(self._timeout_s, _tick)
        timer.daemon = True
        timer.start()
        try:
            return fn(self.store, *args)
        except Exception as exc:            # fuel/epoch/memory trap, or a guest trap
            msg = str(exc).lower()
            if tripped.is_set() or "fuel" in msg or "epoch" in msg or "interrupt" in msg:
                raise ResourceLimitError(
                    f"plugin exceeded its resource budget: {exc}") from exc
            raise
        finally:
            timer.cancel()
