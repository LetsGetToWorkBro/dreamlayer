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

Lazy dependency (wasmtime-py, in the ``platform`` extra; surfaced as the
``wasm_plugins`` capability): ``available()`` is False when
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


def _strip_wit_comments(text: str) -> str:
    """Drop WIT comments so a comment containing ``name: func`` (a doc comment, a
    note) can't be parsed as a phantom function (refute 2026-07-18)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)   # block comments
    text = re.sub(r"//[^\n]*", " ", text)                # line + /// doc comments
    return text


def _wit_blocks(text: str, keyword: str):
    """Yield ``(name, body)`` for each ``keyword NAME { ... }`` with BALANCED
    braces — so a nested record/variant/enum inside an interface does not
    truncate the body at its first ``}`` (which would hide every function after it
    while still passing the equality check — refute 2026-07-18)."""
    for m in re.finditer(rf"\b{keyword}\s+([a-z0-9\-]+)\s*\{{", text):
        depth, i, start = 1, m.end(), m.end()
        while i < len(text) and depth:
            depth += 1 if text[i] == "{" else -1 if text[i] == "}" else 0
            i += 1
        yield m.group(1), text[start:i - 1]


def _remove_nested_braces(body: str) -> str:
    """Strip inner ``{...}`` blocks (record/variant/enum/flags/resource bodies) so
    their fields/methods aren't mistaken for the interface's own functions."""
    prev = None
    while prev != body:
        prev = body
        body = re.sub(r"\{[^{}]*\}", " ", body)
    return body


def wit_interface_functions() -> dict:
    """Parse the WIT into ``{interface_name: {func_name}}`` with names normalised
    to the snake_case the core-ABI catalog uses (WIT is kebab-case). A small,
    dependency-free parser — comment-stripped and brace-balanced so it can't be
    fooled into hiding or inventing a function — enough to cross-check the runtime
    catalog against the formal contract, not a full WIT parser."""
    text = _strip_wit_comments(wit_world())
    out: dict = {}
    for name, body in _wit_blocks(text, "interface"):
        flat = _remove_nested_braces(body)
        funcs = {fm.group(1).replace("-", "_")
                 for fm in re.finditer(r"([a-z0-9\-]+)\s*:\s*func", flat)}
        out[name.replace("-", "_")] = funcs
    return out


def wit_world_imports() -> set:
    """The interface names a ``world`` imports — the full grantable capability
    surface a plugin may draw from."""
    text = _strip_wit_comments(wit_world())
    imports = set()
    for _, body in _wit_blocks(text, "world"):
        for im in re.finditer(r"import\s+([a-z0-9\-]+)\s*;", body):
            imports.add(im.group(1).replace("-", "_"))
    return imports


def capability_function_names() -> dict:
    """The host-function names each capability exposes, as PURE DATA (no wasmtime
    needed). The one place the WIT contract and the runtime `_catalog` are tied
    together: `_catalog` adds ValTypes to exactly these names, and
    `wit_interface_functions()` must equal this — otherwise contract and binding
    have drifted."""
    return {"log": {"log"}, "fs": {"fs_read"},
            "net": {"net_get"}, "cards": {"show_card"}}


#: Manifest capability name → WIT interface name, where the two vocabularies
#: disagree. A manifest's ``requires`` speaks the one every plugin uses
#: (``package.KNOWN_CAPABILITIES``: `network`, `fs`, `cards`…) and the WIT
#: contract names the same power `net`. Translating here rather than teaching
#: the manifest a second vocabulary is the whole point: a wasm author and a
#: Python author declare the SAME word for the same grant, one gate checks it
#: against what the device can hand out, and `dreamlayer.wit` stays the formal
#: contract it is without being bent to match an unrelated list.
_CAPABILITY_ALIASES = {"network": "net"}

#: Linked for every guest, declared or not. `log` is the one interface that
#: carries no authority: the host writes its OWN line, bounded, and never the
#: guest's bytes (see wasm_plugin_host._impls). The WIT calls it "the minimum a
#: plugin needs to speak to the host at all", and a plugin that cannot say
#: anything cannot be debugged by the person who installed it.
ALWAYS_GRANTED = frozenset({"log"})


def granted_interfaces(requires) -> set:
    """The WIT interfaces a manifest's ``requires`` actually grants.

    Unknown names are dropped rather than raising: ``requires`` legitimately
    carries capabilities that mean nothing to a wasm guest (`object_lens`,
    `glance`), because it is the same field a Python package uses.
    """
    known = set(capability_function_names())
    out = set(ALWAYS_GRANTED)
    for cap in requires or ():
        wit = _CAPABILITY_ALIASES.get(cap, cap)
        if wit in known:
            out.add(wit)
    return out


def capability_of_function(fname: str) -> str:
    """The MANIFEST capability a plugin must declare to import `fname`, or ""
    for a name no capability grants. The inverse of the two maps above, so an
    error message names the word the author would have to write."""
    reverse = {wit: cap for cap, wit in _CAPABILITY_ALIASES.items()}
    for wit, funcs in capability_function_names().items():
        if fname in funcs:
            return reverse.get(wit, wit)
    return ""

try:  # optional dep — wasmtime-py, in the `platform` extra (capability: wasm_plugins)
    import wasmtime  # type: ignore
    _HAS_WASMTIME = True
except Exception:
    wasmtime = None                     # type: ignore
    _HAS_WASMTIME = False

# Per-function arity (count of i32 params, count of i32 results) as PURE DATA —
# the core-ABI shape of each host function in the WIT. `_catalog` materialises
# ValTypes from these; keeping the cap→function STRUCTURE in
# capability_function_names() (the single source) means `_catalog` cannot expose
# a function the names dict — and therefore the WIT cross-check — doesn't know
# about, so runtime enforcement and the formal contract cannot silently drift.
_SIGNATURES = {
    "log":       (2, 0),   # (ptr, len) -> ()
    "fs_read":   (1, 1),   # (offset) -> byte
    "net_get":   (1, 1),   # (req_id) -> status
    "show_card": (2, 0),   # (ptr, len) -> ()
}


def _catalog():
    """The host-function surface, grouped by capability, with wasmtime ValTypes.
    Derived from capability_function_names() + _SIGNATURES so it is provably a
    superset of nothing the contract lacks (a function missing a signature raises,
    caught by the tests)."""
    i32 = wasmtime.ValType.i32
    cat: dict = {}
    for cap, fnames in capability_function_names().items():
        cat[cap] = {}
        for fn in fnames:
            n_params, n_results = _SIGNATURES[fn]
            cat[cap][fn] = ([i32() for _ in range(n_params)],
                            [i32() for _ in range(n_results)])
    return cat


def available() -> bool:
    return _HAS_WASMTIME


class CapabilityError(RuntimeError):
    """A plugin imports a host power its manifest never declared."""


class MemoryUnavailable(RuntimeError):
    """The guest exports no linear memory, so a (ptr, len) cannot be resolved."""


class MemoryOutOfBounds(RuntimeError):
    """A (ptr, len) from the guest runs past its own linear memory."""


def needs_memory(fn):
    """Mark a host-function impl as wanting the host as its first argument.

    Opt-in rather than inferred: an impl's arity is not a reliable signal (a
    `log` impl legitimately takes two ints), and guessing would silently change
    what an existing impl receives. Marked impls are called `fn(host, *args)`
    and can use `host.read_str(ptr, n)`.

        impls={"log": needs_memory(lambda host, ptr, n: print(host.read_str(ptr, n)))}
    """
    fn._dl_wants_host = True            # type: ignore[attr-defined]
    return fn


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
            # `add_fuel` is gone from current wasmtime, so a direct call does
            # not typecheck against the installed stubs even though this branch
            # only runs where it exists. Reached through getattr so the legacy
            # path stays honest instead of being deleted or silenced with an
            # ignore that would also hide a real error on the line.
            getattr(self.store, "add_fuel")(fuel)
        self.store.set_limits(memory_size=memory_bytes)   # StoreLimits: memory cap
        self.module = wasmtime.Module(self.engine, wasm)
        self._inst = None
        self.calls: list = []            # audit: which host funcs the guest hit

    @classmethod
    def from_wat(cls, wat: str, granted, impls=None, **limits):
        # `wat2wasm` answers a bytearray; `Module` and this constructor both
        # want bytes. It worked by luck — wasmtime accepts either — but the
        # signature said otherwise, which is the kind of drift that turns into
        # a real failure the first time someone hashes or pins the module.
        return cls(bytes(wasmtime.wat2wasm(wat)), granted, impls, **limits)

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

    # -- guest linear memory -------------------------------------------------
    #
    # The WIT contract passes strings as `(ptr, len)` "into guest linear
    # memory", and until now the host gave an impl no way to resolve one: `log`
    # — described in the contract as "the minimum a plugin needs to speak to the
    # host at all" — received two integers and could not read the bytes they
    # pointed at. So the two string-passing capabilities of the four
    # (`log`, `show_card`) could not carry anything.
    #
    # These accessors close that, and every one of them is BOUNDS-CHECKED
    # against the guest's current memory size. A guest is untrusted by
    # construction here; a ptr/len it chose must never be able to walk the
    # host's process, and `data_ptr`-style raw access would let it.

    def memory(self):
        """The guest's exported linear memory, or None if it exports none."""
        if self._inst is None:
            return None
        return self._inst.exports(self.store).get("memory")

    def read_mem(self, ptr: int, length: int) -> bytes:
        """`length` bytes at `ptr` in guest memory. Raises on an out-of-bounds
        span rather than clamping — a guest handing over a bad ptr/len is a bug
        or an attack, and silently returning fewer bytes would hide both."""
        mem = self.memory()
        if mem is None:
            raise MemoryUnavailable("the guest exports no memory")
        ptr, length = int(ptr), int(length)
        if ptr < 0 or length < 0:
            raise MemoryOutOfBounds(f"negative span ptr={ptr} len={length}")
        size = mem.data_len(self.store)
        if ptr + length > size:
            raise MemoryOutOfBounds(
                f"span ptr={ptr} len={length} runs past guest memory ({size})")
        return bytes(mem.read(self.store, ptr, ptr + length))

    def write_mem(self, ptr: int, data: bytes) -> int:
        """Write `data` at `ptr`. Same bounds rule. Returns the byte count."""
        mem = self.memory()
        if mem is None:
            raise MemoryUnavailable("the guest exports no memory")
        ptr = int(ptr)
        if ptr < 0:
            raise MemoryOutOfBounds(f"negative ptr={ptr}")
        size = mem.data_len(self.store)
        if ptr + len(data) > size:
            raise MemoryOutOfBounds(
                f"write ptr={ptr} len={len(data)} runs past guest memory ({size})")
        mem.write(self.store, data, ptr)
        return len(data)

    def read_str(self, ptr: int, length: int) -> str:
        """UTF-8 at `ptr`, replacing undecodable bytes rather than raising: the
        bytes come from an untrusted guest, and a malformed string is that
        guest's problem to see in a log line, not a host-side exception."""
        return self.read_mem(ptr, length).decode("utf-8", "replace")

    def _wrap(self, cap: str, fname: str):
        impl = self.impls.get(fname)
        wants_host = bool(getattr(impl, "_dl_wants_host", False))
        # Result arity decides what a host function may hand back, and getting
        # it wrong traps the GUEST — "callback produced results when it
        # shouldn't" — from inside a host call, which reads like the plugin's
        # fault and is not. The stub returned 0 unconditionally, so granting a
        # void capability (`log`, `cards`) with no implementation trapped every
        # guest that used it; and an impl that returned a value for a void
        # function trapped it too, which is easy to do by accident (`return 0`,
        # or any expression-bodied lambda).
        returns = _SIGNATURES.get(fname, (0, 0))[1] > 0

        def host_fn(*args):
            self.calls.append((cap, fname, args))
            out = None
            if impl is not None:
                # `needs_memory`-marked impls get the host first, so they can
                # resolve a (ptr, len) through the bounds-checked accessors
                # above. Unmarked impls keep the plain signature they had.
                out = impl(self, *args) if wants_host else impl(*args)
            if not returns:
                return None              # void: anything else is a guest trap
            try:
                return int(out)          # i32 result; None/garbage → the stub's 0
            except (TypeError, ValueError):
                return 0

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
