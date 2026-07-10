"""test_native_timers.py — the native timer/interval/clock Juno builds.

Two layers: the voice grammar (parse_intent → timer/interval/clock), the
figment builders (bounded + verified), and the Brain path that turns a spoken
line into a behavior on the stage.
"""
from __future__ import annotations

from dreamlayer.orchestrator.voice import parse_intent
from dreamlayer.reality_compiler.v2 import native, budgets
from dreamlayer.reality_compiler.v2.interpreter import Stage
from dreamlayer.ai_brain.server import Brain


# -- the voice grammar --------------------------------------------------------

def test_plain_timer_phrasings():
    for text, secs in [
        ("Hey Juno, set a timer for five minutes", 300),
        ("set a timer for 90 seconds", 90),
        ("timer for 2 minutes", 120),
        ("start a 3 minute timer", 180),
        ("count down 45 seconds", 45),
        ("set a timer for 1 hour", 3600),
    ]:
        it = parse_intent(text)
        assert it.kind == "timer", (text, it)
        assert it.args["seconds"] == secs, (text, it.args)


def test_interval_phrasings():
    it = parse_intent("interval timer, 30 seconds on, 15 seconds off, 8 rounds")
    assert it.kind == "interval"
    assert it.args == {"work": 30, "rest": 15, "rounds": 8}

    it2 = parse_intent("intervals 45 seconds work 20 seconds rest")
    assert it2.kind == "interval" and it2.args["work"] == 45 and it2.args["rest"] == 20
    assert it2.args["rounds"] is None


def test_clock_and_time_phrasings():
    assert parse_intent("what time is it").kind == "clock"
    assert parse_intent("what time is it").args["mode"] == "time"
    assert parse_intent("show me a clock").args["mode"] == "show"
    assert parse_intent("put a clock on the hud").args["mode"] == "show"


def test_cancel_phrasings():
    assert parse_intent("stop the timer").kind == "timer_cancel"
    assert parse_intent("cancel the countdown").kind == "timer_cancel"


def test_non_timer_lines_still_route_normally():
    assert parse_intent("what did Marcus need").kind == "recall"
    assert parse_intent("brief me").kind == "brief"
    # a plain question with no timer words falls through to ask
    assert parse_intent("what's the capital of France").kind == "ask"


# -- the figment builders (bounded + runnable) --------------------------------

def test_timer_figment_is_verified_and_counts_down():
    fig = native.timer_figment(3, "Tea")           # 3s run + 3s DONE, then END
    assert budgets.verify(fig).ok
    st = Stage(fig)
    seen = [" / ".join(l.text for l in sorted(st.frame().lines, key=lambda x: x.row))]
    for _ in range(9):
        st.step(1.0)
        seen.append(" / ".join(l.text for l in sorted(st.frame().lines, key=lambda x: x.row)))
    assert any("DONE" in s for s in seen)          # it reaches DONE
    assert st.ended                                 # then ends


def test_interval_figment_counts_rounds_then_ends():
    fig = native.interval_figment(2, 1, rounds=2, label="HIIT")
    assert budgets.verify(fig).ok
    st = Stage(fig)
    labels = []
    for _ in range(8):
        labels.append(st.current)
        st.step(1.0)
    assert "work" in labels and "rest" in labels
    assert st.ended                                 # bounded by rounds


def test_open_interval_runs_until_stopped():
    fig = native.interval_figment(2, 1, rounds=None)
    assert budgets.verify(fig).ok
    st = Stage(fig)
    for _ in range(20):
        st.step(1.0)
    assert not st.ended                             # no rounds → keeps going
    st.inject("long")                               # a hold stops it
    assert st.ended


def test_clock_figment_is_verified():
    assert budgets.verify(native.clock_figment()).ok


# -- the Brain path: a spoken line becomes a behavior on the stage ------------

def test_brain_sets_a_timer_from_voice(tmp_path):
    b = Brain(tmp_path)
    it = parse_intent("set a timer for five minutes")
    out = b.rc_native(it.kind, it.args)
    assert out["ok"] and out["intent"] == "timer"
    assert "5 minutes" in out["say"]
    assert out["figment_id"] and b._rc_active == out["figment_id"]
    # ephemeral: it doesn't clutter the Repertoire
    assert all(e["id"] != out["figment_id"] for e in b.rc_repertoire()["items"])


def test_brain_starts_intervals_from_voice(tmp_path):
    b = Brain(tmp_path)
    it = parse_intent("interval timer 30 seconds on 15 seconds off 8 rounds")
    out = b.rc_native(it.kind, it.args)
    assert out["ok"] and out["intent"] == "interval"
    assert "30 seconds on" in out["say"] and "15 seconds off" in out["say"]
    assert "8 rounds" in out["say"]


def test_brain_answers_the_time(tmp_path):
    b = Brain(tmp_path)
    out = b.rc_native("clock", {"mode": "time"})
    assert out["ok"] and out["intent"] == "clock"
    assert "It's" in out["say"] and ("AM" in out["say"] or "PM" in out["say"])


def test_brain_cancel_clears_the_stage(tmp_path):
    b = Brain(tmp_path)
    b.rc_native("timer", {"seconds": 60})
    assert b._rc_active is not None
    out = b.rc_native_cancel()
    assert out["ok"] and b._rc_active is None
