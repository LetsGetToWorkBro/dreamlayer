"""ops_world_lenses — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ..hud import cards
from ..pipelines import vision
from ._ops_helpers import _parse_scene_reply
from ._ops_helpers import _parse_taste_reply


class WorldLensOps:

    # ------------------------------------------------------------------
    # Instant Skill Overlay (a procedure compiled to a Figment)
    # ------------------------------------------------------------------

    def build_skill(self, name: str, text: str):
        """Compile a step list into a budget-verified Figment ready to deploy.
        Returns (figment, budget_report)."""
        from ..reality_compiler.v2 import compile_skill, parse_skill
        return compile_skill(name, parse_skill(text))


    # ------------------------------------------------------------------
    # On-device fact consistency
    # ------------------------------------------------------------------

    def check_consistency(self, claim: str, now: float | None = None):
        """Flag when a new statement contradicts your own recorded memories.
        Veil-gated; surfaces a card when it fires. Never touches the cloud."""
        if not self.privacy.allow_capture():
            return None
        result = self.consistency.check(claim, now=now)
        if result.fired:
            self.bridge.send_card(result.card, event="consistency")
        return result


    def trace_provenance(self, claim: str, now: float | None = None):
        """Provenance Lens: trace a belief to its origin and standing in your
        own memory. Veil-gated; surfaces a card when a source is found."""
        if not self.privacy.allow_capture():
            return None
        result = self.provenance.trace(claim, now=now)
        if result.found:
            self.bridge.send_card(result.card, event="provenance")
        return result


    def look_at_object(self, frame, now: float | None = None, facet=None):
        """Oracle (Object Lens): recognise the object and surface its panel.

        facet picks the intent — None = everything; "own" = your own facts
        (private, instant glance); "ai" = let an AI explain/translate it;
        "shop" = prices & reviews. Veil-gated; objects only (people are
        Social Lens)."""
        facets = {facet} if facet else None
        self.frame_budget.note_deliberate()
        panel = self.object_lens.look(frame, now=now, facets=facets)
        if panel is not None:
            self.bridge.send_card(panel.to_hud_card(), event="object_panel")
        elif frame is not None and self.privacy.allow_capture():
            # a deliberate look that produced nothing gets an honest card,
            # never silence and never a guess (veiled = deliberately blind,
            # so no card then)
            self.bridge.send_card(cards.couldnt_see(), event="couldnt_see")
        return panel


    def glance(self, frame, dwell_ms: float = 0.0, now: float | None = None):
        """The smart look: classify what's in view, let the lenses bid, and act.

        Fires the clear winner straight to the glasses; sends a one-tap chooser
        card when it's genuinely ambiguous; does nothing when nothing fits or
        the veil is down. This is the no-mode-picker entry point — the wearer
        just looks. Returns the GlanceDecision."""
        from .glance import GlanceContext, GlanceReading
        if not self.privacy.allow_capture():
            from .glance import GlanceDecision
            return GlanceDecision("none", GlanceReading())
        reading = self._classify_glance(frame)
        hint, hts = self._recent_glance_intent
        ctx = GlanceContext(
            recent_intent=hint if (self._clock() - hts) < 6.0 else "",
            user_language=getattr(self.config, "user_language", "en") or "en",
            dwell_ms=dwell_ms, focus=self.focus_active(),
            veiled=not self.privacy.allow_capture())
        decision = self.glance_arbiter.arbitrate(reading, ctx)
        self.publish_plugin_event("glance", {"scene": getattr(reading, "scene", ""),
                                             "kind": decision.kind})
        if decision.kind == "fire" and decision.winner is not None:
            self._run_glance_action(decision.winner.action, frame,
                                    decision.winner.args)
        elif decision.kind == "offer" and decision.card is not None:
            self.bridge.send_card(decision.card, event="glance")
        return decision


    def choose_glance(self, action: str, frame, args: dict | None = None,
                      scene: str = ""):
        """Act on a chooser pick — and teach the arbiter that, for this kind of
        scene, this is the lens you want."""
        if scene and action:
            lens = {"scholar_answer": "scholar_answer", "scholar_form": "scholar_form",
                    "scholar_explain": "scholar_explain", "translate": "rosetta",
                    "oracle": "oracle", "person": "person"}.get(action, action)
            self.glance_arbiter.reinforce(scene, lens)
        return self._run_glance_action(action, frame, args or {})


    def _run_glance_action(self, action: str, frame, args: dict):
        """Route an arbiter action key to the lens that owns it."""
        if action == "scholar_answer":
            return self.read_answer(frame)
        if action == "scholar_form":
            return self.read_form(frame, purpose=args.get("purpose", ""))
        if action == "scholar_explain":
            return self.explain_text(frame)
        if action == "person":
            return self.look_at_person(frame)
        if action == "translate":
            return self.look_at_object(frame, facet="ai")
        if action == "taste":
            return self.taste(frame)
        return self.look_at_object(frame)     # oracle / default


    def _classify_glance(self, frame):
        """Two-tier scene read. A coarse on-device read runs first (free, from
        cheap signals); when it can't tell a form from a question from prose,
        escalate to the Brain's vision tier for a fine read — spending the big
        model only when it changes the answer."""
        from .glance import classify_coarse, GlanceReading
        lang = getattr(self.config, "user_language", "en") or "en"
        signals = {}
        try:
            if self._glance_signals_fn is not None:
                signals = self._glance_signals_fn(frame) or {}
            else:
                # Tier 0: model-backed on the NPU, heuristic offline.
                signals = self.perception.perceive(frame).as_signals()
        except Exception as exc:
            self.health.record_failure("vision", exc)
            signals = {}
        reading = classify_coarse(signals, user_language=lang)
        if self.glance_arbiter.is_ambiguous(reading) and getattr(self, "brain", None):
            fine = self._glance_fine_read(frame)
            if fine is not None:
                return fine
        return reading


    def _glance_fine_read(self, frame):
        """Fine scene classification via the Brain's vision tier (Mac / cloud).
        Returns a GlanceReading or None. The vision model is the seam Ollama
        plugs into; offline this simply returns None and the coarse read stands."""
        from .glance import GlanceReading, SCENES
        prompt = ("Classify what is in this image for a glasses assistant. Reply "
                  "on one line: SCENE: <object|text|form|question|foreign_text|"
                  "person|screen> — then optional tags density=<0-1> "
                  "lang=<iso> fields=<n> question=<yes|no>. Nothing else.")
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return None
        return _parse_scene_reply(ans.text)


    def read_answer(self, frame, question: str = "", now: float | None = None):
        """Scholar: read the question in view and put the answer on the glass.
        Works for any subject; `question` optionally carries a spoken ask about
        what's in front of you. Veil-gated; sends a ScholarCard."""
        return self._scholar_send(self.scholar.answer(frame, question=question))


    def read_form(self, frame, purpose: str = "", now: float | None = None):
        """Scholar: read a form and say what to write in each field. `purpose`
        steers the guidance ("renew my passport", "claim the deduction")."""
        return self._scholar_send(self.scholar.form(frame, purpose=purpose))


    def explain_text(self, frame, now: float | None = None):
        """Scholar: summarize dense legal/technical text in plain words, flagging
        anything that commits you or carries risk."""
        return self._scholar_send(self.scholar.explain(frame))


    def _scholar_send(self, result):
        if result is not None and result.card is not None:
            self.bridge.send_card(result.card, event="scholar")
        return result


    def _scholar_read(self, frame, prompt: str):
        """Scholar's vision seam: read the text in a frame and reason about it,
        through the Brain's vision tier — local model first, cloud only when
        opted in, never while incognito. Falls back to the knowledge tier for a
        text-only reply, and returns None when nothing can read it (so Scholar
        shows an honest 'connect a Brain' card instead of guessing)."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            try:                              # no vision tier — try text knowledge
                ans = self.brain.ask(prompt)
            except Exception:
                ans = None
        if ans is None or ans.is_empty():
            return None
        return ans.text


    def taste(self, frame, budget: float | None = None, now: float | None = None):
        """TasteLens: look at a shelf/menu and put the ranked pick on the glass —
        dietary vetoes first, then budget, then rating/price. Veil-gated; sends a
        TasteCard. Reads through the Brain's vision tier; ranks against your
        DietaryProfile with a pluggable shop_fn for prices/reviews."""
        ranking = self.taste_lens.look(frame, budget=budget)
        card = cards.taste(ranking, unavailable=ranking.unavailable)
        self.bridge.send_card(card, event="taste")
        return ranking


    def _taste_shop(self, label, attrs):
        """TasteLens's price/review seam. Merges the registered shop-provider
        plugins (first provider wins per field); returns {} when none are
        installed. Each provider is isolated — one throwing doesn't sink the rest."""
        merged: dict = {}
        for fn in self._shop_providers:
            try:
                data = fn(label, attrs) or {}
            except Exception:
                continue
            for k, v in data.items():
                merged.setdefault(k, v)
        return merged


    def _taste_read(self, frame):
        """TasteLens's vision seam: read a shelf/menu into a list of items,
        through the Brain's vision tier — local first, cloud only when opted in,
        never while incognito. Returns [] when nothing can read it (so the card
        shows the honest 'connect a Brain' state)."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return []
        prompt = ("List the products or dishes in view for a shopping assistant, "
                  "one per line: NAME | ingredients | price | rating(0-5). "
                  "Use '?' for anything unknown. Nothing else.")
        try:
            ans = self.brain.explain(frame, prompt, want="more")
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return []
        return _parse_taste_reply(ans.text)


    def find_way(self, subject: str, heading_deg: float = 0.0):
        """Waypath Lens: where is my <thing> / where do I go, as a direction
        + distance from your own anchors. Veil-gated."""
        if not self.privacy.allow_capture():
            return None
        cue = self.waypath.locate(subject, heading_deg)
        card = self.waypath.to_hud_card(cue)
        if card is not None:
            self.bridge.send_card(card, event="waypath")
        return cue


    def translate_seen(self, text: str, target: str = "en"):
        """Rosetta Lens (the eye): translate text you look at. Puente is the
        ear (live voice translation)."""
        return self.rosetta.read(text, target=target)

    def translate_heard(self, text: str, target: str = "en", speaker: str = ""):
        """Rosetta Live (the ear, INNOVATION_SESSION 4.6): translate what someone
        is *saying* into your language — offline when the Argos backend is
        installed — and show it as one subtitle card per utterance. Veil-gated;
        nothing is recorded, the caption is a line of text. Returns the card sent,
        or None while incognito."""
        if not self.privacy.allow_capture():
            return None
        res = self.rosetta.read(text, target=target)
        card = cards.spoken_caption(speaker=speaker, text=res.translated)
        self.bridge.send_card(card, event="caption")
        return card

    def thread(self, image: bytes, place: str = "", k: int = 6) -> dict:
        """Thread Lens (INNOVATION_SESSION 4.1): steal color from the world.
        Extract a k-swatch palette from a deliberate snapshot, save it as a
        `taught` memory (recallable by place + time), and hand back the hex
        swatches to paint into the display's dynamic palette bank. Veil-gated;
        the image is never stored — only the palette (a few hex codes)."""
        from ..object_lens.palette_extract import extract_palette
        if not self.privacy.allow_capture():
            return {"ok": False, "reason": "incognito"}
        swatches = extract_palette(image, k)
        if not swatches:
            return {"ok": False, "reason": "no palette"}
        meta = {"palette": swatches, "place": place}
        try:
            self.db.add_memory(kind="taught", summary="palette " + " ".join(swatches),
                               confidence=0.8, meta=meta)
        except Exception as exc:
            self.health.record_failure("thread", exc)
        return {"ok": True, "swatches": swatches, "place": place}

    def ember(self, now=None, window_days: int = 3, weather: str = ""):
        """Ember Lens (INNOVATION_SESSION 4.9, sensitive by design): on a day that
        matters, one quiet line — a memory you *chose to keep* (pinned), a year
        ago today. Never an ambush: only pinned memories surface, at most one, and
        a storm-state morning suppresses it. Veil-gated. Returns the card, or None.
        """
        import datetime as _dt
        import json as _json
        if not self.privacy.allow_capture() or weather == "storm":
            return None
        now = now or _dt.datetime.now(_dt.timezone.utc)
        target = now - _dt.timedelta(days=365)
        lo = (target - _dt.timedelta(days=window_days)).isoformat()
        hi = (target + _dt.timedelta(days=window_days)).isoformat()
        try:
            rows = self.db.conn.execute(
                "SELECT summary, meta FROM memories WHERE created_at BETWEEN ? AND ? "
                "ORDER BY created_at", (lo, hi)).fetchall()
        except Exception:
            return None
        for summary, meta_s in rows:
            meta = _json.loads(meta_s or "{}")
            if meta.get("pinned"):
                card = cards.saved_memory(summary)
                self.bridge.send_card(card, event="ember")
                return card
        return None

    def docent(self, query: str, client=None, synth=None):
        """Docent Lens (INNOVATION_SESSION 4.5): a venue's place-keyed knowledge
        layer. Given a caption/query and a venue's LocalRecall collection
        (``client``), retrieve the venue's *own* passages and compose a short,
        grounded answer — cited from their docs, not a hallucination, and it
        works offline because the collection synced when you arrived. Veil-gated.
        ``synth(query, passages)->str`` is optional (e.g. make_synthesizer over a
        Brain); without it, the top passages are summarized directly. Returns the
        card, or None (incognito / no venue collection / nothing found)."""
        if not self.privacy.allow_capture() or client is None or not query.strip():
            return None
        hits = client.search(query, top_k=3)
        passages = [h.get("text", "").strip() for h in hits if h.get("text")]
        if not passages:
            return None
        answer = synth(query, passages) if synth else " ".join(passages[:2])
        card = cards.scholar(mode="answer", primary=(answer or "").strip()[:96])
        self.bridge.send_card(card, event="docent")
        return card


    def greet(self, person: str, now: float | None = None):
        """Surface a dossier the moment you greet someone the ledger knows.
        Proactive, so Veil-gated. Returns the card sent, or None if unknown or
        silenced."""
        if not self.privacy.allow_capture():
            return None
        d = self.conversation.dossier(person, now)
        if not d.get("known"):
            return None
        card = cards.person_dossier(d)
        self.bridge.send_card(card, event="greet")
        return card


    def load_contact_faces(self, contacts, face_embed_fn=None) -> int:
        """Fan Contacts sync into the on-device face database. Each contact needs
        a 512-d embedding: either supplied on the record, or produced from its
        photo by `face_embed_fn(photo) -> list[float]` (the device seam). Returns
        how many faces were enrolled. Contacts without a usable face are skipped
        (they still live in the Brain's People registry)."""
        from ..social_lens.schema import ContactRecord
        n = 0
        for c in contacts or []:
            name = c.get("name")
            emb = c.get("embedding")
            if emb is None and face_embed_fn is not None and c.get("photo") is not None:
                try:
                    emb = face_embed_fn(c["photo"])
                except Exception:
                    emb = None
            if not name or not emb or len(emb) != 512:
                continue
            try:
                self.social.add_contact(ContactRecord(
                    contact_id=c.get("contact_id", name), name=name, embedding=emb,
                    company=c.get("company"), role=c.get("role"), email=c.get("email")))
                n += 1
            except Exception:
                continue
        return n


    def look_at_person(self, frame, now: float | None = None) -> dict | None:
        """Look at someone → know them. Matches the face against your own
        contacts (on-device, never a stranger lookup) and, when it's someone
        the conversation ledger also knows, follows the identity card with the
        dossier (last spoke, recurring topics, what's open). Veil-gated by
        SocialLens itself. Returns what it surfaced, or None on no match."""
        res = self.social.identify(frame)
        if res is None or res.match is None:
            return None
        name = res.match.contact.name
        # remember who you're looking at, so "remember she likes climbing"
        # right after can attach the note to them
        self._last_person = {"contact_id": res.match.contact.contact_id,
                             "name": name, "ts": self._clock()}
        identity = res.to_hud_card()
        self.bridge.send_card(identity, event="social")
        out = {"person": name, "confidence": res.match.confidence,
               "identity": identity, "dossier": None}
        d = self.conversation.dossier(name, now)
        if d.get("known"):
            dossier = cards.person_dossier(d)
            self.bridge.send_card(dossier, event="greet")
            out["dossier"] = dossier
        # the rescue: one tight cue so you never blank — how you know them,
        # when you last spoke, and the freshest thing you noted
        c = res.match.contact
        out["rescue"] = {
            "name": name,
            "relation": (c.relation or "").strip(),
            "last_seen": d.get("last_seen_ago", "") if d.get("known")
            else (f"met {c.last_met}" if c.last_met else ""),
            "note": c.latest_note(),
            "topic": (d.get("topics") or [""])[0] if d.get("known") else "",
            "debts": c.debt_lines(),
        }
        return out


    # ------------------------------------------------------------------
    # Tell
    # ------------------------------------------------------------------

    def tell_check(self, transcript: str, confidence: float = 0.80) -> dict | None:
        result = self.tell_engine.check(transcript, confidence=confidence)
        if result.fired and result.card:
            self.bridge.send_card(result.card, event="deviation_alert")
            return result.card
        return None
