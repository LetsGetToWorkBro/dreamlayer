"""plugins/validate.py — the gate: does this plugin run cleanly, and is it safe?

Every plugin passes through here before it is ever installed or loaded. Four
lines of defence, cheapest first:

  1. **Manifest** — well-formed name/version/entry/capabilities/api.
  2. **Integrity** — the code's sha256 matches the manifest checksum, so what
     you validated is what you run (tampering is caught).
  3. **Static scan** — the source is parsed to an AST and screened for
     dangerous operations (subprocess, eval/exec, raw sockets, file writes,
     ctypes, dynamic import…). Each is allowed *only* if the manifest declared
     the matching capability — no undeclared reach. Nothing is executed.
  4. **Smoke load** — the module is imported in a fresh namespace and its
     factory is registered against a *mock* context. If it throws, or touches
     an extension point it didn't ask for, it fails here — not on your glasses.

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
    ("subprocess", "*"): "subprocess",
    ("socket", "*"): "network",
    ("ctypes", "*"): "subprocess",
    ("shutil", "rmtree"): "fs",
}
# bare builtins that are dangerous regardless of import
_DANGER_BUILTINS = {
    "eval": None, "exec": None, "compile": None,
    "__import__": None, "open": "fs",
}
# modules whose mere import implies a capability
_DANGER_IMPORTS = {
    "subprocess": "subprocess", "socket": "network", "ctypes": "subprocess",
    "urllib": "network", "http": "network", "requests": "network",
    "pickle": None, "marshal": None,
}


@dataclass
class ValidationReport:
    ok: bool = False
    errors: list = field(default_factory=list)     # hard — will not install
    warnings: list = field(default_factory=list)   # soft — surfaced, not fatal
    capabilities: tuple = ()                        # what it declared

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class _DangerScanner(ast.NodeVisitor):
    def __init__(self, allowed: set):
        self.allowed = allowed
        self.issues: list = []

    def _need(self, cap, what):
        if cap is None:
            self.issues.append(f"forbidden operation: {what}")
        elif cap not in self.allowed:
            self.issues.append(f"{what} needs undeclared capability '{cap}'")

    def visit_Import(self, node):
        for a in node.names:
            top = a.name.split(".")[0]
            if top in _DANGER_IMPORTS:
                self._need(_DANGER_IMPORTS[top], f"import {top}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        top = (node.module or "").split(".")[0]
        if top in _DANGER_IMPORTS:
            self._need(_DANGER_IMPORTS[top], f"from {top} import …")
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name) and f.id in _DANGER_BUILTINS:
            self._need(_DANGER_BUILTINS[f.id], f"{f.id}()")
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            mod, attr = f.value.id, f.attr
            cap = _DANGER_CALLS.get((mod, attr)) or _DANGER_CALLS.get((mod, "*"))
            if cap is not None or (mod, attr) in _DANGER_CALLS:
                self._need(cap, f"{mod}.{attr}()")
        self.generic_visit(node)


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


def validate(package: PluginPackage, host_capabilities=frozenset(),
             run_smoke: bool = True) -> ValidationReport:
    """The whole gate. `host_capabilities` are what this device can grant; a
    plugin requiring more is a hard error (it can't run here safely)."""
    m = package.manifest
    report = ValidationReport(capabilities=tuple(m.requires))

    for p in m.problems():                       # 1. manifest shape
        report.add_error(p)

    if not package.checksum_ok():                # 2. integrity
        report.add_error("checksum mismatch — the code does not match the manifest")

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
