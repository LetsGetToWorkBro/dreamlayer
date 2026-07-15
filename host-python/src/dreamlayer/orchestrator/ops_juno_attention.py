"""ops_juno_attention — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ._ops_host import OpsHost

from ..hud import cards
from ._ops_helpers import _default_http_get
from ._ops_helpers import _default_http_post


class JunoAttentionOps(OpsHost):

    def set_anticipation(self, on: bool = True) -> None:
        self.anticipation_on = on


    def set_cue(self, kind: str, on: bool = True) -> None:
        """Toggle one proactive-cue kind (event / person / place) — the app's
        cue picker. Off kinds simply don't surface."""
        self.anticipation.set_kind(kind, on)


    def cue_kinds(self) -> dict:
        """Which cue kinds are on right now (for the app's picker state)."""
        return {k: (k in self.anticipation.enabled_kinds)
                for k in self.anticipation.KINDS}


    # -- Juno: wake word + multimodal activation + listening feedback --

    def set_wake_source(self, source: str, on: bool = True) -> None:
        """Enable/disable a way to wake Juno (voice / tap / gaze / raise)."""
        if on:
            self.wake_sources.add(source)
        else:
            self.wake_sources.discard(source)


    def set_wake_feedback(self, kind: str, on: bool = True) -> None:
        """Toggle a listening cue (visual ring / audio earcon / haptic tick)."""
        if kind in self.wake_feedback:
            self.wake_feedback[kind] = on


    def juno_listening(self, now: float | None = None) -> bool:
        import time
        return (now if now is not None else time.time()) < self.juno_until


    def begin_listening(self, source: str = "voice", now: float | None = None):
        """Open Juno's listening session and show the reassurance cue — a
        Listening ring plus (device seams) an earcon and a haptic tick, per the
        wake_feedback toggles. Returns the card."""
        import time
        now = now if now is not None else time.time()
        self.juno_until = now + self.juno_session_s
        fb = self.wake_feedback
        card = cards.listening(source, earcon=fb["audio"], haptic=fb["haptic"])
        if fb["visual"]:
            self.bridge.send_card(card, event="listening")
        return card


    def end_listening(self) -> None:
        self.juno_until = 0.0


    def juno_greeting(self) -> str:
        """Juno's greeting, adapted to what it's learned — by name once it
        knows it. Warms on wake / first line of a session."""
        from . import persona
        return persona.greeting(self.user.address())


    def user_snapshot(self, n: int = 5) -> dict:
        """What the Juno has learned about you — name, the topics you return
        to, who you talk with most, and what you've told it to remember. For the
        phone's profile screen; a read, never a write."""
        return self.user.snapshot(n).to_dict()


    def social_people(self) -> list:
        """Everyone you've met, as the phone's People screen reads them: how you
        know them, when you last saw/spoke, your notes, and any open debts.
        On-device; a read of your own social memory."""
        out = []
        for c in self.social.people():
            d = self.conversation.dossier(c.name)
            out.append({
                "contact_id": c.contact_id,
                "name": c.name,
                "relation": c.relation or "",
                "company": c.company or "",
                "role": c.role or "",
                "last_met": c.last_met or "",
                "last_seen": d.get("last_seen_ago", "") if d.get("known") else "",
                "notes": [s.strip() for s in (c.notes or "").split(" • ") if s.strip()],
                "debts": c.debt_lines(),
                "topics": d.get("topics", []) if d.get("known") else [],
            })
        out.sort(key=lambda p: p["name"].lower())
        return out


    def publish_people(self, http_post=None) -> dict | None:
        """Push your social memory to the paired Brain (POST
        /dreamlayer/social/people) so the phone's People screen can read it —
        the same hub->Brain bridge the profile uses. Best-effort, Veil-gated."""
        if not self.privacy.allow_capture() or not self.brain_url:
            return None
        post = http_post or _default_http_post
        try:
            return post(self.brain_url.rstrip("/") + "/dreamlayer/social/people",
                        {"people": self.social_people()}, self.brain_token)
        except Exception:
            return None


    def publish_profile(self, http_post=None) -> dict | None:
        """Push the Juno profile to the paired Mac mini Brain (POST
        /dreamlayer/profile) so the phone can read it — the hub->Brain bridge.
        Best-effort and Veil-gated; silent with no Mac mini. `http_post` defaults
        to urllib."""
        if not self.privacy.allow_capture() or not self.brain_url:
            return None
        post = http_post or _default_http_post
        try:
            out = post(self.brain_url.rstrip("/") + "/dreamlayer/profile",
                       self.user_snapshot(), self.brain_token)
            self._profile_dirty = 0
            return out
        except Exception:
            return None


    def _maybe_publish_profile(self) -> None:
        """Debounced push: sync the profile once enough has changed, so a chatty
        day doesn't hammer the Brain. Explicit teaches push immediately."""
        self._profile_dirty += 1
        if self._profile_dirty >= 10:
            self.publish_profile()


    def activate(self, source: str, now: float | None = None):
        """Wake Juno without a phrase — a tap, a gaze/dwell, or a raise-to-
        speak gesture (the device seam decides which). Enters listening if that
        source is enabled; returns the Listening card or None."""
        if source not in self.wake_sources:
            return None
        return self.begin_listening(source, now)


    def hear(self, text: str, now: float | None = None) -> dict:
        """The wake pipeline for a transcribed line (ASR is the device seam).

          • opens with "Hey Juno" → wake, then run the command if one follows;
          • Juno already listening (session window) → treat as a follow-up,
            no wake word needed (continuous-conversation mode);
          • otherwise → idle (Juno wasn't addressed).
        Each command extends the session so a back-and-forth flows."""
        import time
        from .voice import detect_wake
        now = now if now is not None else time.time()
        heard, remainder = detect_wake(text)
        if heard:
            if "voice" not in self.wake_sources:
                return {"intent": "idle"}
            self.begin_listening("voice", now)
            if remainder:
                self.juno_until = now + self.juno_session_s
                return self.ask_juno(remainder)
            return {"intent": "listening"}
        if self.juno_listening(now):
            self.juno_until = now + self.juno_session_s     # follow-up extends
            return self.ask_juno(text)
        return {"intent": "idle"}


    # -- focus mode: a stretch with the interruptions turned down --------
    # Distinct from Incognito (which pauses *capture*): focus keeps capturing
    # and answering you, but holds back the unasked stuff — anticipatory cards,
    # live captions, and message pop-ups — for a set number of minutes.

    def set_focus(self, minutes: float = 25.0) -> float:
        import time
        self.focus_until = time.time() + max(0.0, minutes) * 60.0
        return self.focus_until


    def clear_focus(self) -> None:
        self.focus_until = 0.0


    def focus_active(self, now: float | None = None) -> bool:
        import time
        return (now if now is not None else time.time()) < getattr(self, "focus_until", 0.0)


    def anticipate_tick(self, context) -> list:
        """Surface the right anticipatory cards for this moment. Silenced by
        the Privacy Veil and by Focus mode; the engine itself de-dupes so
        nothing nags. Returns the cues it flashed."""
        if (not self.anticipation_on or not self.privacy.allow_capture()
                or self.focus_active()):
            return []
        cues = [c for c in self.anticipation.tick(context)
                if self.maturity.allows_proactive(kind=c.kind)]
        for c in cues:
            self.bridge.send_card(c.card, event="anticipate")
        return cues


    def wake(self, http_get=None) -> dict | None:
        """Put the Halo on → the day's brief is waiting. Fetches the brief the
        Brain's scheduler last delivered (GET /dreamlayer/brief/latest on the
        paired Mac mini) and flashes it. As of the figment-migration this rides a
        budget-proven *figment* instead of a MorningBriefCard: the brief owns the
        stage, its synthesis + first points stream into named slots, and it
        clears itself after its window (no per-card renderer twin — the
        whitelisted stage draws it). Veil-gated; silent without a brief or Mac
        mini. Returns what was fed, or None. `http_get` defaults to urllib."""
        if not self.privacy.allow_capture() or not self.brain_url:
            return None
        get = http_get or _default_http_get
        try:
            latest = get(self.brain_url.rstrip("/") + "/dreamlayer/brief/latest",
                         self.brain_token)
        except Exception:
            return None
        if not latest or not latest.get("ts"):
            return None
        return self._brief_to_figment(latest)

    def _brief_to_figment(self, latest: dict) -> dict:
        """Put the morning-brief figment on stage and stream the day's synthesis
        and first two points into its named slots."""
        from ..reality_compiler.v2 import native, transport
        fig = native.morning_brief_figment()
        self.bridge.send_raw(transport.put_envelope(fig))
        self.bridge.send_raw(transport.swap_envelope(fig.id))
        self._active_figment = fig.id
        synthesis = str(latest.get("text") or "A clear morning.")
        points = [str(b) for b in (latest.get("bullets") or []) if b][:2]
        for slot, val in (("synthesis", synthesis),
                          ("point1", points[0] if points else ""),
                          ("point2", points[1] if len(points) > 1 else "")):
            self.bridge.send_raw(transport.text_envelope(fig.id, val, slot=slot))
        return {"figment_id": fig.id, "synthesis": synthesis, "points": points,
                "surface": "figment"}


    def hark(self, clue: str, detail: str = "", importance: str = "normal",
             now: float | None = None, cooldown_s: float = 120.0):
        """Juno's "Listen!" — a proactive tap on the shoulder with one thing
        worth hearing (a clue, a heads-up). Rate-limited so it never nags:
        nothing fires within `cooldown_s` of the last hark. Silenced by the
        Privacy Veil; a *normal* hark also holds during Focus, but an *urgent*
        one pierces it. Returns the card sent, or None if hushed."""
        import time
        now = now if now is not None else time.time()
        if not self.privacy.allow_capture():
            return None
        if importance != "urgent" and self.focus_active():
            return None
        if now - getattr(self, "_last_hark", -1e9) < cooldown_s:
            return None
        self._last_hark = now
        card = cards.hark(clue, detail, importance)
        self.bridge.send_card(card, event="hark")
        return card


    def set_attention(self, on: bool = True) -> None:
        self.attention_on = on


    # -- the proactive heartbeat -----------------------------------------

    def pulse(self, context, commitments=None) -> dict:
        """One proactive heartbeat over the current moment: surface anticipation
        cards *and* decide whether Juno should speak up ("Listen!"/"Watch
        out!"). The device seam assembles the `Context` from live signals (where
        you are, who's in view, calendar, anchors, commitments); start_pulse()
        drives this on an interval. Returns what fired."""
        cues = self.anticipate_tick(context)
        alert = self.attention_tick(context, commitments)
        return {"cues": cues, "alert": alert}


    def start_pulse(self, context_fn, interval: float = 15.0):
        """Run the proactive heartbeat every `interval` seconds. `context_fn()`
        is the device seam — it returns a fresh Context from live sensors each
        tick (or None to skip). Idempotent; safe to call once at startup."""
        import threading
        if self._tick_stop is not None:
            return
        stop = threading.Event()
        self._tick_stop = stop

        def loop():
            while not stop.wait(interval):
                try:
                    ctx = context_fn()
                    if ctx is not None:
                        self.pulse(ctx)
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()


    def stop_pulse(self) -> None:
        if self._tick_stop is not None:
            self._tick_stop.set()
            self._tick_stop = None


    def attention_tick(self, context, commitments=None):
        """Decide whether this moment deserves a spoken "Listen!" / "Watch out!"
        Runs the attention policy over live context and harks the single most
        important fresh alert (watch-outs first). Returns the card it spoke, or
        None. Never nags: each alert is remembered so it won't repeat, and
        hark() paces + Veil/Focus-gates the rest."""
        if not self.attention_on:
            return None
        import time
        now = getattr(context, "now", None)
        now = now if now is not None else time.time()
        # audible interruptions are the LAST privilege the system earns
        if not self.maturity.allows_hark(now):
            return None
        for a in self.attention.evaluate(context, commitments):
            importance = "urgent" if a.level == "watchout" else "normal"
            card = self.hark(a.clue, a.detail, importance, now=now)
            if card is not None:                 # hark actually spoke (passed gates)
                self.attention.mark(a.key, now)
                return card
        return None
