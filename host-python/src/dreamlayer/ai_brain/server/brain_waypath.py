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
                    ts=a.get("ts"), lat=a.get("lat"), lon=a.get("lon"))
            except Exception:
                continue

    def _save_waypath(self) -> None:
        try:
            # lat/lon go to disk with the rest: an anchor that forgets WHERE it
            # was on the next Brain restart drops straight back to the
            # place-only path, which is the bug this feature exists to fix.
            anchors = [{"subject": a.subject, "bearing_deg": a.bearing_deg,
                        "distance_m": a.distance_m, "place": a.place, "ts": a.ts,
                        "lat": a.lat, "lon": a.lon}
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
        # Pin the COORDINATE too, when the Brain has a current fix. This is what
        # `landing/index.html` has always promised — "recalled as direction and
        # distance: '12 m to your left'" — and what `WaypathLens.locate`'s
        # bearing branch has always been able to render. Nothing populated it:
        # `bearing_deg`/`distance_m` are documented as an IMU seam, and the
        # Brain has no IMU. A coordinate needs none.
        #
        # Best-effort by design: no fix means a place-only anchor, exactly as
        # before, and the wearer still gets "at the north rack".
        lat = lon = None
        try:
            fix = self.here()
            if fix:
                lat, lon = fix["lat"], fix["lon"]
        except Exception:                            # noqa: BLE001
            pass
        self.waypath.remember_place(subject, place, lat=lat, lon=lon)
        self._save_waypath()
        say = (f"Got it — your {subject} is at {place}." if place
               else f"Got it — I'll remember your {subject}.")
        return {"intent": "stash", "ok": True, "say": say,
                "subject": subject, "place": place,
                "located": bool(lat is not None)}

    def waypath_locate(self, subject: str, heading_deg: float = 0.0) -> dict:
        subject = (subject or "").strip()
        if not subject:
            return {"intent": "locate", "ok": False, "say": "Find what?"}
        # The current fix turns a stored coordinate into a LIVE bearing. Without
        # it `locate` falls through to the place-only text, which is what it did
        # for every wearer before this.
        try:
            here = self.here()
        except Exception:                            # noqa: BLE001
            here = None
        cue = self.waypath.locate(subject, heading_deg=heading_deg, here=here)
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
        #   * `detail` — this used to be forced empty, because Brain-side
        #     anchors were place-only and `cue.text` was literally "at <place>",
        #     so passing it printed the place twice at two different widths.
        #     That stopped being true when anchors gained coordinates: with a
        #     current fix `cue.text` is now "22m behind you", which is the one
        #     thing the card could not say before and the thing
        #     `landing/index.html` has always promised. So it is passed WHEN A
        #     BEARING WAS COMPUTED and suppressed otherwise — the duplicate is
        #     still a duplicate on the place-only path.
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
                    # A DIRECTION when a compass heading was known, else the
                    # DISTANCE alone — never `cue.text` on that path, because it
                    # is "152m away · at the rack" and `place` is already the
                    # card's hero, so it would print the place twice at two
                    # widths (the reason this field was empty to begin with).
                    "detail": (
                        (cue.text or "") if cue.rel_bearing_deg is not None
                        else (f"{round(cue.distance_m)}m away" if cue.distance_m
                              else "")),
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
