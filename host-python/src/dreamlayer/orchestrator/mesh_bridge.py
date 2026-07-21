"""orchestrator/mesh_bridge.py — tincan to the horizon (Meshtastic).

The tincan/GhostMode bond is Bluetooth-range; a Meshtastic node makes it
miles-range and off-grid: LoRa mesh text + GPS on $6 radios, no wifi, no cell,
no internet. This bridge speaks to a LOCAL node (USB serial, or a node on your
LAN) and relays short tincan lines over the mesh — the same "a few words to the
person you're bonded with" surface, carried by radio instead of BLE.

Posture: LoRa is a broadcast radio — the bridge sends only what the tincan
surface already sends (short typed lines you chose to share), never memories,
transcripts, or positions. Lazy adapter (extras group `mesh`); absent the wheel
or a node, `ready` is False and send() returns False — the BLE tincan behaves
exactly as today.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

log = logging.getLogger("dreamlayer.mesh")

_MAX_BYTES = 230                 # LoRa DATA_PAYLOAD_LEN is 237 BYTES; stay under


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class MeshBridge:
    """Wrap one local Meshtastic node. `available` is the wheel; `ready` once an
    interface actually opened (serial auto-detect, or tcp to a LAN node)."""

    dep = "meshtastic"
    available = _has("meshtastic")

    def __init__(self, tcp_host: Optional[str] = None):
        self._iface: Any = None
        self._tcp_host = tcp_host
        self._listeners: List[Callable[[str, str], None]] = []
        self._on_receive_fn: Any = None   # strong ref for pypubsub's weak registry

    def connect(self) -> bool:
        """Open the node: serial first (a radio on USB), else tcp to a LAN node
        when a host was given. False — never an exception — when neither works."""
        if self._iface is not None:
            return True
        if not self.available:
            return False
        try:
            import meshtastic.serial_interface  # type: ignore
            self._iface = meshtastic.serial_interface.SerialInterface()
        except Exception as exc:                   # noqa: BLE001
            log.debug("[mesh] serial open failed: %s", exc)
            self._iface = None
        if self._iface is None and self._tcp_host:
            try:
                import meshtastic.tcp_interface  # type: ignore
                self._iface = meshtastic.tcp_interface.TCPInterface(
                    hostname=self._tcp_host)
            except Exception as exc:               # noqa: BLE001
                log.debug("[mesh] tcp open failed: %s", exc)
                self._iface = None
        if self._iface is not None:
            self._subscribe()
        return self._iface is not None

    @property
    def ready(self) -> bool:
        return self._iface is not None

    def send(self, text: str, channel: int = 0) -> bool:
        """Send one short line over the mesh. False when not connected, the text
        is empty, or the radio errors — the caller's BLE path still stands.
        Truncation is in BYTES (the radio's ~237-byte payload limit is bytes, so
        a char slice let non-ASCII lines overflow and raise — refute 2026-07-21),
        cut at a codepoint boundary."""
        raw = (text or "").strip().encode("utf-8")[:_MAX_BYTES]
        text = raw.decode("utf-8", "ignore").strip()
        if not text or self._iface is None:
            return False
        try:
            self._iface.sendText(text, channelIndex=max(0, int(channel)))
            return True
        except Exception as exc:                   # noqa: BLE001
            log.error("[mesh] send failed: %s", exc)
            return False

    def on_text(self, fn: Callable[[str, str], None]) -> None:
        """Register `fn(sender_id, text)` for incoming mesh texts."""
        if callable(fn):
            self._listeners.append(fn)

    def _subscribe(self) -> None:
        try:
            from pubsub import pub  # type: ignore  # meshtastic's event bus

            # pypubsub holds listeners by WEAK reference: a bare local closure is
            # garbage-collected the moment _subscribe returns and the listener
            # silently auto-unsubscribes — the receive half never fires (refute
            # 2026-07-21, reproduced against pypubsub 4.0.7). Pin the closure on
            # the instance; rebinding on reconnect also kills the old weakref, so
            # no duplicate delivery either.
            def _on_receive(packet=None, interface=None):  # noqa: ANN001
                try:
                    decoded = (packet or {}).get("decoded", {})
                    if decoded.get("portnum") != "TEXT_MESSAGE_APP":
                        return
                    text = str(decoded.get("text", "") or "").strip()
                    sender = str((packet or {}).get("fromId", "") or "")
                    if not text:
                        return
                    for fn in list(self._listeners):
                        try:
                            fn(sender, text[:_MAX_BYTES])
                        except Exception:          # noqa: BLE001 — one listener, not the bus
                            pass
                except Exception:                  # noqa: BLE001
                    pass
            self._on_receive_fn = _on_receive      # strong ref — see note above
            pub.subscribe(self._on_receive_fn, "meshtastic.receive.text")
        except Exception as exc:                   # noqa: BLE001
            log.debug("[mesh] subscribe failed: %s", exc)

    def close(self) -> None:
        try:
            if self._iface is not None:
                self._iface.close()
        except Exception:                          # noqa: BLE001
            pass
        self._iface = None


def default_mesh(tcp_host: Optional[str] = None) -> Optional[MeshBridge]:
    b = MeshBridge(tcp_host)
    return b if b.available else None
