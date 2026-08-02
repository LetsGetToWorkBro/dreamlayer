"""plugins/validate.py — the gate: does this plugin run cleanly, and is it safe?

Every plugin passes through here before it is ever installed or loaded. Five
lines of defence, cheapest first:

  1. **Manifest** — well-formed name/version/entry/capabilities/api.
  2. **Integrity** — the code's sha256 matches the manifest checksum, so what
     you validated is what you run (tampering is caught).
  2b. **Authenticity** — when the manifest carries an Ed25519 signature it
     must verify against the code payload with the manifest's public key
     (a bad signature is a hard error); when a trusted-keys registry is
     supplied, the key must be in it. Unsigned packages stay installable
     under the curated-registry model, labeled with a warning.
  3. **Static scan** — the source is parsed to an AST and screened for dangerous
     operations (subprocess, eval/exec, raw sockets, file writes, ctypes, dynamic
     import…), each cross-checked against what the manifest declared. Nothing is
     executed.

     THIS IS A LINT, NOT A SECURITY BOUNDARY, and the difference matters enough to
     spell out. An AST screen keyed on names cannot enforce a capability model in
     Python, because reaching a capability does not require naming it. An audit
     walked five separate routes past a scan with ZERO declared capabilities:

         ().__class__.__base__.__subclasses__()      -> subprocess.Popen
         __builtins__["__import__"]("socket")        -> a socket, via subscript
         io.open("/etc/passwd")                      -> a read
         pathlib.Path(p).write_text(...)             -> an arbitrary write
         os.environ.get("...")                       -> the pairing token

     The list is not exhaustive and cannot be made exhaustive; introspection is
     unbounded. So the scan is here to catch honest mistakes and obvious hostility
     early, with a clear message, before anything runs — which is worth having. It
     is NOT what stands between a hostile plugin and the wearer's data. That is the
     kernel or WASM sandbox in `isolation.py` / `wasm_component_host.py`, which is
     why `load_installed` now refuses to run a plugin at all when no such sandbox
     is available. Do not add a capability to this list and consider it enforced.
  4. **Smoke load** (opt-in) — the module is imported in a fresh namespace and
     its factory is built and registered against a *mock* context. If it fails
     to import, its entry factory is missing, or `register()` raises, it fails
     here — not on your glasses. (The mock grants only the declared capabilities
     plus the always-open extension surfaces, so a plugin that reaches for a
     host capability it didn't declare has already been caught by the static
     scan in step 3.) This step *executes plugin code*, so it is **off by
     default** and runs only when the caller passes `run_smoke=True`. Author
     tooling opts in to test its own code; the store install/load path never
     does — validating an untrusted package must not run it.

Honest limit: in-process Python cannot be *fully* sandboxed — a determined
author can hide intent from a static scan. This gate is defence-in-depth
(integrity + declared capabilities + screen + smoke test) for a **curated,
reviewed** registry, not a jail for hostile code. True isolation (subprocess /
wasm / RestrictedPython) is the next hardening; see docs/MARKETPLACE.md.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Optional

from .base import PluginContext
from .package import PluginPackage

# module.attr call patterns that need a capability to be allowed
_DANGER_CALLS = {
    ("os", "system"): "subprocess",
    ("os", "popen"): "subprocess",
    ("os", "remove"): "fs",
    ("os", "unlink"): "fs",
    ("os", "rmdir"): "fs",
    ("os", "execv"): "subprocess",
    ("os", "execve"): "subprocess",
    ("os", "execvp"): "subprocess",
    ("os", "spawnv"): "subprocess",
    ("os", "spawnl"): "subprocess",
    # the rest of the exec*/spawn* family the table missed — each replaces the
    # process image or spawns one (curl exfil / arbitrary binary) exactly like
    # os.system, but a declared-no-subprocess plugin reached them undeclared
    # (refute 2026-07-17).
    ("os", "execl"): "subprocess",
    ("os", "execle"): "subprocess",
    ("os", "execlp"): "subprocess",
    ("os", "execlpe"): "subprocess",
    ("os", "execvpe"): "subprocess",
    ("os", "spawnle"): "subprocess",
    ("os", "spawnlp"): "subprocess",
    ("os", "spawnlpe"): "subprocess",
    ("os", "spawnve"): "subprocess",
    ("os", "spawnvp"): "subprocess",
    ("os", "spawnvpe"): "subprocess",
    ("os", "posix_spawn"): "subprocess",
    ("os", "posix_spawnp"): "subprocess",
    ("pty", "spawn"): "subprocess",
    ("pty", "fork"): "subprocess",
    ("subprocess", "*"): "subprocess",
    ("socket", "*"): "network",
    ("ctypes", "*"): "subprocess",
    ("shutil", "rmtree"): "fs",
    # dynamic import is an import-of-anything laundering channel: it can pull a
    # dangerous module (socket/subprocess) past the static import table, so the
    # scanner cannot resolve it and forbids it outright (audit 2026-07-14).
    ("importlib", "import_module"): None,
    ("importlib", "__import__"): None,
    # builtins.<x> is the same laundering channel by another name: the scanner
    # forbids bare __import__/eval/exec (below), but `builtins.__import__("socket")`
    # slipped past because "builtins" wasn't a sensitive receiver — a declared-
    # no-network plugin could bind a live socket (re-audit 2026-07-15).
    ("builtins", "__import__"): None,
    ("builtins", "eval"): None,
    ("builtins", "exec"): None,
    ("builtins", "compile"): None,
    # asyncio itself is legitimate; only its raw-socket openers imply network.
    ("asyncio", "open_connection"): "network",
    ("asyncio", "open_unix_connection"): "network",
    # Filesystem reach the table simply did not name. An audit read /etc/passwd
    # through `io.open` and wrote an arbitrary file through `pathlib`, both with
    # zero declared capabilities, because only the BARE `open` builtin was listed.
    ("io", "open"): "fs",
    ("io", "FileIO"): "fs",
    ("shutil", "copy"): "fs", ("shutil", "copy2"): "fs",
    ("shutil", "copyfile"): "fs", ("shutil", "move"): "fs",
    ("shutil", "make_archive"): "fs",
    ("shutil", "unpack_archive"): "fs",
    ("tempfile", "NamedTemporaryFile"): "fs", ("tempfile", "mkstemp"): "fs",
    ("tempfile", "mkdtemp"): "fs",
}
# Path-object methods that read or write the filesystem. `pathlib.Path(p)` is an
# unresolved call result, so the (module, attr) table never sees the receiver —
# flag the method name on ANY receiver, the same way the asyncio openers are
# handled. Over-declaration is the safe direction for a screen.
_FS_METHOD_NAMES = {
    "write_text", "write_bytes", "read_text", "read_bytes",
    "unlink", "rmdir", "mkdir", "touch", "rename", "replace", "symlink_to",
    "chmod", "hardlink_to",
}
# asyncio EVENT-LOOP socket openers (loop.create_connection(...)). The loop is
# usually an unresolved call result — asyncio.new_event_loop().create_connection()
# — so the module-qualified table above never sees the receiver. These method
# names are distinctive raw-socket openers; flag them on ANY receiver so a
# connector can't reach the network through a loop without declaring it. Over-
# declaration is the safe direction (refute 2026-07-17). ``ssl`` egress
# (ssl.get_server_certificate opens a TCP socket) is caught via _DANGER_IMPORTS.
_NET_METHOD_OPENERS = {
    "create_connection", "create_unix_connection", "sock_connect",
    "create_datagram_endpoint", "connect_accepted_socket",
    "create_server", "create_unix_server",
}
# modules any of whose attributes reaching a dynamic name (getattr(mod, x)) we
# can't resolve statically — treated as a sensitive receiver so a dynamic
# attribute grab can't launder a call past the (module, attr) table.
_SENSITIVE_MODULES = {m for (m, _) in _DANGER_CALLS}
# bare builtins that are dangerous regardless of import
_DANGER_BUILTINS = {
    "eval": None, "exec": None, "compile": None,
    "__import__": None, "open": "fs",
}
# modules whose mere import implies a capability
_DANGER_IMPORTS = {
    "subprocess": "subprocess", "socket": "network", "ctypes": "subprocess",
    "urllib": "network", "http": "network", "requests": "network",
    # additional network-egress modules the old table missed, so a plugin could
    # exfiltrate via SMTP/FTP/telnet/websockets without declaring 'network'
    # (audit 2026-07-14).
    "ssl": "network",   # ssl.get_server_certificate((host,port)) opens a TCP socket
    "smtplib": "network", "ftplib": "network", "telnetlib": "network",
    "websocket": "network", "websockets": "network",
    "httpx": "network", "aiohttp": "network",
    # more egress channels the table still missed: mail/news protocols, the
    # XML-RPC HTTP client, a second urllib fork, and webbrowser.open("http://…")
    # as a GET-exfil vector — all reach the network without declaring it
    # (re-audit 2026-07-15).
    "xmlrpc": "network", "poplib": "network", "imaplib": "network",
    "nntplib": "network", "urllib3": "network", "webbrowser": "network",
    # asyncore/asynchat ARE network I/O frameworks (dispatcher().connect(...))
    # and their .connect isn't in the method-opener set, so the import is the
    # honest declaration point (refute 2026-07-17).
    "asyncore": "network", "asynchat": "network",
    "pickle": None, "marshal": None,
}

# Full dotted imports whose TOP-LEVEL name is benign but whose submodule is an
# egress channel — `multiprocessing` is fine, `multiprocessing.connection` is
# IPC over a socket/pipe (Client((host,port)) dials out). Matched on the whole
# module path in visit_Import/visit_ImportFrom, so `import
# multiprocessing.connection`, `from multiprocessing.connection import Client`,
# and `from multiprocessing import connection` all declare network
# (refute 2026-07-17).
_DANGER_IMPORT_PATHS = {
    "multiprocessing.connection": "network",
}
# Distinctive network SINK class names reached as a >=2-level attribute chain
# (logging.handlers.HTTPHandler POSTs via http.client; SMTPHandler opens SMTP;
# Socket/Datagram/SysLogHandler open raw sockets). The receiver is not a bare
# module Name, so the (module, attr) call table never sees them; flag the class
# name on ANY receiver, like the asyncio openers. Over-declaration is the safe
# direction for a screen (refute 2026-07-17).
_NET_SINK_CLASSES = {
    "HTTPHandler", "SMTPHandler", "SocketHandler",
    "DatagramHandler", "SysLogHandler",
}


@dataclass
class ValidationReport:
    ok: bool = False
    errors: list = field(default_factory=list)     # hard — will not install
    warnings: list = field(default_factory=list)   # soft — surfaced, not fatal
    capabilities: tuple = ()                        # what it declared
    signed: bool = False                            # author signature verified
    publisher: str = ""                             # trusted-registry name, if any

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# Attribute names that exist to escape the type system. Flagging them does not
# make the scan a boundary (see the module docstring), but a plugin reaching for
# `__subclasses__` is not making an honest mistake, and saying so early is better
# than saying nothing.
_ESCAPE_ATTRS = frozenset({
    "__class__", "__base__", "__bases__", "__mro__", "__subclasses__",
    "__globals__", "__builtins__", "__code__", "__closure__", "__dict__",
    "__getattribute__", "__reduce__", "__reduce_ex__",
})


class _DangerScanner(ast.NodeVisitor):
    def __init__(self, allowed: set):
        self.allowed = allowed
        self.issues: list = []
        # alias → real module, so `import os as o` (then `o.system(…)`) and
        # `from os import system as run` don't slip past the call table under a
        # renamed binding. Without this, aliasing was a trivial bypass.
        self._mod_alias: dict = {}      # local name -> dangerous module
        self._call_alias: dict = {}     # local name -> (module, attr)

    def _need(self, cap, what):
        if cap is None:
            self.issues.append(f"forbidden operation: {what}")
        elif cap not in self.allowed:
            self.issues.append(f"{what} needs undeclared capability '{cap}'")

    def visit_Import(self, node):
        for a in node.names:
            top = a.name.split(".")[0]
            local = (a.asname or a.name).split(".")[0]
            self._mod_alias[local] = top           # remember the (aliased) name
            if top in _DANGER_IMPORTS:
                self._need(_DANGER_IMPORTS[top], f"import {top}")
            cap = _DANGER_IMPORT_PATHS.get(a.name)   # benign top, egress submodule
            if cap is not None:
                self._need(cap, f"import {a.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        top = (node.module or "").split(".")[0]
        if top in _DANGER_IMPORTS:
            self._need(_DANGER_IMPORTS[top], f"from {top} import …")
        # full-path submodule egress: `from multiprocessing.connection import …`
        # (module is the whole path) and `from multiprocessing import connection`
        # (the path is module + the imported name).
        cap = _DANGER_IMPORT_PATHS.get(node.module or "")
        if cap is not None:
            self._need(cap, f"from {node.module} import …")
        for a in node.names:
            capf = _DANGER_IMPORT_PATHS.get(f"{node.module}.{a.name}"
                                            if node.module else a.name)
            if capf is not None:
                self._need(capf, f"from {node.module} import {a.name}")
        # `from os import system` / `from shutil import rmtree` / `from
        # subprocess import run` bind a dangerous callable under a bare name the
        # attribute scan (os.system(…)) would never see — screen the imported
        # names against the same call table, following any `as` rename.
        for a in node.names:
            cap = _DANGER_CALLS.get((top, a.name)) or _DANGER_CALLS.get((top, "*"))
            if cap is not None or (top, a.name) in _DANGER_CALLS:
                self._call_alias[a.asname or a.name] = (top, a.name)
                self._need(cap, f"from {top} import {a.name}")
        self.generic_visit(node)

    def _resolve_mod(self, name: str) -> str:
        """Follow a local name back to a real module through both import aliases
        (`import os as o`) and value rebinds (`o = os`)."""
        return self._mod_alias.get(name, name)

    def visit_Assign(self, node):
        # Track two rebind forms the call table would otherwise miss:
        #   o = os            → `o` becomes an alias of the module
        #   run = os.system   → `run` becomes an alias of the callable
        # Straight-line only (no dataflow) — defence-in-depth, not a proof.
        val = node.value
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name):
                continue
            if isinstance(val, ast.Name) and val.id in self._mod_alias:
                self._mod_alias[tgt.id] = self._mod_alias[val.id]
            elif (isinstance(val, ast.Attribute)
                  and isinstance(val.value, ast.Name)):
                mod = self._resolve_mod(val.value.id)
                if (mod, val.attr) in _DANGER_CALLS or (mod, "*") in _DANGER_CALLS:
                    self._call_alias[tgt.id] = (mod, val.attr)
        self.generic_visit(node)

    def _flag_modattr(self, mod, attr, shown):
        cap = _DANGER_CALLS.get((mod, attr)) or _DANGER_CALLS.get((mod, "*"))
        if cap is not None or (mod, attr) in _DANGER_CALLS:
            self._need(cap, shown)

    def visit_Attribute(self, node):
        """Flag a reach for the type-system escape hatches.

        A plugin touching `__subclasses__` or `__globals__` is not making an honest
        mistake, and the scan exists to say so early. This does not turn the scan
        into a boundary — the routes past it are unbounded (module docstring) — it
        just declines to stay silent about the obvious ones."""
        # `os.environ` is where the pairing token lives. Reading it is not a call,
        # so no call-table entry could ever have caught it.
        if node.attr == "environ" and isinstance(node.value, ast.Name):
            mod = self._alias.get(node.value.id, node.value.id) \
                if hasattr(self, "_alias") else node.value.id
            if mod == "os":
                self._need("secrets", "os.environ")
        if node.attr in _FS_METHOD_NAMES:
            self._need("fs", f".{node.attr}()")
        if node.attr in _ESCAPE_ATTRS:
            self.issues.append(
                f"forbidden operation: {node.attr} (introspection escape); a "
                f"plugin has no honest use for reaching through the type system")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        """`__builtins__["__import__"]("socket")` reaches an import without ever
        naming one — the same escape as above, spelled with brackets."""
        v = node.value
        if isinstance(v, ast.Name) and v.id in _ESCAPE_ATTRS:
            self.issues.append(
                f"forbidden operation: {v.id}[...] (introspection escape)")
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name):
            if f.id in _DANGER_BUILTINS:
                self._need(_DANGER_BUILTINS[f.id], f"{f.id}()")
            elif f.id == "getattr":
                self._scan_getattr(node)
            elif f.id in self._call_alias:         # renamed `from … import x`
                mod, attr = self._call_alias[f.id]
                self._flag_modattr(mod, attr, f"{mod}.{attr}()")
        elif isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name):
                # resolve the receiver through the alias map (o -> os)
                mod = self._resolve_mod(f.value.id)
                self._flag_modattr(mod, f.attr, f"{mod}.{f.attr}()")
            # An asyncio event-loop's raw-socket openers reach the network, but the
            # loop is typically an unresolved call result (new_event_loop()...), so
            # the module-qualified check above never sees it. Same for the
            # logging.handlers.* network SINK classes, whose >=2-level receiver
            # (logging.handlers) is not a bare module Name. Flag both distinctive
            # name sets on ANY receiver (refute 2026-07-17).
            if f.attr in _NET_METHOD_OPENERS or f.attr in _NET_SINK_CLASSES:
                self._need("network", f".{f.attr}()")
        self.generic_visit(node)

    def _scan_getattr(self, node):
        """`getattr(os, 'system')(…)` and `getattr(os, name)` launder an
        attribute grab past the (module, attr) table. Resolve a constant attr
        through the table; a dynamic attr on a sensitive module is forbidden
        (its target is unknowable, so no capability can cover it)."""
        if not node.args:
            return
        recv = node.args[0]
        if not isinstance(recv, ast.Name):
            return
        mod = self._resolve_mod(recv.id)
        if mod not in _SENSITIVE_MODULES:
            return
        attr_node = node.args[1] if len(node.args) > 1 else None
        if isinstance(attr_node, ast.Constant) and isinstance(attr_node.value, str):
            self._flag_modattr(mod, attr_node.value,
                               f"getattr({mod}, {attr_node.value!r})")
        else:
            self.issues.append(
                f"forbidden operation: dynamic getattr on '{mod}' "
                "(attribute not statically knowable)")


def scan_source(source: str, allowed_capabilities) -> list:
    """AST screen for dangerous ops not covered by declared capabilities.
    Returns a list of issue strings ([] = clean). A syntax error is itself an
    issue (the plugin won't even parse)."""
    allowed = set(allowed_capabilities or ())
    try:
        tree = ast.parse(source or "")
    except SyntaxError as e:
        return [f"syntax error: {e.msg} (line {e.lineno})"]
    scanner = _DangerScanner(allowed)
    scanner.visit(tree)
    return scanner.issues


def scan_wasm(payload: bytes, allowed_capabilities, expect_exports=(),
              host_module: str = "dreamlayer") -> list:
    """The `.wasm` counterpart of `scan_source` — step 3 for a guest package.

    Two questions, both answered from the module's own binary sections with no
    runtime and nothing executed (see plugins/wasm_scan.py):

      1. Does it import a host function no declared capability grants? That is
         the manifest-vs-reality lie, and it is the one the Python scan CANNOT
         reliably catch (reaching a capability in Python does not require naming
         it). Here it can: a guest reaches the host only through an import, and
         imports are declared in the binary.
      2. Does it export what the host is about to call — `memory`, the
         allocator, the build function the manifest names? A package missing
         one of those cannot work, and failing at install with the missing name
         beats failing on the glass with nothing.

    Unlike its Python sibling this check has a real counterpart at run time:
    `WasmCapabilityHost` re-asks question 1 with wasmtime's own parser before
    the guest runs, and refuses there too. This one exists so the answer
    arrives before the package is written to disk.

    `host_module` names the import namespace the guest's runtime provides —
    `"dreamlayer"` for the component host, `"extism:host/env"` for Extism. It
    is a parameter rather than two functions because the QUESTIONS are the
    same; only the answer to "whose namespace is legitimate" differs.
    """
    from .wasm_component_host import (capability_function_names,
                                      capability_of_function,
                                      granted_interfaces)
    from .wasm_scan import MalformedModule, module_exports, module_imports

    try:
        imports = module_imports(payload)
        exports = {name for name, _kind in module_exports(payload)}
    except MalformedModule as e:
        # Fatal, not skippable: a module this reader cannot follow is one whose
        # imports were never checked, and "unscanned" must never read as "clean".
        return [f"not a usable WebAssembly module: {e}"]

    catalog = capability_function_names()
    allowed_fns: set = set()
    for wit in granted_interfaces(allowed_capabilities):
        allowed_fns |= catalog.get(wit, set())

    if host_module != "dreamlayer":
        # Extism. Its guests reach the runtime's own PDK ABI
        # (`extism:host/env`: alloc, store_u8, output_set…), which is not a
        # capability and not ours to grant — the host runs them with
        # `functions=[]`, so NOTHING outside that module can even link. The
        # check is therefore all-or-nothing on the module name, and it is the
        # stricter of the two: an Extism guest has no way to declare its way to
        # a power, because there is no power to declare.
        return ([f"imports {m}.{f}, outside the {host_module} surface"
                 for m, f in imports if m != host_module]
                + [f"exports no {w!r} — the host could not call it"
                   for w in expect_exports if w and w not in exports])

    issues = []
    for mod, fname in imports:
        if mod != "dreamlayer":
            # No ambient authority: anything outside the host namespace is not
            # a power the host provides, whatever the manifest declares.
            issues.append(f"imports {mod}.{fname}, outside the host surface")
        elif fname not in allowed_fns:
            cap = capability_of_function(fname)
            issues.append(
                f"imports {fname!r} but did not declare requires:[{cap}]"
                if cap else f"imports unknown host function {fname!r}")
    for want in expect_exports:
        if want and want not in exports:
            issues.append(f"exports no {want!r} — the host could not call it")
    return issues


def smoke_load(package: PluginPackage, host_capabilities=frozenset()) -> list:
    """Import the payload in a fresh namespace, build the plugin, and register it
    against a *mock* context. Returns issues ([] = it ran clean). Executes code,
    so run it only after the static scan passes."""
    if package.manifest.is_extism:
        return _smoke_extism(package)
    if package.manifest.is_wasm:
        return _smoke_wasm(package)
    issues: list = []
    ns: dict = {"__name__": f"dreamlayer_plugin_{package.manifest.name}"}
    try:
        exec(compile(package.source, f"<plugin {package.manifest.name}>", "exec"), ns)
    except Exception as e:               # import-time failure
        return [f"failed to import: {e!r}"]
    factory = ns.get(package.manifest.factory)
    if not callable(factory):
        return [f"entry factory {package.manifest.factory!r} not found or not callable"]
    try:
        plugin = factory()
    except Exception as e:
        return [f"factory raised: {e!r}"]
    # register against a mock context that grants exactly the declared caps
    caps = frozenset(package.manifest.requires) | {
        "object_lens", "glance", "cards"}      # always-available extension points
    ctx = PluginContext(capabilities=caps, config={})
    try:
        plugin.register(ctx)
    except Exception as e:
        issues.append(f"register() raised: {e!r}")
    return issues


def _smoke_wasm(package: PluginPackage) -> list:
    """Instantiate the guest with exactly its declared capabilities linked.

    The wasm analogue of "import it and build the factory", and the cheaper
    half of the bargain: instantiation is where a guest importing an undeclared
    power fails, and it runs no guest code of its own beyond the start section.
    Fuel, an epoch deadline and a memory ceiling bound even that.

    With no runtime installed there is nothing to try, and saying so with `[]`
    is the honest answer — `scan_wasm` has already read the same imports
    statically, so the author is not left with an unchecked package.
    """
    from .wasm_component_host import (WasmCapabilityHost, available,
                                      granted_interfaces)
    if not available():
        return []
    try:
        host = WasmCapabilityHost(
            package.wasm_bytes(),
            granted=granted_interfaces(package.manifest.requires))
        host.instantiate()
    except Exception as e:
        return [f"failed to instantiate: {e!r}"]
    return []


def _smoke_extism(package: PluginPackage) -> list:
    """Call the guest's entry once with an empty sighting.

    Extism constructs its plugin per call, so there is no instantiate step to
    check on its own — the first real call IS the smoke test. `run` answers
    None for a trap, a timeout, a missing export or an unlinkable import, and
    that is the failure this reports.

    An EMPTY reply is not a failure. `{}` is not a real sighting, and "nothing
    to say about this one" is the answer a well-behaved provider gives most of
    the time; calling it broken would fail the gate on correct plugins.
    """
    from .extism_host import default_extism_host
    host = default_extism_host()
    if host is None:
        return []                        # no runtime here; the scan already ran
    out = host.run(package.wasm_bytes(), package.manifest.factory, b"{}")
    if out is None:
        return [f"the guest returned nothing from "
                f"{package.manifest.factory!r} (trap, timeout, or a bad import)"]
    return []


def check_signature(package: PluginPackage,
                    trusted_keys: Optional[dict] = None) -> tuple:
    """Authenticity check (defence 2b). Returns (signed, publisher,
    errors, warnings).

    - signature + pubkey present → must verify over the code payload;
      a bad signature is a hard error (someone re-signed tampered code).
    - `cryptography` not installed → the claim can't be checked: warning,
      and the package counts as UNSIGNED (never as valid).
    - trusted_keys ({publisher_name: pubkey_hex}) provided → a signed
      package's key must be registered, else hard error.
    - unsigned → warning only; the curated-registry model still applies.
    """
    from ..reality_compiler.sign_crypto import verify_detached

    m = package.manifest
    errors: list = []
    warnings: list = []
    if not (m.signature and m.pubkey):
        if m.signature and not m.pubkey:
            errors.append("signature present but no pubkey — unverifiable")
            return False, "", errors, warnings
        warnings.append(
            "unsigned package — trust rests on the curated registry alone")
        return False, "", errors, warnings

    verdict = verify_detached(package.signing_payload(), m.signature, m.pubkey)
    if verdict is None:
        warnings.append(
            "author signature present but the 'cryptography' extra is not "
            "installed — authenticity NOT verified")
        return False, "", errors, warnings
    if verdict is False:
        errors.append(
            "author signature INVALID — the code does not match what the "
            "author signed")
        return False, "", errors, warnings

    publisher = ""
    if trusted_keys is not None:
        by_key = {v: k for k, v in trusted_keys.items()}
        publisher = by_key.get(m.pubkey, "")
        if not publisher:
            errors.append(
                "author key is not in the trusted publisher registry")
            return False, "", errors, warnings
    return True, publisher, errors, warnings


def validate(package: PluginPackage, host_capabilities=frozenset(),
             run_smoke: bool = False,
             trusted_keys: Optional[dict] = None) -> ValidationReport:
    """The whole gate. `host_capabilities` are what this device can grant; a
    plugin requiring more is a hard error (it can't run here safely).
    `trusted_keys` maps publisher name → Ed25519 pubkey hex (registry/keys.json);
    when provided, signed packages must be signed by a registered key.

    `run_smoke` defaults to **False**: the smoke load in step 4 *executes* the
    plugin's module code, so the install/load path (`PluginStore`) must never
    turn it on for code it hasn't already decided to trust — validating a
    package is not consent to run it. Author tooling (`dreamlayer plugins
    validate`, `dev --watch`) sets `run_smoke=True` explicitly: that's the
    author asking to run their own code to see that it imports and registers."""
    m = package.manifest
    report = ValidationReport(capabilities=tuple(m.requires))

    for p in m.problems():                       # 1. manifest shape
        report.add_error(p)

    from .package import sdk_supports, SDK_VERSION   # 1b. SDK compat
    if not sdk_supports(m.min_sdk):
        report.add_error(
            f"needs SDK >= {m.min_sdk}; this host provides {SDK_VERSION}")

    if not package.checksum_ok():                # 2. integrity
        report.add_error("checksum mismatch — the code does not match the manifest")

    signed, publisher, sig_errors, sig_warnings = \
        check_signature(package, trusted_keys)   # 2b. authenticity
    report.signed, report.publisher = signed, publisher
    for e in sig_errors:
        report.add_error(e)
    for w in sig_warnings:
        report.add_warning(w)

    missing = [c for c in m.requires if c not in set(host_capabilities)]
    if missing:                                  # capability grantable here?
        report.add_error("this device can't grant: " + ", ".join(missing))

    if m.carries_wasm:                           # 3. static scan, wasm flavour
        # A `.wasm` payload rides in `source` as base64 (package.py explains
        # why), and base64 is not Python — so scanning it as source reported
        # "syntax error: cannot assign to expression", and EVERY wasm package
        # failed the gate before this branch existed. Routing a wasm package to
        # the component host in store.py was necessary and not sufficient: it
        # could never reach the loader.
        try:
            payload = package.wasm_bytes()
        except ValueError as e:
            report.add_error(str(e))
            payload = b""
        if payload and m.is_extism:
            # Extism owns both sides of the memory dance through its PDK, so
            # the only export to insist on is the one the host will call.
            from .extism_plugin_host import HOST_MODULE
            for issue in scan_wasm(payload, m.requires,
                                   expect_exports=(m.factory,),
                                   host_module=HOST_MODULE):
                report.add_error(issue)
        elif payload:
            from .wasm_plugin_host import ALLOC_EXPORT
            for issue in scan_wasm(payload, m.requires,
                                   expect_exports=("memory", ALLOC_EXPORT,
                                                   m.factory)):
                report.add_error(issue)
    else:
        for issue in scan_source(package.source, m.requires):
            report.add_error(issue)

    # 4. smoke load only if nothing structural is already wrong
    if run_smoke and not report.errors:
        for issue in smoke_load(package, host_capabilities):
            report.add_error(issue)

    report.ok = not report.errors
    return report
