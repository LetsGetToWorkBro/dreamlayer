"""ops_ember — the Ember practice on the coordinator (docs/EMBER.md).

A mixin the Orchestrator inherits; every method here runs on the shared
self, so self.embers (the EmberStore), self.bridge, self.privacy and the
clock resolve exactly like every other ops cluster.

The loop this file owns:

  place match ──▶ tick_ember ──▶ EmberPromptCard (cue only, ambient)
                     │
        wearer speaks within the window
                     │
                ember_attempt ──▶ grade ──▶ scheduler ──▶ flare / reveal
                     │                          │
              "show me" / silence          graduation ──▶ EmberGraduatedCard
                (reveal / missed)                          (offer; burn is
                                                            phone-side only)

Veil contract: prompting is *recall* of something lawfully kept, so it runs
behind allow_recall() (blocked by the full pause veil; incognito does not
silence what you already own — same rule as ask_brain). Keeping and tending
are *capture-adjacent* choices made on the phone over already-lawful events,
but the nightly staging still respects allow_capture() so a veiled evening
stages nothing.
"""
from __future__ import annotations

from ._ops_host import OpsHost

from ..ember import RecallOutcome, ceremony
from ..ember.grading import grade_recall
from ..ember.scheduler import DAY
from ..ember.tending import MAX_KEEPS_PER_DAY, TendingPass
from ..hud import cards

# A prompt holds the conversational floor this long; then walking on is a
# MISSED (rescheduled, unjudged). Matches the card's 12s dismiss plus a
# grace beat for slow, warm retellings.
ATTEMPT_WINDOW_S = 45.0

_REVEAL_PHRASES = ("show me", "tell me", "i don't remember", "i dont remember",
                   "i forgot", "i can't remember", "i cant remember",
                   "no idea", "remind me")
_LATER_PHRASES = ("not now", "later", "skip", "leave it")


class EmberOps(OpsHost):

    # ------------------------------------------------------------------
    # The glow: place-gated prompting
    # ------------------------------------------------------------------

    def tick_ember(self, now: float | None = None,
                   place_signature: str | None = None) -> dict | None:
        """Fire at most one due prompt. Called from on_place (the anchored
        path — the method of loci) and safe from any tick. Never stacks:
        while one prompt holds the floor, no second one fires."""
        if not self.privacy.allow_recall():
            return None
        now = self._clock() if now is None else now
        # never stack: a live glow keeps the floor, and an expired one is
        # resolved (MISSED, never a lapse) by the same check
        if self.ember_prompt_active(now):
            return None
        due = self.embers.due(now, place_signature=place_signature, limit=1)
        if not due:
            return None
        e = due[0]
        self._ember_active = (e.id, now)
        card = cards.ember_prompt(cue=e.cue, place=e.meta.get("place", ""),
                                  reps=e.state.reps)
        self.bridge.send_card(card, event="ember_prompt")
        return card

    def ember_prompt_active(self, now: float | None = None) -> bool:
        """Is a glow holding the floor right now? Expiry is resolved here —
        an expired prompt records its MISSED and stops claiming speech, so
        handle_voice can never swallow an ordinary utterance."""
        active = getattr(self, "_ember_active", None)
        if active is None:
            return False
        now = self._clock() if now is None else now
        if now - active[1] > ATTEMPT_WINDOW_S:
            self.embers.record_review(active[0], RecallOutcome.MISSED, now)
            self._ember_active = None
            return False
        return True

    # ------------------------------------------------------------------
    # The reach: spoken recall
    # ------------------------------------------------------------------

    def ember_attempt(self, text: str, now: float | None = None) -> dict:
        """Grade one spoken reach at the active prompt. handle_voice routes
        un-wake-worded speech here while a prompt holds the floor; explicit
        wake-word speech bypasses Ember entirely (addressing Juno always
        wins over the glow)."""
        now = self._clock() if now is None else now
        active = getattr(self, "_ember_active", None)
        if active is None or now - active[1] > ATTEMPT_WINDOW_S:
            self._ember_active = None
            return {"intent": "ember", "ok": False, "reason": "no active prompt"}
        engram_id = active[0]
        self._ember_active = None
        e = self.embers.get(engram_id)
        if e is None:
            return {"intent": "ember", "ok": False, "reason": "engram gone"}

        t = (text or "").strip().lower().rstrip("?.!")
        if any(p in t for p in _LATER_PHRASES):
            self.embers.record_review(engram_id, RecallOutcome.MISSED, now)
            return {"intent": "ember", "ok": True, "outcome": "missed"}
        if any(p in t for p in _REVEAL_PHRASES):
            return self._ember_reveal(e, now)

        outcome = grade_recall(text, e.answer,
                               similarity_fn=self._ember_similarity())
        if outcome == RecallOutcome.FORGOT:
            return self._ember_reveal(e, now)

        updated = self.embers.record_review(engram_id, outcome, now)
        assert updated is not None      # engram_id was just fetched non-None above
        next_days = max(0.0, (updated.state.due_ts - now) / DAY)
        self.bridge.send_card(
            cards.ember_flare(cue=e.cue, reps=updated.state.reps,
                              next_days=next_days),
            event="ember_flare")
        result = {"intent": "ember", "ok": True, "outcome": outcome.name.lower(),
                  "reps": updated.state.reps,
                  "graduated": updated.state.graduated}
        if updated.state.graduated and not e.state.graduated:
            kept_days = int((now - e.kept_at) / DAY)
            self.bridge.send_card(
                cards.ember_graduated(cue=e.cue, kept_days=kept_days,
                                      reps=updated.state.reps),
                event="ember_graduated")
            result["offer"] = True   # the phone presents the burn, never here
        return result

    def _ember_reveal(self, e, now: float) -> dict:
        """The gentle answer: an honest FORGOT on the curve, the answer on
        the glass — the only surface that ever renders it."""
        updated = self.embers.record_review(e.id, RecallOutcome.FORGOT, now)
        self.bridge.send_card(cards.ember_reveal(cue=e.cue, answer=e.answer),
                              event="ember_reveal")
        return {"intent": "ember", "ok": True, "outcome": "forgot",
                "reps": updated.state.reps if updated else e.state.reps}

    def _ember_similarity(self):
        """Optional semantic upgrade for grading: cosine over the embedder
        ladder when a real embedder is up; None keeps grading purely
        lexical (offline default). Failures degrade to lexical silently —
        recorded on the health ledger by the embedder itself."""
        embedder = getattr(self, "embedder", None)
        if embedder is None:
            return None

        def sim(spoken: str, answer: str) -> float:
            va, vb = embedder.embed(spoken), embedder.embed(answer)
            if not va or not vb:
                return 0.0
            dot = sum(a * b for a, b in zip(va, vb))
            na = sum(a * a for a in va) ** 0.5
            nb = sum(b * b for b in vb) ** 0.5
            return dot / (na * nb) if na and nb else 0.0
        return sim

    # ------------------------------------------------------------------
    # The ritual: morning tending
    # ------------------------------------------------------------------

    def morning_tending(self, reel=None, now: float | None = None) -> list:
        """Stage the day's offers (runs inside maybe_dream_tonight, before
        the retention sweep purges the hot ring). Veil-gated as capture:
        a veiled evening stages nothing."""
        if not self.privacy.allow_capture():
            return []
        tending = TendingPass(self.embers, privacy=self.privacy,
                              now_fn=self._clock)
        return tending.run(self.ring, reel=reel, now=now)

    def tending_candidates(self) -> list:
        return self.embers.candidates()

    def tend_keep(self, candidate_id: int, now: float | None = None) -> dict | None:
        """The wearer cups their hands around one offer. At most
        MAX_KEEPS_PER_DAY keeps stand per night's staging — tending is a
        ritual, not an inbox."""
        now = self._clock() if now is None else now
        kept_today = sum(1 for e in self.embers.engrams()
                         if now - e.kept_at < DAY)
        if kept_today >= MAX_KEEPS_PER_DAY:
            return None
        c = self.embers.resolve_candidate(candidate_id, kept=True)
        if c is None:
            return None
        from ..rem.bias import event_key
        e = self.embers.keep(
            event_key(c.kind, c.summary), c.cue, c.summary, now,
            place_signature=c.place_signature,
            source_memory_id=c.source_memory_id,
            meta={"kind": c.kind})
        return e.to_row()

    def tend_let_go(self, candidate_id: int) -> bool:
        return self.embers.resolve_candidate(candidate_id, kept=False) is not None

    # ------------------------------------------------------------------
    # The ceremony: graduation and the burn
    # ------------------------------------------------------------------

    def ember_offers(self) -> list[dict]:
        """Graduated engrams whose recordings still exist — the standing
        offers the phone presents."""
        return [e.to_row() for e in ceremony.offers(self.embers)]

    def burn_ember(self, engram_id: int, consent: bool = False,
                   now: float | None = None) -> dict:
        """One burn, explicit consent only. Purges the source memory
        ANN-safely through the Retriever and plants the cue-only tombstone
        the anniversary Ember lens resurfaces a year on."""
        now = self._clock() if now is None else now
        receipt = ceremony.burn(self.embers, engram_id, consent=consent,
                                now=now, retriever=self.retriever, db=self.db)
        return {"engram_id": receipt.engram_id, "cue": receipt.cue,
                "burned_at": receipt.burned_at,
                "purged_memory_id": receipt.purged_memory_id,
                "tombstone_memory_id": receipt.tombstone_memory_id,
                "reps": receipt.reps}

    def ember_status(self, now: float | None = None) -> dict:
        now = self._clock() if now is None else now
        return self.embers.status(now)
