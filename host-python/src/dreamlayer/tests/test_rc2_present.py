"""test_rc2_present.py — the phone-facing presentation layer for RC v2.

Pins score_from_beats / figment_brief / repertoire_entry against real
rehearsed figments, so the phone's live mirror can trust these shapes.
"""
from __future__ import annotations

from dreamlayer.reality_compiler.v2 import present
from dreamlayer.reality_compiler.v2.compiler import RealityCompilerV2


def _rolling(rc):
    s = rc.rehearse("Rolling rounds")
    s.double_tap()
    s.say("rolling - three minutes")
    s.say("last ten seconds, pulse")
    s.say("then it starts again")
    return s.finish()


def test_score_reads_beats_with_readings_and_folded_time(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)
    result = _rolling(rc)
    score = present.score_from_beats(result.beats)
    assert [b["kind"] for b in score] == ["double_tap", "say", "say", "say"]
    # the trigger reads as a strong beat
    assert "double-tap" in score[0]["reading"]
    # the spoken duration folds to 180s and carries the raw utterance
    dur = score[1]
    assert dur["text"] == "rolling - three minutes"
    assert dur["foldedSec"] == 180
    assert "folded" in dur["reading"]
    # the pulse mark reads as a pulse
    assert "pulse" in score[2]["reading"].lower()


def test_figment_brief_reads_trigger_and_length(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)
    fig = _rolling(rc).figment
    brief = present.figment_brief(fig)
    assert brief["trigger"] == "double-tap"
    assert brief["length"].startswith("3:00")
    assert "pulse" in brief["length"]


def test_auto_trigger_reads_as_auto(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)
    s = rc.rehearse("Just a timer")
    s.say("focus for two minutes")          # no tap → armed auto-runs
    fig = s.finish().figment
    assert present.figment_brief(fig)["trigger"] == "auto"


def test_repertoire_entry_marks_the_active_one(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)
    entry = rc.keep(_rolling(rc).figment)
    fig_id = entry.figment.id
    # not on stage yet
    row = present.repertoire_entry(entry, active_id=None)
    assert row["id"] == fig_id and row["signed"] is True and row["active"] is False
    assert row["name"] == "Rolling rounds" and row["trigger"] == "double-tap"
    # marked active when it's the deployed one
    row2 = present.repertoire_entry(entry, active_id=fig_id)
    assert row2["active"] is True


def test_revoked_entry_is_not_signed_or_active(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path)
    entry = rc.keep(_rolling(rc).figment)
    rc.vault.revoke(entry.figment.id)
    reloaded = rc.vault.list(include_revoked=True)[0]
    row = present.repertoire_entry(reloaded, active_id=reloaded.figment.id)
    assert row["signed"] is False and row["active"] is False
