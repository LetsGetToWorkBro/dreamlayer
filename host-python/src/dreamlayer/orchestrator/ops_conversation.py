"""ops_conversation — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ._ops_host import OpsHost

from ..hud import cards


class ConversationOps(OpsHost):

    # -- conversation ledger: captions, recall, rewind, dossier ----------

    def set_captions(self, on: bool = True) -> None:
        self.captions_on = on


    def ingest_caption(self, text: str, speaker: str = "",
                       ts: float | None = None, show: bool = True):
        """Record one transcribed line (device seam) and, unless captions are
        off, flash it on the glasses. Veil-gated: nothing is kept or shown while
        capture is paused / incognito. Returns the stored Utterance or None."""
        if not self.privacy.allow_capture():
            return None
        u = self.conversation.add(text, speaker, ts)
        if (u is not None and show and self.captions_on
                and not self.focus_active()):
            self.bridge.send_card(
                cards.spoken_caption(u.speaker, u.text), event="caption")
        # a promise you just made becomes a tracked commitment — feeds the
        # dossier, anticipation, and the quest/drift engine.
        if u is not None and u.is_mine():
            self._capture_commitment(u)
        # the Juno quietly learns you: your own words shape your interests;
        # whoever you're talking to is someone you talk with.
        if u is not None:
            if u.is_mine():
                self.user.observe(u.text)
            else:
                self.user.note_person(u.speaker)
            self._maybe_publish_profile()
        # Truth Lens: read *how* it was said (delivery) for whoever's speaking,
        # and feed it to Discernment before the fact-check runs. Opt-in.
        if (u is not None and self.truthlens_on and not u.is_mine()
                and not self.focus_active()):
            self._read_delivery(u)
        # Veritas: fact-check the line as it lands — self-contradiction (from the
        # ledger) and a world check (Brain/cloud seam). Opt-in; held during Focus.
        if u is not None and self.factcheck_on and not self.focus_active():
            self._fact_check(u)
        # Answer-ahead: if someone *else* just asked a question, pre-fetch the
        # answer so you can say it yourself. Opt-in; held during Focus.
        if (u is not None and self.copilot_on and not u.is_mine()
                and not self.focus_active()):
            self._answer_ahead(u)
        return u


    def set_copilot(self, on: bool = True) -> None:
        """Turn the answer-ahead copilot on or off."""
        self.copilot_on = on


    def _answer_ahead(self, utterance) -> None:
        prompt = self.answer_ahead.consider(utterance.text, utterance.speaker,
                                             now=utterance.ts)
        if prompt.fired and prompt.card is not None:
            self.bridge.send_card(prompt.card, event="answer_ahead")


    def _answer_question(self, question: str):
        """Answer-ahead seam: ask your knowledge tier for the answer to an
        overheard question. Same path as the Juno's own asks (Brain, cloud when
        opted in); returns None offline / on a miss, so nothing is surfaced. A
        retrieval-ranked answerer can drop in behind this shape."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        try:
            ans = self.brain.ask(question)
        except Exception:
            ans = None
        if ans is None or ans.is_empty():
            return None
        return {"text": ans.text, "confidence": float(getattr(ans, "confidence", 0.0) or 0.0),
                "source": getattr(ans, "tier", "") or (ans.sources[0] if ans.sources else "")}


    def set_factcheck(self, on: bool = True) -> None:
        """Turn the live fact-checker (Veritas) on or off."""
        self.factcheck_on = on


    def note_credibility(self, speaker: str, vector) -> None:
        """Hand in the current delivery read (a CredibilityVector) for whoever's
        speaking, so Discernment can fuse *how* they said it with *what* they
        said. Called by the live Truth Lens wiring, or directly by a device."""
        self._credibility[(speaker or "").strip().lower()] = vector


    def set_truthlens(self, on: bool = True) -> None:
        """Turn the live delivery read (Truth Lens → Discernment) on or off."""
        self.truthlens_on = on


    def observe_face(self, frame) -> None:
        """Device seam: hand the Truth Lens a camera frame of the person you're
        with (drives the micro-expression / AU channel + face-match). No-op
        unless the delivery read is on and capture is allowed."""
        if self.truthlens_on and self.privacy.allow_capture():
            self.truth.feed_frame(frame)


    def observe_voice(self, mic_fft, amplitude) -> None:
        """Device seam: hand the Truth Lens a mic FFT window + amplitude (drives
        the voice-stress / prosody channel)."""
        if self.truthlens_on and self.privacy.allow_capture():
            self.truth.feed_audio(mic_fft, amplitude)


    def _read_delivery(self, utterance) -> None:
        """Run the Truth Lens for the current speaker: the linguistic channel
        from this line (real) plus whatever face/voice the device has fed, fused
        against the speaker's baseline → a CredibilityVector into Discernment."""
        who = (utterance.speaker or "").strip()
        self.truth.set_contact(who.lower() or None, who or None)
        self.truth.feed_transcript(utterance.text)
        vector = self.truth.assess()          # ungated: we want reassuring reads too
        if vector is not None:
            self.note_credibility(who, vector)


    def _fact_check(self, utterance) -> None:
        prior = [x.text for x in self.conversation.by_speaker(utterance.speaker)
                 if x is not utterance]
        # Fast half, on this thread: the self-contradiction pass is offline and
        # instant. Skip the world check here (world=False) so the caption
        # pipeline never blocks on the network.
        res = self.veritas.check(utterance.text, utterance.speaker,
                                 prior=prior, now=utterance.ts, world=False)
        if res.fired and res.card is not None:
            self._deliver_fact_check(res, utterance)
            return
        # Slow half, off-path: schedule the world check. It resolves from cache
        # instantly when the claim's been seen, else on a background worker with
        # a hard deadline, and only delivers a verdict worth surfacing.
        if self.veritas.checkable(utterance.text, utterance.speaker):
            self._schedule_world_check(utterance)


    def _schedule_world_check(self, utterance) -> None:
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return
        text, speaker, ts = utterance.text, utterance.speaker, utterance.ts

        def deliver(verdict: dict) -> None:
            # Re-check the gate at delivery time: the veil may have dropped, or
            # Focus started, in the seconds the ask took.
            if not self.factcheck_on or self.focus_active():
                return
            if not self.privacy.allow_capture():
                return
            res = self.veritas.world_result(text, speaker, verdict, now=ts)
            if res.fired and res.card is not None:
                self._deliver_fact_check(res, utterance)

        self.world_check.check_async(text, self.brain.ask, deliver)


    def _deliver_fact_check(self, res, utterance) -> None:
        # Discernment: fuse the content verdict with the current delivery read
        # (Truth Lens, if a recent one exists) and the pattern of prior flags.
        from .discernment import discern
        who = (utterance.speaker or "").strip().lower()
        cred = self._credibility.get(who)
        history = self._speaker_flags.get(who, 0)
        d = discern(res, credibility=cred, history=history)
        self._speaker_flags[who] = history + 1
        card = res.card
        if d.corroboration:                    # re-render the footer with the fused tag
            card = cards.fact_check(verdict=res.verdict, speaker=utterance.speaker or "them",
                                    claim=res.claim, basis=res.basis, detail=res.detail,
                                    corroboration=d.corroboration)
        card["stance"] = d.stance
        card["headline"] = d.headline
        self.bridge.send_card(card, event="fact_check")


    def _verify_claim(self, claim: str):
        """World-check: hand a checkable claim to your knowledge tiers and read
        back a verdict. Routes through the brain router's `ask` — your local
        model first, the cloud tier only if you've opted in (and never while
        incognito, which forces cloud off) — so a world fact can often be checked
        offline, and nothing leaves your devices unless you've allowed it.
        Returns None when no tier can answer, so Veritas falls back to its
        offline self-contradiction pass alone."""
        if not self.privacy.allow_capture() or not getattr(self, "brain", None):
            return None
        from ..ai_brain.verify import verify_claim
        try:
            return verify_claim(claim, self.brain.ask)
        except Exception:
            return None


    def _capture_commitment(self, utterance) -> None:
        from .conversation import parse_commitment
        parsed = parse_commitment(utterance.text)
        if not parsed:
            return
        person = self.conversation.last_other_speaker() or "someone"
        # Only tell the wearer a promise was kept if it actually landed. This
        # path runs off the capture daemon thread; a write that fails there
        # (or anywhere) must surface on the health ledger, never a card that
        # says "captured" over an empty database.
        try:
            self.db.add_commitment(person, parsed["task"], parsed.get("due") or None,
                                   None, 0.7)
        except Exception as exc:
            self.health.record_failure("capture:commitment", exc)
            return
        if not self.focus_active():
            self.bridge.send_card(
                cards.commitment_recall({"person": person, "task": parsed["task"],
                                         "due": parsed.get("due", ""), "confidence": 0.7}),
                event="commitment_captured")


    def live_captions(self, n: int = 6) -> list:
        """The last few utterances, oldest→newest, for the caption strip."""
        return self.conversation.captions(n)


    def recall_conversation(self, topic: str, person: str | None = None,
                            limit: int = 8) -> list:
        """'What did they say about X?' — user-initiated recall. Allowed while
        incognito (reading, not keeping), but the full pause veil is deaf and
        blind, so even an explicit query is held until you lift it."""
        if not self.privacy.allow_recall():
            return []
        return self.conversation.recall(topic, person, limit)


    def rewind_day(self, now: float | None = None) -> list:
        """A digest of today's conversation, grouped into hour blocks.
        Recall-gated: held while the full pause veil is down."""
        if not self.privacy.allow_recall():
            return []
        import time
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
        return self.conversation.timeline(day_start, day_start + 86400)
