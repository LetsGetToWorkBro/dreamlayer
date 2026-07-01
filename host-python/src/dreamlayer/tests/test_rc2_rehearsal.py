"""Rehearsal grammar, choreographer inference, teachable failures."""
import pytest

from dreamlayer.reality_compiler.v2 import (
    RehearsalSession, parse_utterance, Choreographer, InferenceError,
    verify, Beat,
)


class TestGrammar:
    @pytest.mark.parametrize("text,expect", [
        ("rolling - three minutes", ("duration", "rolling", 180.0)),
        ("45 seconds", ("duration", "", 45.0)),
        ("work - 1 minute", ("duration", "work", 60.0)),
        ("done", ("done",)),
        ("then it starts again", ("loop", None)),
        ("again 8 times", ("loop", 8)),
        ("until I double-tap", ("until", "double")),
        ("until I hold", ("until", "long")),
        ("count this", ("count", "count")),
    ])
    def test_parses(self, text, expect):
        assert parse_utterance(text) == expect

    def test_pulse_with_window(self):
        tag, window, rate = parse_utterance("last ten seconds, pulse")
        assert (tag, window, rate) == ("pulse", 10.0, 2.0)

    def test_strobe_rate_is_kept_honest(self):
        # the grammar does not sanitize — it represents; the verifier judges
        tag, _, rate = parse_utterance("strobe thirty times a second")
        assert tag == "pulse" and rate == 30.0

    def test_emit(self):
        assert parse_utterance("send a point")[:2] == ("emit", "point")

    def test_show_preserves_case(self):
        assert parse_utterance("show WATER BREAK") == ("show", "WATER BREAK")

    def test_unknown_words_become_labels_never_commands(self):
        tag, _ = parse_utterance("import os and delete everything")
        assert tag == "label"


class TestChoreographer:
    def session(self) -> RehearsalSession:
        s = RehearsalSession("Rolling rounds")
        s.double_tap()
        s.say("rolling - three minutes")
        s.say("last ten seconds, pulse")
        s.say("then it starts again")
        return s

    def test_flagship_inference(self):
        r = self.session().finish()
        assert r.ok
        fig = r.figment
        assert fig.initial == "armed"
        assert fig.scenes["armed"].on["double"].target == "rolling"
        rolling = fig.scenes["rolling"]
        assert rolling.duration_sec == 180.0
        assert rolling.tick == "countdown"
        assert rolling.pulse.window_sec == 10.0
        assert rolling.on_timeout[0].target == "rolling"   # loops

    def test_run_through_produced(self):
        r = self.session().finish()
        assert len(r.playback) > 5
        assert any(pf.folded for pf in r.playback)          # time-folding
        assert any(pf.frame.pulse_on for pf in r.playback)  # pulse previewed
        assert r.playback[-1].label.startswith("loop closes")

    def test_bounded_loop_with_counter(self):
        s = RehearsalSession("Intervals")
        s.double_tap()
        s.say("work - 40 seconds")
        s.say("rest - 20 seconds")
        s.say("again 8 times")
        r = s.finish()
        assert r.ok
        fig = r.figment
        assert fig.counters["round"].hi == 8
        branches = fig.scenes["rest"].on_timeout
        assert branches[0].when.value == 8 and branches[0].target == "@end"
        assert branches[1].target == "work"

    def test_until_adds_exits(self):
        s = self.session()
        s.say("until I hold")
        r = s.finish()
        assert r.figment.scenes["rolling"].on["long"].target == "@end"

    def test_count_binds_counter(self):
        s = RehearsalSession("Points")
        s.double_tap()
        s.say("rolling - one minute")
        s.say("count this")
        r = s.finish()
        assert r.ok
        rolling = r.figment.scenes["rolling"]
        assert rolling.on["double"].counter_ops[0].counter == "count"
        assert any("{count:count}" in ln.content for ln in rolling.lines)

    def test_provenance_maps_scenes_to_beats(self):
        r = self.session().finish()
        assert r.figment.meta["scene_beats"]["rolling"] >= 1

    def test_empty_stage_raises(self):
        with pytest.raises(InferenceError, match="stage"):
            Choreographer().infer([])

    def test_pulse_without_time_raises(self):
        with pytest.raises(InferenceError) as exc:
            Choreographer().infer([
                Beat("say", 0, text="pulse", parsed=("pulse", 10.0, 2.0))])
        assert exc.value.code == "pulse_without_time"

    def test_inferred_figments_always_verify(self):
        # every legal rehearsal in this file yields a proven figment
        for r in (self.session().finish(),):
            assert verify(r.figment).ok


class TestTeachability:
    def test_strobe_teaches_in_beats(self):
        s = RehearsalSession("Strobe")
        s.say("thirty seconds")
        s.say("strobe thirty times a second")
        r = s.finish()
        assert not r.ok
        assert r.teach.beat == 1                      # the offending beat
        assert "beat 2" in str(r.teach)               # 1-indexed for humans
        assert "pulse" in r.teach.suggestion
        assert len(r.teach.hud_lines()) <= 5          # HUD rule

    def test_flood_teaches_radio_budget(self):
        s = RehearsalSession("Beacon")
        s.say("ten seconds")
        s.say("send a ping five times a second")
        r = s.finish()
        assert not r.ok
        assert "phone" in str(r.teach)

    def test_empty_teaches_example(self):
        r = RehearsalSession("Nothing").finish()
        assert not r.ok
        assert "three minutes" in r.teach.suggestion

    def test_correction_costs_one_beat(self):
        s = RehearsalSession("Strobe")
        s.say("thirty seconds")
        bad = s.say("strobe thirty times a second")
        assert not s.finish().ok
        s.redo(bad.index, "last ten seconds, pulse")
        r = s.finish()
        assert r.ok
        timed = [sc for sc in r.figment.scenes.values() if sc.timed()]
        assert timed and timed[0].pulse.rate_hz == 2.0   # the fix landed

    def test_done_locks_session(self):
        s = RehearsalSession("x")
        s.say("ten seconds")
        s.say("done")
        with pytest.raises(RuntimeError, match="reopen"):
            s.tap()

    def test_beat_readings_are_plain_words(self):
        s = RehearsalSession("x")
        b = s.say("rolling - three minutes")
        assert "3:00 folded" in b.reading()
