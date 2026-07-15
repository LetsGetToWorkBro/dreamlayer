"""ai_brain/server/brain_calendar.py — the Calendar & agenda method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

import json
import time


class CalendarOps:
    def calendar(self, limit: int = 10) -> list:
        """Upcoming events for the glasses + the brief. Reads
        <cfg>/agenda.json (a list of {title, ts, place}); events pulled from
        macOS Calendar carry source:"calendar". [] when empty."""
        events = []
        p = self.cfg_dir / "agenda.json"
        try:
            if p.exists():
                data = json.loads(p.read_text())
                for e in (data if isinstance(data, list) else []):
                    if e.get("title"):
                        events.append({"title": e["title"],
                                       "ts": float(e.get("ts", 0) or 0),
                                       "place": e.get("place", ""),
                                       "source": e.get("source", "manual"),
                                       "calendar": e.get("calendar", "")})
        except Exception:
            pass
        now = time.time()
        upcoming = [e for e in events if e["ts"] >= now - 3600]   # today onward
        upcoming.sort(key=lambda e: e["ts"])
        return upcoming[:limit]

    def add_event(self, title: str, ts: float = 0.0, place: str = "") -> list:
        """Append one event to <cfg>/agenda.json and return the upcoming list."""
        title = (title or "").strip()
        with self._store_lock:
            cur = self._load_json("agenda.json", [])
            if title:
                cur.append({"title": title, "ts": float(ts or 0), "place": place or ""})
                self._save_json("agenda.json", cur)
                self.activity.add("calendar", f"Added event {title}")
        return self.calendar(200)

    def remove_event(self, title: str, ts: float | None = None) -> list:
        """Drop the first agenda event matching title (and ts, if given)."""
        title = (title or "").strip()
        with self._store_lock:
            cur = self._load_json("agenda.json", [])
            kept, removed = [], False
            for e in cur:
                same = (e.get("title") == title and
                        (ts is None or abs(float(e.get("ts", 0) or 0) - float(ts)) < 1))
                if same and not removed:
                    removed = True
                    continue
                kept.append(e)
            if removed:
                self._save_json("agenda.json", kept)
                self.activity.add("calendar", f"Removed event {title}")
        return self.calendar(200)

    def list_calendars(self) -> list[str]:
        """The calendars available to sync from (for the panel's picker)."""
        try:
            return self._calendar_lister()
        except Exception:
            return []

    def sync_calendar(self) -> dict:
        """Pull upcoming Calendar.app events into agenda.json, replacing any
        previously-synced events while keeping the ones you added by hand.
        Synced events carry `source: "calendar"`; manual ones don't."""
        try:
            events = self._calendar_reader(self.config)
        except Exception:
            events = []
        synced = [{"title": e["title"], "ts": float(e.get("ts", 0) or 0),
                   "place": e.get("place", ""), "calendar": e.get("calendar", ""),
                   "source": "calendar"} for e in events if e.get("title")]
        with self._store_lock:
            cur = self._load_json("agenda.json", [])
            # keep everything you added by hand; drop the last sync's events
            manual = [e for e in cur if e.get("source") != "calendar"]
            self._save_json("agenda.json", manual + synced)
        self.last_calendar_sync = time.time()
        self.activity.add("calendar", f"Synced {len(synced)} event(s) from Calendar")
        self.saga_record("calendar")
        return {"items": self.calendar(200), "synced": len(synced)}

    def maybe_sync_calendar(self) -> bool:
        """Run the macOS syncs whose toggles are on. Called by the scheduler."""
        ran = False
        if self.config.calendar_sync:
            self.sync_calendar(); ran = True
        if self.config.contacts_sync:
            self.sync_contacts(); ran = True
        if self.config.reminders_sync:
            self.sync_reminders(); ran = True
        return ran

    def start_calendar_sync(self, interval: int = 900):
        """Background loop: re-pull calendar / contacts / reminders every
        `interval` seconds while their toggles are on. Idempotent."""
        import threading
        if self._cal_stop is not None:
            return
        stop = threading.Event()
        self._cal_stop = stop

        def loop():
            first = True
            while True:
                if stop.wait(2 if first else interval):   # a quick first pull
                    break
                first = False
                try:
                    self.maybe_sync_calendar()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()
