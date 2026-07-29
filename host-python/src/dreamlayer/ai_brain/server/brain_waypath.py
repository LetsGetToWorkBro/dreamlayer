"""ai_brain/server/brain_waypath.py — the Waypath — where you left your things method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

from ._brain_host import BrainHost

import json
import os

from .store import replace_atomic


class WaypathOps(BrainHost):
    def _load_waypath(self) -> None:
        p = self.cfg_dir / "waypath.json"
        if not p.exists():
            return
        try:
            rows = json.loads(p.read_text()) or []
        except Exception:
            return
        for a in rows if isinstance(rows, list) else []:
            try:                       # one bad row must not drop the rest
                self.waypath.remember(
                    a.get("subject", ""), bearing_deg=a.get("bearing_deg"),
                    distance_m=a.get("distance_m"), place=a.get("place", ""),
                    ts=a.get("ts"))
            except Exception:
                continue

    def _save_waypath(self) -> None:
        try:
            anchors = [{"subject": a.subject, "bearing_deg": a.bearing_deg,
                        "distance_m": a.distance_m, "place": a.place, "ts": a.ts}
                       for a in self.waypath.anchors()]
            # atomic: the server is threaded, and a torn write would silently
            # lose every anchor on the next load. A FIXED tmp name is not enough
            # on its own — two request threads share it and can interleave their
            # write_text before either os.replace. Serialize under _store_lock
            # (as _save_json does) and use a per-writer tmp (re-audit 2026-07-15).
            payload = json.dumps(anchors)
            with self._store_lock:
                tmp = self.cfg_dir / f"waypath.json.{os.getpid()}.tmp"
                tmp.write_text(payload)
                # retries on Windows while a reader holds the store open
                replace_atomic(tmp, self.cfg_dir / "waypath.json")
        except Exception:
            pass

    def waypath_stash(self, subject: str, place: str) -> dict:
        subject = (subject or "").strip()
        place = (place or "").strip()
        if not subject:
            return {"intent": "stash", "ok": False, "say": "Left what where?"}
        self.waypath.remember_place(subject, place)
        self._save_waypath()
        say = (f"Got it — your {subject} is at {place}." if place
               else f"Got it — I'll remember your {subject}.")
        return {"intent": "stash", "ok": True, "say": say,
                "subject": subject, "place": place}

    def waypath_locate(self, subject: str) -> dict:
        subject = (subject or "").strip()
        if not subject:
            return {"intent": "locate", "ok": False, "say": "Find what?"}
        cue = self.waypath.locate(subject)
        if not cue.found:
            return {"intent": "locate", "ok": False, "found": False,
                    "say": f"I don't have a spot saved for your {subject} yet."}
        # …and draw it, not only speak it. `hud/cards.py` has had an
        # `object_recall` builder and `halo-lua` a dedicated drawing for it the
        # whole time; nothing the shipped Brain can reach ever called either, so
        # "where did I leave my keys" answered as JSON and the glass stayed
        # blank. That is `decisions/0001` at the card layer.
        #
        # Four of the five arguments below are load-bearing:
        #   * the `cue.place` guard — `waypath_stash` accepts an empty place, and
        #     `waypath.locate` then says "somewhere you saved it" with `place=""`.
        #     The card's HERO SLOT is `place`, so that pushes a blank answer.
        #   * `detail=""` — Brain-side anchors are place-only (no IMU seam), so
        #     `cue.text` is literally "at <place>". Passing it would print the
        #     place twice, clipped to two different widths.
        #   * `confidence=0.9` rather than None — `renderer.lua` initialises the
        #     confidence arc to MEDIUM and only overrides it when a value is
        #     present, so None renders as a hedge rather than as neutral. 0.9 is
        #     what `live_dream` already scores these same anchors.
        #   * `cue.subject`, never the caller's string — `locate` matches on a
        #     substring, so the two can differ, and only the stored anchor is
        #     ours to draw.
        pushed = 0
        if cue.place:
            try:
                from ...hud import cards
                from .brain_social import _ago
                ts = next((getattr(a, "ts", 0.0) for a in self.waypath.anchors()
                           if (getattr(a, "subject", "") or "").strip().lower()
                           == (cue.subject or "").strip().lower()), 0.0)
                pushed = self.push_event("object_recall", cards.object_recall({
                    "object": cue.subject,
                    "place": cue.place,
                    "detail": "",
                    "last_seen": _ago(ts),
                    "confidence": 0.9,
                }), veil_ok=False)
            except Exception:                # noqa: BLE001 — a card must never
                pushed = 0                   # cost the wearer their answer
        # `pushed` rides the response for the same reason the ear's selftest does:
        # a silently-swallowed push reproduces the exact bug this fixes — 200 OK,
        # nothing on the glass.
        return {"intent": "locate", "ok": True, "found": True,
                "subject": cue.subject, "place": cue.place, "detail": cue.text,
                "pushed": pushed,
                "say": f"Your {cue.subject} — {cue.text}."}
