"""ai_brain/server/server.py — the Brain server (runs on your Mac mini).

Serves the control panel and the API the phone and the panel both call:

    GET  /                          control panel
    GET  /dreamlayer/config         config (token-safe) + index stats
    POST /dreamlayer/config         update model / connections
    POST /dreamlayer/folders        {action: add|remove, path}  → reindex
    POST /dreamlayer/upload?folder=&name=   drag-drop a file in → reindex
    POST /dreamlayer/brain/ask      {query} → Answer (logged to history)
    POST /dreamlayer/brain/explain  {label, image?, want?} → Answer
    GET  /dreamlayer/history        recent questions

All /dreamlayer/* calls require the pairing token (when one is set); the
panel page is injected with the token only when opened from localhost.
"""
from __future__ import annotations

import json
import socket
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import threading
import time

from ..schema import Answer
from .store import BrainConfig, QueryHistory, ActivityLog
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer, probe_ollama
from .macos_sources import collect_documents
from .panel import render_panel

TOKEN_HEADER = "X-DreamLayer-Token"


def lan_ip() -> str:
    """This machine's LAN address — the one the phone can actually reach.

    Uses a UDP socket to discover the outbound interface without sending
    anything. Falls back to loopback if there's no network.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _hour_label(ts: float) -> str:
    """'2 PM' for an hour block in the rewind timeline."""
    lt = time.localtime(ts)
    h = lt.tm_hour
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


class Brain:
    """The Brain's live state: config + index + history, rebuilt on change."""

    def __init__(self, cfg_dir: Path | str, sources_fn=None, messages_fn=None,
                 calendar_reader_fn=None, calendar_list_fn=None):
        self.cfg_dir = Path(cfg_dir)
        self.config = BrainConfig.load(self.cfg_dir)
        self.history = QueryHistory(self.cfg_dir)
        self.activity = ActivityLog(self.cfg_dir)
        self.index = FileIndex(self.config)
        # macOS message/mail documents (folded in when email is enabled)
        self._sources_fn = sources_fn or collect_documents
        # the live feed the glasses read hands-free (the Mac is the bridge)
        from .macos_sources import (recent_messages, read_calendar_events,
                                     list_calendars, read_contacts, read_reminders,
                                     list_reminder_lists)
        self._messages_fn = messages_fn or recent_messages
        # macOS Calendar.app → agenda sync (both are injectable seams for tests)
        self._calendar_reader = calendar_reader_fn or read_calendar_events
        self._calendar_lister = calendar_list_fn or list_calendars
        # macOS Contacts + Reminders readers (injectable seams for tests)
        self._contacts_reader = read_contacts
        self._reminders_reader = read_reminders
        self._reminder_lister = list_reminder_lists
        self._sig = None
        self._last_phone_ts = 0.0        # last authed request from off-box (the phone)
        self._started_ts = time.time()
        self.last_index_ts = 0.0
        self.email_docs = 0
        self.last_brief = None
        self._brief_ran_day = None
        self._brief_stop = None
        self._cal_stop = None
        self.last_calendar_sync = 0.0
        self.last_contacts_sync = 0.0
        self.last_reminders_sync = 0.0
        # Saga: the ecosystem progression the phone shows — ranks, level, and
        # achievements. Brain-hosted so the phone (and hub) can read/record it.
        from ...saga import SagaProfile
        self.saga = SagaProfile(self.cfg_dir)
        self._watch_stop: threading.Event | None = None
        # retention: drop logs older than the configured window on boot
        if self.config.retention_days:
            self.history.prune(self.config.retention_days)
            self.activity.prune(self.config.retention_days)
        self._wire_model()
        self.reindex()

    def reindex(self) -> dict:
        self.index.reindex()
        self.email_docs = 0
        if self.config.email_enabled:
            try:
                docs = self._sources_fn(self.config)
                self.email_docs = len(docs)
                self.index.add_documents(docs)
            except Exception:
                pass
        self._sig = self._signature()
        self.last_index_ts = time.time()
        return self.index.stats()

    # -- auto-reindex when watched folders change ------------------------

    def _signature(self):
        sig = []
        for folder in self.config.folders:
            base = Path(folder).expanduser()
            if base.is_dir():
                try:
                    for f in base.rglob("*"):
                        if f.is_file():
                            sig.append((str(f), f.stat().st_mtime_ns))
                except OSError:
                    pass
        return tuple(sorted(sig))

    def poll(self) -> bool:
        """Reindex if the watched folders changed since last scan."""
        if self._signature() != self._sig:
            self.reindex()
            return True
        return False

    def start_watching(self, interval: float = 3.0) -> None:
        if self._watch_stop is not None:
            return
        self._watch_stop = threading.Event()

        def loop():
            while not self._watch_stop.wait(interval):
                try:
                    self.poll()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop_watching(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None

    def _wire_model(self) -> None:
        """Point the index/vision at the configured backend."""
        if self.config.model == "ollama":
            self._backend = OllamaBackend(self.config)
            self.index.synthesizer = make_synthesizer(self._backend)
            self.index.embedder = (self._backend.embed
                                   if self.config.semantic_search else None)
        else:
            self._backend = None
            self.index.synthesizer = None
            self.index.embedder = None

    def save(self) -> None:
        self.config.save(self.cfg_dir)

    def apply_config(self, updates: dict) -> None:
        for k in ("model", "ollama_url", "ollama_chat_model",
                  "ollama_vision_model", "ollama_embed_model",
                  "email_enabled", "summarize_emails", "cloud_enabled",
                  "network_mode", "cloud_base_url", "cloud_api_key", "cloud_model",
                  "semantic_search", "index_extensions", "max_file_kb",
                  "exclude_globs", "quiet_hours", "retention_days", "brief_hour",
                  "calendar_sync", "calendar_names", "calendar_days",
                  "contacts_sync", "reminders_sync", "reminder_lists"):
            if k in updates:
                setattr(self.config, k, updates[k])
        self._wire_model()
        self.save()
        # turning a sync on (or changing its filter) → pull immediately
        try:
            if updates.get("calendar_sync") or ("calendar_names" in updates and self.config.calendar_sync):
                self.sync_calendar()
            if updates.get("contacts_sync"):
                self.sync_contacts()
            if updates.get("reminders_sync") or ("reminder_lists" in updates and self.config.reminders_sync):
                self.sync_reminders()
        except Exception:
            pass
        if updates.get("cloud_enabled"):
            self.saga_record("cloud")
        if updates.get("network_mode") == "lan_only":
            self.saga_record("incognito")

    def incognito_now(self) -> bool:
        """Effective privacy shield: manual LAN-only OR a quiet-hours window."""
        from .store import in_quiet_hours
        return self.config.lan_only or in_quiet_hours(self.config.quiet_hours)

    def missing_folders(self) -> list:
        return [f for f in self.config.folders
                if not Path(f).expanduser().is_dir()]

    def ask(self, query: str) -> Optional[Answer]:
        ans = self.index.ask(query)
        if ans is None and self.config.cloud_ready() and not self.incognito_now():
            ans = self._ask_cloud(query)
        if ans is not None:
            self.history.add(query, ans.text, ans.tier, ans.sources)
            self.saga_record("recall")
        return ans

    def _ask_cloud(self, query: str) -> Optional[Answer]:
        """The one place data leaves the device — logged every single time."""
        from .backends import cloud_chat
        try:
            text = cloud_chat(self.config, query)
        except Exception:
            text = ""
        if not text:
            return None
        self.config.cloud_calls += 1
        self.save()
        self.activity.add("cloud-egress", f"Asked the cloud: {query[:70]}")
        return Answer(text=text, tier="cloud", sources=["cloud"], confidence=0.6)

    def explain(self, label: str, image_b64, want: str) -> Optional[Answer]:
        return vision_answer(self._backend, label, image_b64, want)

    def summarize(self, text: str, max_chars: int = 220) -> str:
        """One-glance summary of a long email. Uses the local model when there
        is one; otherwise clips to the first sentence — never blocks the feed."""
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        if self._backend is not None:
            try:
                s = self._backend.chat(
                    "Summarize this email in one short sentence a person can "
                    "read at a glance. Just the sentence:\n\n" + text[:2000])
                if s and s.strip():
                    return s.strip()
            except Exception:
                pass
        head = text.split(". ")[0].strip()
        return head if 0 < len(head) <= max_chars else text[:max_chars].rstrip() + "…"

    def maybe_run_brief(self, now: float | None = None) -> bool:
        """If it's the configured brief hour and today's brief hasn't run yet,
        generate it and stash it for delivery. Returns True when it ran."""
        hour = self.config.brief_hour
        if hour is None or hour < 0:
            return False
        lt = time.localtime(now if now is not None else time.time())
        day = (lt.tm_year, lt.tm_yday)
        if lt.tm_hour != hour or getattr(self, "_brief_ran_day", None) == day:
            return False
        self._brief_ran_day = day
        b = self.brief()
        self.last_brief = {"text": b["text"], "bullets": b["bullets"],
                           "ts": time.time()}
        self.activity.add("brief", "Morning brief ready")
        return True

    def start_brief_scheduler(self, interval: float = 60.0) -> None:
        if getattr(self, "_brief_stop", None) is not None:
            return
        self._brief_stop = threading.Event()

        def loop():
            while not self._brief_stop.wait(interval):
                try:
                    self.maybe_run_brief()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def export_backup(self) -> dict:
        """A full, restorable snapshot of the Brain — config (incl. secrets),
        query history, activity, and agenda. Handed out only to the local
        panel, so it never crosses the network."""
        self.saga_record("backup")
        return {
            "version": _version(),
            "config": asdict(self.config),
            "history": self.history.recent(2000),
            "activity": self.activity.recent(2000),
            "agenda": self.calendar(200),
        }

    def import_backup(self, data: dict) -> None:
        from .store import field_list
        cfg = data.get("config") or {}
        known = {f.name for f in field_list(BrainConfig)}
        for k, v in cfg.items():
            if k in known:
                setattr(self.config, k, v)
        self.save()
        if isinstance(data.get("history"), list):
            self.history.restore(data["history"])
        if isinstance(data.get("activity"), list):
            self.activity.restore(data["activity"])
        if isinstance(data.get("agenda"), list):
            (self.cfg_dir / "agenda.json").write_text(json.dumps(data["agenda"]))
        self._wire_model()
        self.reindex()

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
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        if title:
            cur.append({"title": title, "ts": float(ts or 0), "place": place or ""})
            p.write_text(json.dumps(cur))
            self.activity.add("calendar", f"Added event {title}")
        return self.calendar(200)

    def remove_event(self, title: str, ts: float | None = None) -> list:
        """Drop the first agenda event matching title (and ts, if given)."""
        title = (title or "").strip()
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        kept, removed = [], False
        for e in (cur if isinstance(cur, list) else []):
            same = (e.get("title") == title and
                    (ts is None or abs(float(e.get("ts", 0) or 0) - float(ts)) < 1))
            if same and not removed:
                removed = True
                continue
            kept.append(e)
        if removed:
            p.write_text(json.dumps(kept))
            self.activity.add("calendar", f"Removed event {title}")
        return self.calendar(200)

    # -- macOS Calendar.app sync (read-only) -----------------------------

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
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        # keep everything you added by hand; drop the last sync's events
        manual = [e for e in cur if e.get("source") != "calendar"]
        synced = [{"title": e["title"], "ts": float(e.get("ts", 0) or 0),
                   "place": e.get("place", ""), "calendar": e.get("calendar", ""),
                   "source": "calendar"} for e in events if e.get("title")]
        p.write_text(json.dumps(manual + synced))
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

    # -- people you've been introduced to (the dossier registry) ---------

    def people(self) -> list:
        """Everyone you've introduced to the Brain, newest first. Backed by
        <cfg>/people.json: a list of {name, note, tags, ts}. [] when empty."""
        p = self.cfg_dir / "people.json"
        try:
            data = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            data = []
        out = []
        for e in (data if isinstance(data, list) else []):
            if e.get("name"):
                out.append({"name": e["name"], "note": e.get("note", ""),
                            "tags": e.get("tags", []), "ts": float(e.get("ts", 0) or 0),
                            "source": e.get("source", "manual")})
        out.sort(key=lambda e: -e["ts"])
        return out

    def add_person(self, name: str, note: str = "", tags=None) -> list:
        """Introduce (or update) a person. Re-adding a name updates the note."""
        name = (name or "").strip()
        if not name:
            return self.people()
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        tags = [t for t in (tags or []) if t]
        cur = [e for e in cur if e.get("name") != name]     # replace existing
        cur.append({"name": name, "note": note or "", "tags": tags,
                    "ts": time.time(), "source": "manual"})
        p.write_text(json.dumps(cur))
        self.activity.add("people", f"Introduced {name}")
        return self.people()

    def remove_person(self, name: str) -> list:
        name = (name or "").strip()
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        kept = [e for e in (cur if isinstance(cur, list) else []) if e.get("name") != name]
        if len(kept) != len(cur if isinstance(cur, list) else []):
            p.write_text(json.dumps(kept))
            self.activity.add("people", f"Removed {name}")
        return self.people()

    def sync_contacts(self) -> dict:
        """Pull macOS Contacts into the People registry. Keeps the people you
        added by hand; replaces the previous contacts pull. Synced entries carry
        source:"contacts"."""
        try:
            contacts = self._contacts_reader(self.config)
        except Exception:
            contacts = []
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        manual = [e for e in cur if e.get("source") != "contacts"]
        manual_names = {e.get("name") for e in manual}
        synced = []
        for c in contacts:
            if not c.get("name") or c["name"] in manual_names:
                continue                                   # never shadow a manual entry
            note = "  •  ".join([x for x in (c.get("company"), c.get("role")) if x])
            synced.append({"name": c["name"], "note": note, "tags": [],
                           "ts": time.time(), "source": "contacts",
                           "email": c.get("email", "")})
        p.write_text(json.dumps(manual + synced))
        self.last_contacts_sync = time.time()
        self.activity.add("people", f"Synced {len(synced)} contact(s)")
        self.saga_record("contacts")
        return {"items": self.people(), "synced": len(synced)}

    # -- reminders: open to-dos from macOS Reminders --------------------

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
        (self.cfg_dir / "reminders.json").write_text(json.dumps(clean))
        self.last_reminders_sync = time.time()
        self.activity.add("reminders", f"Synced {len(clean)} reminder(s)")
        self.saga_record("reminders")
        return {"items": self.reminders(), "synced": len(clean)}

    def list_reminder_lists(self) -> list:
        try:
            return self._reminder_lister()
        except Exception:
            return []

    def saga_record(self, event: str, count: int | None = None) -> list:
        """Advance the Saga profile for an ecosystem event and unlock any badges
        (feature use + the level milestones it crosses). Returns newly-unlocked
        names; logs them to the activity feed."""
        fresh = (self.saga.record(event, count=count) if count is not None
                 else self.saga.record(event))
        fresh += self.saga.note_level(self.saga.snapshot()["level"])
        return fresh

    def pull_model(self, name: str) -> dict:
        """One-click Ollama model pull. Re-probes after so status updates."""
        from .backends import pull_model as _pull
        res = _pull(self.config, name)
        if res.get("ok"):
            self.activity.add("model", f"Pulled model {res.get('model', name)}")
            self._wire_model()
            self.saga_record("model")
        return res

    # -- rewind my day: one merged timeline of what happened -------------

    def rewind(self, now: float | None = None) -> dict:
        """Today, grouped into hour blocks: what the Brain did (activity), the
        messages it relayed, and the events on the agenda — one scrubable
        timeline for the phone. Reads only what the Brain already has."""
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
        items = []
        for a in self.activity.recent(200):
            ts = float(a.get("ts", 0) or 0)
            if ts >= day_start:
                items.append({"ts": ts, "kind": a.get("kind", "activity"),
                              "text": a.get("text", "")})
        try:
            msgs = self._messages_fn(self.config, 50) if self.config.email_enabled else []
            for m in msgs:
                ts = float(m.get("ts", 0) or 0)
                if ts >= day_start and not m.get("from_me"):
                    who = m.get("who", "")
                    body = m.get("subject") or m.get("text", "")
                    items.append({"ts": ts, "kind": "message",
                                  "text": f"{who}: {body}".strip(": ")})
        except Exception:
            pass
        for e in self.calendar(50):
            if day_start <= e["ts"] < day_start + 86400:
                items.append({"ts": e["ts"], "kind": "event", "text": e["title"]})
        blocks: dict[int, list] = {}
        for it in items:
            hr = int((it["ts"] - day_start) // 3600)
            blocks.setdefault(hr, []).append(it)
        out = []
        for hr in sorted(blocks):
            evs = sorted(blocks[hr], key=lambda x: x["ts"])
            out.append({"hour": hr, "label": _hour_label(day_start + hr * 3600),
                        "count": len(evs), "items": evs})
        return {"blocks": out, "count": len(items)}

    def suggest_replies(self, text: str, n: int = 3) -> list:
        """A few short, natural replies to an incoming message — pick one by
        tap now, by voice later. Model-generated with a canned fallback."""
        text = (text or "").strip()
        if self._backend is not None and text:
            try:
                raw = self._backend.chat(
                    f"Suggest {n} short, natural one-line replies to this "
                    f"message. One per line, no numbering, no quotes:\n\n" + text)
                lines = [ln.strip("-•\" ").strip() for ln in raw.splitlines() if ln.strip()]
                if lines:
                    return lines[:n]
            except Exception:
                pass
        return ["On my way", "Give me a few", "Thanks!"][:n]

    def brief(self, agenda=None, since: float = 0.0) -> dict:
        """A one-glance morning brief: what's new (messages/mail) + what's on
        you (agenda the phone passes: commitments, calendar). The model turns
        the points into a warm couple of sentences; with no model it returns
        the structured points. `since` powers 'what did I miss'."""
        agenda = [a for a in (agenda or []) if a]
        for e in self.calendar(5):                    # today's events lead the brief
            when = time.strftime("%I:%M %p", time.localtime(e["ts"])).lstrip("0") if e["ts"] else ""
            agenda.append(e["title"] + (f" at {when}" if when else ""))
        day_end = time.time() + 86400
        due = [r for r in self.reminders() if 0 < r.get("ts", 0) <= day_end]
        for r in due[:3]:                             # to-dos due within a day
            agenda.append("Reminder: " + r["title"])
        try:
            msgs = self._messages_fn(self.config, 20) if self.config.email_enabled else []
        except Exception:
            msgs = []
        incoming = [m for m in msgs if not m.get("from_me") and m.get("ts", 0) > since]
        texts = [m for m in incoming if m.get("channel") != "email"]
        emails = [m for m in incoming if m.get("channel") == "email"]

        bullets = list(agenda)
        if texts:
            who = ", ".join(dict.fromkeys(m.get("who", "") for m in texts if m.get("who")))
            bullets.append(f"{len(texts)} new text{'s' if len(texts) != 1 else ''}"
                           + (f" (from {who[:60]})" if who else ""))
        for m in emails[:3]:
            subj = (m.get("subject") or m.get("text", "")[:40]).strip()
            if subj:
                bullets.append(f"Email: {subj}")
        if not bullets:
            bullets = ["Nothing pressing — a clear morning."]

        text = "  ·  ".join(bullets)
        if self._backend is not None:
            try:
                s = self._backend.chat(
                    "Write a warm, two-sentence morning brief from these points. "
                    "Be concrete, natural, and brief — no preamble:\n\n"
                    + "\n".join("- " + b for b in bullets))
                if s and s.strip():
                    text = s.strip()
            except Exception:
                pass
        self.saga_record("brief")
        return {"text": text, "bullets": bullets,
                "missed": {"texts": len(texts), "emails": len(emails)}}


def make_brain_server(brain: Brain, host: str = "127.0.0.1",
                      port: int = 7777) -> ThreadingHTTPServer:
    token = brain.config.token

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # -- helpers ----------------------------------------------------
        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            tok = brain.config.token        # read live so token rotation applies
            ok = not tok or self.headers.get(TOKEN_HEADER) == tok
            # a successful token-carrying request from off-box is the phone
            if ok and tok and not self._from_localhost():
                brain._last_phone_ts = time.time()
            return ok

        def _from_localhost(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def _raw(self) -> bytes:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(n) if n else b""

        # -- routing ----------------------------------------------------
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                html = render_panel(brain.config.token if self._from_localhost() else "")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/config":
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/status":
                ago = None
                if brain._last_phone_ts:
                    ago = max(0, int(time.time() - brain._last_phone_ts))
                idx_ago = (int(time.time() - brain.last_index_ts)
                           if brain.last_index_ts else None)
                self._json(200, {
                    "brain": True,
                    "model": brain.config.model,
                    "cloud": bool(brain.config.cloud_enabled) and not brain.config.lan_only,
                    "cloud_ready": brain.config.cloud_ready(),
                    "cloud_calls": brain.config.cloud_calls,
                    "incognito": brain.incognito_now(),
                    "quiet": brain.incognito_now() and not brain.config.lan_only,
                    "phone_ago": ago,
                    "index_ago": idx_ago,
                    "missing": brain.missing_folders(),
                    "email_docs": brain.email_docs,
                    "stats": brain.index.stats(),
                })
            elif path == "/dreamlayer/token":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/backup":
                if not self._from_localhost():
                    self._json(403, {"error": "backup is local-only"}); return
                self._json(200, brain.export_backup())
            elif path == "/dreamlayer/health":
                import shutil
                try:
                    du = sum(f.stat().st_size for f in brain.cfg_dir.rglob("*") if f.is_file())
                except OSError:
                    du = 0
                oms = None
                if brain.config.model == "ollama":
                    t0 = time.time()
                    if probe_ollama(brain.config, timeout=3).get("reachable"):
                        oms = int((time.time() - t0) * 1000)
                self._json(200, {"version": _version(), "disk_kb": du // 1000,
                                 "ollama_ms": oms,
                                 "uptime_s": int(time.time() - brain._started_ts)})
            elif path == "/dreamlayer/history":
                self._json(200, {"items": _activity_feed(brain, 40)})
            elif path == "/dreamlayer/calendar":
                self._json(200, {"items": brain.calendar()})
            elif path == "/dreamlayer/people":
                self._json(200, {"items": brain.people()})
            elif path == "/dreamlayer/calendars":
                # available macOS calendars + current sync settings (for the picker)
                self._json(200, {"items": brain.list_calendars(),
                                 "sync": brain.config.calendar_sync,
                                 "selected": brain.config.calendar_names,
                                 "last_sync": brain.last_calendar_sync})
            elif path == "/dreamlayer/contacts":
                self._json(200, {"sync": brain.config.contacts_sync,
                                 "last_sync": brain.last_contacts_sync,
                                 "count": len([p for p in brain.people()
                                               if p.get("source") == "contacts"])})
            elif path == "/dreamlayer/reminders":
                self._json(200, {"items": brain.reminders(),
                                 "lists": brain.list_reminder_lists(),
                                 "sync": brain.config.reminders_sync,
                                 "selected": brain.config.reminder_lists,
                                 "last_sync": brain.last_reminders_sync})
            elif path == "/dreamlayer/rewind":
                self._json(200, brain.rewind())
            elif path == "/dreamlayer/saga":
                self._json(200, brain.saga.snapshot())
            elif path == "/dreamlayer/brief/latest":
                self._json(200, brain.last_brief or {})
            elif path == "/dreamlayer/messages/recent":
                # the live Messages/Mail feed the glasses read hands-free
                if not brain.config.email_enabled:
                    self._json(200, {"items": [], "enabled": False}); return
                try:
                    items = brain._messages_fn(brain.config, 20)
                except Exception:
                    items = []
                if brain.config.summarize_emails:
                    for it in items:
                        if it.get("channel") == "email":
                            it["summary"] = brain.summarize(it.get("text", ""))
                self._json(200, {"items": items, "enabled": True,
                                 "summarize_emails": brain.config.summarize_emails})
            elif path == "/dreamlayer/model/status":
                self._json(200, probe_ollama(brain.config))
            elif path == "/dreamlayer/browse":
                # a server-side folder picker (the panel navigates the Mac's
                # own filesystem) — local-only, like pairing
                if not self._from_localhost():
                    self._json(403, {"error": "browse is local-only"}); return
                self._json(200, _browse_dir(qs.get("path", [""])[0]))
            elif path == "/dreamlayer/pair":
                # a pairing code for the phone — only handed to the local panel
                if not self._from_localhost():
                    self._json(403, {"error": "pairing is local-only"}); return
                from ...pairing import PairingBundle, encode_pairing
                # the code must point the phone at an address it can reach on the
                # LAN — never the loopback/Host the local browser used.
                port = self.server.server_address[1]
                ip = lan_ip()
                if ip and ip != "127.0.0.1":
                    url = f"http://{ip}:{port}"
                else:
                    url = "http://" + (self.headers.get("Host") or f"127.0.0.1:{port}")
                bundle = PairingBundle(brain_url=url, token=brain.config.token)
                brain.activity.add("pair", "Generated a pairing code for the phone")
                brain.saga_record("pair")
                code = encode_pairing(bundle)
                from .qr import to_svg
                self._json(200, {"code": code, "url": url, "qr": to_svg(code)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/folders":
                b = self._body()
                p = b.get("path", "")
                if b.get("action") == "add":
                    if brain.config.add_folder(p):
                        brain.activity.add("folder", f"Added folder {p}")
                        brain.saga_record("folder")
                elif b.get("action") == "remove":
                    brain.config.remove_folder(p)
                    brain.activity.add("folder", f"Removed folder {p}")
                brain.save(); brain.reindex()
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/config":
                body = self._body()
                before = (brain.config.model, brain.config.cloud_enabled,
                          brain.config.network_mode, brain.config.email_enabled)
                brain.apply_config(body)
                brain.reindex()
                if "model" in body and brain.config.model != before[0]:
                    brain.activity.add("model", f"Model set to {brain.config.model}")
                if "cloud_enabled" in body and brain.config.cloud_enabled != before[1]:
                    brain.activity.add("cloud", "Cloud enabled" if brain.config.cloud_enabled else "Cloud disabled")
                if "network_mode" in body and brain.config.network_mode != before[2]:
                    brain.activity.add("privacy", "Incognito on" if brain.config.lan_only else "Incognito off")
                if "email_enabled" in body and brain.config.email_enabled != before[3]:
                    brain.activity.add("config", "Email & iMessage " + ("on" if brain.config.email_enabled else "off"))
                self._json(200, {"config": brain.config.public()})
            elif path == "/dreamlayer/upload":
                folder = (qs.get("folder", [""])[0])
                name = Path(qs.get("name", ["dropped.txt"])[0]).name
                ok = _write_upload(brain, folder, name, self._raw())
                if ok:
                    brain.activity.add("upload", f"Added {name}")
                brain.reindex()
                self._json(200 if ok else 400,
                           {"ok": ok, "stats": brain.index.stats()})
            elif path == "/dreamlayer/brain/ask":
                ans = brain.ask(self._body().get("query", ""))
                self._json(200, _answer_json(ans))
            elif path == "/dreamlayer/brief":
                b = self._body()
                self._json(200, brain.brief(agenda=b.get("agenda"),
                                            since=b.get("since", 0) or 0))
            elif path == "/dreamlayer/replies":
                b = self._body()
                self._json(200, {"replies": brain.suggest_replies(b.get("text", ""))})
            elif path == "/dreamlayer/voice":
                # route a spoken/typed line: ask/recall answered here, the rest
                # returned as a structured intent for the app to act on
                from ...orchestrator.voice import parse_intent
                it = parse_intent(self._body().get("text", ""))
                if it.kind in ("ask", "recall"):
                    ans = brain.ask(it.args.get("query", ""))
                    self._json(200, {"intent": it.kind, "query": it.args.get("query", ""),
                                     "answer": ans.text if ans is not None else ""})
                elif it.kind == "brief":
                    self._json(200, {"intent": "brief", **brain.brief()})
                else:
                    self._json(200, {"intent": it.kind, **it.args})
            elif path == "/dreamlayer/calendar":
                # add or remove an agenda event ({title, ts, place[, remove]})
                b = self._body()
                if b.get("remove"):
                    items = brain.remove_event(b.get("title", ""), b.get("ts"))
                else:
                    items = brain.add_event(b.get("title", ""),
                                            b.get("ts", 0) or 0, b.get("place", ""))
                self._json(200, {"items": items})
            elif path == "/dreamlayer/calendar/sync":
                # pull macOS Calendar.app into the agenda now
                self._json(200, brain.sync_calendar())
            elif path == "/dreamlayer/contacts/sync":
                self._json(200, brain.sync_contacts())
            elif path == "/dreamlayer/reminders/sync":
                self._json(200, brain.sync_reminders())
            elif path == "/dreamlayer/saga/record":
                # the hub / phone reports an ecosystem event it drove (e.g. a
                # voice wake, a dossier, focus, rewind) so its badge can unlock
                ev = self._body().get("event", "")
                self._json(200, {"unlocked": brain.saga_record(ev) if ev else [],
                                 "saga": brain.saga.snapshot()})
            elif path == "/dreamlayer/model/pull":
                # one-click Ollama pull — local-only (it runs a long job on the box)
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                self._json(200, brain.pull_model(self._body().get("model", "")))
            elif path == "/dreamlayer/people":
                # introduce/update or remove a person ({name, note, tags[, remove]})
                b = self._body()
                if b.get("remove"):
                    items = brain.remove_person(b.get("name", ""))
                else:
                    items = brain.add_person(b.get("name", ""), b.get("note", ""),
                                             b.get("tags"))
                self._json(200, {"items": items})
            elif path == "/dreamlayer/brain/explain":
                b = self._body()
                ans = brain.explain(b.get("label", ""), b.get("image"),
                                    b.get("want", "quick"))
                self._json(200, _answer_json(ans))
            elif path == "/dreamlayer/reindex":
                stats = brain.reindex()
                brain.activity.add("index", "Re-indexed your folders")
                self._json(200, {"stats": stats, "missing": brain.missing_folders()})
            elif path == "/dreamlayer/token/rotate":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                import secrets
                brain.config.token = secrets.token_hex(8)
                brain.save()
                brain.activity.add("privacy", "Rotated the pairing token — devices must re-pair")
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/clear":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                what = self._body().get("what", "")
                if what in ("history", "all"): brain.history.clear()
                if what in ("activity", "all"): brain.activity.clear()
                if what in ("folders", "all"):
                    brain.config.folders = []; brain.save(); brain.reindex()
                # don't re-seed the activity log we just cleared
                if what in ("history", "folders"):
                    brain.activity.add("config", f"Cleared {what}")
                self._json(200, {"ok": True, "stats": brain.index.stats()})
            elif path == "/dreamlayer/cloud/test":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .backends import cloud_test
                self._json(200, cloud_test(brain.config))
            elif path == "/dreamlayer/restore":
                if not self._from_localhost():
                    self._json(403, {"error": "restore is local-only"}); return
                brain.import_backup(self._body())
                brain.activity.add("config", "Restored from a backup")
                self._json(200, {"ok": True, "config": brain.config.public()})
            elif path == "/dreamlayer/message/draft":
                from .macos_sources import MessageDraft, build_send_script
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                self._json(200, {"script": build_send_script(d)})
            elif path == "/dreamlayer/message/send":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .macos_sources import MessageDraft, send_message
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                try:
                    res = send_message(d, approved=bool(b.get("approved")))
                    brain.activity.add("message", f"Sent a {d.channel} to {d.to}")
                    self._json(200, res)
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"error": str(e)[:200]})
            else:
                self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


def _write_upload(brain: Brain, folder: str, name: str, data: bytes) -> bool:
    # only into a folder the Brain already watches (no arbitrary writes)
    target = str(Path(folder).expanduser())
    if target not in brain.config.folders:
        return False
    dest = Path(target) / name
    try:
        dest.write_bytes(data)
        return True
    except OSError:
        return False


def _version() -> str:
    try:
        import dreamlayer
        return getattr(dreamlayer, "__version__", "0.0.0")
    except Exception:
        return "0.0.0"


def _answer_json(ans: Optional[Answer]) -> dict:
    if ans is None:
        return {"text": "", "tier": "", "sources": [], "confidence": 0.0}
    return {"text": ans.text, "tier": ans.tier, "sources": ans.sources,
            "confidence": ans.confidence}


def _activity_feed(brain: Brain, n: int = 40) -> list[dict]:
    """One newest-first feed: questions + every action the Brain took."""
    items = []
    for h in brain.history.recent(n):
        items.append({"ts": h.get("ts", 0), "kind": "ask",
                      "query": h.get("query", ""), "text": h.get("answer", ""),
                      "tier": h.get("tier", "")})
    for a in brain.activity.recent(n):
        items.append({"ts": a.get("ts", 0), "kind": a.get("kind", "event"),
                      "text": a.get("text", "")})
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return items[:n]


def _browse_dir(raw: str) -> dict:
    """List the subfolders of a directory so the panel can walk the Mac's own
    filesystem — folders only, hidden entries skipped."""
    base = Path(raw).expanduser() if raw else Path.home()
    try:
        base = base.resolve()
    except OSError:
        base = Path.home()
    if not base.is_dir():
        base = Path.home()
    dirs = []
    try:
        for e in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if e.is_dir() and not e.name.startswith("."):
                dirs.append(e.name)
    except OSError:
        pass
    parent = str(base.parent) if base.parent != base else ""
    return {"path": str(base), "parent": parent, "dirs": dirs,
            "home": str(Path.home())}
