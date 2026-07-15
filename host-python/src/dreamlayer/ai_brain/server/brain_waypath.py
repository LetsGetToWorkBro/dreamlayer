"""ai_brain/server/brain_waypath.py — the Waypath — where you left your things method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

import json
import os


class WaypathOps:
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
                os.replace(tmp, self.cfg_dir / "waypath.json")
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
        return {"intent": "locate", "ok": True, "found": True,
                "subject": cue.subject, "place": cue.place, "detail": cue.text,
                "say": f"Your {cue.subject} — {cue.text}."}
