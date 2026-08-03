"""The always-on ear — minimal, consent-gated speech capture that funnels what a
microphone hears into the Brain's own memory.

Why this exists: the full Orchestrator (orchestrator/orchestrator.py) has always
carried a complete capture stack — a VAD gate, an ASR ladder (Moonshine → faster-
whisper), a sound-event tagger and a bird lens — but the shipped Brain never
instantiated an Orchestrator, so that entire "ear" was dead code from the user's
seat: the voice capabilities installed, lit green on import, and did nothing you
could turn on. This module wires the ear into the Brain WITHOUT dragging in the
whole Orchestrator (which brings a second MemoryDB and a heavy reasoning graph).
It reuses the proven CapturePipeline, giving it a tiny host that satisfies the
pipeline's contract (`hear` + `ingest_caption`) and writes straight into the
Brain's index.

Consent + privacy, by construction:
  * OFF by default. Nothing is captured until the wearer flips `listen_enabled`
    on (the panel's "Listening" switch, with a plain-language explanation).
  * The Veil wins. While incognito / quiet-hours the Brain "logs nothing", so a
    captured utterance is dropped, never stored.
  * PII is scrubbed before any write (contact/financial identifiers only — never
    the names and places the product exists to remember).
  * Nothing is uploaded. Transcription is on-device; only the text lands in the
    local index.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("dreamlayer.ear")

# The capabilities this minimal ear genuinely drives. While the ear is running,
# the Brain sets DL_WIRED_<KEY> for each so capabilities.state() reports them
# "active" (installed → really on); when the ear stops they revert to "dormant".
# We deliberately do NOT claim the caps this minimal ear does not exercise —
# asr_alignment stays dormant until the full Orchestrator path is wired, so the
# meter never over-reports.
#
# `wake_word` IS here now, and like `live_interpret` it is NOT put in
# `active_caps` at start(): that set is fixed when the microphone opens, and
# what promotes this is the spotter having genuinely FIRED, which can only
# happen later. `_sync_ear_wired` asks `wake_live()` fresh on every sync for
# exactly that reason. An engine that loaded is not an engine that heard you.
#
# `live_interpret` IS here now, and it is promoted on a stricter test than the
# others: not "the wheel is installed", not even "an interpreter object exists",
# but "a segment has actually come back translated" (`_interpret_ok`). That is the
# `tagger_live` lesson applied — `SoundEventDetector` reported live off a present
# wheel with no model loaded, so `detect()` could only ever return nothing. The
# SeamlessM4T model is a multi-gigabyte lazy load that can fail long after the
# wheel imports, so nothing short of a real translated line proves it runs.
EAR_CAPS = ("voice_vad", "local_asr", "mic_capture", "asr_moonshine",
            "onnx_speech", "sound_events", "bird_song", "live_interpret",
            "wake_word")


class _EarGate:
    """The privacy gate the CapturePipeline reads at its door (push_pcm →
    _veiled → orch.privacy.allow_capture). Mirrors WorldLensHost._LookGate:
    allow_capture() is False while the Brain is incognito / in quiet hours, so a
    veiled stretch accumulates NO audio at all — not even in the ring. Fails
    CLOSED (returns False) when the posture can't be read, so an unreadable trust
    signal veils rather than opens the mic. WITHOUT this attribute the pipeline's
    _veiled() raises AttributeError and (fail-closed) drops every window, so the
    ear would open the mic yet capture nothing — this gate is load-bearing."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                        # noqa: BLE001 — unreadable → veiled
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class EarHost:
    """Drives a CapturePipeline over a microphone and remembers what it hears.

    Implements the CapturePipeline host contract: `hear(text)` (wake/command —
    a no-op here, since the minimal ear has no wake engine) and
    `ingest_caption(text, speaker)` (the conversation ledger → the Brain's index).
    """

    def __init__(self, brain):
        self.brain = brain
        # The CapturePipeline reads self.privacy at its door on every window —
        # this MUST exist or _veiled() fails closed and the ear captures nothing.
        self.privacy = _EarGate(brain)
        self._pipe = None
        self._lock = threading.RLock()
        self._bird = None
        self._bird_built = False
        # None = not tried, False = tried and unavailable, else the diarizer.
        self._diar: object = None
        self._last_answer_ts = 0.0
        self._last_wake_ts = 0.0
        #: Utterances the wake path actually answered — either signal. Distinct
        #: from `wake_live()`, which counts only the ACOUSTIC spotter.
        self.wake_answers = 0
        self._wake = None
        self._wake_built = False
        self.last_heard = ""
        self.heard_count = 0
        self.active_caps = frozenset()          # the caps THIS run genuinely drives
        # -- live interpreter state. `_interpret_ok` is the honesty bit: it flips
        # once a segment has genuinely come back translated, and it is what
        # promotes the capability. Never reset by a toggle — that a model DID load
        # and translate on this process stays true when you switch the feature off
        # and on, and re-proving it would need another utterance.
        self._interpret_on = False
        self._interpret_target = "en"
        self._interpret_ok = False
        self.interpreted_count = 0
        # -- "Read the room": the credibility read over this ear's conversation.
        # Per-ear, because the Mac's mic and the phone streaming in are two
        # different rooms and TruthLens carries rolling per-conversation state.
        # Constructed eagerly (it is a few attributes; the nine-stage lens inside
        # is lazy) so `set_truth` can be pushed in before the mic ever opens,
        # exactly like the interpreter's persisted setting.
        from .truth_live import TruthRead
        self.truth = TruthRead(brain)
        # -- Lexicon: a rare word the room just used, defined on the glass.
        # Constructed eagerly for the same reason `truth` is (it is a few
        # attributes; the word list and the HTTP connector inside it are both
        # lazy), so nothing here costs a Brain that never switches it on.
        from .lexicon_live import LexiconRead
        self.lexicon = LexiconRead(brain)

    # -- CapturePipeline host contract -------------------------------------

    def hear(self, text: str, addressed=None) -> None:
        """Wake / command path — "Hey Juno, …" answered on the glass.

        This was a `return`. The always-on ear transcribed everything, folded it
        into memory, and could not be TALKED TO: the one gesture the product is
        named for did nothing, and `wake_word` could not be wired because there
        was nothing for a spotter to trigger.

        TWO WAKE SIGNALS, AND THEY ARE OR'ed
        ------------------------------------
        `addressed` is the ACOUSTIC verdict — True/False from a spotter that
        ran, None when there is no spotter. `voice.detect_wake` is the text-level
        regex over what ASR produced. Either one is enough.

        Never AND. The floor rule this repo holds every optional dependency to
        says installing one must not return LESS than the fallback, and an
        acoustic spotter that could veto the regex would do exactly that — a
        quiet "hey juno" that the model scores at 0.4 and ASR transcribes
        perfectly would stop working the day the wearer installed the engine.
        The other direction is the real prize: ASR mishears the phrase
        constantly ("hey you know", "a j you know"), and the spotter listens to
        the audio, so it catches the wakes the regex loses.

        That is worth being precise about, because the capability's own gain
        text is wrong for THIS product: it says the spotter means "ASR only runs
        once addressed". Not here — the ear transcribes every segment anyway for
        the conversation ledger, so nothing is saved. What is bought is
        RELIABILITY, not latency, and claiming the latency would be describing
        an architecture we do not have.

        POSTURE
        -------
        Veil-gated: incognito means the ear neither remembers nor answers.
        Unlike `note_question` (the ambient answer-ahead path, which forces
        `no_cloud=True` because a bystander's overheard sentence chose nothing),
        this utterance was ADDRESSED to the device — the wearer's own request,
        which is precisely what their cloud configuration is configured for. So
        it takes the same posture as `/dreamlayer/voice`: the Brain's own config
        decides, and `Brain.ask` still refuses to egress while incognito.

        Only `ask`/`recall` are routed. Every other intent is a device ACTION
        (stash, focus, forget), and firing those from room audio is a far bigger
        consent question than answering one — the phone and panel own that path
        deliberately, not by omission.

        Never raises, and never logs the text: the transcript is sensitive and
        must not be interpolated into a log message (logging-discipline seam).
        """
        text = (text or "").strip()
        if not text:
            return
        try:
            from ...orchestrator.voice import parse_intent
            spoken, remainder = self._salutation(text)
            if not (spoken or addressed is True):
                return                           # nobody was talking to us
            # A spotter fired on audio the regex could not confirm, so there is
            # no phrase to strip and the whole line is the question.
            query_text = remainder if spoken else text
            if not query_text:
                return                           # the wake phrase, and nothing
            if self._veiled():                   # else — no question to answer
                return
            import time as _t
            now = _t.time()
            if now - self._last_wake_ts < self._WAKE_MIN_GAP_S:
                # A spotter stuck at fire-on-everything would otherwise repaint
                # the glass every segment. Deliberately separate from
                # `_ANSWER_MIN_GAP_S`: that one throttles UNASKED answers and is
                # long, this one only stops a runaway and is short enough that a
                # wearer asking two questions in a row gets two answers.
                return
            self._last_wake_ts = now
            self.wake_answers += 1
            it = parse_intent(query_text)
            if it.kind not in ("ask", "recall"):
                return
            ans = self.brain.ask(it.args.get("query", "") or query_text)
            from ...hud import cards
            if ans is None or ans.is_empty():
                self.brain.push_event("juno", cards.low_confidence())
                return
            self.brain.push_event("juno", cards.juno_reply(ans.text))
        except Exception as exc:                 # noqa: BLE001 — never cost the
            log.warning("[ear] wake path failed: %s",   # utterance its memory
                        type(exc).__name__)

    @staticmethod
    def _salutation(text: str):
        """`detect_wake`, but only the phrases somebody says ON PURPOSE.

        `voice.WAKE` contains bare "juno" and bare "dreamlayer", and
        `detect_wake` matches either as a leading token. That was harmless while
        `hear()` was a no-op. The moment it answers, *"Juno is a nice name for a
        dog"* becomes a question sent to `ask()` and drawn on the glass
        mid-conversation — and so does any sentence starting with the product's
        own name, which is a thing wearers of this product say.

        The bare forms stay valid on `/dreamlayer/voice`, where somebody
        deliberately opened the mic and spoke into it. The AMBIENT path needs a
        stronger signal because nobody chose to address anything, so it takes
        only the salutation forms.

        DERIVED from `WAKE` rather than duplicated: adding "hi juno" there arms
        this automatically, and adding a bare word does not — which is the exact
        asymmetry the two paths want.
        """
        from ...orchestrator.voice import WAKE
        t = (text or "").strip()
        low = t.lower()
        for w in (p for p in WAKE if " " in p):
            if low == w or low.startswith(w + " ") or low.startswith(w + ","):
                return True, t[len(w):].lstrip(" ,.!—-").strip()
        return False, t

    def _veiled(self) -> bool:
        """The Veil, fail-closed — an unreadable posture is treated as veiled."""
        try:
            return bool(self.brain.incognito_now())
        except Exception:                        # noqa: BLE001
            return True

    def wake_live(self) -> bool:
        """Whether the ACOUSTIC spotter has genuinely fired this run.

        Not "an engine loaded", and deliberately not `wake_answers` either:
        answering counts the text regex too, and that has always worked. The
        capability is the spotter, so the proof is the spotter hearing
        something.
        """
        return int(getattr(self._pipe, "wakes", 0) or 0) > 0

    def ingest_caption(self, text: str, speaker=None) -> None:
        """Fold a transcribed utterance into the Brain's memory — Veil-gated and
        PII-scrubbed. Never raises into the capture loop."""
        text = (text or "").strip()
        if not text:
            return
        # The Veil: incognito / quiet-hours means "logs nothing" — drop it.
        # FAIL CLOSED: if the posture can't be read, treat it as veiled and drop
        # the utterance rather than store it (an unreadable trust signal must
        # never resolve to "capture" — matches _LookGate on the vision path).
        try:
            veiled = bool(self.brain.incognito_now())
        except Exception:                        # noqa: BLE001 — unreadable → veiled
            veiled = True
        if veiled:
            return
        # PII scrub before any write (same narrow policy as the memory write
        # path: strip contact/financial identifiers, keep names and places).
        try:
            from ...memory.pii_presidio import default_redactor
            red = default_redactor()
            if red is not None:
                text = red.redact(text)
        except Exception:                        # noqa: BLE001
            pass
        self.last_heard = text
        self.heard_count += 1
        # …and DRAW it, when the wearer has asked for captions. `spoken_caption`
        # is a declared HUD feature ("Live captions") that no shipped Brain
        # could produce: `hud/cards.py` has built the card all along and nothing
        # reachable ever called it, so the glass stayed blank while the ear
        # heard everything — decisions/0001 at the card layer, the same shape as
        # the ObjectRecall gap.
        #
        # Three things make this safe to wire rather than merely possible:
        #   * its OWN opt-in. Remembering speech and displaying it are different
        #     exposures; `captions_enabled` defaults False, so an existing
        #     wearer who turned Listening on gets no new behaviour.
        #   * the redacted text, not the raw. This runs AFTER the PII scrub
        #     above, so the card carries what the store carries and never more.
        #   * `privacy=self.privacy` handed to the builder, which blanks both
        #     speaker and body if the gate reads shut between the check above
        #     and here — the builder fails closed on its own.
        # The text is never logged; only ever drawn (test_logging_discipline).
        try:
            if getattr(self.brain.config, "captions_enabled", False):
                from ...hud import cards
                self.brain.push_event(
                    "caption",
                    cards.spoken_caption(speaker or "", text, privacy=self.privacy),
                    veil_ok=False)
        except Exception as exc:                 # noqa: BLE001 — a card must never
            log.warning("[ear] caption push failed: %s", type(exc).__name__)
        # …and paint that voice's timbre at the rim (Dream Mode's Timbre lens).
        # Here because this is the one place a speaker LABEL exists: the reactor
        # needs to know who spoke, and nothing downstream of the caption does.
        # It reads only the label — never the transcript — and its own cooldown
        # keeps a talkative room from strobing the rim.
        try:
            from .dream_reactors import reactors
            reactors(self.brain).note_speaker(speaker or "")
        except Exception as exc:                 # noqa: BLE001 — never break capture
            log.warning("[ear] timbre push failed: %s", type(exc).__name__)
        # …and CATCH A NAME, when someone introduced themselves. Only a closed
        # grammar of self-introductions ("my name is …", "I'm …") captures
        # anything, so ordinary chatter produces nothing — and hearing a name
        # SAVES nothing: it stages an offer that expires by itself and asks.
        # Fed the redacted text like the rest of this method.
        try:
            ih = self.brain.intro()
            if ih is not None:
                ih.heard(text)
        except Exception as exc:                 # noqa: BLE001 — a name must
            log.warning("[intro] heard failed: %s", type(exc).__name__)  # never
        # …and READ THE ROOM, when the wearer has asked for that. Fed the
        # redacted text for the same reason captions are: what the gauge reasons
        # over is what the store holds, never more. `speaker` keys the
        # per-contact baseline, so the read is "unusual FOR THIS PERSON" once the
        # speaker seam has a name, and the conservative stranger path otherwise.
        try:
            self.truth.note_transcript(text, speaker or "")
        except Exception as exc:                     # noqa: BLE001 — a gauge must
            log.warning("[truth] read failed: %s", type(exc).__name__)   # never
        # …and CHECK IT, when the wearer has asked for a live fact-checker.
        #
        # "Live fact-checker" has been a switch in the phone's Settings since
        # launch — "as people talk, Juno quietly checks what's said" — and
        # `setFactCheck` wrote AsyncStorage and stopped there. The Brain grew no
        # such flag, and `LensHost.fact_check` could only ever be called by
        # someone typing a claim into a route. So the feature the copy promised
        # did not exist, and this is the line that makes it true.
        #
        # The lens is left to do its own refusing: it returns `fired: False` for
        # an unverifiable claim, an unreachable tier, or a speaker still inside
        # the cooldown, and only pushes a card when it genuinely has something.
        # Fed the redacted text like everything else here, and gated on its own
        # opt-in because it is the one lens on this path that SPENDS something
        # (a verifier pass per utterance).
        try:
            if getattr(self.brain.config, "fact_check_enabled", False):
                ls = self.brain.lenses()
                if ls is not None:
                    ls.fact_check(text)
        except Exception as exc:                     # noqa: BLE001 — a check must
            log.warning("[ear] fact check failed: %s", type(exc).__name__)  # never
        # …and DEFINE a word the room used that the wearer may not know.
        #
        # The vocabulary half of the line above: fact-check asks whether what was
        # said is TRUE, Lexicon asks what one word of it MEANS. It hangs here, on
        # the redacted text, and the ordering is the whole safety argument — this
        # is the only thing on the ear's path that egresses, and what it may send
        # is one word that survived `default_redactor()`, never the utterance.
        #
        # Its own opt-in (`lexicon_enabled`, default off) for the same reason
        # fact-check has one, only more so: this one leaves the device. The
        # module does its own refusing — the Veil, the rarity gate, the dedupe
        # set and the interruption preference are all inside `note_transcript`,
        # so there is nothing to keep in step out here.
        try:
            self.lexicon.note_transcript(text)
        except Exception as exc:                     # noqa: BLE001 — a definition
            log.warning("[lexicon] read failed: %s",  # must never cost the
                        type(exc).__name__)          # utterance its memory
        # …and ANSWER it, when the room asked a question and the Brain knows.
        self._answer_ahead(text)
        name = "heard" if not speaker else f"heard:{speaker}"
        # The room ear does NOT steer the lens, and cannot be made to safely.
        #
        # It used to call brain.note_spoken_intent() for every utterance it heard,
        # so a bystander saying "how far is that" redirected the wearer's next look.
        # The obvious guard — skip utterances attributed to someone else — is
        # still not enough, and the reason has CHANGED since it was written: back
        # then no production CapturePipeline was built with a `speaker_resolver`,
        # so `speaker` was always empty and a guard on it could never fire. The
        # speaker seam (`_voice_seam`, voice_live.py) now populates it whenever
        # the wearer has consented and a real model loaded — but only for people
        # who are ENROLLED. Everyone else in earshot still arrives unattributed,
        # which is exactly what voice_guard requires, so an empty label cannot be
        # read as "the wearer said it" and the guard would fire on the wrong half.
        #
        # The lens stays steered only from the deliberate path either way.
        #
        # The lens is steered only from the deliberate path: the wearer holding the
        # Live Lens with captions on, which POSTs its own phrase to /live/intent.
        # That is an action, not an overheard sentence. The ear still remembers
        # everything it is allowed to — that is its job — it just does not get to
        # point the camera.
        try:
            self.brain.index.add_documents([(name, text)])
        except Exception as exc:                 # noqa: BLE001
            log.warning("[ear] index ingest failed: %s", exc)
        # …and into the statement ring the lens set reads (lens_hosts.py).
        # `brain.index` is NOT a substitute for it: index.py:156 is an in-memory
        # document list rebuilt from disk, with no timestamps and no kinds, and
        # Candor / Provenance / Commitment Drift all reason over WHEN something
        # was said and WHAT kind of thing it was. Without this call the ring is
        # empty on every shipped Brain and all seven lenses answer "nothing to
        # report" forever.
        #
        # `via="heard"` is the honest value and it matters: Provenance treats
        # "said"/"saw"/"observed" as FIRSTHAND, and the room ear is not
        # firsthand — it is ambient audio in front of the wearer. Passing
        # "said" here would make the lens claim the wearer witnessed anything
        # anyone near them mentioned.
        #
        # `said_by`, NOT `person`, and the difference is a ledger. `person` is the
        # SUBJECT of an extracted event — who a promise is made TO — while
        # `said_by` is who uttered the line. `owed()` returns the wearer's own
        # commitments by excluding every row that carries `said_by`, so a speaker
        # arriving in the `person` slot leaves an overheard promise looking like
        # one the WEARER made: someone else's debt on your list. And `they_said`
        # matches on `said_by` alone, so the attribution landing in the wrong key
        # meant "what did Marcus say last time" could never answer from live
        # capture at all — the whole point of the memory-based Truth Lens.
        #
        # This was latent rather than harmless: `speaker` is empty on a shipped
        # Brain today (no CapturePipeline is built with a resolver), so the bug
        # bites the moment ANY speaker producer is wired, which is exactly the
        # next thing anyone would do here. Fixed ahead of that producer, not
        # after it.
        try:
            ls = self.brain.lenses()
            if ls is not None:
                ls.ingest_utterance(text, via="heard", said_by=speaker or "")
        except Exception as exc:                 # noqa: BLE001
            log.warning("[ear] lens ingest failed: %s", type(exc).__name__)
        # fold into the temporal knowledge graph too, when one is built
        try:
            g = self.brain._graph_recall()
            if g is not None:
                g.index(text)
        except Exception:                        # noqa: BLE001
            pass
        try:
            self.brain.activity.add("ear", "Heard and remembered an utterance")
        except Exception:                        # noqa: BLE001
            pass

    # -- the answer before you speak ---------------------------------------

    #: wh-openers that make a line a question without a "?" — ASR punctuation is
    #: unreliable and a transcript often arrives with none at all.
    _WH = ("who", "what", "when", "where", "why", "how", "which", "whose",
           "did", "do", "does", "is", "are", "was", "were", "can", "could",
           "will", "would", "should", "have", "has", "had")
    _ANSWER_MIN_CONFIDENCE = 0.35
    _ANSWER_MIN_GAP_S = 20.0
    #: Runaway guard on the ADDRESSED path, not a throttle. Long enough that a
    #: spotter firing on every segment cannot repaint the glass continuously,
    #: short enough that "Hey Juno, what did Ana say" followed immediately by
    #: "Hey Juno, and when" gets two answers — which `_ANSWER_MIN_GAP_S` at 20 s
    #: would silently eat.
    _WAKE_MIN_GAP_S = 2.0

    @classmethod
    def _is_question(cls, text: str) -> bool:
        """Is this line a question worth trying to answer?

        Deliberately narrow. Every false positive spends a memory search and
        risks a card, and the wearer cannot un-see one — so a bare "what?" or
        "really?" must not qualify. Four or more words, and either explicit
        punctuation or an interrogative opener.
        """
        t = (text or "").strip()
        words = t.lower().split()
        if len(words) < 4:
            return False
        if t.endswith("?"):
            return True
        return words[0].strip(",.").rstrip("'") in cls._WH

    def _answer_ahead(self, text: str) -> None:
        """Answer a question the room just asked, from the wearer's own memory.

        `answer_ahead`'s own docstring is "a question the room just asked you,
        with the answer already pulled from your knowledge" — it was recorded as
        blocked on "a predicted question the premonition lens does not produce",
        which was a mis-read of the title. Nothing needs predicting: the
        question arrives in the transcript.

        Four gates, and each is answering a specific objection:

          * ITS OWN OPT-IN, off by default. Remembering, drawing and ANSWERING
            what the room says are three different exposures.
          * `no_cloud=True`, unconditionally. This is the one that matters. The
            wearer typing a question chose to ask it and may egress; a bystander's
            overheard sentence chose nothing, so it must never leave the device
            whatever the cloud settings say. Not read from config — passed as a
            constant, so no configuration can turn it off.
          * A CONFIDENCE FLOOR. `ask` falls through tiers and will return a weak
            keyword-index hit for almost anything; drawing that would put a
            confident-looking wrong answer on the glass mid-conversation.
          * A RATE LIMIT. A conversation is mostly questions. Without this the
            glass would answer continuously, which is both useless and the
            fastest way to make a wearer switch the feature off.

        This is NOT the lens-steering the note above forbids, and the difference
        is worth stating rather than assuming: steering changed what the Brain
        CAPTURED, persistently, from a bystander's words. This changes only what
        the wearer momentarily sees, on their own display, with nothing stored
        and nothing sent. Same input, different blast radius.
        """
        try:
            if not getattr(self.brain.config, "answer_ahead_enabled", False):
                return
            if not self._is_question(text):
                return
            import time as _t
            now = _t.time()
            if now - float(getattr(self, "_last_answer_ts", 0.0)) < self._ANSWER_MIN_GAP_S:
                return
            ans = self.brain.ask(text, no_cloud=True)
            if ans is None or ans.is_empty():
                return
            if float(getattr(ans, "confidence", 0.0) or 0.0) < self._ANSWER_MIN_CONFIDENCE:
                return
            self._last_answer_ts = now
            from ...hud import cards
            self.brain.push_event("answer_ahead", cards.answer_ahead(
                question=text, answer=ans.text,
                speaker="",                      # never attributed: see above
                source=getattr(ans, "tier", "") or ""), veil_ok=False)
        except Exception as exc:                 # noqa: BLE001 — never cost the
            log.warning("[ear] answer-ahead failed: %s",   # utterance its memory
                        type(exc).__name__)

    def note_acoustic_context(self, tags) -> None:
        """World-sound hook (CapturePipeline calls it with the tagger's tags): a
        smoke alarm, glass breaking, a siren, a doorbell, your kettle. Surface the
        single most important one as a HarkCard pushed to the Live Lens — the
        safety/attention tap the glasses give you. Categorical only: a sound TYPE,
        never a voiceprint or any captured content, so a watch-out (smoke alarm)
        pierces the veil while a mere 'listen' (kettle) stays quiet under it.
        Best-effort; a hub without the sound-events pack simply gets no tags."""
        if not tags:
            return
        try:
            from ...orchestrator.sound_events import attention_for
            alert = attention_for(tags)
        except Exception:                            # noqa: BLE001
            return
        if alert is None:
            return
        try:
            from ...hud import cards
            urgent = getattr(alert, "level", "") == "watchout"
            card = cards.hark(
                clue=getattr(alert, "clue", "") or "There's something here.",
                detail=getattr(alert, "detail", "") or "heard nearby",
                importance="urgent" if urgent else "normal")
            # a watch-out (smoke alarm/glass/siren) is safety — it pierces the
            # veil (veil_ok); a 'listen' is suppressed under the shield.
            self.brain.push_event("hark", card, veil_ok=urgent)
        except Exception:                            # noqa: BLE001
            return

    def _diarizer(self):
        """The streaming diarizer, or None when diart is not installed.

        Built once and held for the life of the pipeline: diart clusters
        WITHIN a stream, so a fresh one per segment would restart the labels
        every utterance and `spk0` would mean a different person each time.
        """
        if self._diar is None:
            try:
                from ...social_lens.diarize_diart import DiartDiarizer
                d = DiartDiarizer()
                # The fallback answers one speaker for everything, which the
                # capture path already treats as "unattributed" — holding it
                # would be a seam that can only ever return its own null.
                self._diar = d if getattr(d, "_pipeline", None) is not None \
                    else False
            except Exception as exc:             # noqa: BLE001
                log.info("[ear] diarization unavailable: %s",
                         type(exc).__name__)
                self._diar = False
        return self._diar or None

    def _wake_engine(self):
        """The acoustic wake spotter, or None when openWakeWord is absent.

        Built once and held: the model is a few MB of ONNX and it carries
        rolling state across calls, so a fresh one per segment would both cost
        a load per utterance and reset whatever context it uses to score.

        A spotter whose model failed to load is NOT held. `OpenWakeWordEngine`
        keeps `available` True (the wheel imported) with `_model` None after a
        load failure, and `detect` then returns `(False, 0.0)` forever — a seam
        that can only ever return its own null. Handing that to the pipeline
        would turn `addressed` from None ("no engine, trust the regex") into
        False ("an engine listened and heard nothing") on every single segment,
        which is the same information but a strictly worse-sounding one, and it
        would make `wake_live()` permanently false while the report insisted the
        capability was installed. Same test `_diarizer` applies for the same
        reason.
        """
        if not self._wake_built:
            self._wake_built = True
            try:
                from ...orchestrator.wakeword import OpenWakeWordEngine
                e = OpenWakeWordEngine()
                self._wake = e if getattr(e, "_model", None) is not None else None
            except Exception as exc:             # noqa: BLE001
                log.info("[ear] wake spotter unavailable: %s",
                         type(exc).__name__)
                self._wake = None
            if self._wake is None:
                # The sherpa keyword spotter, when a model directory supplies
                # one. Second rung by the same rule as the others — but note
                # this is the one place the ORDER is arguably wrong on licence
                # grounds rather than technical ones: sherpa-onnx is Apache-2.0
                # and openWakeWord is non-commercial. Whoever ships this may
                # want them the other way round; that is not a decision to make
                # silently here, so the note is the flag.
                self._wake = self._sherpa().wake()
        return self._wake

    def _sherpa(self):
        """The Brain's unified ONNX engine — the last rung under every seam."""
        from .sherpa_live import stack
        return stack(self.brain)

    def _voice_seam(self):
        """(embedder, resolver, enrolled_names) for the CapturePipeline, or
        (None, None, None) when voice recall is off, unconsented, or has no
        model.

        All three are returned together on purpose. A pipeline given an embedder
        but no resolver computes a biometric of everyone in earshot and does
        nothing with it — the worst of both — and one given a resolver with no
        embedder never calls it. They are one decision, so they are one call.
        """
        try:
            vr = self.brain.voice_recall()
        except Exception as exc:                     # noqa: BLE001
            log.info("[ear] no voice recall: %s", type(exc).__name__)
            return None, None, None
        if vr is None or not vr.enabled or not vr.model_available:
            return None, None, None
        try:
            names = [p["name"] for p in vr.people() if p.get("name")]
            return vr._get_embedder(), vr.resolver(), names
        except Exception as exc:                     # noqa: BLE001
            log.warning("[ear] voice seam failed: %s", type(exc).__name__)
            return None, None, None

    # -- the live interpreter: foreign speech, voiced back to you -----------
    #
    # This is `live_interpret`, and the whole feature was one missing method. The
    # capture loop has called `note_speech_audio(segment, sample_rate)` on its host
    # at every endpointed segment since it was written; `RosettaLens.hear()` has
    # been able to carry that audio across languages just as long; the Orchestrator
    # implements the seam (ops_juno_attention.py). The Brain's ear simply did not
    # have the method, so on the shipped product the hook found nothing callable
    # and no-op'd — the exact "adapter built, nothing calls it" shape the
    # reachability audit keeps surfacing, one method wide.

    def _rosetta(self):
        """The Brain's ONE RosettaLens — the same object the eye translates with.

        Deliberately not a second lens: `world_lens()` builds it with both an
        Argos `translate_fn` (the eye) and a SeamlessM4T `interpret_fn` (the ear),
        and a private copy here would drift from the one the object-lens registry
        already holds. Returns None when the world lens can't be built at all.
        """
        try:
            return getattr(self.brain.world_lens(), "rosetta", None)
        except Exception as exc:                     # noqa: BLE001
            log.debug("[interpret] no world lens: %s", type(exc).__name__)
            return None

    def _can_interpret(self) -> bool:
        """Is an interpreter actually wired? (the wheel is present AND the lens
        got an `interpret_fn`).

        Deliberately does NOT consult `SeamlessInterpreter.ready`, tempting as
        that is: `ready` triggers the lazy multi-gigabyte model load, so a status
        poll would kick off a download. Readiness is proved by use instead —
        `_interpret_ok`, set when a real segment comes back translated.
        """
        lens = self._rosetta()
        return lens is not None and getattr(lens, "_interpret", None) is not None

    @property
    def interpreting(self) -> bool:
        """True only when the interpreter has PROVED itself on this process: the
        switch is on, the ear is open, and a segment has actually come back
        translated. This is what promotes `live_interpret` to "active"."""
        return bool(self._interpret_on and self.listening and self._interpret_ok)

    def set_interpret(self, on: bool = True, target: str = "en") -> dict:
        """Turn the live interpreter on/off and choose the language Juno answers
        IN. Reports what is actually true rather than echoing the request, so a
        wearer who flips it on without the pack installed is told so."""
        self._interpret_on = bool(on)
        self._interpret_target = (str(target or "en").strip() or "en")[:8]
        can = self._can_interpret()
        return {"ok": True, "on": self._interpret_on,
                "target": self._interpret_target,
                "can_interpret": can,
                "proved": self._interpret_ok,
                "reason": "" if can else "no-interpreter",
                "detail": "" if can else ("install the interpreter pack "
                                          "(SeamlessM4T) to hear a translation"),
                "interpreted_count": self.interpreted_count}

    def note_speech_audio(self, segment, sample_rate: int = 16000) -> None:
        """CapturePipeline endpointed a speech segment — the raw-audio hook.

        TWO consumers, each with its own switch, and the audio is what neither
        can get from the transcript:

          * the live interpreter, which renders the utterance into the wearer's
            own language (`_interpret_on`);
          * the Truth Lens's voice-stress channel, which measures HOW it was
            said — pitch, jitter, shimmer, hesitation (`truth.enabled`).

        The Truth Lens is fed FIRST and unconditionally of the interpreter,
        because it used to sit behind `if not self._interpret_on: return` while
        being a completely separate feature — a wearer who wanted the room read
        and no translation would have got silence, and the reason would have
        been a shared early return rather than anything they set.

        The raw audio is used and dropped; nothing here stores it.

        Veil-gated with a SECOND check even though the pipeline already gates its
        door: `push_pcm` refuses to accumulate while veiled, but the segment now in
        hand was accumulated before that and the shield may have come down in
        between. Fails CLOSED, like every other gate in this file. (`TruthRead`
        re-checks the same way, for the same reason, on its own side.)
        """
        try:
            self.truth.note_audio(segment, sample_rate)
        except Exception as exc:                     # noqa: BLE001 — never break
            log.warning("[truth] audio note failed: %s", type(exc).__name__)
        if not self._interpret_on:
            return
        try:
            if not self.privacy.allow_capture():
                return
        except Exception:                            # noqa: BLE001
            return                                   # unknown posture → veiled
        lens = self._rosetta()
        if lens is None or getattr(lens, "_interpret", None) is None:
            return
        try:
            res = lens.hear(segment, sample_rate, self._interpret_target)
        except Exception as exc:                     # noqa: BLE001 — never break
            log.warning("[interpret] hear failed: %s", type(exc).__name__)
            return
        line = (getattr(res, "translated", "") or "").strip()
        if not line:
            # An empty line is the honest miss: the model declined, is still
            # loading, or the segment was not speech in another language. NOT a
            # proof of readiness, so the capability stays dormant.
            return
        self._interpret_ok = True
        self.interpreted_count += 1
        try:
            self.brain._sync_ear_wired()             # first line → cap goes active
        except Exception:                            # noqa: BLE001
            pass
        try:
            from ...hud import cards
            # `original=""` on purpose. SeamlessM4T does speech→text IN THE TARGET
            # language in one pass — it never produces a source transcript, and
            # `RosettaLens.hear` documents `source_text` as empty for exactly that
            # reason. Putting the ASR transcript there would look like the same
            # utterance while being a separate engine's guess at it.
            card = cards.live_caption_card(
                original="", translation=line,
                src_lang="", dst_lang=self._interpret_target,
                privacy=self.privacy)
            # veil_ok=False: this card is nothing BUT captured speech.
            self.brain.push_event("interpret", card, veil_ok=False)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[interpret] card push failed: %s", type(exc).__name__)

    # -- lifecycle ---------------------------------------------------------

    @property
    def listening(self) -> bool:
        return self._pipe is not None

    def start(self, mic=None) -> dict:
        """Open the microphone and run the capture loop on a daemon thread. Never
        raises; on any missing piece returns {ok: False, reason, detail} and
        changes nothing. Idempotent — a second start while already listening is a
        no-op status read. Pass `mic` (a MicSource) to drive it from a fixture
        instead of real hardware (used by the tests via SyntheticMicSource)."""
        with self._lock:
            if self._pipe is not None:
                return {"ok": True, **self.status()}
            from ...orchestrator.asr_select import make_asr, asr_engine_name
            asr = make_asr(None, None)
            if asr is None:
                # Last rung: the unified ONNX engine, when the wearer pointed
                # the Brain at a sherpa model directory. Deliberately AFTER
                # Moonshine and faster-whisper — installing one wheel must not
                # take a working purpose-built engine away from somebody who
                # already had one. On a machine with neither, this is the whole
                # voice stack from a single install, which is the capability's
                # actual pitch.
                asr = self._sherpa().asr()
            if asr is None:
                return {"ok": False, "reason": "no-asr",
                        "detail": "no on-device speech engine installed "
                                  "(install the Sharp Ears pack)"}
            if mic is None:
                from ...orchestrator.capture import SoundDeviceMic
                mic = SoundDeviceMic()
                if not getattr(mic, "available", False):
                    return {"ok": False, "reason": "no-mic",
                            "detail": "no microphone backend (sounddevice) "
                                      "available on this machine"}
            from ...orchestrator.capture import CapturePipeline, SoundDeviceMic
            from ...orchestrator.vad_gate import default_vad
            try:
                from ...orchestrator.sound_events import default_sound_detector
                tagger = default_sound_detector()
            except Exception:                    # noqa: BLE001
                tagger = None
            # `SoundEventDetector` has its own sherpa rung, but it reads
            # $DL_AUDIO_TAG_DIR — a second directory to configure, and env-only,
            # which the bundled .app cannot set. A wearer who pointed the Brain
            # at ONE sherpa export should get tagging out of it too.
            if tagger is None or not getattr(tagger, "ready", False):
                tagger = self._sherpa().tagger() or tagger
            if not self._bird_built:
                self._bird_built = True
                try:
                    from ...orchestrator.bird_lens import default_bird_lens
                    self._bird = default_bird_lens()
                except Exception:                # noqa: BLE001
                    self._bird = None
            # `default_vad()` is never None — with silero absent it returns a
            # gate running the cheap energy heuristic, which is a real decision
            # and the reason the ambient path works at all. So the sherpa rung
            # slots in on `_model is None` rather than on `vad is None`: a
            # loaded Silero VAD keeps its place, and an energy threshold gives
            # way to a real model. Writing this as `default_vad() or …` would
            # have silently made the rung unreachable forever, which is the
            # shape of defect this whole line of work is about.
            vad = default_vad()
            if getattr(vad, "_model", None) is None:
                vad = self._sherpa().vad() or vad
            # Who is speaking — the producer `said_by` never had. Only wired
            # when the wearer has consented AND a real speaker model loaded;
            # `voice_recall()` returns (None, None, None) otherwise and the
            # pipeline runs exactly as it does today, unattributed.
            #
            # `enrolled_speakers` is handed over so `voice_guard` can do its job
            # rather than being bypassed: it decides whether a computed
            # embedding is RETAINED, and a name that is not on this list is a
            # stranger whose vector is dropped. Auto-enrol widens the list — it
            # does not remove the check.
            speaker, resolver, enrolled = self._voice_seam()
            # Anonymous turn-taking, a different question from identity: how
            # many voices are in this segment. It only ever fills a label the
            # resolver left blank, so a real name always wins, and its tags
            # (`spk0`/`spk1`) mean nothing outside the stream that made them —
            # nothing is enrolled, matched or persisted by this path.
            pipe = CapturePipeline(self, vad=vad, asr=asr,
                                   tagger=tagger, bird=self._bird,
                                   speaker=speaker, speaker_resolver=resolver,
                                   enrolled_speakers=enrolled,
                                   wake=self._wake_engine(),
                                   diarizer=self._diarizer())
            try:
                pipe.start(mic)
            except Exception as exc:             # noqa: BLE001 — a dead mic isn't fatal
                log.error("[ear] mic open failed: %s", exc)
                return {"ok": False, "reason": "mic-error", "detail": str(exc)}
            self._pipe = pipe
            # Say so on the glass. `listening()` is the other declared HUD
            # feature the shipped Brain could never produce — "Hey Juno", the
            # reassurance cue that the microphone is genuinely open. The Brain
            # ships no wake-word engine (`hear()` above is a no-op and wake_word
            # stays dormant), so the honest `source` is NOT "voice": the mic was
            # opened by the wearer flipping a switch, and the card says so.
            #
            # earcon/haptic are switched OFF rather than defaulted on. Both are
            # device seams the Live Lens cannot honour, and the one card in this
            # product that earns a sound is a safety tap (`note_acoustic_context`
            # is the sole veil-piercing path) — a settings toggle is not that.
            #
            # veil_ok=False even though this card carries no captured content:
            # under the Veil the ear stores nothing, so announcing that it is
            # listening would be the one misleading thing it could draw.
            try:
                from ...hud import cards
                self.brain.push_event(
                    "listening", cards.listening("tap", earcon=False, haptic=False),
                    veil_ok=False)
            except Exception as exc:             # noqa: BLE001 — never block the mic
                log.warning("[ear] listening card push failed: %s",
                            type(exc).__name__)
            # Promote ONLY the caps this run genuinely drives — not the whole
            # EAR_CAPS set. make_asr picks Moonshine XOR faster-whisper (never
            # sherpa/onnx), so onnx_speech is never on the ear's path; VAD /
            # sound-events / birds / a real mic are each conditional on having
            # actually built. This keeps the capability report and the meter
            # honest (the audit's finding: a blanket promotion lied about the
            # engines that weren't running).
            engine = asr_engine_name(asr)
            caps = set()
            caps.add("asr_moonshine" if engine == "moonshine" else "local_asr")
            if vad is not None:
                caps.add("voice_vad")
            # A tagger object is not a working tagger. `SoundEventDetector`
            # exposes TWO booleans and they mean different things: `available` is
            # the WHEEL (and is what `default_sound_detector` filters on, so a
            # non-None tagger only proves the wheel), while `ready` is a MODEL
            # actually loaded — and `detect()` returns [] unless `ready`. On a
            # bare `pip install dreamlayer[voice]` the wheel is there and no model
            # is, so this reported sound_events live for a seam that could only
            # ever return nothing: exactly the blanket over-promotion the comment
            # above says was removed. Ask for `ready` when the seam offers it.
            tagger_live = bool(getattr(tagger, "ready", tagger is not None))
            if tagger_live:
                caps.add("sound_events")
            if self._bird is not None:
                caps.add("bird_song")
            if isinstance(mic, SoundDeviceMic):   # a real mic, not a test fixture
                caps.add("mic_capture")
            self.active_caps = frozenset(caps & set(EAR_CAPS))
            return {"ok": True, "engine": engine,
                    "sound_events": tagger_live,
                    "birds": self._bird is not None,
                    "active_caps": sorted(self.active_caps),
                    **self.status()}

    def stop(self) -> None:
        """Close the microphone and tear the loop down. Safe when not listening."""
        with self._lock:
            pipe, self._pipe = self._pipe, None
            self.active_caps = frozenset()       # nothing is driven once stopped
        if pipe is not None:
            try:
                pipe.stop()
            except Exception:                    # noqa: BLE001
                pass

    def status(self) -> dict:
        # Deliberately does NOT echo the last transcript: a status endpoint has
        # no need to hand captured content back over the wire (even to a token
        # holder), and the Live Lens credential IS the Brain token. Counts only.
        return {"listening": self.listening,
                "heard_count": self.heard_count,
                # the interpreter, reported as four separate facts because they
                # fail independently: the switch, the pack, whether it has ever
                # actually produced a line, and how many.
                "interpret": self._interpret_on,
                "interpret_target": self._interpret_target,
                "can_interpret": self._can_interpret(),
                "interpret_proved": self._interpret_ok,
                "interpreted_count": self.interpreted_count,
                # …and the room read, on the same principle: the switch and
                # whether it has ever genuinely produced a gauge are separate
                # facts, and only the second one means the feature works.
                "truth": self.truth.enabled,
                "truth_proved": self.truth.proved,
                "truth_reads": self.truth.read_count,
                # …and Lexicon, reported on the same three-fact principle: the
                # switch, whether a definition has ever genuinely reached the
                # glass, and how many. Deliberately NOT the words themselves —
                # `status` does not hand captured content back over the wire.
                "lexicon": self.lexicon.enabled,
                "lexicon_proved": self.lexicon.proved,
                "lexicon_defined": self.lexicon.defined_count}

    def set_truth(self, on: bool = True) -> dict:
        """Turn the room read on/off for THIS ear. Mirrors `set_interpret`: the
        Brain owns persistence and pushes the setting into every ear."""
        return self.truth.set_enabled(on)
