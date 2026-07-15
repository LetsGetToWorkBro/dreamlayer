"""ops_plugins — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ._ops_host import OpsHost



class PluginOps(OpsHost):

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
        real registries — including the v2 event bus (veil-gated) and the db
        that backs per-plugin persisted settings."""
        from ..plugins import PluginContext
        return PluginContext(
            object_registry=self.object_lens.registry,
            glance_arbiter=self.glance_arbiter,
            brain=self.brain, perception=self.perception, renderer=renderer,
            capabilities=self._plugin_capabilities(),
            ring=self.ring, veil=self.privacy, mesh=self.mesh,
            shop_registry=self._shop_providers, config=config,
            events=self.plugin_events, db=self.db)


    def load_plugins(self, plugins, renderer=None, config=None):
        """Load a list of plugins into this orchestrator. Gated by capabilities,
        failures isolated. Registered plugins are started (v2 lifecycle).
        Returns a LoadResult (loaded / skipped / failed)."""
        from ..plugins import PluginRegistry
        reg = self.plugins or PluginRegistry(
            self.plugin_context(renderer, config), health=self.health,
            caplog=self.capability_log)
        res = reg.load_all(plugins)
        reg.start_all()
        self.plugins = reg
        # transparency: record what each loaded plugin was granted
        for name, obj in reg.plugins.items():
            self.capability_log.grant(name, getattr(obj, "requires", ()))
        return res


    def capability_report(self, name: str | None = None):
        """The plugin capability-transparency log the wearer can read: what each
        loaded plugin was granted and what it has actually done with it (host
        events routed to it, isolated-provider calls). Pass a name for one
        plugin, else every plugin seen. See orchestrator/capability_log.py for
        the honest scope (in-process raw network isn't intercepted)."""
        if name is not None:
            return self.capability_log.summary(name)
        return self.capability_log.report()


    def tick_plugins(self, now: float | None = None) -> list:
        """Tick every loaded plugin (v2); emit their non-None commands as raw
        frames. Safe no-op when nothing is loaded."""
        if self.plugins is None:
            return []
        import time as _t
        cmds = self.plugins.tick_all(now if now is not None else _t.monotonic())
        for cmd in cmds:
            if isinstance(cmd, dict):
                self.bridge.send_raw(cmd)
        return cmds


    def publish_plugin_event(self, kind: str, payload: dict | None = None) -> None:
        """Fan a host moment out to subscribed plugins (veil-gated in the bus)
        and to plugins implementing on_event. One call, both paths."""
        self.plugin_events.publish(kind, payload or {})
        if self.plugins is not None:
            self.plugins.dispatch_event(kind, payload or {})
