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
  3. **Static scan** — the source is parsed to an AST and screened for
     dangerous operations (subprocess, eval/exec, raw sockets, file writes,
     ctypes, dynamic import…). Each is allowed *only* if the manifest declared
     the matching capability — no undeclared reach. Nothing is executed.
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


def smoke_load(package: PluginPackage, host_capabilities=frozenset()) -> list:
    """Import the payload in a fresh namespace, build the plugin, and register it
    against a *mock* context. Returns issues ([] = it ran clean). Executes code,
    so run it only after the static scan passes."""
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

    for issue in scan_source(package.source, m.requires):   # 3. static scan
        report.add_error(issue)

    # 4. smoke load only if nothing structural is already wrong
    if run_smoke and not report.errors:
        for issue in smoke_load(package, host_capabilities):
            report.add_error(issue)

    report.ok = not report.errors
    return report
