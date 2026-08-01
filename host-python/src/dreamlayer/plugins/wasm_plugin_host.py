"""plugins/wasm_plugin_host.py — a WASM guest, wearing the plugin-host shape.

`wasm_component_host.WasmCapabilityHost` runs a guest in-process with zero
ambient authority. `PluginStore.load_installed` speaks a different language:
`start()`, `register_into(orchestrator)`, `stop()`, the same three
`SubprocessPluginHost` answers. This is the adapter between them, and it is the
piece whose absence made the strongest isolation tier unreachable — the store
routed on `wasm_host.available()` (the *subprocess* WASI tier) and never asked
whether the package itself was a wasm guest.

THE ABI, and why it is this shape
---------------------------------
A provider has to receive a sighting and answer with rows. Both are strings, and
the core-ABI contract passes strings as `(ptr, len)` into guest linear memory —
so the guest has to be able to hand the host a buffer, and the host has to be
able to read one back. Three exports, all `i32`, no packing tricks:

    dl_alloc(size: i32) -> i32
        Reserve `size` bytes and return the offset. The host writes the
        sighting JSON there. A guest that cannot allocate cannot be handed
        anything, so this is required.

    dl_build(ptr: i32, len: i32, cap: i32) -> i32
        Read the sighting JSON at (ptr, len); write the response JSON back into
        the SAME buffer, whose capacity is `cap`; return the response length, or
        a negative number for "nothing to say". Writing in place is what keeps
        this to one call and to i32 only — no (ptr<<32|len) packing, which the
        host's i32-only signature table could not carry anyway.

    memory
        The guest's linear memory, exported so the host can reach the buffer.

`dl_alloc` and `dl_build` are the guest's side; `manifest.entry`'s function half
names the build export, so a plugin may call it something else.

The response is `{"rows": [{"label": ..., "detail": ...}, ...]}`. Rows become
`PanelRow`s, exactly as the subprocess host's proxy does — same registry, same
shape, so a wasm plugin and a Python one are indistinguishable downstream.

WHAT THE GUEST CANNOT DO, which is the point
--------------------------------------------
It cannot open a file, a socket, or a clock. It has no syscalls to name. It can
call precisely the host functions its manifest's capabilities link, and
`WasmCapabilityHost` refuses to instantiate a module that imports one it did not
declare — so a plugin that lies about its powers fails to load rather than
failing closed at the first call. Fuel, an epoch deadline and a memory ceiling
bound it besides.
"""
from __future__ import annotations

import json
import logging
import weakref
from typing import Any, List

log = logging.getLogger("dreamlayer.wasm_plugin_host")

#: The guest's allocator export. Fixed rather than manifest-configurable: it is
#: part of the ABI, not of the plugin's identity, and one more configurable name
#: is one more thing a signature has to cover.
ALLOC_EXPORT = "dl_alloc"

#: How much room the host gives a response. A guest that wants to say more than
#: this is saying too much for a panel row.
RESPONSE_CAP = 16 * 1024

#: Rows past this are dropped. The subprocess host bounds its proxy the same
#: way; an unbounded list from an untrusted guest is a memory bug waiting.
MAX_ROWS = 32


#: Hosts with a guest instantiated right now. Weak, so a host that is dropped
#: without `stop()` leaves on its own — a set that only ever grows would turn
#: this into "a guest ran once", and the capabilities page has a standing rule
#: that proof something once worked is not a claim that it still does.
_LIVE: "weakref.WeakSet" = weakref.WeakSet()


def live_guests() -> int:
    """How many `.wasm` guests are instantiated in this process.

    The promotion proof for the `wasm_plugins` capability. wasmtime importing
    says only that the tier COULD be used; a running guest is the tier being
    used, under enforced capabilities and with zero ambient authority. Stopping
    the last plugin takes the capability back down, which is the point.
    """
    return len(_LIVE)


def available() -> bool:
    """True when wasmtime-py is installed. Module-level so `store.py` can ask
    without importing the host class."""
    try:
        from .wasm_component_host import available as _avail
        return bool(_avail())
    except Exception:                                # pragma: no cover
        return False


class WasmComponentPluginHost:
    """Adapts a `.wasm` package to the `start / register_into / stop` contract
    `PluginStore.load_installed` uses for every isolated host."""

    def __init__(self, package_dir, requires=(), health=None, name="",
                 caplog=None):
        self.dir = package_dir
        self.requires = tuple(requires or ())
        self.health = health
        self.name = name or "wasm-plugin"
        self.caplog = caplog
        self._host = None
        self._build_export = "dl_build"
        self.rejected: list = []

    @staticmethod
    def available() -> bool:
        return available()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Load the guest and instantiate it. False (never an exception) when
        anything is wrong, so one bad plugin cannot stop a boot.

        Instantiation is the security-relevant moment: `WasmCapabilityHost`
        pre-scans the module's imports and refuses one that names a capability
        the manifest did not declare. A plugin that lies fails HERE, before a
        single guest instruction runs.
        """
        try:
            from pathlib import Path

            from .package import PluginPackage
            from .wasm_component_host import (WasmCapabilityHost,
                                              granted_interfaces)

            pkg = PluginPackage.load(Path(self.dir))
            if not pkg.manifest.is_wasm:
                return False
            self._build_export = pkg.manifest.factory or "dl_build"
            # `requires` is manifest vocabulary (`network`, and plenty of names
            # that mean nothing to a guest); the host links WIT interfaces.
            # Handing it the raw list would have granted `net` to nobody and
            # `log` to no one at all.
            self._host = WasmCapabilityHost(
                pkg.wasm_bytes(), granted=granted_interfaces(self.requires),
                impls=self._impls())
            self._host.instantiate()
            _LIVE.add(self)
            return True
        except Exception as exc:                     # noqa: BLE001
            # Only the exception KIND, never its message: that text is the
            # guest's (plugins/hookspecs.py sets the precedent).
        # The plugin name goes through `extra={}` — the ONE redaction seam
        # (logging_setup.JsonLineFormatter) — not into the message string,
        # which is emitted verbatim. It is the wearer's own package name and
        # NAME_RE keeps it to [a-z0-9-], never a person's; the discipline is
        # not to make the reader check that at every call site.
            log.warning("[wasm-plugin] failed to start",
                        extra={"plugin": self.name, "err": type(exc).__name__})
            if self.health is not None:
                try:
                    self.health.record_failure(f"plugin:{self.name}", exc)
                except Exception:                    # noqa: BLE001
                    pass
            self._host = None
            return False

    def stop(self) -> None:
        """Drop the instance. There is no process to reap — the guest only ever
        existed inside this store — so this is deliberately quiet."""
        _LIVE.discard(self)
        self._host = None

    def _impls(self) -> dict:
        """Host functions for the capabilities this package declared.

        `log` is implemented for real (it is the one the WIT calls "the minimum
        a plugin needs to speak to the host at all"), through the bounds-checked
        accessor so a hostile ptr/len is refused rather than read. Everything
        else is left to `WasmCapabilityHost`'s zero stub: linked because it was
        declared, and doing nothing until someone implements it.
        """
        from .wasm_component_host import needs_memory

        @needs_memory
        def _log(host, ptr, n):
            try:
                line = host.read_str(ptr, n)
            except Exception:                        # noqa: BLE001
                # A bad ptr/len is the guest's bug; refusing to read it is the
                # whole point of the bounds check, and there is nothing to say.
                return None
            # A plugin's log line is third-party text: kept to a length, and
            # never interpolated into the message (logging discipline).
            log.info("[wasm-plugin] guest said something",
                     extra={"plugin": self.name, "chars": len(line[:2000])})
            return None                              # `log` is a void import

        return {"log": _log}

    # -- the provider surface ---------------------------------------------

    def register_into(self, orchestrator) -> dict:
        """Put one proxy provider into the object-lens registry.

        A wasm guest offers exactly one provider — its build export — where the
        subprocess host can offer several. That is not a limitation worth
        working around yet: a plugin wanting more can branch on the sighting it
        is handed, and inventing a multi-provider handshake before anything
        needs one would be guessing at an interface.
        """
        registered = {"object_providers": 0, "shop_providers": 0,
                      "rejected": self.rejected}
        if self._host is None:
            return registered
        try:
            orchestrator.object_lens.registry.register(GuestProvider(self))
            registered["object_providers"] = 1
        except Exception as exc:                     # noqa: BLE001
            log.warning("[wasm-plugin] could not register",
                        extra={"plugin": self.name, "err": type(exc).__name__})
        return registered

    def build_rows(self, sighting: dict) -> List[dict]:
        """One round trip: sighting in, rows out. `[]` for anything unusual —
        a guest with nothing to say, a trap, a budget trip, malformed JSON.

        Never raises into the lens. A plugin is untrusted code and the glance
        path it sits on must not be one bad guest away from failing.
        """
        host = self._host
        if host is None:
            return []
        try:
            payload = json.dumps(sighting, separators=(",", ":")).encode("utf-8")
            if len(payload) > RESPONSE_CAP:
                return []
            ptr = host.call(ALLOC_EXPORT, RESPONSE_CAP)
            if not isinstance(ptr, int) or ptr <= 0:
                return []
            host.write_mem(ptr, payload)
            n = host.call(self._build_export, ptr, len(payload), RESPONSE_CAP)
            if not isinstance(n, int) or n <= 0:
                return []                            # "nothing to say"
            if n > RESPONSE_CAP:
                log.warning("[wasm-plugin] over-long response",
                            extra={"plugin": self.name})
                return []
            body = host.read_str(ptr, n)
            rows = json.loads(body).get("rows") or []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[wasm-plugin] build failed",
                        extra={"plugin": self.name, "err": type(exc).__name__})
            return []
        out = []
        for r in rows[:MAX_ROWS]:
            if isinstance(r, dict):
                out.append({"label": str(r.get("label", ""))[:200],
                            "detail": str(r.get("detail", ""))[:400]})
        return out


class GuestProvider:
    """A PanelProvider whose rows come from a guest. Duck-typed against
    `object_lens.providers.PanelProvider`, exactly like the subprocess host's
    proxy — so downstream cannot tell a wasm plugin from a Python one.

    Public, and shared with `extism_plugin_host`: the two runtimes differ in how
    a guest is confined and what it may call, and in nothing at all about how a
    row reaches the panel. Duplicating this for the second runtime would be
    inviting them to drift on the one part that must not.
    """

    def __init__(self, host, facet: str = "own"):
        self._host = host
        self.facet = facet
        self.name = host.name

    @staticmethod
    def _sighting_dict(sighting) -> dict:
        return {"label": getattr(sighting, "label", ""),
                "confidence": getattr(sighting, "confidence", 0.0),
                "attributes": dict(getattr(sighting, "attributes", {}) or {})}

    def matches(self, sighting) -> bool:
        # One round trip for matches+build, cached against THIS sighting — the
        # registry calls matches() then build(), and a guest call is not free.
        sd = self._sighting_dict(sighting)
        rows = self._host.build_rows(sd)
        self._last: tuple[dict, Any] | None = (sd, rows)
        return bool(rows)

    def build(self, sighting, now=None) -> list:
        from ..object_lens.schema import PanelRow
        sd = self._sighting_dict(sighting)
        cached = getattr(self, "_last", None)
        rows = cached[1] if (cached and cached[0] == sd) else None
        self._last = None                            # consume — never twice
        if rows is None:
            rows = self._host.build_rows(sd)
        # `source` names the plugin, exactly as the subprocess proxy does, so a
        # row on the glass can be traced back to the guest that produced it.
        return [PanelRow(label=r["label"], detail=r["detail"],
                         source=self.name) for r in rows]
