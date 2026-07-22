"""The always-on ear: consent-gated on-device voice capture wired into the
shipped Brain. Before this the whole capture stack (VAD → ASR ladder → sound
events → memory) existed only inside an Orchestrator the Brain never built, so
the voice capabilities installed and did nothing reachable. These tests pin:

  * the ear is OFF by default and only runs on explicit opt-in (listen_enabled),
  * a heard utterance lands in the Brain's memory,
  * the Veil (incognito / quiet-hours) drops utterances — "logs nothing",
  * PII is scrubbed before any write, but names and places survive,
  * start/stop is safe/idempotent and flips the capability report honestly
    (DL_WIRED_<KEY> set only while the microphone is actually open),
  * a missing engine / mic degrades to an honest {ok:False} — never a crash.

Uses a fake ASR + SyntheticMicSource, so it runs with no audio deps installed.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from dreamlayer import capabilities as C
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.ear import EarHost, EAR_CAPS
from dreamlayer.orchestrator.capture import SyntheticMicSource


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture(autouse=True)
def _clear_wired_env():
    for key in EAR_CAPS:
        os.environ.pop("DL_WIRED_" + key.upper(), None)
    yield
    for key in EAR_CAPS:
        os.environ.pop("DL_WIRED_" + key.upper(), None)


# --- the pipeline path: the ear must have a privacy gate ----------------------
# Regression for the dead-ear bug: CapturePipeline reads orch.privacy at its
# door (push_pcm -> _veiled -> orch.privacy.allow_capture). If EarHost has no
# `privacy`, _veiled() fails closed and EVERY window is dropped — the mic opens
# but nothing is ever transcribed or stored. These tests drive a real utterance
# THROUGH the pipeline (not around it, as the ingest_caption tests do).

class _FixedASR:
    def __init__(self, text): self._t = text
    def transcribe(self, segment): return self._t


def test_ear_exposes_a_working_privacy_gate(brain):
    ear = EarHost(brain)
    assert hasattr(ear, "privacy")
    assert ear.privacy.allow_capture() is True          # not incognito → open


def test_utterance_flows_through_the_pipeline_to_memory(brain):
    from dreamlayer.orchestrator.capture import CapturePipeline
    ear = EarHost(brain)
    pipe = CapturePipeline(ear, vad=None, asr=_FixedASR("ship the beta on Friday"))
    assert pipe._veiled() is False                      # the door is open
    pipe.push_pcm([0.1] * 320)                           # a speech window
    pipe.flush()                                         # endpoint → asr → ingest
    assert ear.heard_count >= 1
    assert "friday" in ear.last_heard.lower()


def test_pipeline_door_is_veiled_while_incognito(brain):
    from dreamlayer.orchestrator.capture import CapturePipeline
    brain.config.network_mode = "lan_only"              # incognito
    ear = EarHost(brain)
    pipe = CapturePipeline(ear, vad=None, asr=_FixedASR("a secret"))
    assert pipe._veiled() is True                        # gate closed at the door
    pipe.push_pcm([0.1] * 320)
    pipe.flush()
    assert ear.heard_count == 0                          # nothing accumulated


# --- ingest: the value path ---------------------------------------------------

def test_heard_utterance_lands_in_memory(brain):
    ear = EarHost(brain)
    ear.ingest_caption("we agreed to ship the beta on Friday")
    assert ear.heard_count == 1
    assert "Friday" in ear.last_heard


def test_pii_scrubbed_but_names_and_places_survive(brain):
    ear = EarHost(brain)
    ear.ingest_caption("Call Alice at 555-123-4567 about the Oak St lease")
    assert "555-123-4567" not in ear.last_heard        # scrubbed
    assert "Alice" in ear.last_heard                   # name kept
    assert "Oak St" in ear.last_heard                  # place kept


def test_veil_down_logs_nothing(brain):
    ear = EarHost(brain)
    brain.config.network_mode = "lan_only"             # incognito
    ear.ingest_caption("a secret spoken while incognito")
    assert ear.heard_count == 0                         # dropped, not stored


def test_empty_caption_is_ignored(brain):
    ear = EarHost(brain)
    ear.ingest_caption("   ")
    assert ear.heard_count == 0


# --- lifecycle + honest capability promotion ---------------------------------

def _fake_asr_engine():
    class _Engine:
        def transcribe(self, seg):
            return ""
    return _Engine()


def test_start_ear_requires_opt_in(brain):
    assert brain.config.listen_enabled is False
    res = brain.start_ear(mic=SyntheticMicSource(pcm=[0.0] * 320))
    assert res["ok"] is False and res["reason"] == "disabled"


def test_start_and_stop_flip_the_capability_report(brain, monkeypatch):
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: _fake_asr_engine())
    brain.config.listen_enabled = True
    res = brain.start_ear(mic=SyntheticMicSource(pcm=[0.0] * 320))
    assert res["ok"] is True
    assert brain.ear_status()["listening"] is True
    # ONLY the genuinely-driven caps are promoted. The fake engine is not
    # Moonshine → local_asr, not asr_moonshine; make_asr never selects sherpa →
    # onnx_speech is NEVER promoted; a SyntheticMicSource is not the sounddevice
    # mic → mic_capture is not promoted; no tagger/bird built here either.
    assert os.environ.get("DL_WIRED_LOCAL_ASR") == "1"
    for key in ("asr_moonshine", "onnx_speech", "mic_capture",
                "sound_events", "bird_song"):
        assert "DL_WIRED_" + key.upper() not in os.environ, key
    brain.stop_ear()
    assert brain.ear_status()["listening"] is False
    for key in EAR_CAPS:
        assert "DL_WIRED_" + key.upper() not in os.environ


def test_start_ear_no_asr_is_honest(brain, monkeypatch):
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: None)
    brain.config.listen_enabled = True
    res = brain.start_ear(mic=SyntheticMicSource(pcm=[0.0] * 320))
    assert res["ok"] is False and res["reason"] == "no-asr"
    assert brain.ear_status()["listening"] is False


def test_stop_ear_safe_when_idle(brain):
    brain.stop_ear()                    # never listened — must not raise
    assert brain.ear_status()["listening"] is False


def test_ear_status_reports_the_persisted_switch(brain):
    st = brain.ear_status()
    assert st["enabled"] is False and st["listening"] is False


# --- the DL_WIRED promotion in isolation (works even with audio deps absent) --

def test_dl_wired_promotes_a_dormant_cap_to_active(monkeypatch):
    # a synthetic, definitely-installed cap that we force into the dormant set
    cap = C.Cap(key="probe_wired", title="t", tier="test",
                modules=("json",), extra="memory", seam="x.py")
    monkeypatch.setattr(C, "_NOT_WIRED", frozenset({"probe_wired"}))
    assert C.state(cap, env={}) == "dormant"
    assert C.state(cap, env={"DL_WIRED_PROBE_WIRED": "1"}) == "active"
    # a disable flag still wins over a wired flag
    assert C.state(cap, env={"DL_WIRED_PROBE_WIRED": "1",
                             "DL_DISABLE_PROBE_WIRED": "1"}) == "off"
