"""ai_brain/server/brain_reminders.py — the Reminders method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

from ._brain_host import BrainHost

import json
import time


class ReminderOps(BrainHost):
    def reminders(self) -> list:
        """Open reminders, dated first. Backed by <cfg>/reminders.json."""
        p = self.cfg_dir / "reminders.json"
        try:
            data = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            data = []
        out = [e for e in (data if isinstance(data, list) else []) if e.get("title")]
        out.sort(key=lambda e: (float(e.get("ts", 0) or 0) == 0, float(e.get("ts", 0) or 0)))
        return out

    def sync_reminders(self) -> dict:
        """Pull open macOS reminders into <cfg>/reminders.json (full replace)."""
        try:
            items = self._reminders_reader(self.config)
        except Exception:
            items = []
        clean = [{"title": r["title"], "ts": float(r.get("ts", 0) or 0),
                  "list": r.get("list", "")} for r in items if r.get("title")]
        self._save_json("reminders.json", clean)
        self.last_reminders_sync = time.time()
        self.activity.add("reminders", f"Synced {len(clean)} reminder(s)")
        self.saga_record("reminders")
        return {"items": self.reminders(), "synced": len(clean)}

    def list_reminder_lists(self) -> list:
        try:
            return self._reminder_lister()
        except Exception:
            return []
