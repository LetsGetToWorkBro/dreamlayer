from __future__ import annotations
import json


class ProactiveEngine:
    """Surface place-triggered memories on the HUD.

    Privacy contract: if a PrivacyGate is supplied and currently paused,
    on_place() always returns None — nothing is surfaced on the HUD while
    the user has explicitly silenced capture.
    """

    def __init__(self, db, min_conf: float = 0.45, privacy=None):
        self.db = db
        self.min_conf = min_conf
        self._privacy = privacy  # optional PrivacyGate

    def on_place(self, signature: str):
        # Privacy-first: if capture is paused, never surface proactive cards
        if self._privacy is not None and self._privacy.paused:
            return None

        place = next(
            (p for p in self.db.places() if p["signature"] == signature), None
        )
        if not place:
            return None

        best = None
        for m in self.db.memories():
            if (
                m.get("place_id") == place["id"]
                and (m.get("confidence") or 0) >= self.min_conf
            ):
                if best is None or m["confidence"] > best["confidence"]:
                    best = m

        if not best:
            return None

        meta = json.loads(best.get("meta") or "{}")
        return {
            "summary": best["summary"],
            "person": meta.get("person"),
            "confidence": best["confidence"],
        }
