"""ops_commitments — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from . import answer_builder
from . import intents
from ..hud import cards
import json


class CommitmentRecallOps:

    # ------------------------------------------------------------------
    # Commitment Drift
    # ------------------------------------------------------------------

    def nudge_commitment(self, subject: str, now: float | None = None):
        """Progress toward a commitment (heals it toward bloom)."""
        return self.drift_engine.nudge(subject, now=now)


    def keep_commitment(self, subject: str, now: float | None = None):
        """Mark a commitment kept — bloom and pin."""
        return self.drift_engine.keep(subject, now=now)


    def break_commitment(self, subject: str, now: float | None = None):
        """Mark a commitment broken — shatter and pin."""
        return self.drift_engine.break_(subject, now=now)


    # ------------------------------------------------------------------
    # Life Quest Engine (Commitment Drift as a personal RPG)
    # ------------------------------------------------------------------

    def quests(self, now: float | None = None):
        """Active commitments, seen as quests (most-imperilled first)."""
        return self.quest.quests(now=now)


    def complete_quest(self, subject: str, now: float | None = None):
        """Keep a commitment: award XP, extend the streak, surface a reward."""
        reward = self.quest.complete(subject, now=now)
        if reward is not None:
            self.bridge.send_card(reward.to_hud_card(), event="quest_complete")
        return reward


    def abandon_quest(self, subject: str, now: float | None = None) -> bool:
        return self.quest.abandon(subject, now=now)


    def quest_stats(self):
        return self.quest.stats()


    def _stash(self, subject: str, place: str) -> dict:
        """"I left my bike at the north rack" — drop a Waypath anchor so a later
        "where's my bike?" answers. Veil-gated (it's a memory of your things)."""
        subject = (subject or "").strip()
        place = (place or "").strip()
        if not subject:
            return {"intent": "stash", "ok": False, "say": "Left what where?"}
        if self.incognito or not self.privacy.allow_capture():
            return {"intent": "stash", "ok": False, "say": "Not while you're incognito."}
        self.waypath.remember_place(subject, place)
        say = (f"Got it — your {subject} is at {place}." if place
               else f"Got it — I'll remember your {subject}.")
        return {"intent": "stash", "ok": True, "say": say,
                "subject": subject, "place": place}


    def _locate(self, subject: str, heading_deg: float = 0.0) -> dict:
        """"where's my bike?" — answer from a Waypath anchor you dropped. Draws
        the direction/place card on the glasses when found."""
        subject = (subject or "").strip()
        if not subject:
            return {"intent": "locate", "ok": False, "say": "Find what?"}
        cue = self.find_way(subject, heading_deg)   # veil-gated; draws the card
        if cue is None:
            return {"intent": "locate", "ok": False,
                    "say": "Not while you're incognito."}
        if not cue.found:
            # no dropped Waypath anchor — retrace from ambient sightings instead
            rt = self.retrace(subject)
            if rt.get("found"):
                return rt
            return {"intent": "locate", "ok": False, "found": False,
                    "say": f"I don't have a spot saved for your {subject} yet."}
        return {"intent": "locate", "ok": True, "found": True,
                "subject": cue.subject, "place": cue.place, "detail": cue.text,
                "say": f"Your {cue.subject} — {cue.text}."}

    def retrace(self, subject: str) -> dict:
        """Where did I last *see* it? — ambient-sighting recall (INNOVATION 2.6).
        Unlike _locate (a Waypath anchor you dropped), this answers from the
        passive sightings the ambient pipeline understood: Retriever.search
        blended with recency, joined to place + time. No image is stored — the
        sighting is a single row, findable *and* forgettable."""
        from ..config import CONFIG
        subject = (subject or "").strip()
        if not subject:
            return {"intent": "retrace", "ok": False, "found": False, "say": "Find what?"}
        # a read of past sightings: recall-gated (incognito blocks capture/
        # writes, not recall — pinned by test_waypath_voice; only the full
        # pause veil holds recall too)
        if not self.privacy.allow_recall():
            return {"intent": "retrace", "ok": False, "found": False,
                    "say": "Not while the veil is down."}
        scored = self.retriever.search(subject, kind="object", top_k=5)
        strong = [(s, m) for s, m in scored if s >= CONFIG.recall_min_confidence]
        if not strong:
            return {"intent": "retrace", "ok": False, "found": False,
                    "say": f"I haven't understood your {subject} anywhere yet."}
        # recency blend: among the confident sightings, the *last* place it was
        # understood is what a "where is it" question is actually asking for
        score, mem = max(strong, key=lambda sm: self._source_ts(sm[1]) or 0.0)
        meta = json.loads(mem.get("meta") or "{}")
        place = meta.get("place") or meta.get("location") or ""
        when = self._human_when(mem.get("created_at"))
        obj = meta.get("object") or mem.get("summary", subject)
        card = cards.object_recall({"object": obj, "place": place, "detail": when,
                                    "last_seen": when, "confidence": round(score, 2)})
        self.bridge.send_card(card)
        say = (f"Your {subject} — {place}, {when}." if place
               else f"Your {subject} — {when}.")
        return {"intent": "retrace", "ok": True, "found": True, "subject": subject,
                "place": place, "when": when, "say": say}

    @staticmethod
    def _human_when(created_at, now=None) -> str:
        """A glanceable time phrase from an ISO ``created_at``: '8:40am',
        '8:40am yesterday', or '8:40am on Jul 03'. ``now`` is injectable for tests."""
        if not created_at:
            return ""
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(str(created_at))
        except (TypeError, ValueError):
            return ""
        h = dt.hour % 12 or 12
        t = f"{h}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"
        now = now or datetime.now(dt.tzinfo)
        try:
            days = (now.date() - dt.date()).days
        except (TypeError, ValueError, AttributeError):
            return t
        if days <= 0:
            return t
        if days == 1:
            return f"{t} yesterday"
        return f"{t} on {dt.strftime('%b %d')}"


    def _debt(self, who: str | None, direction: str, what: str,
              within_sec: float = 90.0) -> dict:
        """Track "Marcus owes me $20" / "I owe Dana lunch" on that person, so it
        surfaces on their recall card next time. By name, or (who=None) whoever
        you just looked at. Veil-gated."""
        what = (what or "").strip()
        if not what:
            return {"intent": "debt", "ok": False, "say": "Owes what?"}
        if self.incognito or not self.privacy.allow_capture():
            return {"intent": "debt", "ok": False, "say": "Not while you're incognito."}
        if who:
            contact = self.social.add_debt(direction, what, who=who)
            if contact is None:
                return {"intent": "debt", "ok": False,
                        "say": f"I don't know who {who} is yet."}
            name = contact.name
        else:
            lp = self._last_person
            if not lp or (self._clock() - lp.get("ts", 0)) > within_sec:
                return {"intent": "debt", "ok": False,
                        "say": "Look at someone first, then tell me."}
            contact = self.social.add_debt_by_id(lp["contact_id"], direction, what)
            name = contact.name if contact is not None else lp["name"]
        say = (f"Noted — {name} owes you {what}." if direction == "they_owe"
               else f"Noted — you owe {name} {what}.")
        self.publish_people()
        return {"intent": "debt", "ok": True, "who": name, "dir": direction,
                "what": what, "say": say}


    def _debt_settle(self, who: str | None, within_sec: float = 90.0) -> dict:
        if self.incognito or not self.privacy.allow_capture():
            return {"intent": "debt_settle", "ok": False, "say": "Not while you're incognito."}
        if who:
            contact = self.social.settle(who=who)
            if contact is None:
                return {"intent": "debt_settle", "ok": False,
                        "say": f"I don't know who {who} is yet."}
            name = contact.name
        else:
            lp = self._last_person
            if not lp or (self._clock() - lp.get("ts", 0)) > within_sec:
                return {"intent": "debt_settle", "ok": False,
                        "say": "Look at someone first, then tell me."}
            self.social.settle_by_id(lp["contact_id"])
            name = lp["name"]
        self.publish_people()
        return {"intent": "debt_settle", "ok": True, "who": name,
                "say": f"Squared up with {name}."}


    def _meet_person(self, name: str | None, relation: str | None,
                     note: str | None, frame=None) -> dict:
        """Meet someone on the spot — "this is my colleague Sarah, she's a PM".
        Grabs the face in view + the name, creates the contact, and seeds the
        dossier with the relationship and any note. Veil-gated."""
        if not name:
            return {"intent": "meet_person", "ok": False, "say": "Who is this?"}
        if self.incognito or not self.privacy.allow_capture():
            return {"intent": "meet_person", "ok": False,
                    "say": "Not while you're incognito."}
        rec = self.social.meet(name, frame=frame, note=note, relation=relation)
        if rec is None:
            return {"intent": "meet_person", "ok": False,
                    "say": "Couldn't add them just now."}
        self._last_person = {"contact_id": rec.contact_id, "name": name,
                             "ts": self._clock()}
        tail = (" — I'll know them next time" if frame is not None
                else " (no face in view, so name only)")
        self.publish_people()
        return {"intent": "meet_person", "ok": True, "who": name,
                "relation": relation, "note": note,
                "say": f"Good to meet {name}{tail}."}


    def _note_about_person(self, who: str | None, note: str,
                           within_sec: float = 90.0) -> dict:
        """Jot a note about a person — by name, or (who=None) whoever you just
        looked at. Appends to their own contact so it shows on the recall card
        next time. Veil-gated: nothing is written while capture is paused."""
        note = (note or "").strip()
        if not note:
            return {"intent": "note_person", "ok": False,
                    "say": "What should I remember about them?"}
        if self.incognito or not self.privacy.allow_capture():
            return {"intent": "note_person", "ok": False,
                    "say": "Not while you're incognito."}
        if who:
            contact = self.social.add_note(note, who=who)
            if contact is None:
                return {"intent": "note_person", "ok": False,
                        "say": f"I don't know who {who} is yet."}
            target_name = contact.name
        else:
            # "her / him / this person" → whoever you just looked at
            lp = self._last_person
            if not lp or (self._clock() - lp.get("ts", 0)) > within_sec:
                return {"intent": "note_person", "ok": False,
                        "say": "Look at someone first, then tell me to remember."}
            contact = self.social.add_note_by_id(lp["contact_id"], note)
            target_name = contact.name if contact is not None else lp["name"]
        self.publish_people()
        return {"intent": "note_person", "ok": True, "who": target_name,
                "note": note,
                "say": f"Got it — I'll remember that about {target_name}."}


    def tick_drift(self, now: float | None = None) -> list[dict]:
        alert_records = self.drift_engine.tick(now=now)
        hud_cards = []
        for rec in alert_records:
            meta = rec.event.meta or {}
            card = cards.commitment_drift({
                "task":        rec.event.summary,
                "person":      meta.get("person", ""),
                "drift_state": rec.state,
                "decay":       rec.decay,
                "due":         meta.get("due", ""),
                "confidence":  rec.event.confidence,
            })
            self.bridge.send_card(card, event="drift_alert")
            hud_cards.append(card)
        return hud_cards


    # ------------------------------------------------------------------
    # Active recall
    # ------------------------------------------------------------------

    def ask(self, query):
        self.bridge.send_command("ask")
        # recall-gated like every other recall surface (P1-7 / re-audit): a full
        # pause veil blocks recall, so we must not touch retriever/db or draw a
        # memory card here. Incognito still allows recall (it blocks capture,
        # not looking back at what you already know).
        if not self.privacy.allow_recall():
            veil = cards.privacy_veil()
            self.bridge.send_card(veil)
            return veil
        intent = intents.classify(query)
        source = None
        if intent["intent"] == "object_recall":
            scored = self.retriever.search(query, kind="object")
            card = answer_builder.build_object_answer(scored)
            if scored:
                source = scored[0][1]
        elif intent["intent"] == "commitment_recall":
            commits = self.db.commitments(person=intent.get("person"))
            card = answer_builder.build_commitment_answer(commits)
            if commits:
                source = commits[0]
        else:
            card = cards.low_confidence()
        # Meridian: answers condense from where they live in time — stamp
        # the Focus law's origin angle from the source memory's timestamp
        # (docs/cinema_v2/focus.md). No timestamp -> the card enters from
        # "now", which is the honest default.
        origin_ts = self._source_ts(source)
        if origin_ts is not None and card.get("type") in (
            "ObjectRecallCard", "CommitmentRecallCard"
        ):
            card["origin_deg"] = round(self.horizon.angle_for_ts(origin_ts), 1)
        self.bridge.send_card(card)
        return card


    @staticmethod
    def _source_ts(row) -> float | None:
        """Best-effort event timestamp from a memory/commitment row."""
        if not row:
            return None
        meta = row.get("meta")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        if isinstance(meta, dict) and meta.get("timestamp"):
            try:
                return float(meta["timestamp"])
            except (TypeError, ValueError):
                pass
        created = row.get("created_at")
        if created:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(str(created))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                pass
        return None


    def on_place(self, signature):
        """Handle place signature match — feeds Dream Mode ghost layer if active."""
        if not self.privacy.allow_capture():
            return None
        p = self.proactive.on_place(signature)
        self.publish_plugin_event("place", {"signature": signature})

        if self.state.is_dream():
            anchors = []
            if p:
                # on_place returns a DICT ({summary, person, confidence}); the
                # old getattr() reads always hit the default, so every dream
                # anchor carried an empty summary. Use dict access.
                anchors = [{
                    "id":         str(p.get("id", signature)),
                    "summary":    p.get("summary",  ""),
                    "place":      p.get("place",    ""),
                    "ts_label":   p.get("ts_label", ""),
                    "confidence": p.get("confidence", None),
                }]
            self.dream.feed_place(signature, anchors)
            return None

        # a proactive place card is an interruption — the maturity arc gates
        # it (the ambient dream ghost-layer above is not, and never is)
        conf = float((p or {}).get("confidence") or 1.0) if p else 1.0
        if p and not self.maturity.allows_proactive(kind="place",
                                                    confidence=conf):
            return None
        card = answer_builder.build_proactive(p)
        if card:
            self.bridge.send_card(card, event="proactive_trigger")
        return card


    # ------------------------------------------------------------------
    # Privacy
    # ------------------------------------------------------------------

    def pause(self):
        self.privacy.pause()
        self.bridge.inject_event("privacy_pause")
        self.bridge.send_card(cards.privacy_veil(), event="privacy_pause")
        self.publish_plugin_event("veil", {"paused": True})


    def resume(self):
        self.privacy.resume()
        self.bridge.inject_event("privacy_resume")
        self.bridge.send_command("resume")
        self.publish_plugin_event("veil", {"paused": False})
