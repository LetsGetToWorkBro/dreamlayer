""""Read the room" — the last declared HUD card the Brain could not produce.

`scripts/hud_reachability.py` had one entry under NO BRAIN-SIDE PRODUCER, and
the shape was the one this repo keeps finding: the card builder existed, the
nine-stage pipeline existed, the DEVICE had a full Testimony Thread animation
for it, and the only `TruthLens(...)` in the tree belonged to the Orchestrator,
which no shipped Brain constructs (`decisions/0001`).

These tests cover the producer AND the three defects that wiring it exposed —
each of which would have made the feature worse than its own absence:

  * a baseline that could never calibrate (learning gated on a channel the
    codebase had already declared synthetic and barred from every verdict);
  * a baseline learned only from the moments flagged abnormal;
  * a per-contact standard deviation that never converged, so the "personal
    baseline" multiplied its evidence by a random factor.

The last one is the important one to keep pinned. A dormant capability costs the
wearer the feature. One that is active and wrong costs them the feature AND the
signal that it is broken — and a credibility readout is not a place to be
confidently wrong about a person.
"""
from __future__ import annotations

import math
import statistics

import pytest

from dreamlayer.truth_lens.narrative_store import NarrativeStore
from dreamlayer.truth_lens.schema import (
    AUFrame, ContactBaseline, LinguisticFrame, ProsodyFrame,
)


# --------------------------------------------------------------------------
# fixtures: a Brain small enough to see through
# --------------------------------------------------------------------------

class FakeBrain:
    """The surface `TruthRead` actually touches. Deliberately tiny: anything it
    needs beyond this is a coupling worth noticing."""

    def __init__(self, veiled=False, raises=False):
        self.pushed: list = []
        self.activity_log: list = []
        self._veiled = veiled
        self._raises = raises
        brain = self

        class _Activity:
            def add(self, kind, msg):
                brain.activity_log.append((kind, msg))
        self.activity = _Activity()

    def incognito_now(self):
        if self._raises:
            raise RuntimeError("posture unreadable")
        return self._veiled

    def push_event(self, kind, card=None, veil_ok=False):
        self.pushed.append({"kind": kind, "card": card, "veil_ok": veil_ok})
        return 1


def _tone(f0=120.0, jitter=1.5, secs=2.0, seed=1, gaps=0, amp=0.3):
    """A synthetic voiced segment: mono float PCM in [-1, 1] at 16 kHz, which is
    exactly what every `MicSource` in this product produces. `gaps` punches
    silences in, which is what `prosody` reads as hesitation."""
    np = pytest.importorskip("numpy")
    sr = 16000
    t = np.arange(int(sr * secs)) / sr
    rs = np.random.RandomState(seed)
    f = f0 + jitter * np.sin(2 * np.pi * 3.1 * t) + rs.normal(0, max(jitter, 0.5) * 0.3, t.shape)
    sig = amp * np.sin(2 * np.pi * np.cumsum(f) / sr)
    for g in range(gaps):
        sig[int((0.3 + g * 0.4) * sr):int((0.36 + g * 0.4) * sr)] = 0.0
    return sig.tolist()


CALM = "We shipped the build on Tuesday and the tests all passed."
RATTLED = "I mean, I guess maybe I probably wasn't really there, you know, I think."


def _read(brain):
    from dreamlayer.ai_brain.server.truth_live import TruthRead
    tr = TruthRead(brain)
    tr.set_enabled(True)
    return tr


def _converse(tr, n, text=CALM, who="marcus", f0=120.0, jitter=1.5, gaps=0):
    """`n` utterances, fed in the order the capture pipeline feeds them: audio
    first (`_speech_audio`), transcript second (`_route`)."""
    for i in range(n):
        tr.note_audio(_tone(f0, jitter, seed=i, gaps=gaps), 16000)
        tr.note_transcript(text, who)


# --------------------------------------------------------------------------


class TestTheBrainCanNowProduceTheCard:
    """The gap itself: a Brain, a microphone and a transcript are enough."""

    def test_off_by_default(self):
        from dreamlayer.ai_brain.server.truth_live import TruthRead
        tr = TruthRead(FakeBrain())
        assert tr.enabled is False
        assert tr.proved is False
        _converse(tr, 3)
        assert tr.note_transcript(RATTLED, "marcus") == 0
        assert tr.brain.pushed == [], "a switched-off lens drew a card"

    def test_a_conversation_produces_a_truthlenscard(self):
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)                       # learn what calm sounds like
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        pushed = tr.note_transcript(RATTLED, "marcus")
        assert pushed == 1, "the fused read reached no surface"
        card = b.pushed[-1]["card"]
        assert card["type"] == "TruthLensCard"
        assert card["verdict"] in ("UNCERTAIN", "ELEVATED", "HIGH ALERT")
        assert card["footer"] == "marcus"

    def test_proved_is_earned_not_configured(self):
        """The honesty bit this codebase promotes capabilities on. Turning the
        switch on, importing the module and constructing the lens are all things
        that can be true while the wearer has seen nothing."""
        b = FakeBrain()
        tr = _read(b)
        assert tr.proved is False, "proved before any read"
        _converse(tr, 14)
        assert tr.proved is False, "calm speech alone counted as proof"
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        tr.note_transcript(RATTLED, "marcus")
        assert tr.proved is True and tr.read_count == 1

    def test_the_card_is_pushed_veil_ok_false(self):
        """This card is nothing BUT a judgment derived from captured speech, so
        it must never ride a veil-exempt push."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        tr.note_transcript(RATTLED, "marcus")
        assert b.pushed[-1]["veil_ok"] is False


class TestItReadsOnlyWhatItCanActuallyMeasure:
    """The claim the surface makes has to match the evidence behind it."""

    def test_the_micro_expression_stages_draw_as_empty(self):
        """`fusion.AU_CHANNEL_REAL` is False — no action-unit detector backs the
        AU channel. The face/au rings must therefore read `insufficient`, which
        the gauge draws as an absent slot. A card claiming a nine-stage read
        while measuring two channels is the overclaim this whole audit is about.
        """
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        tr.note_transcript(RATTLED, "marcus")
        stages = {s["name"]: s for s in b.pushed[-1]["card"]["stages"]}
        for name in ("face", "au"):
            assert stages[name]["direction"] == "insufficient", (
                f"{name} claimed a measurement with no detector behind it")
            assert stages[name]["confidence"] == 0.0

    def test_the_two_real_channels_do_carry_the_verdict(self):
        """The other direction — if everything read `insufficient` the gauge
        would be honest and useless."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        tr.note_transcript(RATTLED, "marcus")
        stages = {s["name"]: s for s in b.pushed[-1]["card"]["stages"]}
        for name in ("voice", "prosody", "linguistic"):
            assert stages[name]["direction"] != "insufficient", (
                f"{name} measured nothing on a real segment")

    def test_the_status_states_its_channels(self):
        from dreamlayer.ai_brain.server.truth_live import TruthRead
        st = TruthRead(FakeBrain()).status()
        assert st["channels"] == ["voice_stress", "linguistic"]
        assert "Micro-expressions are NOT read" in st["note"]

    def test_audio_at_another_rate_is_refused_not_resampled(self):
        """`ProsodyAnalyzer`'s F0 search band is precomputed as BIN indices from
        16 kHz / 512, so a differently-rated frame searches the wrong
        frequencies and returns a confident wrong pitch rather than failing. No
        read beats a false one."""
        b = FakeBrain()
        tr = _read(b)
        tr.note_audio(_tone(secs=3.0), 44100)
        assert tr._truth_lens()._current_prosody is None
        tr.note_audio(_tone(secs=3.0), 16000)
        assert tr._truth_lens()._current_prosody is not None

    def test_the_fft_size_matches_the_analyser_it_feeds(self):
        """The constant is mirrored rather than imported (prosody pulls numpy at
        module scope); this is what stops the mirror drifting."""
        from dreamlayer.ai_brain.server import truth_live
        from dreamlayer.truth_lens import prosody
        assert truth_live.FFT_SIZE == prosody.FFT_SIZE


class TestTheVeilWins:
    def test_a_veiled_conversation_is_never_read(self):
        b = FakeBrain(veiled=True)
        tr = _read(b)
        _converse(tr, 14)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        assert tr.note_transcript(RATTLED, "marcus") == 0
        assert b.pushed == []

    def test_an_unreadable_posture_fails_closed(self):
        """An unknown trust signal must resolve to veiled, never to "read the
        person in front of you"."""
        b = FakeBrain(raises=True)
        tr = _read(b)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        assert tr.note_transcript(RATTLED, "marcus") == 0
        assert b.pushed == []


class TestTheGaugeIsNotAnAccusationMachine:
    def test_ordinary_speech_draws_nothing(self):
        """Fourteen calm utterances from the same speaker. Before the display
        threshold was aligned with the verdict vocabulary this drew four cards,
        every one of them reading CREDIBLE — an overlay announcing that nothing
        was the matter, on ordinary speech, repeatedly. A readout that appears
        constantly is one the wearer stops seeing."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)
        assert b.pushed == [], (
            f"calm conversation drew {len(b.pushed)} card(s)")

    def test_the_gauge_never_draws_a_reassuring_verdict(self):
        """The invariant behind that, pinned so the two constants cannot drift
        apart again: `renderer.DISPLAY_THRESHOLD` is the point where
        `CredibilityVector.label` stops saying CREDIBLE. Checked against the
        label function itself rather than against the literal 0.40, so moving
        either one without the other fails here."""
        from dreamlayer.truth_lens.renderer import DISPLAY_THRESHOLD
        from dreamlayer.truth_lens.schema import CredibilityVector

        def label_at(dp):
            return CredibilityVector(deception_prob=dp, confidence=0.9,
                                     micro_expression_z=0.0, voice_stress_z=0.0,
                                     linguistic_z=0.0, dominant_channel="voice_stress",
                                     is_stranger=False).label
        assert label_at(DISPLAY_THRESHOLD) not in ("CREDIBLE", "CALIBRATING"), (
            "the display gate fires on reads the verdict scale calls unremarkable")
        assert label_at(DISPLAY_THRESHOLD - 0.01) == "CREDIBLE", (
            "the gate is above the CREDIBLE band rather than at its edge — "
            "reads worth showing are being suppressed")

    def test_a_stranger_is_treated_conservatively(self):
        """No baseline means no personalisation, and the fusion engine dampens
        accordingly. An unidentified voice must not attract a verdict."""
        b = FakeBrain()
        tr = _read(b)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        assert tr.note_transcript(RATTLED, "") == 0
        assert b.pushed == []


class TestTheBaselineCanCalibrateWithoutACamera:
    """Defect 1. Learning was gated on `au`, which is permanently None on every
    surface the Brain has — and which `AU_CHANNEL_REAL` had already barred from
    influencing any verdict."""

    def test_prosody_and_language_alone_calibrate(self):
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 12)
        bl = tr._truth_lens()._store.get_baseline("marcus")
        assert bl is not None, "a mic-only Brain learned no baseline at all"
        assert bl.is_calibrated is True
        assert bl.au_n == 0, "an AU frame appeared from nowhere"
        assert bl.prosody_n == 12 and bl.linguistic_n == 12

    def test_the_known_contact_path_is_reachable_from_cold(self):
        """The deadlock, stated as the thing it prevented. With no baseline the
        stranger branch caps its output at `max(score) * 0.3` — at most 0.30
        against the display threshold — so nothing drew, so nothing was learned,
        forever. This asserts a cold start can now reach a personalised read."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 14)
        tr.note_audio(_tone(250.0, 80.0, seed=99, gaps=4), 16000)
        tr.note_transcript(RATTLED, "marcus")
        assert b.pushed, "the known-contact path is still unreachable from cold"
        assert b.pushed[-1]["card"]["is_stranger"] is False


class TestTheBaselineLearnsFromNormalMoments:
    """Defect 2. `tick()` updated the baseline AFTER the display gate, so a
    contact's "normal, non-stressed state" was learned exclusively from the
    moments flagged abnormal enough to show."""

    def test_undisplayed_utterances_still_teach(self):
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 6)
        assert b.pushed == [], "the fixture drew cards; it is not testing the quiet path"
        bl = tr._truth_lens()._store.get_baseline("marcus")
        assert bl is not None and bl.sample_count == 6, (
            "utterances that drew nothing taught the baseline nothing — the "
            "reference for 'normal' can only be built from normal moments")

    def test_an_anomaly_is_still_logged_only_when_it_is_shown(self):
        """The deliberate asymmetry. The baseline learns unconditionally; the
        ANOMALY LOG stays behind the display gate, because a read suppressed for
        want of confidence is a judgment we declined to make and banking it
        while declining to show it is the worse of the two options."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 6)
        store = tr._truth_lens()._store
        assert not store.get_anomaly_log("marcus"), (
            "an anomaly was logged for a read that was never displayed")


class TestThePersonalBaselineIsActuallyAStandardDeviation:
    """Defect 3, and the one that made this ACTIVE AND WRONG rather than merely
    missing. Every z-score in `fusion._avg_abs_z` divides by these numbers."""

    def _feed(self, values):
        bl = ContactBaseline(contact_id="x")
        for v in values:
            bl.update(None, ProsodyFrame(
                pitch_mean_hz=v, pitch_variance=50.0, jitter_pct=2.0,
                shimmer_pct=3.0, hesitation_rate=0.1, pause_ratio=0.2,
                speech_rate_norm=1.0, energy_db=-20.0), None)
        return bl

    def test_the_std_converges_on_the_true_spread(self):
        import random
        random.seed(7)
        values = [120 + random.uniform(-4, 4) for _ in range(14)]
        bl = self._feed(values)
        assert bl.prosody_std["pitch_mean_hz"] == pytest.approx(
            statistics.stdev(values), rel=1e-9), (
            "the stored spread is not the sample standard deviation")

    def test_the_mean_converges_too(self):
        import random
        random.seed(11)
        values = [120 + random.uniform(-4, 4) for _ in range(30)]
        bl = self._feed(values)
        assert bl.prosody_mean["pitch_mean_hz"] == pytest.approx(
            statistics.fmean(values), rel=1e-9)

    def test_it_is_not_the_last_samples_deviation(self):
        """The specific thing that was wrong, pinned so it cannot come back.
        The old expression — `abs(delta * (v - m)) ** 0.5` — depends only on the
        most recent reading, so appending one more sample from the SAME
        distribution used to move the stored spread wildly. A real running std
        barely moves."""
        import random
        random.seed(3)
        values = [120 + random.uniform(-4, 4) for _ in range(40)]
        before = self._feed(values).prosody_std["pitch_mean_hz"]
        after = self._feed(values + [values[0]]).prosody_std["pitch_mean_hz"]
        assert abs(after - before) < 0.15 * before, (
            "one more ordinary sample moved the spread by "
            f"{abs(after - before) / before:.0%} — this is a per-sample "
            "estimate, not a running standard deviation")

    def test_a_constant_speaker_does_not_divide_by_zero(self):
        """The floor is a guard now rather than, as before, the value the
        estimate kept collapsing to."""
        bl = self._feed([120.0] * 15)
        assert bl.prosody_std["pitch_mean_hz"] >= 0.01
        assert math.isfinite(120.0 / bl.prosody_std["pitch_mean_hz"])

    def test_a_channel_present_only_sometimes_uses_its_own_count(self):
        """Welford divides the delta by the number of samples that actually
        contributed. Using the global `sample_count` for a channel seen on only
        some observations weights each new reading far too lightly, and the mean
        crawls toward the truth instead of converging on it."""
        bl = ContactBaseline(contact_id="x")
        ling = LinguisticFrame(hedging_rate=0.5, first_person_rate=0.1,
                               complexity_score=0.3, negation_rate=0.1,
                               word_count=20)
        for i in range(10):                      # 10 observations, language only
            bl.update(None, None, ling)
        for i in range(3):                       # then 3 that also carry voice
            bl.update(None, ProsodyFrame(
                pitch_mean_hz=200.0, pitch_variance=1.0, jitter_pct=1.0,
                shimmer_pct=1.0, hesitation_rate=0.0, pause_ratio=0.0,
                speech_rate_norm=1.0, energy_db=-20.0), ling)
        assert bl.sample_count == 13
        assert bl.linguistic_n == 13 and bl.prosody_n == 3
        # 3 identical readings → the mean IS that reading. Divided by the global
        # 13 it would sit near 46, not 200.
        assert bl.prosody_mean["pitch_mean_hz"] == pytest.approx(200.0), (
            "a partially-present channel was averaged over the global count")

    def test_au_uses_its_own_count_as_well(self):
        bl = ContactBaseline(contact_id="x")
        ling = LinguisticFrame(hedging_rate=0.1, first_person_rate=0.1,
                               complexity_score=0.1, negation_rate=0.1,
                               word_count=10)
        for _ in range(8):
            bl.update(None, None, ling)
        for _ in range(2):
            bl.update(AUFrame(au_values=[0.7] * 17, face_confidence=0.9), None, None)
        assert bl.au_n == 2
        assert all(m == pytest.approx(0.7) for m in bl.au_mean)


class TestOneBuilderForOneCardType:
    """`TruthLensResult.to_gauge_card` used to assemble the payload inline, a
    second independent definition of TruthLensCard alongside
    `hud/cards.py:truth_gauge_card`. They had already drifted, and the HUD
    reachability checker — which maps a card type to the builder that makes it —
    could not see this path as a producer at all."""

    def test_the_result_builds_through_the_shared_builder(self, monkeypatch):
        from dreamlayer.hud import cards
        from dreamlayer.truth_lens.schema import CredibilityVector, TruthLensResult
        calls = []
        real = cards.truth_gauge_card

        def spy(**kw):
            calls.append(kw)
            return real(**kw)
        monkeypatch.setattr(cards, "truth_gauge_card", spy)
        res = TruthLensResult(credibility=CredibilityVector(
            deception_prob=0.8, confidence=0.7, micro_expression_z=0.0,
            voice_stress_z=2.0, linguistic_z=1.5,
            dominant_channel="voice_stress", is_stranger=False))
        card = res.to_gauge_card()
        assert calls, "to_gauge_card assembled its own dict again"
        assert card["type"] == "TruthLensCard"

    def test_the_richer_fields_survive_the_delegation(self):
        from dreamlayer.truth_lens.schema import CredibilityVector, TruthLensResult
        res = TruthLensResult(credibility=CredibilityVector(
            deception_prob=0.8, confidence=0.7, micro_expression_z=0.0,
            voice_stress_z=2.0, linguistic_z=1.5,
            dominant_channel="voice_stress", is_stranger=True))
        card = res.to_gauge_card()
        assert card["is_stranger"] is True
        assert card["deception_prob"] == 0.8
        assert card["footer"] == "Stranger"
        assert card["lines"][2] == "80% deception signal"


class TestTheLiveLensDrawsIt:
    """The phone is the only surface a Brain push reaches. A card with a
    producer and no drawing there is still invisible to the wearer."""

    def _live(self):
        from dreamlayer.ai_brain.server import live
        import pathlib
        return pathlib.Path(live.__file__).read_text(encoding="utf-8")

    def test_renderevent_routes_truthlenscard(self):
        src = self._live()
        assert 'else if (t === "TruthLensCard") glassTestimonyCard(c);' in src, (
            "TruthLensCard falls through to the generic renderer — the verdict "
            "word would draw without the thread that says which stages measured "
            "anything")

    def test_the_renderer_exists(self):
        assert "function glassTestimonyCard(c){" in self._live()

    def test_it_uses_the_devices_geometry(self):
        """Same nine 40-degree slots at r=64 the device draws
        (`animations.lua:TESTIMONY_R/SLOT_DEG`), or the two surfaces disagree
        about what the wearer is looking at."""
        import pathlib
        import re
        src = self._live()
        body = src.split("function glassTestimonyCard(c){", 1)[1]
        assert "const R = 64, SLOT = 40" in body
        lua = pathlib.Path("halo-lua/display/animations.lua")
        if lua.exists():
            text = lua.read_text(encoding="utf-8")
            r = re.search(r"TESTIMONY_R\s*=\s*(\d+)", text)
            deg = re.search(r"TESTIMONY_SLOT_DEG\s*=\s*(\d+)", text)
            assert r and int(r.group(1)) == 64
            assert deg and int(deg.group(1)) == 40

    def test_insufficient_stages_draw_nothing(self):
        """The empty slot IS the message: it is how the card says a stage had no
        detector behind it. Filling it with anything would be the overclaim."""
        body = self._live().split("function glassTestimonyCard(c){", 1)[1]
        head = body.split("function ", 1)[0]
        assert 'if (dir === "insufficient") continue;' in head

    def test_no_duplicate_function_names_in_the_live_lens(self):
        """A duplicate `function foo(){}` in one script silently replaces the
        earlier one — this bit once already, when a second `refreshVoice` took
        over the Juno TTS one."""
        import collections
        import re
        names = re.findall(r"^function\s+([A-Za-z_$][\w$]*)\s*\(",
                           self._live(), re.M)
        dupes = [n for n, c in collections.Counter(names).items() if c > 1]
        assert not dupes, f"duplicate function declarations: {dupes}"


class TestTheSwitchIsHonest:
    def test_the_config_flag_defaults_off(self):
        from dreamlayer.ai_brain.server.store import BrainConfig
        assert BrainConfig().truth_lens_enabled is False

    def test_turning_it_off_drops_the_conversation_state(self):
        """Session state, not learned history: the per-contact baselines survive
        (only `forget` erases those), but the rolling read does not resume a
        conversation that has ended."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 6)
        lens = tr._truth_lens()
        assert lens._current_prosody is not None
        tr.set_enabled(False)
        assert lens._current_prosody is None and lens._current_contact_id is None
        assert lens._store.get_baseline("marcus") is not None, (
            "a toggle erased learned history")

    def test_forget_reaches_the_credibility_baseline(self):
        """"Forget that" has to reach stored judgments about a person, not just
        their memories."""
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 6)
        assert tr._truth_lens()._store.get_baseline("marcus") is not None
        tr.forget("marcus")
        assert tr._truth_lens()._store.get_baseline("marcus") is None

    def test_forget_all_reaches_every_baseline(self):
        b = FakeBrain()
        tr = _read(b)
        _converse(tr, 4, who="marcus")
        _converse(tr, 4, who="dana")
        tr.forget_all()
        store = tr._truth_lens()._store
        assert store.get_baseline("marcus") is None
        assert store.get_baseline("dana") is None


class TestTheEarDrivesIt:
    """The producer is only reachable if the ear actually calls it."""

    def _ear_src(self):
        import pathlib
        from dreamlayer.ai_brain.server import ear
        return pathlib.Path(ear.__file__).read_text(encoding="utf-8")

    def test_ingest_caption_feeds_the_transcript(self):
        assert "self.truth.note_transcript(text, speaker or \"\")" in self._ear_src()

    def test_note_speech_audio_feeds_the_prosody_channel(self):
        assert "self.truth.note_audio(segment, sample_rate)" in self._ear_src()

    def test_the_audio_feed_is_not_behind_the_interpreter_switch(self):
        """Two independent features shared one early return: `note_speech_audio`
        opened with the interpreter's own `if not self._interpret_on: return`,
        so a wearer who wanted the room read and no translation got silence for
        a reason they had never set.

        Asserted behaviourally rather than by reading the source, because the
        source now DISCUSSES that guard in prose and a textual check matches the
        explanation instead of the code.
        """
        from dreamlayer.ai_brain.server.ear import EarHost
        ear = EarHost(FakeBrain())
        assert ear._interpret_on is False, "fixture: the interpreter must be off"
        got: list = []
        ear.truth.note_audio = lambda seg, rate=16000: got.append((len(seg), rate))
        ear.note_speech_audio([0.0] * 1024, 16000)
        assert got == [(1024, 16000)], (
            "with the interpreter off the room read received no audio — the two "
            "features are sharing an early return again")

    def test_the_transcript_is_fed_after_the_pii_scrub(self):
        """What the gauge reasons over must be what the store holds and never
        more."""
        body = self._ear_src().split("def ingest_caption(", 1)[1]
        assert body.index("default_redactor") < body.index("self.truth.note_transcript")
