"""`live_interpret` — someone's foreign speech, voiced back in your language.

Ranked the highest-value dormant capability by declared gain (+4.5), and the
reason it was cheap is the reason it is worth pinning hard: almost all of it
already existed and was joined by nothing.

  * `CapturePipeline._endpoint` has called `note_speech_audio(segment, rate)` on
    its host at every endpointed segment since it was written.
  * `RosettaLens.hear(audio, rate, target)` has been able to carry that audio
    across languages just as long — `interpret_fn` is a real constructor
    parameter, not a docstring aspiration.
  * `rosetta_seamless.make_interpret_fn()` is a ready-to-wire callable.
  * `orchestrator/ops_juno_attention.py` implements the seam.

The Brain's `EarHost` simply had no `note_speech_audio`, and `world_lens.py` built
its `RosettaLens` without `interpret_fn`. So the hook found nothing callable and
the lens had nothing to call: importable, never called, one method wide.

WHAT THESE TESTS ARE MOSTLY ABOUT. Not the happy path — the gates, and the
honesty of the capability report. A microphone that also runs a translation model
over every utterance is the most consequential thing in this product, so every
refusal below is tested separately from every other, and `live_interpret` is
promoted on a stricter test than any other ear cap: a segment must have actually
come back translated. That is the `tagger_live` lesson (a present wheel with no
model loaded reported live for a seam that could only return nothing) applied to
a model whose lazy load is measured in gigabytes.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server.ear import EAR_CAPS, EarHost
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.rosetta import RosettaLens

LIVE = (pathlib.Path(__file__).resolve().parents[1]
        / "ai_brain" / "server" / "live.py")
PANEL = (pathlib.Path(__file__).resolve().parents[1]
         / "ai_brain" / "server" / "panel.py")


@pytest.fixture
def brain():
    b = Brain(tempfile.mkdtemp())
    b.config.listen_enabled = True
    return b


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card, veil_ok)) or 1)
    return seen


def _ear(brain, *, reply="the meeting moved to Thursday", target="en",
         wired=True, listening=True):
    """An EarHost whose Rosetta has (or has not) a working interpreter.

    The lens is swapped rather than the whole world lens: `_rosetta()` is
    deliberately defined as "the ONE lens the eye also translates with", and a
    test that replaced that indirection would stop checking it.
    """
    ear = EarHost(brain)
    calls = []

    def _interp(audio, sample_rate=16000, tgt="en"):
        calls.append({"audio": audio, "rate": sample_rate, "target": tgt})
        return reply

    lens = RosettaLens(interpret_fn=_interp if wired else None, engine="argos")
    ear._rosetta = lambda: lens
    if listening:
        ear._pipe = object()             # `listening` reads _pipe is not None
    ear.set_interpret(True, target)
    return ear, calls


# --- the gates, one at a time ----------------------------------------------

class TestEveryRefusalSeparately:

    def test_off_by_default_nothing_is_interpreted(self, brain):
        ear, calls = _ear(brain)
        ear.set_interpret(False)
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls == [] and pushes == []

    def test_the_veil_refuses_a_segment_already_in_hand(self, brain):
        """The pipeline gates its own door — `push_pcm` accumulates nothing while
        veiled — but this segment was gathered BEFORE the shield came down, and it
        is in hand now. So the gate is checked again here, at the point of use."""
        ear, calls = _ear(brain)
        pushes = _pushes(brain)
        brain.incognito_now = lambda: True
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls == [], "a veiled utterance was translated"
        assert pushes == []

    def test_a_brain_whose_posture_raises_is_treated_as_veiled(self, brain):
        """Fails CLOSED. An unknown posture is not a permission.

        Caught by `_EarGate` itself here, one layer below — which is exactly why
        the test below exists as well."""
        ear, calls = _ear(brain)

        def _boom():
            raise RuntimeError("posture unreadable")
        brain.incognito_now = _boom
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls == []

    def test_a_GATE_that_raises_is_also_treated_as_veiled(self, brain):
        """The OUTER try/except, which the test above does not reach.

        `_EarGate.allow_capture` already fails closed on a raising posture, so
        with only that test a mutation turning this method's `except … return`
        into a `pass` survived — the utterance would have been translated whenever
        the gate OBJECT itself was broken rather than the posture behind it.
        `privacy` is an attribute, so it can be absent, None, or a stub; the gate
        raising is a real state and its answer must be "no".
        """
        ear, calls = _ear(brain)
        pushes = _pushes(brain)

        class _BrokenGate:
            def allow_capture(self):
                raise RuntimeError("gate is broken")
        ear.privacy = _BrokenGate()
        ear.note_speech_audio([0.1] * 1600, 16000)     # must not raise
        assert calls == [], "a broken privacy gate let audio through"
        assert pushes == []

    def test_a_missing_gate_is_treated_as_veiled(self, brain):
        """The other shape of the same failure: no gate at all."""
        ear, calls = _ear(brain)
        ear.privacy = None
        ear.note_speech_audio([0.1] * 1600, 16000)     # must not raise
        assert calls == []

    def test_no_interpreter_wired_is_a_silent_no_op(self, brain):
        """The pack is absent: `hear()` would no-op anyway, but we must not push a
        card, count an utterance, or promote the capability off nothing."""
        ear, _calls = _ear(brain, wired=False)
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert pushes == []
        assert ear.interpreted_count == 0
        assert ear.interpreting is False

    def test_an_interpreter_that_raises_never_reaches_the_capture_loop(self, brain):
        ear = EarHost(brain)

        def _boom(audio, sample_rate=16000, tgt="en"):
            raise RuntimeError("model exploded")
        ear._rosetta = lambda: RosettaLens(interpret_fn=_boom)
        ear._pipe = object()
        ear.set_interpret(True, "en")
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)     # must not raise
        assert pushes == []
        assert ear.interpreting is False

    def test_an_empty_translation_is_a_miss_not_a_card(self, brain):
        """The model declining — still loading, or the speech was already in the
        target language. An honest miss must not push an empty card, and above all
        must not count as proof the interpreter works."""
        ear, calls = _ear(brain, reply="   ")
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls, "the interpreter was not even asked"
        assert pushes == []
        assert ear.interpreted_count == 0
        assert ear.interpreting is False

    def test_a_private_zone_suspends_interpretation(self, brain):
        """`incognito_now` is the one gate, and a private zone is one of its terms
        — so this is really a test that the interpreter reads the composite
        posture rather than the incognito flag alone."""
        ear, calls = _ear(brain)
        brain.private_zone_now = lambda: "the flat"
        # zones raise the shield through the same predicate the ear already reads
        if not brain.incognito_now():
            pytest.skip("private zone does not feed incognito_now on this build")
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls == []


# --- the happy path, and what reaches the glass ----------------------------

class TestWhatArrivesOnTheLens:

    def test_the_segment_and_rate_reach_the_interpreter_unchanged(self, brain):
        """The audio is passed through, not re-sampled or truncated here — the
        adapter does its own coercion and knows its model's rate."""
        ear, calls = _ear(brain)
        seg = [0.25] * 800
        ear.note_speech_audio(seg, 8000)
        assert len(calls) == 1
        assert calls[0]["audio"] is seg
        assert calls[0]["rate"] == 8000

    def test_the_configured_target_language_is_the_one_asked_for(self, brain):
        ear, calls = _ear(brain, target="ja")
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert calls[0]["target"] == "ja"

    def test_it_pushes_a_live_caption_card_with_the_meaning(self, brain):
        ear, _ = _ear(brain, reply="the meeting moved to Thursday")
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert len(pushes) == 1
        kind, card, veil_ok = pushes[0]
        assert kind == "interpret"
        assert card["type"] == "LiveCaptionCard"
        assert card["translation"] == "the meeting moved to Thursday"
        assert veil_ok is False, "a card that is nothing but captured speech"

    def test_no_source_transcript_is_invented(self, brain):
        """SeamlessM4T goes speech→target-text in ONE pass and never produces a
        transcript of the original; `RosettaLens.hear` documents `source_text` as
        empty for that reason. Filling `original` with the ASR's separate guess
        would look like the same utterance while being a different engine's."""
        ear, _ = _ear(brain)
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        card = pushes[0][1]
        assert card["original"] == ""
        assert card["src_lang"] == ""
        assert card["footer"] == ""

    def test_the_card_stays_until_the_next_utterance_replaces_it(self, brain):
        """`dismiss_ms: 0` is the card contract for "stays until replaced", which
        is what makes a stream of them readable mid-conversation."""
        ear, _ = _ear(brain)
        pushes = _pushes(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert pushes[0][1]["dismiss_ms"] == 0

    def test_a_failing_push_does_not_lose_the_count(self, brain):
        """The utterance WAS interpreted; a broken display must not un-prove it."""
        ear, _ = _ear(brain)

        def _boom(kind, card=None, veil_ok=False):
            raise RuntimeError("no lens attached")
        brain.push_event = _boom
        ear.note_speech_audio([0.1] * 1600, 16000)     # must not raise
        assert ear.interpreted_count == 1
        assert ear.interpreting is True


# --- the capability report, held to the stricter test ----------------------

class TestTheCapabilityIsPromotedOnlyByPROOF:

    def test_live_interpret_is_an_ear_cap_now(self):
        assert "live_interpret" in EAR_CAPS

    def test_it_stays_declared_dormant_so_the_default_is_honest(self):
        """Like the other ear caps: listed in `_NOT_WIRED` so a Brain that is not
        listening reports "dormant", and promoted at runtime while it genuinely
        runs. Removing it from that set would light it green on a bare install."""
        from dreamlayer import capabilities as C
        assert "live_interpret" in C._NOT_WIRED

    def test_the_wheel_alone_does_not_promote_it(self, brain):
        """The `tagger_live` lesson. An interpreter object with no model loaded
        reports `can_interpret` true — that is only the wheel — and must NOT be
        reported active."""
        ear, _ = _ear(brain)
        assert ear._can_interpret() is True
        assert ear.interpreting is False, "promoted before translating anything"

    def test_one_real_translation_promotes_it(self, brain):
        ear, _ = _ear(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert ear.interpreting is True

    def test_switching_it_off_demotes_it_without_forgetting_the_proof(self, brain):
        """Two different facts. "Is it running" follows the switch; "did this
        process ever load the model" cannot become false again, and re-proving it
        would need another utterance the wearer has not spoken yet."""
        ear, _ = _ear(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        ear.set_interpret(False)
        assert ear.interpreting is False
        assert ear._interpret_ok is True

    def test_a_closed_ear_demotes_it(self, brain):
        """No microphone, nothing to interpret — whatever the switch says."""
        ear, _ = _ear(brain)
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert ear.interpreting is True
        ear._pipe = None
        assert ear.interpreting is False

    def test_the_env_flag_follows_the_ear(self, brain, monkeypatch):
        """`_sync_ear_wired` is what `capabilities.state()` actually reads. The
        flag has to be SET while interpreting and CLEARED when not, or the meter
        keeps claiming a feature that stopped."""
        import os
        monkeypatch.delenv("DL_WIRED_LIVE_INTERPRET", raising=False)
        ear, _ = _ear(brain)
        brain._ear = ear
        brain._sync_ear_wired()
        assert "DL_WIRED_LIVE_INTERPRET" not in os.environ
        ear.note_speech_audio([0.1] * 1600, 16000)
        assert os.environ.get("DL_WIRED_LIVE_INTERPRET") == "1"
        ear.set_interpret(False)
        brain._sync_ear_wired()
        assert "DL_WIRED_LIVE_INTERPRET" not in os.environ

    def test_the_first_line_promotes_it_without_waiting_for_a_poll(self, brain,
                                                                  monkeypatch):
        """A capability that only goes active on the next status poll reads
        dormant while it is demonstrably working."""
        import os
        monkeypatch.delenv("DL_WIRED_LIVE_INTERPRET", raising=False)
        ear, _ = _ear(brain)
        brain._ear = ear
        ear.note_speech_audio([0.1] * 1600, 16000)     # no explicit sync call
        assert os.environ.get("DL_WIRED_LIVE_INTERPRET") == "1"


# --- the lens the eye and the ear share ------------------------------------

class TestTheOneRosettaLens:

    def test_the_world_lens_wires_an_interpreter_when_the_wheel_is_present(
            self, brain, monkeypatch):
        """The missing argument — the whole of `live_interpret` on the Brain.
        `RosettaLens` was constructed here with `translate_fn` only, so `_interpret`
        was None and no wearer setting could change it. Mirrors orchestrator.py,
        which got this right.

        The wheel's presence is FORCED rather than observed. Asserting
        `wired is SeamlessInterpreter.available` reads like a test and is vacuous
        wherever transformers is absent — which is CI and every dev box that has
        not opted into a multi-gigabyte model: both sides were False, so a mutation
        deleting the argument entirely passed. Patch the availability instead, and
        the assertion means something everywhere.
        """
        import dreamlayer.rosetta_seamless as RS
        monkeypatch.setattr(RS.SeamlessInterpreter, "available", True)
        monkeypatch.setattr(RS, "make_interpret_fn",
                            lambda *a, **k: (lambda *_a, **_k: "carried across"))
        brain._world_lens = None                      # force a rebuild
        lens = brain.world_lens().rosetta
        assert getattr(lens, "_interpret", None) is not None, (
            "interpret_fn was not passed to the lens the Brain builds")
        # and it is the interpreter that actually answers, not a stub name match
        assert lens.hear([0.1] * 16, 16000, "en").translated == "carried across"

    def test_no_interpreter_is_wired_when_the_wheel_is_absent(self, brain,
                                                              monkeypatch):
        """The other direction, so the fix cannot be "always wire something".
        A fabricated interpreter would report the capability green and then return
        nothing."""
        import dreamlayer.rosetta_seamless as RS
        monkeypatch.setattr(RS.SeamlessInterpreter, "available", False)
        brain._world_lens = None
        assert getattr(brain.world_lens().rosetta, "_interpret", None) is None

    def test_the_ear_uses_the_same_lens_the_eye_translates_with(self, brain):
        """Not a private second lens. A copy would drift from the one already in
        the object-lens registry, and the eye's Argos backend would be missing
        from it."""
        ear = EarHost(brain)
        assert ear._rosetta() is brain.world_lens().rosetta

    def test_a_brain_with_no_world_lens_does_not_raise(self, brain):
        """`_rosetta` is called from the capture loop; it must degrade, not throw."""
        ear = EarHost(brain)

        def _boom():
            raise RuntimeError("no lens")
        brain.world_lens = _boom
        assert ear._rosetta() is None
        ear.set_interpret(True, "en")
        ear.note_speech_audio([0.1] * 1600, 16000)      # must not raise


# --- the surfaces ----------------------------------------------------------

class TestItIsReachableFromBothSurfaces:

    def test_the_brain_toggle_persists_and_reports_the_truth(self, brain):
        out = brain.set_interpret(True, "ja")
        assert brain.config.interpret_enabled is True
        assert brain.config.interpret_target == "ja"
        assert out["on"] is True and out["target"] == "ja"

    def test_the_toggle_reaches_both_ears(self, brain):
        """The Mac's microphone and the phone acting as the mic are two EarHosts,
        and the wearer set ONE switch. A toggle that reached only the local ear
        would look dead to anyone using the Live Lens as their mic — which is the
        likelier way to use an interpreter, since it is the ear you take to the
        conversation."""
        brain._ear = EarHost(brain)
        brain._remote_ear = EarHost(brain)
        brain.set_interpret(True, "fr")
        for e in (brain._ear, brain._remote_ear):
            assert e._interpret_on is True
            assert e._interpret_target == "fr"

    def test_a_config_write_reaches_the_running_ear(self, brain):
        """The write-only-setting bug. `apply_config` persisted the flag and left
        the open microphone unchanged until the next restart, so the panel switch
        said on while the ear was not interpreting."""
        brain._ear = EarHost(brain)
        brain.apply_config({"interpret_enabled": True, "interpret_target": "de"})
        assert brain._ear._interpret_on is True
        assert brain._ear._interpret_target == "de"

    def test_a_restart_carries_the_setting_into_a_fresh_ear(self, brain):
        """`EarHost.__init__` starts with the interpreter off, so without
        `_apply_interpret` a wearer who had it on, restarted, and turned Listening
        back on got a silent ear and a switch that claimed otherwise.

        Goes through `start_ear`, NOT `_apply_interpret` directly: testing the
        method proves the method, and a mutation deleting the CALL from `start_ear`
        survived a test that did. The start itself fails here (no speech engine
        installed) and that is fine — the setting must be applied either way, since
        a wearer who installs the pack and retries must not need a second toggle.
        """
        brain.config.interpret_enabled = True
        brain.config.interpret_target = "es"
        brain.start_ear()
        assert brain._ear is not None
        assert brain._ear._interpret_on is True
        assert brain._ear._interpret_target == "es"

    def test_the_phone_becoming_the_mic_also_carries_the_setting(self, brain):
        """The same call site on the remote-ear path. Two places construct an
        `EarHost`; each needs the setting pushed in."""
        brain.config.remote_listen_enabled = True
        brain.config.interpret_enabled = True
        brain.config.interpret_target = "ko"
        brain.hear_remote([0.0] * 160)
        if brain._remote_ear is None:
            pytest.skip("no on-device ASR engine to open a remote ear")
        assert brain._remote_ear._interpret_on is True
        assert brain._remote_ear._interpret_target == "ko"

    def test_the_target_language_never_becomes_empty(self, brain):
        for bad in ("", "   ", None):
            brain.set_interpret(True, bad)
            assert brain.config.interpret_target.strip(), bad

    def test_an_absurd_target_is_bounded_not_stored_whole(self, brain):
        brain.set_interpret(True, "x" * 200)
        assert len(brain.config.interpret_target) <= 8

    def test_the_EAR_bounds_and_cleans_the_target_itself(self, brain):
        """`Brain.set_interpret` bounds the CONFIG copy, and `EarHost` bounds its
        own — two separate assignments, and a test that only checked the config one
        left the ear's mutable to anything. It is the ear's value that reaches
        `hear()`, so `str(None)` becoming the language "None" would be a silent
        fallback to English on every utterance.
        """
        ear = EarHost(brain)
        ear.set_interpret(True, "y" * 200)
        assert len(ear._interpret_target) <= 8
        for bad in ("", "   ", None):
            ear.set_interpret(True, bad)
            assert ear._interpret_target == "en", bad

    def test_the_status_reports_the_four_facts_separately(self, brain):
        """They fail independently: the switch, the pack, whether it has ever
        produced a line, and how many. One boolean could not say which."""
        ear, _ = _ear(brain)
        brain._ear = ear
        st = brain.ear_status()
        for key in ("interpret", "interpret_target", "can_interpret",
                    "interpret_proved", "interpreted_count"):
            assert key in st, key

    def test_the_status_still_never_echoes_captured_content(self, brain):
        """The existing contract for this endpoint. A translated line is captured
        speech; counts are not."""
        ear, _ = _ear(brain, reply="a sentence someone said out loud")
        brain._ear = ear
        ear.note_speech_audio([0.1] * 1600, 16000)
        blob = repr(brain.ear_status())
        assert "a sentence someone said out loud" not in blob

    def test_the_live_lens_draws_it_properly_and_speaks_it(self):
        """The whole feature is "spoken into your ear" — drawing it silently would
        be the caption feature again. `speak()` already refuses when the voice
        switch is off or the veil is up, so this adds no new escape for audio."""
        src = LIVE.read_text(encoding="utf-8")
        assert 't === "LiveCaptionCard") glassInterpretCard' in src
        i = src.index("function glassInterpretCard")
        body = src[i:i + 2200]
        assert "speak(line)" in body, "the interpreter draws but never speaks"
        assert "c.translation" in body

    def test_the_live_lens_offers_a_chip_only_while_an_ear_is_open(self):
        """An interpreter with no microphone is a switch that cannot do anything."""
        src = LIVE.read_text(encoding="utf-8")
        assert 'id="interpbtn"' in src
        i = src.index("function _interpShow")
        body = src[i:i + 500]
        assert "hearOn || earListening" in body
        assert "el.hidden = !live" in body

    def test_the_panel_language_list_matches_what_the_model_supports(self):
        """A menu offering a language the adapter cannot map would silently fall
        back to English — the picker and `_LANG3` have to be one list."""
        from dreamlayer.rosetta_seamless import _codes
        src = PANEL.read_text(encoding="utf-8")
        i = src.index('id="interpTarget"')
        block = src[i:src.index("</select>", i)]
        for code in _codes():
            assert f'value="{code}"' in block, f"panel cannot select {code}"

    def test_the_panel_saves_through_the_route_not_just_config(self):
        """A `/config` write alone would persist the flag and leave the running
        microphone unchanged."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function saveInterpret")
        assert "/dreamlayer/interpret" in src[i:i + 500]

    def test_the_route_is_registered(self):
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        assert '"/dreamlayer/interpret": _post_interpret' in src
