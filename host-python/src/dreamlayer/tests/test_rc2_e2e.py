"""End-to-end: the blind-handoff test — the one test that proves the
paradigm (docs/rc_v2/rehearsal.md §8).

One sentence of instruction ("show the glasses one round of what you
want"), one performed round, and the user must land a deployed, correct,
budget-proven, signed 3-minute pulse timer — no manual, no syntax.
"""
from dreamlayer.reality_compiler.v2 import (
    RealityCompilerV2, Stage, verify, transcript,
)


def test_blind_handoff_rehearsal(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)

    # --- the user performs one round, in sketch time -----------------------
    session = rc.rehearse("Rolling rounds")
    session.double_tap()                       # "the trigger goes here"
    session.say("rolling - three minutes")     # time is spoken, not lived
    session.say("last ten seconds, pulse")
    session.say("then it starts again")
    result = session.finish()

    # --- it compiled, and the user can watch what was learned --------------
    assert result.ok, result.teach
    assert len(result.playback) >= 8
    text = transcript(result.playback)
    assert "3:00" in text                      # the countdown was previewed
    assert any(f.folded for f in result.playback)          # time was folded
    assert any(f.frame.pulse_on for f in result.playback)  # pulse was seen

    # --- the machine is proven, not promised -------------------------------
    report = result.report
    assert report.ok
    assert report.worst_display_hz <= 4.0
    assert report.worst_emit_per_sec <= 1.0

    # --- keep signs it; deploy hot-swaps it; both are checked --------------
    entry = rc.keep(result.figment)
    assert rc.vault.signer.verify(entry.figment, entry.sig)
    record = rc.deploy(result.figment.id)
    assert record.success
    assert [e["t"] for e in record.envelopes] == ["figment_put",
                                                  "figment_swap"]

    # --- and it is the behavior the user performed -------------------------
    st = Stage(result.figment)
    st.inject("double")
    st.step(60)
    frame = st.frame()
    assert frame.lines[0].text == "ROLLING"
    assert frame.lines[1].text == "2:00"
    st.step(112)                               # 172 s in: inside the pulse
    assert st.remaining() <= 10
    st.step(8)                                 # round ends → loops
    assert st.current == "rolling" and not st.ended
    assert st.frame().lines[1].text == "3:00"

    # --- under 60 seconds of user time, by construction --------------------
    # 4 beats: a tap and three short utterances (~15 s), one nod to keep.
    assert len(result.beats) == 4


def test_blind_handoff_failure_path_is_teachable(tmp_path):
    """The same handoff, but the user asks for something unsafe: the
    system must explain in their own words and cost them one beat."""
    rc = RealityCompilerV2(vault_dir=tmp_path)
    session = rc.rehearse("Strobe drill")
    session.say("thirty seconds")
    bad = session.say("strobe thirty times a second")
    result = session.finish()

    assert not result.ok
    assert result.teach.beat == bad.index
    assert "beat 2" in str(result.teach)
    assert "strobe" not in str(result.teach).lower().replace(
        "it doesn't strobe", "")               # explains limits, not jargon

    session.redo(bad.index, "last ten seconds, pulse")
    fixed = session.finish()
    assert fixed.ok
    assert verify(fixed.figment).ok
