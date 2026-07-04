"""test_brain_rc.py — the Brain's Reality Compiler v2 surface.

Pins the endpoints the phone's Rehearsal screen drives: rehearse (a
performance → live score + proof + preview, or a teach card), keep (sign +
vault), repertoire (list), deploy (hot-swap → on stage), revoke (durable).
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import Brain

ROLLING = [
    {"kind": "double_tap"},
    {"kind": "say", "text": "rolling - three minutes"},
    {"kind": "say", "text": "last ten seconds, pulse"},
    {"kind": "say", "text": "then it starts again"},
]


def test_rehearse_returns_score_proof_and_preview(tmp_path):
    b = Brain(tmp_path)
    r = b.rc_rehearse("Rolling rounds", ROLLING)
    assert r["ok"] is True
    assert [x["kind"] for x in r["score"]] == ["double_tap", "say", "say", "say"]
    assert r["score"][1]["foldedSec"] == 180
    assert r["brief"]["trigger"] == "double-tap" and "pulse" in r["brief"]["length"]
    assert r["report"]["scenes"] >= 1
    assert r["report"]["display_hz"] <= 4.0        # within the pulse budget
    assert len(r["preview"]) > 0                    # a folded run-through to watch
    assert r["figment_id"]


def test_unsafe_rehearsal_returns_a_teach_card_not_a_figment(tmp_path):
    b = Brain(tmp_path)
    r = b.rc_rehearse("Strobe drill", [
        {"kind": "say", "text": "thirty seconds"},
        {"kind": "say", "text": "strobe thirty times a second"},
    ])
    assert r["ok"] is False
    assert "figment_id" not in r
    assert r["teach"]["title"] and isinstance(r["teach"]["lines"], list)


def test_keep_then_repertoire_lists_the_figment(tmp_path):
    b = Brain(tmp_path)
    fid = b.rc_rehearse("Rolling rounds", ROLLING)["figment_id"]
    kept = b.rc_keep(fid)
    assert kept["ok"] and kept["entry"]["name"] == "Rolling rounds"
    assert kept["entry"]["signed"] is True and kept["entry"]["active"] is False
    rep = b.rc_repertoire()
    assert [e["id"] for e in rep["items"]] == [fid]


def test_keep_rejects_an_unrehearsed_id(tmp_path):
    b = Brain(tmp_path)
    r = b.rc_keep("nope")
    assert r["ok"] is False and "error" in r


def test_deploy_puts_it_on_stage_then_revoke_clears_it(tmp_path):
    b = Brain(tmp_path)
    fid = b.rc_rehearse("Rolling rounds", ROLLING)["figment_id"]
    b.rc_keep(fid)
    dep = b.rc_deploy(fid)
    assert dep["ok"] and dep["active"] == fid
    assert any(e["id"] == fid and e["active"] for e in dep["items"])
    # revoke: off stage, and gone from the (non-revoked) repertoire
    rev = b.rc_revoke(fid)
    assert rev["ok"] and rev["active"] is None
    assert all(e["id"] != fid for e in rev["items"])


def test_deploy_refuses_a_revoked_figment(tmp_path):
    b = Brain(tmp_path)
    fid = b.rc_rehearse("Rolling rounds", ROLLING)["figment_id"]
    b.rc_keep(fid)
    b.rc_revoke(fid)
    again = b.rc_deploy(fid)
    assert again["ok"] is False and "REFUSED" in again["message"]


def test_empty_performance_is_a_gentle_teach_not_a_crash(tmp_path):
    b = Brain(tmp_path)
    r = b.rc_rehearse("Nothing", [])
    assert r["ok"] is False and r.get("teach")
