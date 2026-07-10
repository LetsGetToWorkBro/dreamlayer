"""test_ledger_emits.py — ledger emits (INNOVATION_SESSION 5.1 #5): an emit
flagged record=true is data you keep — the deployer drains it into the Vault
performance log. Grammar + interpreter + vault, end to end."""
from __future__ import annotations

from dreamlayer.reality_compiler.v2.figment import Figment, Scene, Transition
from dreamlayer.reality_compiler.v2.interpreter import Stage, log_recorded
from dreamlayer.reality_compiler.v2.vault import Vault


def _rep_figment(record: bool):
    """A one-scene rep counter that emits on each second (self-loop)."""
    f = Figment(name="reps", initial="a")
    f.scenes["a"] = Scene(
        id="a", duration_sec=1.0,
        on_timeout=[Transition(target="a", emit="rep", record=record)])
    return f


def test_record_flag_serializes_round_trip():
    t = Transition(target="a", emit="rep", record=True)
    d = t.to_dict()
    assert d["record"] is True
    back = Transition.from_dict(d)
    assert back.record is True
    # and it rides in the signed canonical JSON
    assert '"record":true' in _rep_figment(True).canonical_json()


def test_recorded_emits_are_tracked_separately():
    stage = Stage(_rep_figment(record=True))
    for _ in range(3):
        stage.step(1.0)
    assert len(stage.emits) == 3
    assert len(stage.recorded) == 3


def test_unrecorded_emits_are_not_kept():
    stage = Stage(_rep_figment(record=False))
    for _ in range(3):
        stage.step(1.0)
    assert len(stage.emits) == 3
    assert stage.recorded == []


def test_recorded_emits_drain_to_the_vault_log(tmp_path):
    stage = Stage(_rep_figment(record=True))
    for _ in range(3):
        stage.step(1.0)
    v = Vault(tmp_path)
    n = log_recorded(stage, v, "fig1")
    assert n == 3
    hist = v.performance_history("fig1")
    assert len(hist) == 3 and all(h["emit"] == "rep" for h in hist)
    # buffer is drained after logging
    assert stage.recorded == []
