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
# wake_word (a wake-word engine), live_interpret (the SeamlessM4T interpreter),
# diarization and asr_alignment stay dormant until the full Orchestrator path is
# wired, so the meter never over-reports.
EAR_CAPS = ("voice_vad", "local_asr", "mic_capture", "asr_moonshine",
            "onnx_speech", "sound_events", "bird_song")


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
        self.last_heard = ""
        self.heard_count = 0
        self.active_caps = frozenset()          # the caps THIS run genuinely drives

    # -- CapturePipeline host contract -------------------------------------

    def hear(self, text: str) -> None:
        """Wake / command path. The minimal ear ships no wake-word engine (that
        is the full Orchestrator's job — wake_word stays dormant), so this is a
        no-op. Present so CapturePipeline._route's contract is satisfied without
        raising. Deliberately logs NOTHING here: the transcript is sensitive and
        must never be interpolated into a log message (logging-discipline seam)."""
        return

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
        name = "heard" if not speaker else f"heard:{speaker}"
        try:
            self.brain.index.add_documents([(name, text)])
        except Exception as exc:                 # noqa: BLE001
            log.warning("[ear] index ingest failed: %s", exc)
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
            if not self._bird_built:
                self._bird_built = True
                try:
                    from ...orchestrator.bird_lens import default_bird_lens
                    self._bird = default_bird_lens()
                except Exception:                # noqa: BLE001
                    self._bird = None
            vad = default_vad()
            pipe = CapturePipeline(self, vad=vad, asr=asr,
                                   tagger=tagger, bird=self._bird)
            try:
                pipe.start(mic)
            except Exception as exc:             # noqa: BLE001 — a dead mic isn't fatal
                log.error("[ear] mic open failed: %s", exc)
                return {"ok": False, "reason": "mic-error", "detail": str(exc)}
            self._pipe = pipe
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
            if tagger is not None:
                caps.add("sound_events")
            if self._bird is not None:
                caps.add("bird_song")
            if isinstance(mic, SoundDeviceMic):   # a real mic, not a test fixture
                caps.add("mic_capture")
            self.active_caps = frozenset(caps & set(EAR_CAPS))
            return {"ok": True, "engine": engine,
                    "sound_events": tagger is not None,
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
                "heard_count": self.heard_count}
