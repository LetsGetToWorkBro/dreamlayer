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

Sandbox posture (v1): plugins are trusted in-process Python — the open-source
ethos is *read the code you run*. The capability gate keeps a plugin that only
asked for `midi` from silently using `vision`; a real process/wasm sandbox is a
later hardening.
"""
from __future__ import annotations

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


# --- the narrow surface a plugin is handed ----------------------------------

class PluginContext:
    """Everything a plugin may touch — and nothing more. Each `add_*` wires
    into the real registry when the host provided one, and records what was
    added (for introspection/tests). Absent targets no-op gracefully, so a
    plugin runs the same in a minimal test harness as in the full app."""

    def __init__(self, *, object_registry=None, glance_arbiter=None,
                 brain=None, perception=None, renderer=None,
                 capabilities=frozenset(), ring=None, veil=None,
                 mesh=None, shop_registry=None, config: Optional[dict] = None):
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

    # -- extension points ----------------------------------------------------

    def add_object_provider(self, provider) -> None:
        """Register a look-at-a-thing panel provider (object_lens facet)."""
        self.added["object_provider"].append(provider)
        if self._object_registry is not None:
            self._object_registry.register(provider)

    def add_glance_candidate(self, candidate) -> None:
        """Add a lens the Glance Arbiter can route a look to."""
        self.added["glance_candidate"].append(candidate)
        if self._glance is not None:
            self._glance.candidates.append(candidate)

    def add_vision_brain(self, brain) -> None:
        self.added["vision_brain"].append(brain)
        if self._brain is not None:
            self._brain.add_vision(brain)

    def add_knowledge_brain(self, brain) -> None:
        self.added["knowledge_brain"].append(brain)
        if self._brain is not None:
            self._brain.add_knowledge(brain)

    def add_perceptor(self, perceptor, prefer: bool = True) -> None:
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
        {rating?, price?, …}. Consulted when a shelf/menu is ranked."""
        self.added["shop_provider"].append(fn)
        if self._shop_registry is not None:
            self._shop_registry.append(fn)


# --- the loader --------------------------------------------------------------

@dataclass
class LoadResult:
    loaded: list = field(default_factory=list)     # names that registered
    skipped: list = field(default_factory=list)    # (name, reason) — missing capability
    failed: list = field(default_factory=list)     # (name, error) — register() threw


class PluginRegistry:
    """Loads plugins into a context, gating on capabilities and isolating
    failures. Idempotent per name — a plugin loads once."""

    def __init__(self, context: PluginContext):
        self.ctx = context
        self.result = LoadResult()
        self._seen: set = set()

    def load(self, plugin) -> bool:
        name = getattr(plugin, "name", repr(plugin))
        if name in self._seen:
            return False
        self._seen.add(name)
        missing = [c for c in getattr(plugin, "requires", ()) if not self.ctx.has(c)]
        if missing:
            self.result.skipped.append((name, "missing capability: " + ", ".join(missing)))
            return False
        try:
            plugin.register(self.ctx)
        except Exception as e:                     # one bad plugin never sinks the app
            self.result.failed.append((name, repr(e)))
            return False
        self.result.loaded.append(name)
        return True

    def load_all(self, plugins) -> LoadResult:
        for p in plugins:
            self.load(p)
        return self.result
