"""ops_confluence — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ._ops_host import OpsHost


class ConfluenceOps(OpsHost):

    # ------------------------------------------------------------------
    # Confluence (two-wearer) plumbing
    # ------------------------------------------------------------------

    def attach_confluence(self, bonds, sky) -> None:
        """A bond went live: entangle the sky and arm the tin can.

        Inject the wearer's real veil into the app-built sky so its own
        allow_recall() gate (in receive/tick) actually fires — otherwise the
        sky is constructed with a permissive default and the gate is vacuous
        on the live path, letting a peer's weather fold in (and re-paint after
        unpause) while fully veiled (refute-remediation 2026-07)."""
        from ..confluence import TinCan
        self.bonds = bonds
        self.tincan = TinCan(bonds)
        if sky is not None:
            sky._privacy = self.privacy
        self.dream.confluence = sky


    def detach_confluence(self) -> None:
        self.bonds = None
        self.tincan = None
        self.dream.confluence = None


    def receive_confluence(self, wire: dict) -> None:
        """One entry point for everything the peer's phone sends."""
        from ..confluence import TinCan, unwrap_gift
        if self.bonds is None:
            return
        if "ping" in wire:
            if self.bonds.receive_weather(wire) is not None:
                self.bridge.send_raw(TinCan.render_frame(wire))
        elif "gift" in wire:
            # thread the wearer's veil into the inbound render: a full pause
            # means deaf-and-blind, so a peer's gifted sky must not paint while
            # veiled (unwrap_gift recall-gates on this). Phase 3 wiring.
            for frame in unwrap_gift(self.bonds, wire, privacy=self.privacy):
                self.bridge.send_raw(frame)
        elif self.dream.confluence is not None and self.privacy.allow_recall():
            # deaf-and-blind while fully veiled: don't fold peer weather into the
            # entangled sky at all (so nothing is held to re-paint after unpause).
            self.dream.confluence.receive(wire)


    def outgoing_weather(self) -> dict | None:
        """My weather packet for the peer this tick (app layer sends)."""
        if self.bonds is None:
            return None
        pkt = self.bonds.send_weather(self.dream.inner.state,
                                      self.dream.last_palette_colors)
        return pkt.to_wire() if pkt else None


    def on_speaker(self, speaker: str | None,
                   direction_deg: float | None = None) -> None:
        """The social/truth stack identified (or failed to identify) the
        current voice — Timbre renders it at the rim in Dream Mode."""
        self.dream._ctx.speaker = speaker
        if direction_deg is not None:
            self.dream._ctx.extra["voice_direction_deg"] = direction_deg


    # ------------------------------------------------------------------
    # W7: off-grid mesh (Meshtastic) — the bond, at miles range
    # ------------------------------------------------------------------

    def attach_mesh(self, bridge=None, tcp_host: str | None = None) -> bool:
        """Bring a Meshtastic node online: a bond that carries over LoRa when
        BLE/wifi/cell are all gone. Inbound texts surface as message cards.
        `bridge` is injectable for tests; else a local node (USB → LAN tcp).
        Returns whether a node actually connected. Never raises."""
        try:
            if bridge is None:
                from .mesh_bridge import default_mesh
                bridge = default_mesh(tcp_host)
            if bridge is None:
                return False
            if not bridge.connect():
                return False
            bridge.on_text(self._on_mesh_text)
            self._mesh = bridge
            return True
        except Exception:                              # noqa: BLE001 — never fail wiring
            self._mesh = None
            return False

    def detach_mesh(self) -> None:
        mesh = getattr(self, "_mesh", None)
        if mesh is not None:
            try:
                mesh.close()
            except Exception:                          # noqa: BLE001
                pass
        self._mesh = None

    def mesh_send(self, text: str) -> bool:
        """Send one short line over the mesh. False when no node is attached or
        the radio errors — the BLE path is unaffected."""
        mesh = getattr(self, "_mesh", None)
        if mesh is None:
            return False
        try:
            return bool(mesh.send(text))
        except Exception:                              # noqa: BLE001
            return False

    def _on_mesh_text(self, sender: str, text: str) -> None:
        """An off-grid text arrived — show it on the glass (veil-gated). The
        mesh is a broadcast radio: this only renders text a peer chose to send."""
        text = (text or "").strip()
        if not text or not self.privacy.allow_capture():
            return
        from ..hud import cards
        card = cards.juno_reply(f"{sender or 'mesh'}: {text}"[:160], "answer")
        try:
            self.bridge.send_card(card, event="mesh")
        except Exception:                              # noqa: BLE001
            pass

    def mesh_tee(self, pattern) -> None:
        """When a tincan ping fires and a mesh node is up, also send it over LoRa
        so the bond reaches miles, not just BLE range. Nonverbal by design — a
        short pulse marker, never a transcript."""
        if getattr(self, "_mesh", None) is None or not pattern:
            return
        n = len(pattern) if hasattr(pattern, "__len__") else 1
        self.mesh_send("·" * max(1, min(n, 8)))
