"""plugins/hookspecs.py — pluggy hook specifications + an entry-point loader
that discovers third-party plugins installed as Python packages.

ADD-alongside: `plugins/base.py` (PluginRegistry / PluginContext / make_plugin)
is untouched. This module adds a *second, optional* discovery doorway — the
setuptools-entry-point / pluggy convention — that resolves each discovered
plugin down to the SAME `register(ctx)` surface base.py already defines. So a
plugin authored for pluggy and one authored as a plain `register` callable are
loaded through the exact same PluginRegistry.

pluggy is optional (extras group `platform`). When it is absent, entry-point
discovery still works via importlib.metadata (stdlib), and the hookspec markers
degrade to no-op decorators — nothing here is required for the core plugin
system to run.
"""
from __future__ import annotations

import logging
from typing import List

log = logging.getLogger("dreamlayer.plugins.hookspecs")

try:
    import pluggy  # type: ignore
    _HAS_PLUGGY = True
    hookspec = pluggy.HookspecMarker("dreamlayer")
    hookimpl = pluggy.HookimplMarker("dreamlayer")
except ImportError:
    _HAS_PLUGGY = False

    def hookspec(fn=None, **_kw):          # type: ignore[misc]  # no-op fallback for the pluggy marker
        return fn if fn is not None else (lambda f: f)

    def hookimpl(fn=None, **_kw):          # type: ignore[misc]  # so downstream @hookimpl still parses
        return fn if fn is not None else (lambda f: f)


# The entry-point group third-party packages advertise under, e.g. in their
# pyproject:  [project.entry-points."dreamlayer.plugins"]  myplug = "pkg.mod:plugin"
ENTRY_POINT_GROUP = "dreamlayer.plugins"


class DreamlayerHooks:
    """The formal hook surface. A pluggy plugin implements `dreamlayer_register`
    to extend the layer; the arg is the same narrow PluginContext base.py hands
    out, so a hook and a plain register callable are interchangeable."""

    @hookspec
    def dreamlayer_register(self, ctx) -> None:  # pragma: no cover - spec only
        """Called once at load with the host's PluginContext."""


def discover_entrypoint_plugins() -> List:
    """Return plugin objects advertised by installed packages under
    ENTRY_POINT_GROUP. Each is expected to expose `register(ctx)` (a
    SimplePlugin, a module, or any object base.PluginRegistry.load accepts).

    Uses stdlib importlib.metadata — works with or without pluggy. Failures to
    load a single entry point are isolated and logged, never fatal.
    """
    found: List = []
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - py<3.8 only
        return found

    try:
        eps = entry_points()
        # py3.10+: selectable API; older: dict-like
        group = (eps.select(group=ENTRY_POINT_GROUP)
                 # legacy importlib.metadata dict API (py<3.10); stubs type the
                 # modern EntryPoints, so the list default trips [arg-type].
                 if hasattr(eps, "select") else eps.get(ENTRY_POINT_GROUP, []))  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("[hookspecs] entry-point scan failed: %s", exc)
        return found

    for ep in group:
        try:
            found.append(ep.load())
        except Exception as exc:
            log.warning("[hookspecs] skipping plugin %r: %s", getattr(ep, "name", ep), exc)
    return found


def make_pluggy_manager():
    """Build a pluggy PluginManager registered with DreamlayerHooks, or None
    when pluggy is not installed. Callers that want the plain path use
    `discover_entrypoint_plugins()` + `PluginRegistry.load_all`.
    """
    if not _HAS_PLUGGY:
        return None
    pm = pluggy.PluginManager("dreamlayer")
    pm.add_hookspecs(DreamlayerHooks)
    try:
        pm.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
    except Exception as exc:  # pragma: no cover - env dependent
        log.warning("[hookspecs] setuptools entrypoint load failed: %s", exc)
    return pm


available = _HAS_PLUGGY


def load_into(registry, plugins: List | None = None) -> int:
    """Discover entry-point plugins (plus any explicitly `plugins`) and load
    them into an existing `plugins.base.PluginRegistry`. Returns the count
    loaded. Zero host edits: this just feeds base.py's own loader.
    """
    batch = list(plugins or []) + discover_entrypoint_plugins()
    loaded = 0
    for p in batch:
        try:
            if registry.load(p):
                loaded += 1
        except Exception as exc:
            log.warning("[hookspecs] load failed for %r: %s", p, exc)
    return loaded
