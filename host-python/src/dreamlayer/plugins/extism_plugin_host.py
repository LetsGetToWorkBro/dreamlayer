"""plugins/extism_plugin_host.py — the Extism runtime, wearing the host shape.

`extism_host.ExtismHost` has run untrusted WASM under hard limits for months and
had exactly one caller: its own tests. What it lacked was not a runtime but a
PACKAGE — nothing on disk was ever an Extism guest, so nothing ever reached it.
`manifest.kind == "extism"` is that package, and this is the adapter from
`ExtismHost.run(wasm, func, input) -> bytes | None` to the
`start / register_into / stop` contract `PluginStore.load_installed` speaks.

WHY A SECOND WASM RUNTIME IS NOT A DUPLICATE
--------------------------------------------
`wasm_plugin_host` runs a guest in-process and LINKS the host functions its
manifest declared: capabilities enforced by the runtime, with `log`, `fs_read`,
`net_get`, `show_card` available to a plugin that asks. Extism inverts it —
`functions=[]`, `wasi=False`, `allowed_hosts=[]` — so the guest has no host
functions at all. Not "declares none": *has* none, structurally, even if some
future import registered host functions process-wide.

That makes Extism the stricter of the two and the poorer: a guest that cannot
call anything also cannot log, and it gets one shot per sighting with bytes in
and bytes out. Which is right depends on the plugin, and a store that offers
only the more capable one is offering the wearer less isolation than it could.

The ABI is Extism's own, so a plugin written in Rust/Go/JS with the standard PDK
just works: the export named by `manifest.entry` takes the sighting JSON as its
input and returns `{"rows": [...]}` as its output. There is no `dl_alloc` and no
`memory` export to write, because the PDK owns both sides of that.
"""
from __future__ import annotations

import json
import logging
import weakref
from typing import List

from .wasm_plugin_host import MAX_ROWS, RESPONSE_CAP, GuestProvider

log = logging.getLogger("dreamlayer.extism_plugin_host")

#: The import namespace the Extism runtime provides. A guest importing anything
#: else cannot link, so the gate refuses it at install rather than at first use.
HOST_MODULE = "extism:host/env"


#: Hosts with a guest loaded right now — the promotion proof for the
#: `extism_plugins` capability, on the same rule as its sibling: the wheel
#: importing is not a guest running.
_LIVE: "weakref.WeakSet" = weakref.WeakSet()


def live_guests() -> int:
    return len(_LIVE)


def available() -> bool:
    """True when the extism wheel is installed."""
    try:
        from .extism_host import ExtismHost
        return bool(ExtismHost.available)
    except Exception:                                # pragma: no cover
        return False


class ExtismPluginHost:
    """Adapts an `extism`-kind package to the isolated-host contract."""

    def __init__(self, package_dir, requires=(), health=None, name="",
                 caplog=None):
        self.dir = package_dir
        self.requires = tuple(requires or ())
        self.health = health
        self.name = name or "extism-plugin"
        self.caplog = caplog
        self._wasm: bytes = b""
        self._host = None
        self._func = "run"
        self.rejected: list = []

    @staticmethod
    def available() -> bool:
        return available()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Read the guest and hold a configured runtime. False, never an
        exception, so one bad plugin cannot stop a boot.

        Unlike the component host there is no instantiate step to fail on: an
        Extism plugin is constructed per call (that is how the runtime bounds
        memory and wall-clock), so `start` proves the package is readable and
        the runtime is present, and a broken module surfaces on the first
        `build_rows` as no rows.
        """
        try:
            from pathlib import Path

            from .extism_host import default_extism_host
            from .package import PluginPackage

            pkg = PluginPackage.load(Path(self.dir))
            if not pkg.manifest.is_extism:
                return False
            host = default_extism_host()
            if host is None:
                return False
            self._wasm = pkg.wasm_bytes()
            self._func = pkg.manifest.factory or "run"
            self._host = host
            _LIVE.add(self)
            return True
        except Exception as exc:                     # noqa: BLE001
            # Only the exception KIND — the message is the guest's, and the
            # logging discipline keeps third-party text out of log lines.
            log.warning("[extism-plugin] %s failed to start: %s",
                        self.name, type(exc).__name__)
            if self.health is not None:
                try:
                    self.health.record_failure(f"plugin:{self.name}", exc)
                except Exception:                    # noqa: BLE001
                    pass
            self._host = None
            return False

    def stop(self) -> None:
        _LIVE.discard(self)
        self._host = None
        self._wasm = b""

    # -- the provider surface ---------------------------------------------

    def register_into(self, orchestrator) -> dict:
        registered = {"object_providers": 0, "shop_providers": 0,
                      "rejected": self.rejected}
        if self._host is None:
            return registered
        try:
            orchestrator.object_lens.registry.register(GuestProvider(self))
            registered["object_providers"] = 1
        except Exception as exc:                     # noqa: BLE001
            log.warning("[extism-plugin] %s could not register: %s",
                        self.name, type(exc).__name__)
        return registered

    def build_rows(self, sighting: dict) -> List[dict]:
        """Sighting in, rows out. `[]` for anything unusual — `ExtismHost.run`
        already answers None for a trap, a timeout, a memory trip or an
        oversized reply, so this only has to bound and shape what comes back."""
        host = self._host
        if host is None or not self._wasm:
            return []
        try:
            payload = json.dumps(sighting, separators=(",", ":")).encode("utf-8")
            if len(payload) > RESPONSE_CAP:
                return []
            out = host.run(self._wasm, self._func, payload)
            if not out:
                return []                            # "nothing to say"
            if len(out) > RESPONSE_CAP:
                log.warning("[extism-plugin] %s returned an over-long response",
                            self.name)
                return []
            rows = json.loads(out.decode("utf-8", "replace")).get("rows") or []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[extism-plugin] %s build failed: %s",
                        self.name, type(exc).__name__)
            return []
        out_rows = []
        for r in rows[:MAX_ROWS]:
            if isinstance(r, dict):
                out_rows.append({"label": str(r.get("label", ""))[:200],
                                 "detail": str(r.get("detail", ""))[:400]})
        return out_rows
