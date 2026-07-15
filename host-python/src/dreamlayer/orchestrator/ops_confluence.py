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
