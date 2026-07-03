"""test_truthlens_wiring.py — the live delivery read feeding Discernment.

The linguistic channel is computed for real from each caption; face (AU) and
voice (prosody) are device seams fed via observe_face / observe_voice. The fused
CredibilityVector flows into Discernment through note_credibility, so a disputed
claim delivered under stress becomes the strongest flag — end to end.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _frame(value: float = 0.6) -> np.ndarray:
    return np.full((32, 32), value, dtype=np.float32)


def _fft(peak_hz: float = 200.0) -> np.ndarray:
    fft = np.zeros(512)
    idx = int(peak_hz / (4000 / 512))
    fft[idx] = 1.0
    return fft


def _factcards(br):
    return [f for f in br.raw if f.get("type") == "FactCheckCard"]


# -- opt-in + seams -----------------------------------------------------------

def test_off_by_default_no_delivery_read():
    orc = Orchestrator(FakeBridge())
    assert orc.truthlens_on is False
    orc.observe_face(_frame())               # seam is a no-op while off
    orc.ingest_caption("The rent is 2000.", speaker="Dana", ts=1.0)
    assert not orc._credibility


def test_delivery_read_populates_credibility():
    orc = Orchestrator(FakeBridge())
    orc.set_truthlens(True)
    orc.observe_face(_frame(0.9))            # a face frame drives the AU channel
    orc.observe_voice(_fft(300.0), 0.8)      # a mic window drives prosody
    orc.ingest_caption("The deal is completely finalized, trust me.",
                       speaker="Marcus", ts=1.0)
    cred = orc._credibility.get("marcus")    # a CredibilityVector was recorded
    assert cred is not None
    assert hasattr(cred, "deception_prob") and hasattr(cred, "confidence")


def test_your_own_lines_are_not_read():
    orc = Orchestrator(FakeBridge())
    orc.set_truthlens(True)
    orc.observe_face(_frame(0.9))
    orc.ingest_caption("I think it's fine.", speaker="", ts=1.0)   # the wearer
    assert not orc._credibility


# -- a stranger's read is not yet trusted -------------------------------------

def test_a_stranger_read_stays_uncalibrated():
    orc = Orchestrator(FakeBridge())
    orc.set_truthlens(True)
    orc.observe_face(_frame(0.9))
    orc.observe_voice(_fft(300.0), 0.8)
    orc.ingest_caption("Nice to meet you.", speaker="NewPerson", ts=1.0)
    cred = orc._credibility["newperson"]
    assert cred.is_stranger and cred.confidence <= 0.2   # noise until we know them


# -- end to end: once calibrated, delivery folds into the fact-check ----------

def _stream_audio(orc, n: int = 40):
    """Feed one prosody window's worth of mic frames (production streams these)."""
    for _ in range(n):
        orc.observe_voice(_fft(200.0), 0.5)


def test_delivery_folds_in_once_the_baseline_is_calibrated():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_truthlens(True)
    _stream_audio(orc)                        # one prosody window (persists)
    orc.observe_face(_frame(0.6))             # a face frame (persists)
    # warm up a per-contact baseline for Marcus (all three channels present)
    for i in range(12):
        orc.ingest_caption("Good to see you again.", speaker="Marcus", ts=float(i))
    assert not orc._credibility["marcus"].is_stranger      # calibrated now

    # now a self-contradiction, with the delivery read live
    orc.set_factcheck(True)
    orc.ingest_caption("The deal closed at 2 million.", speaker="Marcus", ts=100.0)
    orc.ingest_caption("Actually it closed at 3 million.", speaker="Marcus", ts=140.0)

    cards = _factcards(br)
    assert cards and cards[-1]["verdict"] == "self_contradiction"
    assert "stance" in cards[-1] and cards[-1].get("headline")
    assert cards[-1]["footer"] != "Marcus"     # the delivery read was folded in
