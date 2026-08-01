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


def discover_entrypoints() -> List:
    """Return the entry points advertised under ENTRY_POINT_GROUP — WITHOUT
    importing any of them.

    This used to be `discover_entrypoint_plugins()` and it called `ep.load()`
    on everything it found, which is where the problem was: **loading an entry
    point IS importing it**, so third-party module code ran in-process, with the
    host user's full authority, at DISCOVERY time — before any policy could look
    at it.

    That is not a small gap next to what this repo already does. `PluginStore.
    load_installed` validates a package, checks it against a registered
    publisher key or a first-party content-hash pin, and drops anything
    unvouched into a WASM or subprocess jail, with `require_sandbox` to refuse
    outright when no real sandbox exists. Discovery by entry point walked
    straight past every one of those steps, and the module's own docstring
    described it as reaching "the SAME `register(ctx)` surface" — which is true
    of the registration step and silent about the authority step, the only one
    that matters here.

    The setuptools convention cannot be made safe by ordering, because there is
    no "before" to inspect: the import is the load. So the split is the fix —
    this half enumerates, `load_entrypoint` imports, and the caller has to say
    which entry points earned it.
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

    # The entry points themselves, unimported. `ep.value` names the module and
    # attribute a load WOULD execute, which is exactly what a policy needs to
    # decide on — and what the old version threw away by importing first.
    return list(group)


def load_entrypoint(ep):
    """Import ONE entry point and return the plugin object, or None.

    Separated from discovery so that importing third-party code is a decision
    somebody makes rather than a side effect of looking. Callers are expected to
    have checked `ep.value` against whatever they trust — a registered
    publisher, a first-party pin, an explicit allow-list from the wearer —
    before calling this, because after this line the code has run.
    """
    try:
        return ep.load()
    except Exception as exc:
        log.warning("[hookspecs] skipping plugin %r: %s",
                    getattr(ep, "name", ep), exc)
        return None


def make_pluggy_manager(load_entrypoints: bool = False):
    """Build a pluggy PluginManager registered with DreamlayerHooks, or None
    when pluggy is not installed.

    `load_entrypoints` defaults to False for the same reason `load_into` does:
    `pm.load_setuptools_entrypoints` imports every advertised package, and it
    used to be called unconditionally here — so merely asking for a manager ran
    third-party code. Building the manager and populating it are now two
    decisions, and only the second one executes anything.
    """
    if not _HAS_PLUGGY:
        return None
    pm = pluggy.PluginManager("dreamlayer")
    pm.add_hookspecs(DreamlayerHooks)
    if load_entrypoints:
        try:
            pm.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
        except Exception as exc:  # pragma: no cover - env dependent
            log.warning("[hookspecs] setuptools entrypoint load failed: %s", exc)
    return pm


available = _HAS_PLUGGY


def load_into(registry, plugins: List | None = None,
              allow_entrypoints=None) -> int:
    """Load plugins into an existing `plugins.base.PluginRegistry`.

    `plugins` are objects the caller already holds and has already decided
    about. Entry points are DIFFERENT and are off by default: importing one
    executes third-party code in-process, so this will not do it on the caller's
    behalf just because a package advertised itself.

    `allow_entrypoints` is the decision, and it has to be made explicitly:

      * ``None`` (default) — enumerate nothing. Any advertised entry points are
        logged by name so the omission is visible rather than silent.
      * a callable ``(ep) -> bool`` — the policy. Called with the unimported
        entry point, whose ``.value`` names the module that would run.
      * ``True`` — import everything advertised. Only correct where every
        installed package has already been read and vouched for, which is the
        same posture `PluginStore.load_installed(isolate="trusted")` names.

    Returns the count loaded.
    """
    batch = list(plugins or [])
    eps = discover_entrypoints()
    if eps and allow_entrypoints is None:
        log.info("[hookspecs] %d entry-point plugin(s) advertised and NOT "
                 "loaded (no policy given): %s", len(eps),
                 ", ".join(str(getattr(e, "name", e)) for e in eps))
    elif eps:
        decide = (lambda _ep: True) if allow_entrypoints is True else allow_entrypoints
        for ep in eps:
            try:
                if not decide(ep):
                    continue
            except Exception as exc:                 # a policy that raises
                log.warning("[hookspecs] policy failed for %r: %s",
                            getattr(ep, "name", ep), exc)
                continue                             # …refuses, never admits
            obj = load_entrypoint(ep)
            if obj is not None:
                batch.append(obj)
    loaded = 0
    for p in batch:
        try:
            if registry.load(p):
                loaded += 1
        except Exception as exc:
            log.warning("[hookspecs] load failed for %r: %s", p, exc)
    return loaded
