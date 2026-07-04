"""dreamlayer.plugins — the supported extension surface (see docs/PLATFORM.md).

The registries the codebase already had, given one doorway: object-lens
providers, Glance Arbiter candidates, Brain/Perception tiers, and HUD card
renderers. A plugin is a `register(ctx)` callable gated by capabilities and
loaded with failures isolated. First-party features are built through the same
doorway (dogfood), so the API is proven by use.
"""
from .base import (
    Plugin, SimplePlugin, make_plugin, PluginContext, PluginRegistry,
    LoadResult,
)

__all__ = [
    "Plugin", "SimplePlugin", "make_plugin", "PluginContext",
    "PluginRegistry", "LoadResult",
]
