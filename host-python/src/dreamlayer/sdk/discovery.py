"""Entry-point discovery — the standard, `pip`/`uv`-native way to find plugins.

Layered *under* the manifest, not instead of it. An installed Python package
advertises a plugin by declaring, in its own ``pyproject.toml``::

    [project.entry-points."dreamlayer.plugins"]
    my-plugin = "my_pkg.plugin:plugin"      # -> a factory returning a plugin object

``discover()`` finds every such entry point in the current environment.
The **manifest** (``plugin.json`` / the registry) remains the trust +
capability layer: an entry point says *where* a plugin loads from; the manifest
says *what it may do*, and the gate still decides whether it runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

ENTRY_GROUP = "dreamlayer.plugins"


@dataclass
class DiscoveredPlugin:
    name: str                      # the entry-point name
    value: str                     # "module:attr" load target
    dist: str = ""                 # distribution that declared it
    version: str = ""

    def load(self):
        """Import and call the entry-point target, returning the plugin object.
        Raises on import/factory error — the caller decides how to handle it."""
        import importlib
        module, _, attr = self.value.partition(":")
        obj = importlib.import_module(module)
        for part in (attr.split(".") if attr else []):
            obj = getattr(obj, part)
        return obj() if callable(obj) else obj


def discover(group: str = ENTRY_GROUP) -> list:
    """Every plugin advertised via ``[project.entry-points."dreamlayer.plugins"]``
    in the current environment. Import-safe: it reads metadata, it does not load
    or run any plugin code (call ``DiscoveredPlugin.load()`` for that)."""
    from importlib import metadata
    out: list = []
    try:
        eps = metadata.entry_points()
        # Python 3.10+ selectable API; 3.9 returns a dict.
        selected = eps.select(group=group) if hasattr(eps, "select") \
            else eps.get(group, [])
    except Exception:
        return out
    for ep in selected:
        dist = getattr(getattr(ep, "dist", None), "name", "") or ""
        ver = getattr(getattr(ep, "dist", None), "version", "") or ""
        out.append(DiscoveredPlugin(name=ep.name, value=ep.value, dist=dist, version=ver))
    return out


def load_discovered(group: str = ENTRY_GROUP,
                    on_error: Optional[Callable[[str, Exception], None]] = None) -> list:
    """Discover *and* load every entry-point plugin into live objects, isolating
    failures (one bad plugin never sinks the rest). ``on_error(name, exc)`` is
    called per failure when provided."""
    objs = []
    for d in discover(group):
        try:
            objs.append(d.load())
        except Exception as exc:               # import error / bad factory
            if on_error is not None:
                on_error(d.name, exc)
    return objs
