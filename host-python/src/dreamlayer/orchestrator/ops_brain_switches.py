"""ops_brain_switches — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ..hud import cards


class BrainSwitchOps:

    # ------------------------------------------------------------------
    # AI brain — knowledge queries (folds into Lucid Recall) + cloud gate
    # ------------------------------------------------------------------

    def ask_brain(self, query: str):
        """Ask your own knowledge (files/mail on the Mac mini brain). Returns
        an Answer, attributed to the tier that answered. Recall-gated: blocked
        by a full pause veil, but allowed while incognito — asking what you
        already know isn't *keeping* anything. (Cloud escalation stays off
        while incognito via the brain's own opt-in, so nothing leaves.)"""
        if not self.privacy.allow_recall():
            return None
        answer = self.brain.ask(query)
        if answer is not None and not answer.is_empty():
            self.bridge.send_card(
                cards.answer_card(answer.text, sources=answer.sources,
                                  tier=answer.tier)
                if hasattr(cards, "answer_card") else
                {"type": "AnswerCard", "primary": answer.text,
                 "footer": f"{answer.tier} · {', '.join(answer.sources)}",
                 "lines": [answer.text]},
                event="brain_answer")
        return answer


    # -- the three brain switches ---------------------------------------

    def connect_mac_mini(self, connected: bool = True) -> None:
        """Add (or drop) your Mac mini as the local brain. When connected the
        router uses its bigger local model + your indexed files; when not, the
        phone is the brain (on-device only, more limited but works anywhere)."""
        self.mac_mini_connected = connected
        self.brain.set_local_only(not connected)


    def use_cloud(self, on: bool = True) -> None:
        """The cloud switch — reach for the hardest, non-personal asks. Its own
        control, independent of where the local brain lives; remembered across
        incognito. No-op on the router while incognito holds cloud off."""
        self._cloud_pref = on
        if not self.incognito:
            self.brain.opt_in_cloud(on)


    def set_incognito(self, on: bool = True) -> None:
        """Privacy shield for a session: forces the cloud off (restoring your
        preference when you leave), marks the session private, and drops the
        capture veil hub-side — ingest keeps nothing while incognito holds,
        even if a capture pipeline is still feeding. (The explicit pause is an
        independent veil input, so leaving incognito never clears a pause the
        user set themselves.) Replaces the old 'home'/private mode."""
        self.incognito = on
        self.brain.opt_in_cloud(False if on else self._cloud_pref)
        self.privacy.set_incognito(on)


    def brain_status(self) -> dict:
        """A compact snapshot for the phone app / panel to render."""
        return {
            "brain":     "mac_mini" if self.mac_mini_connected else "phone",
            "cloud":     bool(self.brain.cloud_opt_in),
            "incognito": self.incognito,
            "glasses":   bool(self.glasses_id),
        }


    # -- back-compat aliases (the model is the three switches above) -----

    @property
    def private_mode(self) -> bool:
        return self.incognito


    @property
    def brain_mode(self) -> str:
        if self.incognito:
            return "home"
        return "phone" if self.brain.local_only else "connected"


    def opt_in_cloud(self, on: bool = True) -> None:
        self.use_cloud(on)


    def set_private_mode(self, on: bool = True) -> None:
        self.set_incognito(on)


    def set_brain_mode(self, mode: str, cloud: bool | None = None) -> None:
        """Compat shim over the three switches:
          connected — Mac mini on, cloud on         (best answer wins)
          home      — Mac mini on, incognito         (private, no cloud)
          phone     — phone is the brain             (cloud per `cloud`)"""
        if mode not in ("connected", "home", "phone"):
            raise ValueError(f"unknown brain mode: {mode!r}")
        self.set_incognito(mode == "home")
        self.connect_mac_mini(mode != "phone")
        if cloud is not None:
            self.use_cloud(cloud)
        elif mode == "connected":
            self.use_cloud(True)
