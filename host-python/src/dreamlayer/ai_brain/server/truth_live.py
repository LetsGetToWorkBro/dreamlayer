"""ai_brain/server/truth_live.py — "Read the room", produced by the Brain.

`truth_gauge` was the last declared HUD feature with NO BRAIN-SIDE PRODUCER
(`scripts/hud_reachability.py`). Everything else was already built:

  * `hud/cards.py:truth_gauge_card()` — the card builder;
  * `truth_lens/` — nine stages: face, AU, prosody, linguistic, fusion,
    narrative store, renderer;
  * `halo-lua/display/renderer.lua:draw_testimony` — the Testimony Thread, a
    full Meridian animation on the DEVICE.

And the only `TruthLens(...)` in the tree is built by the Orchestrator, which
the shipped Brain never constructs (`decisions/0001`). The phone talks to the
Brain and nothing else, so "Read the room" was absent from the phone entirely
and reached the glass only on a surface that does not exist yet. This is the
producer that closes it — the same shape as the caption, interpreter and
speaker-recall seams before it: the pipeline was complete and nothing called it.

WHAT IT ACTUALLY READS, and what it does not
--------------------------------------------
Two channels, both of which the Brain genuinely has and neither of which is a
biometric template:

  * **voice stress** — pitch mean/variance, jitter, shimmer, hesitation rate,
    pause ratio, speech rate and energy, computed by `truth_lens/prosody.py`
    from the same endpointed speech segment the interpreter already receives;
  * **linguistic markers** — hedging rate, first-person rate, sentence
    complexity and negation rate, from `truth_lens/linguistic.py` over the
    transcript that `ingest_caption` already holds.

The **micro-expression channel stays off**. `fusion.AU_CHANNEL_REAL` is False
because `au_detector` produces frame-hash noise rather than measured action
units, so the AU stage contributes zero weight, is excluded from the confidence
count, and draws as an honest *empty slot* on the thread. That is deliberate and
it is the difference between a delivery read and a lie detector: this surface
never claims to have seen a face twitch, because it has not.

`set_contact()` is fed from the speaker label the capture pipeline resolves, so
the per-contact baseline in `narrative_store` is real personalisation — "unusual
*for this person*" — rather than an absolute threshold applied to everyone. With
no speaker identified, fusion takes its conservative stranger path, which pins
confidence at 0.2 and therefore reads `CALIBRATING` rather than a verdict.

Gates, in the order they apply
------------------------------
  1. `truth_lens_enabled` — its own persisted opt-in, default False;
  2. the ear is open at all (this is fed from the capture pipeline);
  3. the Veil — `_TruthGate` fails CLOSED, so an unreadable posture is veiled;
  4. `TruthLens`'s own emit cooldown and the renderer's display thresholds.

Nothing here stores audio. The PCM is turned into per-frame spectra, fed, and
dropped; the transcript arrives already PII-scrubbed by `ingest_caption`. The
transcript is never logged — only ever drawn (`test_logging_discipline`).
"""
from __future__ import annotations

import logging

log = logging.getLogger("dreamlayer.truth_live")

#: FFT frame size the prosody analyser is written against (`prosody.SAMPLE_RATE_HZ`
#: / `prosody.FFT_SIZE` fix its bin geometry). Imported rather than duplicated
#: would be neater, but prosody.py pulls numpy at module scope and this module is
#: constructed on a Brain that may never open a microphone — so the constant is
#: mirrored here and pinned by a test that reads the real one.
FFT_SIZE = 512

#: Longest stretch of a single endpointed segment fed to the prosody analyser,
#: in frames. `CapturePipeline.MAX_SEGMENT_MS` is 12 s, i.e. ~375 frames at
#: 32 ms each, and `ProsodyAnalyzer` emits one `ProsodyFrame` per 40 frames — so
#: a monologue would emit nine windows and only the last would survive as
#: `_current_prosody`. Capping the work is honest (the read describes the END of
#: the utterance, which is what the transcript's verdict lands on anyway) and
#: bounds the per-segment cost.
MAX_FRAMES = 400


class _TruthGate:
    """The Veil, as the Truth Lens sees it. Fails CLOSED: an unreadable posture
    is a veiled one, so a broken trust signal can never resolve to "read the
    person in front of you". Mirrors `_EarGate` / `_LookGate` exactly."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class TruthRead:
    """One conversation's credibility read, hanging off one `EarHost`.

    Per-ear rather than per-Brain on purpose: the Mac's own microphone and the
    phone streaming in are two different rooms with two different people in
    them, and `TruthLens` carries rolling per-conversation state (the current
    speaker, the last prosody window, the last utterance). One shared instance
    would blend two conversations into one verdict.
    """

    def __init__(self, brain):
        self.brain = brain
        self.privacy = _TruthGate(brain)
        self._on = False
        self._lens = None
        # The honesty bit, and the whole point of the pattern: `_proved` flips
        # only once a card has genuinely been built from a real fused read. A
        # switch being on proves nothing; neither does the module importing.
        self._proved = False
        self.read_count = 0
        self.last_verdict = ""

    # -- construction ------------------------------------------------------

    def _truth_lens(self):
        """Build the nine-stage lens on first use and cache it.

        Lazy because `truth_lens.analyzer` imports numpy and the whole face
        stack transitively: a Brain whose wearer never turns this on should
        never pay for it. Returns None when it cannot be built, which every
        caller reads as "no answer" — never as "nothing to report".
        """
        if self._lens is None:
            try:
                from ...truth_lens.analyzer import TruthLens
                # cooldown_s=0: the emit rate is governed by how often the
                # wearer's conversation partner finishes an utterance, which is
                # already a natural several-seconds cadence. The analyzer's own
                # 3 s default on top of that silently swallowed short exchanges.
                self._lens = TruthLens(cooldown_s=0.0, privacy=self.privacy)
            except Exception as exc:                 # noqa: BLE001
                log.warning("[truth] lens unavailable: %s", type(exc).__name__)
                self._lens = None
        return self._lens

    # -- the switch --------------------------------------------------------

    def set_enabled(self, on: bool = True) -> dict:
        """Turn the read on/off. Reports what is actually TRUE rather than
        echoing the request, so a wearer who flips it on without a microphone is
        told so instead of watching a live-looking switch do nothing."""
        self._on = bool(on)
        if not self._on:
            # Drop the rolling conversation state, so turning it back on later
            # starts from the room you are in NOW rather than resuming a verdict
            # about a conversation that ended. The per-contact baselines in the
            # narrative store survive — those are learned history, not session
            # state, and `forget()` is the thing that erases them.
            lens = self._lens
            if lens is not None:
                try:
                    lens.reset()
                except Exception:                    # noqa: BLE001
                    pass
        return self.status()

    @property
    def enabled(self) -> bool:
        return self._on

    @property
    def proved(self) -> bool:
        """True only once a real fused read has produced a card on this process.
        This is what makes the HUD feature honestly "reachable" rather than
        merely wired."""
        return self._proved

    def status(self) -> dict:
        return {"ok": True, "on": self._on, "proved": self._proved,
                "reads": self.read_count, "last_verdict": self.last_verdict,
                # The channel inventory, stated rather than implied. A surface
                # that shows a nine-ring gauge owes the wearer an answer to "so
                # which of those nine actually measured anything".
                "channels": ["voice_stress", "linguistic"],
                "note": "reads delivery — voice stress and word choice. "
                        "Micro-expressions are NOT read: no action-unit "
                        "detector backs that stage, so it stays empty."}

    # -- the feeds ---------------------------------------------------------

    def note_audio(self, segment, sample_rate: int = 16000) -> None:
        """One endpointed speech segment → prosody frames.

        Called from the ear's `note_speech_audio`, the same hook the live
        interpreter rides. Veil-gated again here even though the capture
        pipeline gates its own door: the segment in hand was accumulated BEFORE
        this call and the shield may have come down in between.

        Never raises into the capture loop — a prosody failure must cost the
        wearer a gauge, never their microphone.
        """
        if not self._on:
            return
        try:
            if not self.privacy.allow_capture():
                return
        except Exception:                            # noqa: BLE001
            return                                   # unknown posture → veiled
        lens = self._truth_lens()
        if lens is None:
            return
        try:
            for spectrum, amplitude in self._frames(segment, sample_rate):
                lens.feed_audio(spectrum, amplitude)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[truth] prosody feed failed: %s", type(exc).__name__)

    @staticmethod
    def _frames(segment, sample_rate: int):
        """Chop mono float PCM into (magnitude spectrum, amplitude) frames.

        `ProsodyAnalyzer` is written against 512-point spectra at 16 kHz — its
        F0 search band (80–400 Hz) is precomputed as BIN indices from exactly
        that geometry, so a frame of a different length would silently search
        the wrong frequencies rather than fail. Audio at another rate is
        therefore NOT resampled and NOT fed: a wrong pitch read presented as a
        stress signal is the "active and wrong" failure this codebase keeps
        finding, and no read is better than a confident false one.

        `amplitude` is mean absolute sample value, which is what
        `prosody.SILENCE_THRESHOLD` (0.02) is calibrated against for the mono
        float PCM in [-1, 1] that every MicSource in this product produces.
        """
        import numpy as np
        if sample_rate != 16000:
            return
        arr = np.asarray(segment, dtype=float).ravel()
        n_frames = min(int(len(arr) // FFT_SIZE), MAX_FRAMES)
        for i in range(n_frames):
            block = arr[i * FFT_SIZE:(i + 1) * FFT_SIZE]
            # rfft magnitude, normalised by frame length so the spectrum is
            # scale-comparable with `prosody._estimate_f0`'s 1e-4 noise floor
            # regardless of how long a block is.
            spectrum = np.abs(np.fft.rfft(block)) / FFT_SIZE
            yield spectrum, float(np.mean(np.abs(block)))

    def note_transcript(self, text: str, speaker: str = "") -> int:
        """One utterance → the linguistic channel, then a fused read.

        Returns the number of surfaces the card reached (0 when nothing was
        emitted), so a caller can tell "read, nothing worth showing" from "never
        ran". Called from `ingest_caption` AFTER the PII scrub, so the words that
        reach the analyser are the words that reached the store and never more.

        Ordering matters and is not accidental: `CapturePipeline._endpoint` calls
        `_speech_audio` (→ `note_audio`) BEFORE `_route` (→ this), so by the time
        an utterance arrives its prosody window is already resident and the fuse
        sees both channels rather than language alone.
        """
        if not self._on:
            return 0
        text = (text or "").strip()
        if not text:
            return 0
        try:
            if not self.privacy.allow_capture():
                return 0
        except Exception:                            # noqa: BLE001
            return 0
        lens = self._truth_lens()
        if lens is None:
            return 0
        try:
            # WHO is speaking, so the baseline is theirs. An empty label is the
            # honest "stranger" — passed through as None rather than as the
            # string "", which would key a shared baseline that every
            # unidentified voice in every room contributed to.
            lens.set_contact(speaker or None, speaker or None)
            lens.feed_transcript(text)
            result = lens.tick()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[truth] read failed: %s", type(exc).__name__)
            return 0
        if result is None:
            # Not a failure: `tick` returns None when the read is below the
            # display threshold, which for a credible speaker is the NORMAL
            # outcome and must not draw anything. A gauge that appears on every
            # utterance is an accusation machine, not a lens.
            return 0
        return self._push(result)

    # -- the card ----------------------------------------------------------

    def _push(self, result) -> int:
        """Build the Testimony Thread payload and push it to the glass."""
        try:
            card = result.to_gauge_card()
        except Exception as exc:                     # noqa: BLE001
            log.warning("[truth] card build failed: %s", type(exc).__name__)
            return 0
        # `footer` carries the contact name straight from the result, and a name
        # is exactly the thing the logging-discipline seam forbids in a message —
        # so it is drawn and counted, never logged.
        verdict = str(card.get("verdict") or "")
        try:
            pushed = self.brain.push_event("truth", card, veil_ok=False)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[truth] push failed: %s", type(exc).__name__)
            return 0
        # Proof, not configuration: the feature counts as genuinely working only
        # once a real fused read has been built into a card and handed to a
        # surface. A switch flipped on, a module that imports, and a lens that
        # constructs are all things that can be true while the wearer sees
        # nothing.
        self._proved = True
        self.read_count += 1
        self.last_verdict = verdict
        try:
            self.brain.activity.add("truth", "Read the room during a conversation")
        except Exception:                            # noqa: BLE001
            pass
        return int(pushed or 0)

    # -- erasure -----------------------------------------------------------

    def forget(self, contact_id: str) -> None:
        """"Forget that" reaches the credibility baseline too. A per-contact
        deception baseline is a stored judgment about a person and belongs in
        the same sweep as their memories."""
        lens = self._lens
        if lens is None:
            return
        try:
            lens.forget(contact_id)
        except Exception:                            # noqa: BLE001
            pass

    def forget_all(self) -> None:
        """The erase-everything path. `reset()` clears only session state, so
        this has to call through to the narrative store or the baselines outlive
        the erase."""
        lens = self._lens
        if lens is None:
            return
        try:
            lens.forget_all()
        except Exception:                            # noqa: BLE001
            pass
