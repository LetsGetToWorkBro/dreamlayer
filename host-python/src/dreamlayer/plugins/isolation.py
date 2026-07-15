"""plugins/isolation.py — the capability-mediated subprocess jail.

The static gate (validate.py) can catch obvious danger in *reviewed* code, but
it can never fully sandbox in-process Python — a determined author hides intent.
This is the real isolation validate.py deferred: an unreviewed third-party plugin
runs in a child process (sandbox_child.py), and the host holds only thin proxies
that speak JSON-lines RPC to it.

What crosses the boundary is deliberately tiny: object-provider ``matches``/
``build`` and shop-provider calls — pure request→data, each under the same
glance-panel deadline the in-process registry uses, each failure/timeout recorded
to the HealthLedger and the provider skipped. The child can compute; it cannot
touch the wearer's frame (never sent), the display, the mesh, the filesystem, or
the network on the host's behalf. A hung child is killed; a crashed child is
reported, not fatal.

Usage (via PluginStore.load_installed(..., isolate="untrusted")):
    host = SubprocessPluginHost(pkg_dir, capabilities, health=…)
    if host.start():
        host.register_into(orchestrator)   # proxies land in the real registries
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from ..orchestrator.budgets import GLANCE_PANEL_MS, run_with_deadline
from ..object_lens.schema import PanelRow


class SubprocessPluginHost:
    """Owns one sandbox child and the host-side proxies for its providers."""

    def __init__(self, package_dir, capabilities, health=None,
                 deadline_ms: float = GLANCE_PANEL_MS, name: str = "", caplog=None):
        self.package_dir = Path(package_dir)
        self.capabilities = list(capabilities or [])
        self.health = health
        self.caplog = caplog               # CapabilityLedger (transparency)
        self.deadline_ms = deadline_ms
        self.name = name or self.package_dir.name
        self._proc: Optional[subprocess.Popen] = None
        self.provider_meta: list = []      # [{facet,name}] from the child
        self.shop_count = 0
        self.rejected: list = []
        self._dead = False
        self.sandbox: Optional[str] = None  # which OS sandbox wrapped the child

    # ------------------------------------------------------------------

    def _seam(self) -> str:
        return f"plugin:{self.name}"

    def _fail(self, exc) -> None:
        if self.health is not None:
            self.health.record_failure(self._seam(), exc)

    def _child_argv(self) -> list:
        """The command that launches the sandbox child. Subclasses (e.g. the
        WASM host) override this to run the same child under a different runtime;
        the RPC/proxy machinery above is unchanged."""
        from . import os_sandbox
        prefix = os_sandbox.wrapper(self.capabilities, self.package_dir)
        self.sandbox = os_sandbox.available() if prefix else None
        return prefix + [sys.executable, "-m", "dreamlayer.plugins.sandbox_child",
                         str(self.package_dir), json.dumps(self.capabilities)]

    def start(self) -> bool:
        """Launch the child and read its registration manifest. Returns whether
        the plugin registered any proxyable extension point."""
        try:
            self._proc = subprocess.Popen(
                self._child_argv(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except Exception as exc:
            self._fail(exc)
            return False
        init = self._rpc({"op": "init"})
        if not init or not init.get("ok"):
            self._fail(RuntimeError((init or {}).get("error", "child init failed")))
            self.stop()
            return False
        meta = self._rpc({"op": "meta"}) or {}
        self.provider_meta = meta.get("providers", [])
        self.shop_count = int(init.get("shops", 0))
        self.rejected = list(init.get("rejected", []))
        return bool(self.provider_meta or self.shop_count)

    _TIMEOUT = object()

    def _rpc(self, req: dict) -> Optional[dict]:
        """One request/response, under the deadline. A timeout or a dead pipe
        kills the child and marks the host dead (all proxies then no-op). Every
        such failure is recorded to the plugin's health seam."""
        if self._proc is None or self._dead:
            return None
        if self.caplog is not None and req.get("op") in ("build", "shop"):
            self.caplog.record(self.name, f"rpc:{req['op']}")   # isolated provider call
        proc = self._proc

        def _exchange():
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("sandbox child closed the pipe")
            return json.loads(line)

        try:
            # sentinel default distinguishes a real None reply from a timeout
            result = run_with_deadline(_exchange, self.deadline_ms,
                                       health=None, seam=self._seam(),
                                       default=self._TIMEOUT)
        except Exception as exc:                   # child raised / pipe died
            self._fail(exc)
            self._dead = True
            self.stop()
            return None
        if result is self._TIMEOUT:                # deadline missed → untrustworthy
            self._fail(TimeoutError(f"sandbox {self.name} missed "
                                    f"{self.deadline_ms:.0f}ms"))
            self._dead = True
            self.stop()
            return None
        return result

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    # ------------------------------------------------------------------
    # host-side proxies

    def register_into(self, orchestrator) -> dict:
        """Materialise proxies for every provider the child registered and put
        them into the orchestrator's real registries. Returns a summary."""
        registered: dict[str, Any] = {"object_providers": 0, "shop_providers": 0,
                      "rejected": self.rejected}
        for idx, meta in enumerate(self.provider_meta):
            prov = _ProxyProvider(self, idx, facet=meta.get("facet", "own"),
                                  name=meta.get("name", "provider"))
            orchestrator.object_lens.registry.register(prov)
            registered["object_providers"] += 1
        for idx in range(self.shop_count):
            orchestrator._shop_providers.append(_proxy_shop_fn(self, idx))
            registered["shop_providers"] += 1
        return registered


class _ProxyProvider:
    """A PanelProvider whose matches/build run in the sandbox child. Shape-
    compatible with object_lens.providers.PanelProvider (duck-typed)."""

    def __init__(self, host: SubprocessPluginHost, idx: int,
                 facet: str = "own", name: str = "provider"):
        self._host = host
        self._idx = idx
        self.facet = facet
        self.name = name

    def _sighting_dict(self, sighting) -> dict:
        return {"label": getattr(sighting, "label", ""),
                "confidence": getattr(sighting, "confidence", 0.0),
                "attributes": dict(getattr(sighting, "attributes", {}) or {})}

    def matches(self, sighting) -> bool:
        # matches+build are one round-trip; we cache the last build *keyed by
        # the sighting* so the registry's matches()→build() sequence costs one
        # RPC, not two — but a build() for a different sighting never reuses it.
        sd = self._sighting_dict(sighting)
        resp = self._host._rpc({"op": "build", "idx": self._idx, "sighting": sd})
        self._last: tuple[dict, Any] | None = (sd, resp)
        return bool(resp and resp.get("ok") and resp.get("rows"))

    def build(self, sighting, now=None) -> list:
        sd = self._sighting_dict(sighting)
        cached = getattr(self, "_last", None)
        resp = cached[1] if (cached and cached[0] == sd) else None
        self._last = None                     # consume — never serve twice
        if not (resp and resp.get("ok")):
            resp = self._host._rpc({"op": "build", "idx": self._idx, "sighting": sd})
        if not (resp and resp.get("ok")):
            return []
        return [PanelRow(label=r.get("label", ""), detail=r.get("detail", ""),
                         kind=r.get("kind", ""), value=r.get("value"),
                         source=r.get("source", self.name))
                for r in resp.get("rows", [])]


def _proxy_shop_fn(host: SubprocessPluginHost, idx: int):
    def shop(label: str, attrs: dict) -> dict:
        resp = host._rpc({"op": "shop", "idx": idx,
                          "label": label, "attrs": attrs or {}})
        return (resp or {}).get("result", {}) if resp and resp.get("ok") else {}
    return shop
