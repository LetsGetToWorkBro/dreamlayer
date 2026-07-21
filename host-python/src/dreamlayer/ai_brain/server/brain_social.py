"""ai_brain/server/brain_social.py — the People & social memory method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

from ._brain_host import BrainHost

import json
import time


class SocialOps(BrainHost):
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

    def known_names(self) -> set:
        """Everyone you've CONSENTED to remember — the roster the person guard
        consults so an introduced person is recognized, not deferred as a
        stranger. Union of the People registry (people.json) and the social
        mirror. Cached against people.json's mtime so it's cheap to call on every
        look."""
        p = self.cfg_dir / "people.json"
        try:
            mt = p.stat().st_mtime if p.exists() else 0.0
        except OSError:
            mt = 0.0
        mirror = getattr(self, "social_people", []) or []
        cache = getattr(self, "_known_names_cache", None)
        if cache is not None and cache[0] == mt and cache[2] == len(mirror):
            return cache[1]
        names = {e["name"].strip() for e in self.people() if e.get("name")}
        for pp in mirror:
            n = str(pp.get("name", "")).strip()
            if n:
                names.add(n)
        self._known_names_cache = (mt, names, len(mirror))
        return names

    def introduce(self, text: str):
        """Natural-language front door to add_person: 'this is Sarah', 'meet
        Sarah', 'her name is Sarah', 'I'm Sarah from marketing' → enroll Sarah
        (with consent, on-device). Returns {name, ...} or None when the text
        isn't an introduction. If a meeting is running, the person also joins it
        as an attendee."""
        from ...social_lens.introductions import parse_introduction
        parsed = parse_introduction(text)
        if not parsed:
            return None
        self.add_person(parsed["name"], note=parsed.get("note", ""))
        try:
            self._meetings().add_attendee(parsed["name"])
        except Exception:                              # noqa: BLE001
            pass
        return parsed

    # -- meetings ----------------------------------------------------------
    def _meetings(self):
        m = getattr(self, "_meeting_log", None)
        if m is None:
            from ...social_lens.meeting import MeetingLog
            m = MeetingLog(self.cfg_dir / "meetings.json")
            self._meeting_log = m
        return m

    def meetings(self, limit: int = 50) -> list:
        return self._meetings().all(limit)

    def meeting_command(self, text: str):
        """Natural-language meeting control: 'start a meeting [with X and Y]',
        'note that …' / 'action: …', 'end the meeting'. Returns a result dict
        (with a `say`) or None when the text isn't a meeting command."""
        import re
        t = (text or "").strip()
        if not t:
            return None
        log = self._meetings()
        if re.match(r"(?i)^\s*(start|begin)\s+(a\s+|the\s+)?meeting\b", t):
            who = re.split(r"(?i)\bwith\b", t, 1)
            names = []
            if len(who) > 1:
                from ...social_lens.introductions import _NAME
                names = re.findall(_NAME, who[1])
            mtg = log.start(attendees=names)
            for n in names:                            # enroll attendees you name
                self.add_person(n, note="met in a meeting")
            self.activity.add("meeting", "Meeting started")
            say = "Meeting started." + (f" With {', '.join(names)}." if names else "")
            return {"intent": "meeting_start", "say": say, "meeting": mtg}
        if re.match(r"(?i)^\s*(end|stop|finish|wrap up)\s+(the\s+)?meeting\b", t):
            mtg = log.end()
            if mtg is None:
                return {"intent": "meeting_end", "say": "No meeting is running."}
            n = len(mtg.get("actions", []))
            self.activity.add("meeting", f"Meeting ended — {n} action(s)")
            say = f"Meeting ended. {n} action item{'s' if n != 1 else ''} captured."
            return {"intent": "meeting_end", "say": say, "meeting": mtg}
        m = re.match(r"(?i)^\s*(?:note(?:\s+that)?|action(?:\s+item)?|todo)\s*[:\-]?\s+(.+)$", t)
        if m and log.current() is not None:
            mtg = log.note(m.group(1))
            return {"intent": "meeting_note", "say": "Noted.", "meeting": mtg}
        return None

    def add_person(self, name: str, note: str = "", tags=None) -> list:
        """Introduce (or update) a person. Re-adding a name updates the note."""
        name = (name or "").strip()
        if not name:
            return self.people()
        tags = [t for t in (tags or []) if t]
        with self._store_lock:
            cur = self._load_json("people.json", [])
            cur = [e for e in cur if e.get("name") != name]     # replace existing
            cur.append({"name": name, "note": note or "", "tags": tags,
                        "ts": time.time(), "source": "manual"})
            self._save_json("people.json", cur)
            self.activity.add("people", f"Introduced {name}")
        return self.people()

    def remove_person(self, name: str) -> list:
        name = (name or "").strip()
        with self._store_lock:
            cur = self._load_json("people.json", [])
            kept = [e for e in cur if e.get("name") != name]
            if len(kept) != len(cur):
                self._save_json("people.json", kept)
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
        with self._store_lock:
            cur = self._load_json("people.json", [])
            manual = [e for e in cur if e.get("source") != "contacts"]
            manual_names = {e.get("name") for e in manual}
            synced = []
            for c in contacts:
                if not c.get("name") or c["name"] in manual_names:
                    continue                               # never shadow a manual entry
                note = "  •  ".join([x for x in (c.get("company"), c.get("role")) if x])
                synced.append({"name": c["name"], "note": note, "tags": [],
                               "ts": time.time(), "source": "contacts",
                               "email": c.get("email", "")})
            self._save_json("people.json", manual + synced)
        self.last_contacts_sync = time.time()
        self.activity.add("people", f"Synced {len(synced)} contact(s)")
        self.saga_record("contacts")
        return {"items": self.people(), "synced": len(synced)}

    def _load_people(self) -> list:
        p = self.cfg_dir / "social_people.json"
        if p.exists():
            try:
                return json.loads(p.read_text()) or []
            except Exception:
                return []
        return []

    def _save_people(self) -> None:
        try:
            self._save_json("social_people.json", self.social_people)
        except Exception:
            pass

    def social_people_state(self) -> dict:
        return {"people": self.social_people}

    def receive_people(self, payload: dict) -> dict:
        """Store the snapshot the hub pushed (merging so phone-side edits made
        while the hub was offline aren't clobbered by name that isn't present)."""
        incoming = (payload or {}).get("people") or []
        self.social_people = list(incoming)
        self._save_people()
        return {"ok": True, "count": len(self.social_people)}

    def edit_person(self, body: dict) -> dict:
        """Apply a phone edit to a person in the mirror: add a note, set the
        relationship, remove a note, or settle debts. Returns the updated
        person, or {ok:False} if the id isn't in the mirror."""
        b = body or {}
        cid = str(b.get("contact_id", ""))
        action = str(b.get("action", ""))
        person = next((p for p in self.social_people
                       if p.get("contact_id") == cid), None)
        if person is None:
            return {"ok": False, "error": "no such person"}
        if action == "note":
            note = str(b.get("value", "")).strip()
            if note:
                person.setdefault("notes", []).append(note)
        elif action == "remove_note":
            note = str(b.get("value", ""))
            person["notes"] = [n for n in person.get("notes", []) if n != note]
        elif action == "relation":
            person["relation"] = str(b.get("value", "")).strip()
        elif action == "settle":
            person["debts"] = []
        else:
            return {"ok": False, "error": "unknown action"}
        self._save_people()
        return {"ok": True, "person": person}

    def _find_person(self, name: str):
        nl = (name or "").strip().lower()
        if not nl:
            return None
        exact = next((p for p in self.social_people
                      if p.get("name", "").lower() == nl), None)
        if exact:
            return exact
        # unique first-name match
        starts = [p for p in self.social_people
                  if p.get("name", "").lower().split()[:1] == [nl]]
        return starts[0] if len(starts) == 1 else None

    def voice_social(self, intent: str, args: dict) -> dict:
        """Full-parity social voice from the phone's typed box: note / meet /
        debt / settle, applied to the people mirror the People screen reads.
        The hub owns the truth on-glass; this keeps the phone consistent when
        you type instead of speaking to the glasses."""
        a = args or {}
        who = str(a.get("who") or "").strip()

        if intent == "meet_person":
            if not who:
                return {"intent": intent, "ok": False, "say": "Who is this?"}
            person = self._find_person(who)
            if person is None:
                safe = "".join(c for c in who.lower() if c.isalnum()) or "person"
                person = {"contact_id": f"phone_{safe}", "name": who,
                          "relation": "", "company": "", "role": "",
                          "last_met": "", "last_seen": "", "notes": [],
                          "debts": [], "topics": []}
                self.social_people.append(person)
            if a.get("relation"):
                person["relation"] = str(a["relation"]).strip()
            if a.get("note"):
                person.setdefault("notes", []).append(str(a["note"]).strip())
            self._save_people()
            return {"intent": intent, "ok": True, "who": who,
                    "say": f"Good to meet {who}."}

        if not who:
            return {"intent": intent, "ok": False,
                    "say": "Who do you mean? Say their name."}
        person = self._find_person(who)
        if person is None:
            return {"intent": intent, "ok": False,
                    "say": f"I don't know who {who} is yet."}
        name = person["name"]
        if intent == "note_person":
            note = str(a.get("note") or "").strip()
            if note:
                person.setdefault("notes", []).append(note)
            say = f"Got it — I'll remember that about {name}."
        elif intent == "debt":
            what = str(a.get("what") or "").strip()
            if a.get("dir") == "they_owe":
                person.setdefault("debts", []).append(f"owes you {what}")
                say = f"Noted — {name} owes you {what}."
            else:
                person.setdefault("debts", []).append(f"you owe {what}")
                say = f"Noted — you owe {name} {what}."
        elif intent == "debt_settle":
            person["debts"] = []
            say = f"Squared up with {name}."
        else:
            return {"intent": intent, "ok": False, "say": ""}
        self._save_people()
        return {"intent": intent, "ok": True, "who": name, "say": say}
