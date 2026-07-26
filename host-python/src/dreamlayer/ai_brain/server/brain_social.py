"""ai_brain/server/brain_social.py — the People & social memory method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every
method runs on the shared Brain ``self`` — the orchestrator ops_* pattern.
"""
from __future__ import annotations

from ._brain_host import BrainHost

import json
import re
import time


# "who is Sarah" / "what do I know about Marcus" — the dossier question. It only
# ever RESOLVES against your consented roster (see _roster_name_in), so a general
# question ("who is the mayor") is never hijacked into a person lookup.
_DOSSIER_ASK = re.compile(
    r"(?i)\b(?:who\s+is|who\s+was|who'?s|what\s+do\s+i\s+know\s+about|"
    r"what\s+do\s+you\s+know\s+about|tell\s+me\s+about|remind\s+me\s+about|"
    r"catch\s+me\s+up\s+on|brief\s+me\s+on)\b")


def _ago(ts: float, now: float | None = None) -> str:
    """A coarse, honest relative time ('3d ago'); '' when there's no timestamp."""
    try:
        ts = float(ts or 0.0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    d = max(0.0, (now if now is not None else time.time()) - ts)
    if d < 90:
        return "just now"
    if d < 5400:
        return f"{int(d // 60)} min ago"
    if d < 172800:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


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
            ner = None
            try:                                       # sharper commitments if GLiNER is installed
                from ...social_lens.commitment_ner import default_commitment_ner
                ner = default_commitment_ner()
            except Exception:                          # noqa: BLE001
                ner = None
            m = MeetingLog(self.cfg_dir / "meetings.json", ner=ner)
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
        # W6: start rehearsing the name — the moment right after you meet someone
        # is exactly when it slips. Best-effort; never fails the introduction.
        try:
            self.rehearse_person(name, note or "")
        except Exception:                          # noqa: BLE001
            pass
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

    # -- the dossier: what you honestly know about someone you introduced -----
    # Face recognition is deliberately NOT the trigger for this. The Brain the
    # phone talks to has NO face-recognition model: truth_lens.face_embed is a
    # documented deterministic STUB (it reports a face in any non-dark frame and
    # hashes pixel sums, so two photos of the same person score ~0.00 against each
    # other and only byte-identical pixels ever "match"). Wiring that to a dossier
    # would fabricate identity — the exact dishonesty this project refuses — so
    # the dossier is keyed on a NAME the wearer supplies, which is also the
    # consent-first trigger, and every field comes from the wearer's OWN records.
    # The look path keeps deferring faces (object_lens.person_guard); it must stay
    # that way until a real, deliberately-chosen face model is wired.

    def _roster_name_in(self, text: str, anchored: bool = False):
        """The consented-roster name mentioned in `text`, or None.

        Roster-gated on purpose: a name that isn't someone you introduced returns
        None, so "who is the mayor" is never treated as a person lookup and falls
        through to normal recall. Prefers the longest full-name match; a bare
        first name resolves ONLY when it's unambiguous (never guess between two
        people who share one).

        With ``anchored`` the name must be the FIRST thing in `text`. dossier_query
        passes the OBJECT of the question ("who is <this>"), so a roster name that
        is also an ordinary word — Will, May, Art, Grace — can no longer hijack a
        general question: "who is the will of the people" leaves the object as
        "the will of the people", which starts with "the", so nothing matches and
        it falls through to normal recall (audit 2026-07-23)."""
        t = " ".join(str(text or "").lower().split())
        if not t:
            return None
        names = [n for n in self.known_names() if n and n.strip()]

        def _hit(pat: str) -> bool:
            if anchored:
                return re.match(pat + r"\b", t) is not None
            return re.search(r"\b" + pat + r"\b", t) is not None

        for n in sorted(names, key=lambda s: -len(s)):
            if _hit(re.escape(n.strip().lower())):
                return n
        firsts: dict = {}
        for n in names:
            parts = n.strip().lower().split()
            if parts:
                firsts.setdefault(parts[0], []).append(n)
        hits = [ns for f, ns in firsts.items() if _hit(re.escape(f))]
        if len(hits) == 1 and len(hits[0]) == 1:
            cand = hits[0][0]
            # Don't answer about the wrong person of the same first name: when the
            # question supplies a surname AND the roster entry has a DIFFERENT one,
            # refuse ("who is Sarah Chen" must not return Sarah Okafor). A roster
            # entry with no surname still answers — the card shows the name we
            # actually hold, so there is nothing to mistake (audit 2026-07-23).
            asked = t.split()
            held = cand.strip().lower().split()
            if anchored and len(asked) > 1 and len(held) > 1 and asked[1] != held[1]:
                return None
            return cand
        return None

    def person_dossier(self, name: str, now: float | None = None) -> dict:
        """Everything the Brain honestly knows about ONE person you introduced.

        Assembled ONLY from your own records — the People roster (people.json),
        the social mirror the People screen edits, and your own memory index.
        No face recognition, no external lookup, nothing invented: someone you
        never introduced comes back ``{known: False}`` rather than a guess."""
        raw = str(name or "").strip()          # str(): a caller may hand us anything
        if not raw:
            return {"known": False, "name": ""}
        roster = self.people()
        target = next((e for e in roster
                       if e["name"].strip().lower() == raw.lower()), None)
        if target is None:                             # unambiguous first name only
            cands = [e for e in roster
                     if e["name"].strip().lower().split()[:1] == [raw.lower()]]
            target = cands[0] if len(cands) == 1 else None
        mirror = self._find_person(raw) or {}
        if target is None and not mirror:
            return {"known": False, "name": raw}       # never introduced → say so
        full = str((target or {}).get("name") or mirror.get("name") or raw).strip()
        note = str((target or {}).get("note") or "")
        tags = [str(t) for t in ((target or {}).get("tags") or []) if str(t).strip()]
        relation = str(mirror.get("relation") or "").strip()
        company = str(mirror.get("company") or "").strip()
        role = str(mirror.get("role") or "").strip()
        notes = [str(n).strip() for n in (mirror.get("notes") or []) if str(n).strip()]
        debts = [str(d).strip() for d in (mirror.get("debts") or []) if str(d).strip()]
        topics = [str(t).strip() for t in (mirror.get("topics") or []) if str(t).strip()]
        if note and note not in notes:
            notes = [note] + notes
        introduced = _ago((target or {}).get("ts") or 0.0, now)
        # what YOU wrote that mentions them — your own memory, never a lookup
        mentions: list = []
        try:
            for _p, passage, _h in (self.index.search(full, k=3) or []):
                s = " ".join(str(passage).split())
                if s:
                    mentions.append(s[:160])
        except Exception:                              # noqa: BLE001
            mentions = []
        bits = [b for b in (relation, role, company) if b]
        headline = (" · ".join(bits[:2]) if bits
                    else (f"introduced {introduced}" if introduced else "in your People"))
        detail = (("about " + ", ".join(topics[:3])) if topics
                  else (" · ".join(tags[:3]) if tags else ""))
        footer = (notes[0] if notes else (mentions[0] if mentions else ""))[:80]
        from ...hud import cards
        card = cards.person_dossier({
            "person": full, "last_seen_ago": "", "last_line": footer,
            "topics": topics[:3], "exchanges": len(mentions),
        })
        # the honest copy for a NAME-keyed recall (the device card's default
        # headline assumes a conversation ledger; ours is the roster + memory)
        card.update({"eyebrow": "YOU KNOW", "headline": headline, "detail": detail,
                     "footer": footer, "relation": relation, "notes": notes[:3],
                     "debts": debts[:2], "introduced": introduced,
                     "lines": [full] + [x for x in (headline, detail) if x] + notes[:2]})
        return {"known": True, "name": full, "relation": relation,
                "company": company, "role": role, "note": note, "tags": tags,
                "notes": notes, "debts": debts, "topics": topics,
                "introduced_ago": introduced, "mentions": mentions, "card": card}

    def dossier_query(self, text: str, now: float | None = None):
        """'who is Sarah' / 'what do I know about Marcus' → the person dossier.

        Returns None when the text isn't a dossier question OR names nobody you
        introduced — so the caller falls through to normal recall and a general
        question still gets a general answer."""
        t = (text or "").strip()
        if not t:
            return None
        m = _DOSSIER_ASK.search(t)
        if not m:
            return None
        # the OBJECT of the question, anchored — see _roster_name_in(anchored=)
        tail = " ".join(t[m.end():].split()).strip(" \t,:;-–—?!.\"")
        who = self._roster_name_in(tail, anchored=True)
        if not who:
            return None
        # A possessive right after the name asks about someone/something ELSE
        # ("who is Sarah Chen's manager") — hand that to normal recall instead of
        # answering with Sarah's own dossier. Checked AFTER the match so it works
        # for a multi-token name too, not just the first token (audit 2026-07-23).
        low, wl = tail.lower(), who.strip().lower()
        for cand in (wl, wl.split()[0] if wl.split() else wl):
            if low.startswith(cand):
                rest = low[len(cand):]
                if rest.startswith("'s") or rest.startswith("’s"):
                    return None
                break
        d = self.person_dossier(who, now)
        if not d.get("known"):
            return None
        card = d.get("card") or {}
        say_bits = [b for b in (card.get("headline"), card.get("detail"),
                                (d.get("notes") or [""])[0]) if b]
        say = (f"{d['name']} — " + " · ".join(say_bits[:2])) if say_bits else d["name"]
        try:
            self.activity.add("people", f"Recalled {d['name']}")
        except Exception:                              # noqa: BLE001
            pass
        return {"intent": "dossier", "who": d["name"], "say": say, "card": card,
                "dossier": {k: v for k, v in d.items() if k != "card"}}

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
