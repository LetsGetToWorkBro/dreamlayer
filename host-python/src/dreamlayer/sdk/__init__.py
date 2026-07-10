"""dreamlayer.sdk — the supported surface for building DreamLayer plugins.

This is the *one* module a plugin author imports from. Everything here is a
stable, curated re-export of DreamLayer's extension points; nothing below it is
supported for third parties, and the host is free to move its internals as long
as these names keep their meaning. Import from here, never from
``dreamlayer.orchestrator.*`` / ``dreamlayer.object_lens.*`` / the rest of the
host — those paths are internal and *will* move.

    from dreamlayer.sdk import make_plugin

    def register(ctx):
        ctx.add_card_renderer("MyCard", draw_my_card)

    def plugin():
        return make_plugin("my-plugin", register, requires=("cards",))

A plugin is a small object with ``name``, ``version``, ``requires``, and a
``register(ctx)`` method (``make_plugin`` builds one from a callable). API v2
adds an optional lifecycle — ``start(ctx)`` / ``stop()`` / ``tick(now)`` /
``on_event(kind, payload)`` — plus veil-gated events (``ctx.subscribe``) and
per-plugin persisted settings (``ctx.settings``). Declare only the capabilities
you use in ``requires``; the host grants them and the validation gate refuses
anything undeclared.

The surface, by what you're building:

* **A HUD card** — ``ctx.add_card_renderer(card_type, fn)`` where
  ``fn(draw, card)`` paints with a Pillow-style ``draw`` on a 256×256 additive
  display. Declares ``cards``.
* **A look-at-a-thing panel row** — subclass :class:`PanelProvider`
  (``matches``/``build`` returning :class:`PanelRow` from an
  :class:`ObjectSighting`). Declares ``object_lens``.
* **A new lens the glance can route to** — subclass :class:`LensCandidate`
  (``bid(reading, ctx)`` returning a :class:`LensBid` from a
  :class:`GlanceReading`). Declares ``glance``.
* **A TasteLens price/review connector** — ``ctx.add_shop_provider(fn)`` where
  ``fn(label, attrs) -> {rating?, price?, ...}``. Declares ``shop``.
* **An on-glass perceptor** — an object with ``listen(audio)`` /
  ``perceive(frame)`` returning an :class:`AudioPercept`; register with
  ``ctx.add_perceptor(...)``. Declares ``perception``.

Package + ship: :func:`validate` runs the same gate the store does (integrity,
capability scan, smoke test); :class:`PluginPackage` + :class:`PluginManifest`
build the publishable artifact. The ``dreamlayer plugins`` CLI wraps all of it.
"""
from __future__ import annotations

# --- authoring: the plugin object + the context it's handed ------------------
from ..plugins.base import (
    Plugin,
    SimplePlugin,
    make_plugin,
    PluginContext,
    PluginSettings,
)

# --- extension base classes: what your plugin subclasses / returns -----------
from ..object_lens.providers import PanelProvider
from ..object_lens.schema import ObjectSighting, PanelRow, ObjectPanel
from ..orchestrator.glance import LensCandidate, LensBid, GlanceReading
from ..ai_brain.perception import AudioPercept

# --- events (API v2): react to host moments ----------------------------------
from ..plugins.events import PluginEventBus, KINDS as EVENT_KINDS

# --- packaging + the validation gate (for tooling / local checks) ------------
from ..plugins.package import (
    PluginManifest,
    PluginPackage,
    sha256_of,
    KNOWN_CAPABILITIES,
    API_VERSION,
    SUPPORTED_API,
)
from ..plugins.validate import validate, scan_source, ValidationReport

# SDK contract version. Independent of the host package version: it bumps only
# when this surface changes in a way a plugin author would notice. A future
# standalone ``dreamlayer-sdk`` distribution inherits this number.
__version__ = "1.0.0"

# The latest plugin API level this SDK speaks (SUPPORTED_API is the full set a
# host accepts; API_VERSION is the manifest default). Modern plugins target this.
API = max(SUPPORTED_API, key=int)

__all__ = [
    # authoring
    "make_plugin", "SimplePlugin", "Plugin", "PluginContext", "PluginSettings",
    # extension base classes
    "PanelProvider", "PanelRow", "ObjectSighting", "ObjectPanel",
    "LensCandidate", "LensBid", "GlanceReading", "AudioPercept",
    # events
    "PluginEventBus", "EVENT_KINDS",
    # packaging + validation
    "PluginManifest", "PluginPackage", "sha256_of", "validate", "scan_source",
    "ValidationReport", "KNOWN_CAPABILITIES", "API_VERSION", "SUPPORTED_API",
    # version
    "__version__", "API",
]
