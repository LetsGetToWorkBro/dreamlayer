"""ops_plugins — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ..hud import cards
from ..pipelines import vision


class PluginOps:

    def _plugin_capabilities(self) -> frozenset:
        """What this host offers plugins right now — checked against each
        plugin's `requires` at load time (so a vision-needing plugin waits
        until a vision tier is present)."""
        caps = {"object_lens", "glance", "perception", "cards", "ring", "shop"}
        if getattr(self, "mesh", None) is not None:
            caps.add("mesh")
        # the hub can reach the internet unless the Veil / incognito is on
        try:
            if self.privacy.allow_capture():
                caps.add("network")
        except Exception:
            caps.add("network")
        try:
            if self.brain is not None and self.brain.has_vision():
                caps.add("vision")
        except Exception:
            pass
        return frozenset(caps)


    def plugin_context(self, renderer=None, config=None):
        """The narrow surface a plugin is handed, wired to this orchestrator's
        real registries."""
        from ..plugins import PluginContext
        return PluginContext(
            object_registry=self.object_lens.registry,
            glance_arbiter=self.glance_arbiter,
            brain=self.brain, perception=self.perception, renderer=renderer,
            capabilities=self._plugin_capabilities(),
            ring=self.ring, veil=self.privacy, mesh=self.mesh,
            shop_registry=self._shop_providers, config=config)


    def load_plugins(self, plugins, renderer=None, config=None):
        """Load a list of plugins into this orchestrator. Gated by capabilities,
        failures isolated. Returns a LoadResult (loaded / skipped / failed)."""
        from ..plugins import PluginRegistry
        reg = self.plugins or PluginRegistry(self.plugin_context(renderer, config))
        res = reg.load_all(plugins)
        self.plugins = reg
        return res
