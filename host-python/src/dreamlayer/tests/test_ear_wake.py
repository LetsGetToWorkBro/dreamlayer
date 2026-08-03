"""test_ear_wake.py — "Hey Juno" reaches the Brain at last.

`EarHost.hear` was `return`. The always-on ear transcribed everything and folded
it into memory, and the one gesture the product is named for did nothing — so
`wake_word` could not be wired, because there was nothing for a spotter to
trigger. `CapturePipeline` made that worse in a way nobody could see from
outside: it ACCEPTED a `wake=` engine, assigned it to `self.wake`, and never
referenced it again. A caller could hand it a working spotter and the pipeline
would drop it on the floor.

Two signals decide whether we were addressed — the acoustic spotter and the
text-level regex — and the tests that matter here are about how they combine.
They are OR'ed, never AND'ed: an engine that could VETO the regex would make a
wake stop working the day the wearer installed it, which is the floor rule this
repo holds every optional dependency to, inverted.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.schema import Answer
from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.orchestrator.capture import CapturePipeline, _accepts


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


def _answers(brain, text="Ana said the deposit clears Friday", conf=0.8):
    calls = []

    def _ask(query, no_cloud=False):
        calls.append({"query": query, "no_cloud": no_cloud})
        return Answer(text=text, sources=[], tier="laptop", confidence=conf)
    brain.ask = _ask
    return calls


class _Spotter:
    """A wake engine with a switch, standing in for openWakeWord."""

    def __init__(self, fires=False, score=0.9, boom=False):
        self.fires = fires
        self.score = score
        self.boom = boom
        self.calls = 0
        self._model = object()          # a LOADED model — see `_wake_engine`

    def detect(self, samples):
        self.calls += 1
        if self.boom:
            raise RuntimeError("onnxruntime session died")
        return (self.fires, self.score)


class _Hub:
    """Minimal CapturePipeline host that records what it was told."""

    def __init__(self):
        self.heard = []
        self.captions = []

    def hear(self, text, addressed=None):
        self.heard.append((text, addressed))

    def ingest_caption(self, text, speaker=None):
        self.captions.append((text, speaker))


class _OldHub:
    """A host written against the ORIGINAL one-argument contract."""

    def __init__(self):
        self.heard = []

    def hear(self, text):
        self.heard.append(text)

    def ingest_caption(self, text, speaker=None):
        pass


class _ASR:
    def __init__(self, text):
        self.text = text

    def transcribe(self, segment):
        return self.text


class TestThePipelineNoLongerDropsTheEngine:
    """`self.wake` was assigned and referenced nowhere else in the file."""

    def _pipe(self, hub, wake, text="hey juno what did Ana say"):
        return CapturePipeline(hub, asr=_ASR(text), wake=wake)

    def test_the_spotter_is_actually_consulted(self):
        hub, spot = _Hub(), _Spotter(fires=True)
        p = self._pipe(hub, spot)
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert spot.calls == 1, "the wake engine was never asked"
        assert hub.heard == [("hey juno what did Ana say", True)]

    def test_it_runs_once_per_utterance_not_once_per_window(self):
        """A segment is one complete utterance, which is the granularity
        "was I addressed?" is asked at — and one inference per utterance
        instead of five per second."""
        hub, spot = _Hub(), _Spotter()
        p = self._pipe(hub, spot)
        for _ in range(4):
            p.push_pcm([0.1] * 200, ts=0.0)
        p._seg = [0.1] * 800
        p._endpoint(1.0)
        assert spot.calls == 1

    def test_no_engine_reports_none_not_false(self):
        """The hub must tell "nothing listened" from "something listened and
        heard nothing" — the first means trust the regex."""
        hub = _Hub()
        self._pipe(hub, None)._endpoint.__self__._seg = []
        p = self._pipe(hub, None)
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert hub.heard == [("hey juno what did Ana say", None)]

    def test_a_spotter_that_raises_never_breaks_capture(self):
        hub, spot = _Hub(), _Spotter(boom=True)
        p = self._pipe(hub, spot)
        p._seg = [0.1] * 800
        assert p._endpoint(0.0) == "hey juno what did Ana say"
        assert hub.heard == [("hey juno what did Ana say", None)]
        assert hub.captions, "the utterance lost its memory over a wake failure"

    def test_the_counter_follows_fires_not_calls(self):
        hub, spot = _Hub(), _Spotter(fires=False)
        p = self._pipe(hub, spot)
        for _ in range(3):
            p._seg = [0.1] * 800
            p._endpoint(0.0)
        assert spot.calls == 3
        assert p.wakes == 0, "a spotter that heard nothing counted three wakes"
        spot.fires = True
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert p.wakes == 1

    def test_last_wake_carries_the_score(self):
        hub, spot = _Hub(), _Spotter(fires=True, score=0.77)
        p = self._pipe(hub, spot)
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert p.last_wake == (True, 0.77)


class TestTheHostContractStayedCompatible:
    """`hear(text)` is the documented contract and other hosts implement it."""

    def test_a_one_argument_host_is_still_called_correctly(self):
        hub, spot = _OldHub(), _Spotter(fires=True)
        p = CapturePipeline(hub, asr=_ASR("hey juno hello"), wake=spot)
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert hub.heard == ["hey juno hello"]

    def test_the_signature_is_probed_once_not_per_utterance(self):
        hub = _Hub()
        p = CapturePipeline(hub, asr=_ASR("hi"))
        assert p._hear_takes_wake is None
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert p._hear_takes_wake is True

    def test_the_probe_never_calls_the_hub_to_find_out(self):
        """Calling with the kwarg and catching TypeError would swallow a
        TypeError raised INSIDE the hub and silently run the whole wake/command
        path a second time on one utterance."""
        calls = []

        class _Raises:
            def hear(self, text, addressed=None):
                calls.append(text)
                raise TypeError("something inside hear() is broken")

            def ingest_caption(self, text, speaker=None):
                pass

        p = CapturePipeline(_Raises(), asr=_ASR("hi"))
        p._seg = [0.1] * 800
        p._endpoint(0.0)
        assert calls == ["hi"], f"hear() ran {len(calls)} times for one utterance"

    @pytest.mark.parametrize("fn,want", [
        (lambda text, addressed=None: None, True),
        (lambda text: None, False),
        (lambda text, **kw: None, True),
        (lambda *a: None, False),
    ])
    def test_the_signature_probe_reads_what_it_claims(self, fn, want):
        assert _accepts(fn, "addressed") is want

    def test_a_c_callable_is_not_a_crash(self):
        assert _accepts(len, "addressed") is False


class TestTheTwoWakeSignalsAreOred:
    """The floor rule, inverted: installing the optional engine must never LOSE
    a wake the fallback would have caught."""

    def test_the_text_regex_alone_still_wakes(self, brain):
        calls, seen = _answers(brain), _pushes(brain)
        EarHost(brain).hear("hey juno what did Ana say", addressed=None)
        assert calls, "the regex path stopped working"
        assert seen and seen[0][1]["type"] == "JunoReplyCard"

    def test_a_spotter_saying_no_cannot_veto_the_regex(self, brain):
        """The regression this is built to prevent: a quiet "hey juno" the
        model scores at 0.4 and ASR transcribes perfectly would stop working
        the day the wearer installed the engine."""
        calls = _answers(brain)
        EarHost(brain).hear("hey juno what did Ana say", addressed=False)
        assert calls, "the acoustic engine vetoed a wake the regex caught"

    def test_the_spotter_alone_wakes_when_asr_misheard_the_phrase(self, brain):
        """The prize. ASR mangles the phrase constantly ("hey you know", "a j
        you know"); the spotter listens to the audio, so it catches those."""
        calls = _answers(brain)
        EarHost(brain).hear("hey you know what did Ana say", addressed=True)
        assert calls, "an acoustically-confirmed wake was dropped"
        assert calls[0]["query"], "the query came through empty"

    def test_the_whole_line_is_the_question_when_only_audio_confirmed(self,
                                                                     brain):
        """There is no phrase to strip off a line the regex did not match."""
        calls = _answers(brain)
        EarHost(brain).hear("hey you know when does the lease end",
                            addressed=True)
        assert "lease" in calls[0]["query"]

    @pytest.mark.parametrize("line", [
        "the deposit clears Friday",
        "what did you think of the flat",
    ])
    def test_ordinary_conversation_is_never_answered(self, brain, line):
        calls, seen = _answers(brain), _pushes(brain)
        EarHost(brain).hear(line, addressed=False)
        assert not calls, "the ear answered a line nobody addressed to it"
        assert not seen

    @pytest.mark.parametrize("line", [
        "juno is a nice name for a dog",
        "dreamlayer keeps everything on the device",
        "Juno, the film, is underrated",
    ])
    def test_the_product_saying_its_own_name_is_not_being_addressed(self, brain,
                                                                    line):
        """A real defect this wiring would otherwise have INTRODUCED, caught by
        its own test. `voice.WAKE` holds bare "juno" and bare "dreamlayer", and
        `detect_wake` matches either as a leading token — harmless while
        `hear()` was a `return`, and the moment it answers, any sentence
        starting with the product's own name becomes a question drawn on the
        glass mid-conversation. Wearers of this product say those words."""
        from dreamlayer.orchestrator.voice import detect_wake
        assert detect_wake(line)[0] is True, (
            "detect_wake no longer matches this, so the test proves nothing")
        calls = _answers(brain)
        EarHost(brain).hear(line, addressed=None)
        assert not calls

    def test_the_bare_forms_still_work_where_somebody_chose_to_speak(self):
        """Only the AMBIENT path is narrowed. `/dreamlayer/voice` — where the
        wearer deliberately opened the mic — keeps every phrase."""
        from dreamlayer.orchestrator.voice import WAKE, detect_wake
        assert "juno" in WAKE
        assert detect_wake("juno what did Ana say")[0] is True

    def test_the_salutation_set_is_derived_not_duplicated(self):
        """Adding "hi juno" to `WAKE` must arm the ambient path automatically,
        and adding a bare word must not — which is the whole asymmetry."""
        from dreamlayer.orchestrator.voice import WAKE
        for phrase in (p for p in WAKE if " " in p):
            assert EarHost._salutation(phrase + " what did Ana say")[0] is True
        for phrase in (p for p in WAKE if " " not in p):
            assert EarHost._salutation(phrase + " what did Ana say")[0] is False

    def test_the_wake_phrase_alone_asks_nothing(self, brain):
        calls = _answers(brain)
        EarHost(brain).hear("hey juno", addressed=True)
        assert not calls, "a bare wake phrase was sent to ask() as an empty query"


class TestThePosture:
    def test_incognito_answers_nothing(self, brain, monkeypatch):
        calls, seen = _answers(brain), _pushes(brain)
        monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
        EarHost(brain).hear("hey juno what did Ana say", addressed=True)
        assert not calls and not seen

    def test_an_unreadable_posture_is_treated_as_veiled(self, brain,
                                                        monkeypatch):
        calls = _answers(brain)

        def _boom(self):
            raise RuntimeError("trust store unreadable")
        monkeypatch.setattr(type(brain), "incognito_now", _boom)
        EarHost(brain).hear("hey juno what did Ana say", addressed=True)
        assert not calls, "an unreadable veil resolved to 'answer it'"

    def test_an_addressed_question_uses_the_wearers_own_cloud_setting(self,
                                                                     brain):
        """The deliberate difference from `note_question`, which forces
        `no_cloud=True` because a bystander's overheard sentence chose nothing.
        This utterance was ADDRESSED to the device — the wearer's own request,
        which is what their cloud configuration exists for — so it takes the
        same posture as `/dreamlayer/voice`. `Brain.ask` still refuses to egress
        while incognito, and incognito is already checked above."""
        calls = _answers(brain)
        EarHost(brain).hear("hey juno what did Ana say", addressed=True)
        assert calls[0]["no_cloud"] is False

    @pytest.mark.parametrize("line", [
        "hey juno remember that Ana owes me twenty",   # -> debt
        "hey juno note that Ana said the lease is signed",  # -> note_person
    ])
    def test_only_ask_and_recall_are_routed(self, brain, line):
        """Every other intent is a device ACTION that WRITES — a debt recorded,
        a person noted — and firing those from room audio is a far bigger
        consent question than answering one. The phone and panel own that path
        deliberately, not by omission.

        The two cases here are checked against `parse_intent` first, because
        most action-sounding phrases ("stash this", "turn on focus") actually
        classify as `ask` and would prove nothing about this guard."""
        from dreamlayer.orchestrator.voice import parse_intent
        _wake, rest = EarHost._salutation(line)
        assert parse_intent(rest).kind not in ("ask", "recall"), (
            f"{rest!r} no longer parses as an action — bad fixture")

        calls, seen = _answers(brain), _pushes(brain)
        EarHost(brain).hear(line, addressed=True)
        assert not calls, "an ambient utterance triggered a device action"
        assert not seen

    def test_a_runaway_spotter_cannot_repaint_the_glass(self, brain):
        seen = _pushes(brain)
        _answers(brain)
        ear = EarHost(brain)
        for _ in range(6):
            ear.hear("hey juno what did Ana say", addressed=True)
        assert len(seen) == 1, f"{len(seen)} cards from a stuck spotter"

    def test_two_real_questions_in_a_row_both_answer(self, brain,
                                                     monkeypatch):
        """The guard is a runaway stop, not a throttle — `_ANSWER_MIN_GAP_S` at
        20 s would silently eat the follow-up."""
        seen = _pushes(brain)
        _answers(brain)
        ear = EarHost(brain)
        ear.hear("hey juno what did Ana say", addressed=True)
        ear._last_wake_ts -= (ear._WAKE_MIN_GAP_S + 0.1)
        ear.hear("hey juno and when does it clear", addressed=True)
        assert len(seen) == 2
        assert ear._WAKE_MIN_GAP_S < ear._ANSWER_MIN_GAP_S

    def test_nothing_known_says_so_rather_than_drawing_nothing(self, brain):
        seen = _pushes(brain)
        brain.ask = lambda q, no_cloud=False: None
        EarHost(brain).hear("hey juno what did Ana say", addressed=True)
        assert seen and seen[0][1]["type"] == "LowConfidenceCard"

    def test_a_failing_ask_never_costs_the_utterance(self, brain):
        def _boom(q, no_cloud=False):
            raise RuntimeError("index corrupt")
        brain.ask = _boom
        EarHost(brain).hear("hey juno what did Ana say", addressed=True)  # no raise


class TestTheEngineItBuilds:
    def test_a_spotter_whose_model_failed_to_load_is_not_held(self, brain,
                                                              monkeypatch):
        """`OpenWakeWordEngine` keeps `available` True with `_model` None after
        a load failure, and `detect` then returns (False, 0.0) forever. Handing
        that to the pipeline would turn `addressed` from None ("trust the
        regex") into False ("an engine listened and heard nothing") on every
        segment — the same information, worse-sounding — and pin `wake_live()`
        false while the report insisted the capability was installed."""
        import dreamlayer.orchestrator.wakeword as ww

        class _Dead:
            available = True
            _model = None
        monkeypatch.setattr(ww, "OpenWakeWordEngine", _Dead)
        assert EarHost(brain)._wake_engine() is None

    def test_a_loaded_spotter_is_held_and_built_once(self, brain, monkeypatch):
        import dreamlayer.orchestrator.wakeword as ww
        built = []

        class _Live:
            _model = object()

            def __init__(self):
                built.append(1)
        monkeypatch.setattr(ww, "OpenWakeWordEngine", _Live)
        ear = EarHost(brain)
        first = ear._wake_engine()
        assert first is not None
        assert ear._wake_engine() is first
        assert len(built) == 1, "a model reloaded per utterance"

    def test_an_import_failure_is_not_a_crash(self, brain, monkeypatch):
        import dreamlayer.orchestrator.wakeword as ww

        def _boom():
            raise RuntimeError("no onnxruntime")
        monkeypatch.setattr(ww, "OpenWakeWordEngine", _boom)
        assert EarHost(brain)._wake_engine() is None


class TestThePromotionFollowsTheSpotterNotTheAnswer:
    def test_wake_live_is_false_before_anything_fires(self, brain):
        assert EarHost(brain).wake_live() is False

    def test_answering_on_the_regex_alone_does_not_promote(self, brain):
        """The sharpest line here. `hear()` answers on the text regex too, and
        that has always worked — promoting on an answer would report the
        acoustic engine live on a machine with no engine at all."""
        _answers(brain)
        _pushes(brain)
        ear = EarHost(brain)
        ear.hear("hey juno what did Ana say", addressed=None)
        assert ear.wake_answers == 1
        assert ear.wake_live() is False

    def test_a_fired_spotter_promotes(self, brain):
        ear = EarHost(brain)
        hub_pipe = CapturePipeline(_Hub(), asr=_ASR("hey juno hi"),
                                   wake=_Spotter(fires=True))
        hub_pipe._seg = [0.1] * 800
        hub_pipe._endpoint(0.0)
        ear._pipe = hub_pipe
        assert ear.wake_live() is True

    def test_the_sync_reads_it_fresh_rather_than_at_mic_open(self, brain,
                                                             monkeypatch):
        """`active_caps` is fixed when the microphone opens; a spotter fires
        later, so a start-time set could never carry this."""
        import os
        monkeypatch.delenv("DL_WIRED_WAKE_WORD", raising=False)
        ear = EarHost(brain)
        ear._pipe = CapturePipeline(_Hub(), asr=_ASR("hi"))
        brain._ear = ear
        brain._sync_ear_wired()
        assert "DL_WIRED_WAKE_WORD" not in os.environ

        ear._pipe.wakes = 1
        brain._sync_ear_wired()
        assert os.environ.get("DL_WIRED_WAKE_WORD") == "1"

        ear._pipe.wakes = 0
        brain._sync_ear_wired()
        assert "DL_WIRED_WAKE_WORD" not in os.environ

    def test_a_stopped_ear_promotes_nothing(self, brain, monkeypatch):
        import os
        monkeypatch.delenv("DL_WIRED_WAKE_WORD", raising=False)
        ear = EarHost(brain)
        ear._pipe = None                          # not listening
        brain._ear = ear
        brain._sync_ear_wired()
        assert "DL_WIRED_WAKE_WORD" not in os.environ
