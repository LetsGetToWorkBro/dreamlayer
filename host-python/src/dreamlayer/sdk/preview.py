"""Render a plugin's HUD card through the *real* on-glass renderer.

This is the SDK's superpower: because DreamLayer runs the exact device render
path in a software rasterizer, an author can see — and snapshot-test — precisely
what their card looks like on the glasses, from a unit test, with no hardware.

    from dreamlayer.sdk import render_card
    img = render_card(my_plugin, {"type": "HelloCard", "text": "hi"})
    img.save("preview.png")            # a PIL image, 256x256, the device output

Use it for visual regression: render, then assert against a committed golden
(pixel-equal or a small tolerance). The renderer + PIL are imported lazily, so
``import dreamlayer.sdk`` stays light for authors who don't preview.
"""
from __future__ import annotations

from typing import Optional


def _plugin_object(plugin):
    """Accept a plugin object, a factory callable, or a PluginPackage."""
    from ..plugins.package import PluginPackage
    from ..plugins.store import load_plugin_object
    if isinstance(plugin, PluginPackage):
        return load_plugin_object(plugin)
    return plugin() if callable(plugin) and not hasattr(plugin, "register") else plugin


def registered_card_types(plugin) -> list:
    """The card types a plugin registers (populated by running its
    ``register`` against a renderer). Empty for provider-only plugins."""
    from ..hud.renderer import CardRenderer
    from ..plugins.base import PluginContext, PluginRegistry
    from ..plugins.package import KNOWN_CAPABILITIES
    renderer = CardRenderer()
    ctx = PluginContext(renderer=renderer,
                        capabilities=frozenset(KNOWN_CAPABILITIES), config={})
    PluginRegistry(ctx).load_all([_plugin_object(plugin)])
    return list(renderer._extra.keys())


def contributions(plugin) -> dict:
    """What a plugin *adds* to the layer — the à-la-carte contribution map,
    discovered by running its ``register`` against a recording context. Card
    renderers are listed by type; other extension points by count. This is how
    the store/CLI show "what does this plugin do" without pluggy-style hook
    discovery (see docs/adr/0001-plugin-extension-model.md)."""
    from ..plugins.base import PluginContext, PluginRegistry
    from ..plugins.package import KNOWN_CAPABILITIES
    ctx = PluginContext(capabilities=frozenset(KNOWN_CAPABILITIES), config={})
    PluginRegistry(ctx).load_all([_plugin_object(plugin)])
    out: dict = {}
    for kind, items in ctx.added.items():
        if items:
            out[kind] = list(items) if kind == "card_renderer" else len(items)
    return out


def render_card(plugin, card: Optional[dict] = None):
    """Render ``card`` through the real 256×256 device renderer and return a PIL
    image. ``plugin`` is a plugin object / factory / PluginPackage; ``card`` is
    the dict your card logic emits (defaults to an empty card of the plugin's
    first registered type). Raises ``ValueError`` if the plugin registers no
    card renderer."""
    from ..hud.renderer import CardRenderer
    from ..plugins.base import PluginContext, PluginRegistry
    from ..plugins.package import KNOWN_CAPABILITIES

    renderer = CardRenderer()
    ctx = PluginContext(renderer=renderer,
                        capabilities=frozenset(KNOWN_CAPABILITIES), config={})
    reg = PluginRegistry(ctx)
    reg.load_all([_plugin_object(plugin)])
    reg.start_all()                       # v2 plugins may finish wiring in start()
    types = list(renderer._extra.keys())
    if not types:
        raise ValueError("this plugin registers no card renderer — nothing to preview")
    card = dict(card or {})
    card.setdefault("type", types[0])
    if card["type"] not in renderer._extra:
        raise ValueError(f"card type {card['type']!r} is not one this plugin "
                         f"registers ({', '.join(types)})")
    return renderer.render(card)
