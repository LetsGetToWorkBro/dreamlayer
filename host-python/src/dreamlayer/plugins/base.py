"""plugins/base.py — the extension surface, formalised.

DreamLayer was already a plugin system in disguise: the object-lens
`ProviderRegistry` (providers declare `matches`/`build`), the Glance Arbiter's
candidate list (candidates declare `bid`), the `BrainRouter` / `PerceptionRouter`
tiers, and the HUD renderer's dispatch map are all declarative registries. This
module gives them one supported doorway so third parties can extend the layer
without touching core — and so first-party features can be built *through* the
same doorway (dogfood).

A plugin is small:

    def register(ctx):
        ctx.add_object_provider(MyProvider())        # look-at-a-thing rows
        ctx.add_glance_candidate(MyCandidate())      # a new lens the look can pick
        ctx.add_card_renderer("MyCard", draw_my_card)

    my_plugin = make_plugin("my-plugin", register, requires=("vision",))

`PluginContext` is the *narrow* surface a plugin is handed — it can extend the
registries and read veil/ring state, but it cannot reach into private
orchestrator internals. `PluginRegistry` loads plugins, checks each plugin's
`requires` against the host's capabilities, and isolates failures: one bad or
mismatched plugin is skipped, never fatal.

API v2 adds three things without breaking a single v1 plugin:
  - **Lifecycle** — optional ``start(ctx)`` / ``stop()`` / ``tick(now)`` /
    ``on_event(kind, payload)`` methods (all duck-typed; a plugin implements
    only what it needs). ``tick`` formalises the dream-reactor shape.
  - **Events** — ``ctx.subscribe(kind, fn)`` over the veil-gated
    ``PluginEventBus`` (see events.py); each kind requires the matching
    capability.
  - **Settings** — ``ctx.settings``, a per-plugin persisted dict.

Sandbox posture: reviewed first-party and curated plugins run in-process
(*read the code you run*). *Unreviewed* third-party plugins can be run in a
capability-mediated subprocess (see isolation.py) — the real jail v1 deferred.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable


# --- what a plugin is --------------------------------------------------------

@runtime_checkable
class Plugin(Protocol):
    name: str
    version: str
    requires: tuple            # capability names the host must provide

    def register(self, ctx: "PluginContext") -> None: ...


@dataclass
class SimplePlugin:
    """A plugin from a plain `register(ctx)` callable — the common case."""
    name: str
    register_fn: Callable[["PluginContext"], None]
    version: str = "0.1.0"
    requires: tuple = ()

    def register(self, ctx: "PluginContext") -> None:
        self.register_fn(ctx)


def make_plugin(name: str, register: Callable[["PluginContext"], None],
                requires: tuple = (), version: str = "0.1.0") -> SimplePlugin:
    return SimplePlugin(name=name, register_fn=register, requires=tuple(requires),
                        version=version)


# --- the capability-scoped, veil-gated memory surface -----------------------

class MemoryFacade:
    """The ONLY supported way a plugin reads the wearer's memory.

    The audit (2026-07-14 CRITICAL #4) found that an in-process plugin was
    handed the raw ``MemoryDB`` (all embeddings/contacts) via ``ctx._db`` — a
    clean memory-exfil surface, since underscore-prefixing is not access
    control in Python. This facade replaces that: it exposes only a handful of
    read-only queries and enforces two gates on **every** call:

      * **capability** — the plugin must hold the declared ``memory``
        capability; without it a read raises :class:`PermissionError`. The
        default orchestrator never grants ``memory``
        (``PluginOps._plugin_capabilities``), so by default this facade refuses
        everything — the fail-closed posture the audit asks for.
      * **veil** — while recall is paused/incognito (``allow_recall()`` is
        false, or the gate raises) every read returns ``[]``, so a plugin can't
        read memory during the Veil even when it holds the capability.

    There is deliberately no write/purge/raw-connection surface here.
    """

    def __init__(self, db, *, caps, veil):
        self._db = db
        self._caps = frozenset(caps or ())
        self._veil = veil

    def _require_cap(self) -> None:
        if "memory" not in self._caps:
            raise PermissionError(
                "plugin memory access requires the declared 'memory' capability")

    def _recall_ok(self) -> bool:
        v = self._veil
        if v is None or not hasattr(v, "allow_recall"):
            return True
        try:
            return bool(v.allow_recall())
        except Exception:
            return False                      # gate raised → fail closed (veiled)

    def memories(self, kind: str | None = None) -> list:
        """Kept memories (optionally filtered by kind). ``[]`` while veiled."""
        self._require_cap()
        if self._db is None or not self._recall_ok():
            return []
        return list(self._db.memories(kind))

    def commitments(self, person: str | None = None) -> list:
        """Kept commitments/promises. ``[]`` while veiled."""
        self._require_cap()
        if self._db is None or not self._recall_ok():
            return []
        return list(self._db.commitments(person))

    def places(self) -> list:
        """Known places. ``[]`` while veiled."""
        self._require_cap()
        if self._db is None or not self._recall_ok():
            return []
        return list(self._db.places())


# --- the narrow surface a plugin is handed ----------------------------------

class PluginContext:
    """Everything a plugin may touch — and nothing more. Each `add_*` wires
    into the real registry when the host provided one, and records what was
    added (for introspection/tests). Absent targets no-op gracefully, so a
    plugin runs the same in a minimal test harness as in the full app."""

    def __init__(self, *, object_registry=None, glance_arbiter=None,
                 brain=None, perception=None, renderer=None,
                 capabilities=frozenset(), ring=None, veil=None,
                 mesh=None, shop_registry=None, config: Optional[dict] = None,
                 events=None, db=None):
        self._object_registry = object_registry
        self._glance = glance_arbiter
        self._brain = brain
        self._perception = perception
        self._renderer = renderer
        self._caps = frozenset(capabilities)
        self._ring = ring
        self._veil = veil
        self._mesh = mesh
        self._shop_registry = shop_registry
        self.config = dict(config or {})
        self.added: dict[str, list] = {
            "object_provider": [], "glance_candidate": [], "vision_brain": [],
            "knowledge_brain": [], "perceptor": [], "card_renderer": [],
            "shop_provider": [],
        }
        # v2: the event bus, a db for persisted settings, and the name of the
        # plugin currently being registered/ticked (set by the registry so a
        # shared context still gives each plugin its own settings/subscriptions).
        # `_db` is a PRIVATE backing store used only for (a) per-plugin settings
        # k/v and (b) constructing the capability-scoped `memory` facade — it is
        # NOT a plugin-facing surface. A plugin reads memory ONLY through
        # `ctx.memory` (gated); the raw db is never exposed as an extension
        # point (audit 2026-07-14 CRITICAL #4).
        self._events = events
        self._db = db
        self._current_plugin = ""
        self._settings_cache: dict[str, dict] = {}

    @contextmanager
    def _as(self, plugin_name: str):
        """Scope the context to one plugin (settings/subscription ownership)."""
        prev = self._current_plugin
        self._current_plugin = plugin_name
        try:
            yield
        finally:
            self._current_plugin = prev

    # -- capability queries --------------------------------------------------

    def has(self, capability: str) -> bool:
        return capability in self._caps

    @property
    def capabilities(self) -> frozenset:
        return self._caps

    # -- read-only host state a plugin may look at ---------------------------

    @property
    def ring(self):
        return self._ring

    @property
    def mesh(self):
        return self._mesh

    def veiled(self) -> bool:
        v = self._veil
        return bool(v is not None and hasattr(v, "allow_capture")
                    and not v.allow_capture())

    @property
    def memory(self) -> "MemoryFacade":
        """The capability-scoped, veil-gated memory surface — the ONLY supported
        way a plugin reads the wearer's kept memories/commitments/places.
        Requires the declared ``memory`` capability and honours the Veil (see
        :class:`MemoryFacade`). The raw ``MemoryDB`` is never handed out."""
        return MemoryFacade(self._db, caps=self._caps, veil=self._veil)

    # -- extension points ----------------------------------------------------

    def add_object_provider(self, provider) -> None:
        """Register a look-at-a-thing panel provider (object_lens facet).
        Requires the declared ``object_lens`` capability — enforced here at the
        call site (audit 2026-07-14): an undeclared reach is refused and
        recorded, never silently wired into the real registry."""
        if not self.has("object_lens"):
            self.added.setdefault("rejected", []).append(
                ("object_provider", "object_lens"))
            return
        self.added["object_provider"].append(provider)
        if self._object_registry is not None:
            self._object_registry.register(provider)

    def add_glance_candidate(self, candidate) -> None:
        """Add a lens the Glance Arbiter can route a look to."""
        self.added["glance_candidate"].append(candidate)
        if self._glance is not None:
            self._glance.candidates.append(candidate)

    def add_vision_brain(self, brain) -> None:
        # A vision/knowledge tier is fed the wearer's frame/recall-query text and
        # is consulted by the router in EVERY privacy mode, so registering one is
        # a capability, not a free extension point. Enforce the declared grant at
        # the call site (audit 2026-07-14): an undeclared reach is refused and
        # recorded, never silently wired into the real router.
        if not self.has("vision"):
            self.added.setdefault("rejected", []).append(("vision_brain", "vision"))
            return
        self.added["vision_brain"].append(brain)
        if self._brain is not None:
            self._brain.add_vision(brain)

    def add_knowledge_brain(self, brain) -> None:
        if not self.has("knowledge"):
            self.added.setdefault("rejected", []).append(
                ("knowledge_brain", "knowledge"))
            return
        self.added["knowledge_brain"].append(brain)
        if self._brain is not None:
            self._brain.add_knowledge(brain)

    def add_perceptor(self, perceptor, prefer: bool = True) -> None:
        """Register an on-glass perceptor (fed live frames/audio). Requires the
        declared ``perception`` capability — enforced at the call site (audit
        2026-07-14): an undeclared reach is refused and recorded, never wired
        into the real perception router."""
        if not self.has("perception"):
            self.added.setdefault("rejected", []).append(
                ("perceptor", "perception"))
            return
        self.added["perceptor"].append(perceptor)
        if self._perception is not None:
            self._perception.add_perceptor(perceptor, prefer=prefer)

    def add_card_renderer(self, card_type: str, fn) -> None:
        """Register a renderer for the plugin's own card type."""
        self.added["card_renderer"].append(card_type)
        if self._renderer is not None and hasattr(self._renderer, "register"):
            self._renderer.register(card_type, fn)

    def add_shop_provider(self, fn) -> None:
        """Register a TasteLens price/review connector: fn(label, attrs) ->
        {rating?, price?, …}. Consulted when a shelf/menu is ranked.

        A shop connector reaches an external price/review source, so it must
        have declared either the ``shop`` entitlement or ``network`` (its egress
        channel) — enforced at the call site (audit 2026-07-14). An undeclared
        reach is refused and recorded, never wired into the taste registry."""
        if not (self.has("shop") or self.has("network")):
            self.added.setdefault("rejected", []).append(
                ("shop_provider", "shop"))
            return
        self.added["shop_provider"].append(fn)
        if self._shop_registry is not None:
            self._shop_registry.append(fn)

    # -- v2: events ----------------------------------------------------------

    def subscribe(self, kind: str, fn) -> bool:
        """React to a host moment (see plugins/events.py KINDS). The kind's
        required capability must be declared, or the subscription is refused —
        no undeclared reach into the wearer's activity. Returns whether it
        subscribed."""
        from .events import REQUIRED_CAP
        cap = REQUIRED_CAP.get(kind)
        if cap is not None and not self.has(cap):
            return False
        if self._events is None:
            return False
        return self._events.subscribe(kind, fn, plugin_name=self._current_plugin)

    # -- v2: per-plugin persisted settings -----------------------------------

    @property
    def settings(self) -> "PluginSettings":
        """A small persisted dict scoped to the current plugin (backed by the
        MemoryDB settings table when a db is wired, in-memory otherwise)."""
        name = self._current_plugin or "_"
        return PluginSettings(self, name)

    def _load_settings(self, name: str) -> dict:
        if name in self._settings_cache:
            return self._settings_cache[name]
        data: dict = {}
        if self._db is not None and hasattr(self._db, "get_setting"):
            raw = self._db.get_setting(f"plugin:{name}")
            if raw:
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    data = {}
        self._settings_cache[name] = data
        return data

    def _save_settings(self, name: str, data: dict) -> None:
        self._settings_cache[name] = data
        if self._db is not None and hasattr(self._db, "set_setting"):
            self._db.set_setting(f"plugin:{name}", json.dumps(data))


class PluginSettings:
    """Dict-like persisted view for one plugin. Writes flush immediately."""

    def __init__(self, ctx: "PluginContext", name: str):
        self._ctx = ctx
        self._name = name

    def get(self, key: str, default=None):
        return self._ctx._load_settings(self._name).get(key, default)

    def set(self, key: str, value) -> None:
        data = dict(self._ctx._load_settings(self._name))
        data[key] = value
        self._ctx._save_settings(self._name, data)

    def all(self) -> dict:
        return dict(self._ctx._load_settings(self._name))


# --- the loader --------------------------------------------------------------

@dataclass
class LoadResult:
    loaded: list = field(default_factory=list)     # names that registered
    skipped: list = field(default_factory=list)    # (name, reason) — missing capability
    failed: list = field(default_factory=list)     # (name, error) — register() threw


class PluginRegistry:
    """Loads plugins into a context, gating on capabilities and isolating
    failures. Idempotent per name — a plugin loads once. v2 adds a lifecycle
    (start/stop/tick/on_event), so the registry keeps the live plugin objects
    and drives them; every lifecycle call is isolated and (optionally) recorded
    to a HealthLedger under seam ``plugin:<name>``."""

    def __init__(self, context: PluginContext, health=None, caplog=None):
        self.ctx = context
        self.result = LoadResult()
        self._seen: set = set()
        self._objs: dict[str, object] = {}   # name -> live plugin (for lifecycle)
        self._health = health
        self._caplog = caplog                # CapabilityLedger (transparency)

    def _name(self, plugin) -> str:
        return getattr(plugin, "name", repr(plugin))

    def _record(self, name: str, exc) -> None:
        if self._health is not None:
            self._health.record_failure(f"plugin:{name}", exc)

    def load(self, plugin) -> bool:
        name = self._name(plugin)
        if name in self._seen:
            return False
        self._seen.add(name)
        missing = [c for c in getattr(plugin, "requires", ()) if not self.ctx.has(c)]
        if missing:
            self.result.skipped.append((name, "missing capability: " + ", ".join(missing)))
            return False
        try:
            with self.ctx._as(name):               # scope settings/subscriptions
                plugin.register(self.ctx)
        except Exception as e:                     # one bad plugin never sinks the app
            self.result.failed.append((name, repr(e)))
            self._record(name, e)
            return False
        self.result.loaded.append(name)
        self._objs[name] = plugin
        return True

    def load_all(self, plugins) -> LoadResult:
        for p in plugins:
            self.load(p)
        return self.result

    # -- v2 lifecycle --------------------------------------------------------

    def _call(self, plugin, method: str, *args):
        """Invoke an optional lifecycle method under this plugin's scope,
        isolating + recording failures. Returns the result or None."""
        fn = getattr(plugin, method, None)
        if not callable(fn):
            return None
        name = self._name(plugin)
        try:
            with self.ctx._as(name):
                return fn(*args)
        except Exception as exc:
            self._record(name, exc)
            return None

    def start_all(self) -> None:
        for p in list(self._objs.values()):
            self._call(p, "start", self.ctx)

    def stop_all(self) -> None:
        for p in list(self._objs.values()):
            self._call(p, "stop")

    def tick_all(self, now: float) -> list:
        """Tick every plugin; return the non-None commands they emit (the
        dream-reactor pattern, formalised)."""
        out = []
        for p in list(self._objs.values()):
            cmd = self._call(p, "tick", now)
            if cmd is not None:
                out.append(cmd)
        return out

    def dispatch_event(self, kind: str, payload: dict) -> None:
        """Deliver a lifecycle-style event to plugins that implement
        ``on_event`` (distinct from bus subscriptions, which are per-callback)."""
        for name, p in list(self._objs.items()):
            if callable(getattr(p, "on_event", None)):
                self._call(p, "on_event", kind, payload)
                if self._caplog is not None:      # transparency: event routed here
                    self._caplog.record(name, f"event:{kind}")

    def reload(self, plugin) -> bool:
        """Hot-reload: stop + forget the old instance of this name, then load
        the given (freshly-validated) plugin object. Caller re-validates."""
        name = self._name(plugin)
        old = self._objs.pop(name, None)
        if old is not None:
            self._call(old, "stop")
        if self.ctx._events is not None:
            self.ctx._events.unsubscribe_plugin(name)
        self._seen.discard(name)
        self.result.loaded = [n for n in self.result.loaded if n != name]
        return self.load(plugin)

    @property
    def plugins(self) -> dict:
        return dict(self._objs)
