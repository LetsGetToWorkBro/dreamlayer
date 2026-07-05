"""test_memories_endpoint.py — the phone Memories tab's real backend.

The tab used to render seed-only sample data (refresh() was a no-op). The Brain
now assembles kept memory from what it holds — places you saved (Waypath),
people you've met and favors owed (Social Lens), and dated reminders — served at
GET /dreamlayer/memories.
"""
from __future__ import annotations

import json
import time

from dreamlayer.ai_brain.server import Brain


def _seed(tmp_path) -> Brain:
    b = Brain(tmp_path)
    # a place you saved
    b.waypath_stash("bike", "the north rack")
    # a person you met, with a favor owed
    b.voice_social("meet_person", {"who": "Priya", "relation": "neighbor",
                                    "note": "teaches ceramics"})
    b.voice_social("debt", {"who": "Priya", "dir": "they_owe", "what": "$20"})
    # a dated reminder
    (tmp_path / "reminders.json").write_text(json.dumps(
        [{"title": "Renew passport", "ts": time.time() + 3600, "list": ""}]))
    return b


def test_memories_assembles_all_kinds(tmp_path):
    mems = _seed(tmp_path).memories()["memories"]
    kinds = {m["kind"] for m in mems}
    assert {"Place", "Person", "Promise"} <= kinds
    joined = " | ".join(m["summary"] for m in mems)
    assert "north rack" in joined
    assert "Priya" in joined
    assert "Priya owes you $20" in joined
    assert "Renew passport" in joined
    # every memory carries an epoch-ms ts and an id the phone can key on
    assert all(isinstance(m["ts"], int) and m["id"] for m in mems)


def test_memories_empty_is_clean(tmp_path):
    assert Brain(tmp_path).memories()["memories"] == []


def test_future_reminder_reads_tomorrow_not_yesterday(tmp_path):
    """Review finding: a reminder for tomorrow 9am was labeled "Yesterday" —
    the 48h window was signed-blind. Calendar-day labels fix it."""
    b = Brain(tmp_path)
    tomorrow = time.time() + 24 * 3600
    (tmp_path / "reminders.json").write_text(json.dumps(
        [{"title": "Dentist", "ts": tomorrow, "list": ""}]))
    m = next(x for x in b.memories()["memories"] if x["summary"] == "Dentist")
    assert m["createdAt"].startswith("Tomorrow, ")
    # and it floats to the top — upcoming beats past
    assert b.memories()["memories"][0]["summary"] == "Dentist"


def test_old_memory_gets_a_date_not_a_bare_weekday(tmp_path):
    b = Brain(tmp_path)
    b.waypath.remember_place("skis", "the storage unit",
                             ts=time.time() - 21 * 86400)
    b._save_waypath()
    m = next(x for x in b.memories()["memories"] if "skis" in x["summary"])
    # three weeks old: "Jun 14, 4:15 PM"-style, not an ambiguous "Tue, 4:15 PM"
    assert m["createdAt"][0].isupper() and any(c.isdigit() for c in m["createdAt"].split(",")[0])


def test_people_and_debts_are_undated_living_memory(tmp_path):
    """Review finding: person/debt rows were stamped ts=now on every call —
    pinned above genuinely recent places, forever "today" on the phone."""
    b = _seed(tmp_path)
    mems = b.memories()["memories"]
    for m in mems:
        if m["kind"] == "Person" or m["createdAt"] == "open":
            assert m["ts"] == 0, m
    # the dated rows (place, reminder) outrank the undated living memory
    kinds_in_order = [m["kind"] for m in mems]
    assert kinds_in_order.index("Place") < kinds_in_order.index("Person")


def test_waypath_load_survives_a_bad_row(tmp_path):
    """Review finding: one malformed row silently dropped every anchor."""
    (tmp_path / "waypath.json").write_text(json.dumps([
        {"subject": None, "place": "x"},                 # bad
        {"subject": "bike", "place": "the rack", "ts": time.time()},
    ]))
    b = Brain(tmp_path)
    assert b.waypath_locate("bike")["found"]


def test_debt_you_owe_phrasing(tmp_path):
    b = Brain(tmp_path)
    b.voice_social("meet_person", {"who": "Dana"})
    b.voice_social("debt", {"who": "Dana", "dir": "i_owe", "what": "lunch"})
    proms = [m["summary"] for m in b.memories()["memories"] if m["kind"] == "Promise"]
    assert any(s == "You owe Dana lunch" for s in proms), proms


def test_memories_over_http(tmp_path):
    import threading, urllib.request
    from dreamlayer.ai_brain.server.server import make_brain_server
    b = _seed(tmp_path)
    srv = make_brain_server(b, host="127.0.0.1", port=7806)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = b.config.token
    try:
        req = urllib.request.Request("http://127.0.0.1:7806/dreamlayer/memories")
        if tok:
            req.add_header("X-DreamLayer-Token", tok)
        got = json.loads(urllib.request.urlopen(req).read())
        assert got["memories"] and any(m["kind"] == "Place" for m in got["memories"])
    finally:
        srv.shutdown()
