"""The phone as the live mic: audio the PHONE captures streams to the Brain,
which transcribes it on-device and remembers it — so the ear travels with you,
not with the Mac. This pins the new seam end to end, with no audio deps:

  * RemoteMicSource turns a pushed byte-stream into the fixed windows the
    CapturePipeline pulls, and is bounded (drop-oldest) so a stalled reader
    can't grow memory,
  * decode_audio parses little-endian Int16 PCM and resamples to 16 kHz,
  * a streamed utterance flows through the SAME pipeline to memory,
  * the phone ear is OFF until its own opt-in (remote_listen_enabled) — separate
    from the Mac-mic listen_enabled, so one never opens the other,
  * the Veil (incognito / quiet-hours) drops the phone's audio too,
  * a missing on-device ASR degrades to an honest {ok:False}, never a crash.
"""
from __future__ import annotations

import struct
import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server import live as live_mod
from dreamlayer.orchestrator.capture import (
    CapturePipeline, RemoteMicSource, SAMPLE_RATE,
)


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class _FixedASR:
    def __init__(self, text): self._t = text
    def transcribe(self, segment): return self._t


def _fake_asr_engine():
    class _Engine:
        def transcribe(self, seg): return ""
    return _Engine()


# --- RemoteMicSource: the push→window seam -----------------------------------

def test_remote_mic_yields_windows_as_audio_arrives():
    s = RemoteMicSource()
    s.open(SAMPLE_RATE, 320)
    assert s.read() is None                      # nothing streamed yet → idle
    s.push([0.2] * 700)
    assert len(s.read()) == 320                  # first window
    assert len(s.read()) == 320                  # second window
    assert s.read() is None                      # 60 left < a full window


def test_remote_mic_drops_oldest_when_flooded():
    s = RemoteMicSource(max_seconds=0.02)        # cap = 16000 * 0.02 = 320 samples
    s.open(SAMPLE_RATE, 320)
    s.push([1.0] * 4000)                         # far over cap → trimmed to 320
    assert s.read() is not None                  # exactly one window survives
    assert s.read() is None


def test_remote_mic_push_before_open_is_safe():
    s = RemoteMicSource()
    s.push([0.1] * 320)                          # buffered even before open()
    s.open(SAMPLE_RATE, 320)                     # open() clears — a fresh session
    assert s.read() is None


# --- decode_audio: Int16 PCM → floats, with resample -------------------------

def test_decode_audio_int16_to_unit_floats():
    body = struct.pack("<4h", 0, 16384, -16384, 32767)
    out = live_mod.decode_audio(body, SAMPLE_RATE)
    assert len(out) == 4
    assert out[0] == 0.0
    assert abs(out[1] - 0.5) < 0.01
    assert abs(out[2] + 0.5) < 0.01


def test_decode_audio_resamples_48k_to_16k():
    n = 480
    body = struct.pack("<%dh" % n, *([1000] * n))
    out = live_mod.decode_audio(body, 48000)
    assert abs(len(out) - n * SAMPLE_RATE // 48000) <= 1     # ~160 samples


def test_decode_audio_drops_a_malformed_chunk():
    assert live_mod.decode_audio(b"", SAMPLE_RATE) == []
    assert live_mod.decode_audio(b"\x01", SAMPLE_RATE) == []  # a lone odd byte


# --- the streamed utterance reaches memory (same pipeline as the local ear) ---

def test_streamed_audio_flows_through_the_pipeline_to_memory(brain):
    ear = EarHost(brain)
    src = RemoteMicSource()
    src.open(SAMPLE_RATE, 320)
    src.push([0.1] * 320)                        # the phone streamed a window
    window = src.read()
    assert window is not None and len(window) == 320
    pipe = CapturePipeline(ear, vad=None, asr=_FixedASR("meet Sam at noon"))
    assert pipe._veiled() is False
    pipe.push_pcm(window)
    pipe.flush()
    assert ear.heard_count >= 1
    assert "sam" in ear.last_heard.lower()


def test_streamed_audio_is_veiled_while_incognito(brain):
    brain.config.network_mode = "lan_only"       # incognito → the shield is up
    ear = EarHost(brain)
    src = RemoteMicSource()
    src.open(SAMPLE_RATE, 320)
    src.push([0.1] * 320)
    pipe = CapturePipeline(ear, vad=None, asr=_FixedASR("a secret"))
    assert pipe._veiled() is True
    pipe.push_pcm(src.read())
    pipe.flush()
    assert ear.heard_count == 0                   # dropped, never stored


# --- Brain.hear_remote: consent + lifecycle ----------------------------------

def test_phone_ear_is_off_until_its_own_opt_in(brain):
    assert brain.config.remote_listen_enabled is False
    res = brain.hear_remote([0.0] * 320)
    assert res["ok"] is False and res["reason"] == "disabled"


def test_phone_opt_in_does_not_open_the_mac_mic(brain, monkeypatch):
    # turning the phone ear on must NOT start the Mac-mic ear (separate consent)
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: _fake_asr_engine())
    brain.config.remote_listen_enabled = True
    res = brain.hear_remote([0.0] * 4000)
    assert res["ok"] is True and res["remote_listening"] is True
    st = brain.ear_status()
    assert st["remote_listening"] is True         # the phone ear is up
    assert st["listening"] is False               # the Mac-mic ear is NOT
    brain.stop_remote_ear()
    assert brain.ear_status()["remote_listening"] is False


def test_phone_ear_no_asr_is_honest(brain, monkeypatch):
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: None)
    brain.config.remote_listen_enabled = True
    res = brain.hear_remote([0.0] * 320)
    assert res["ok"] is False and res["reason"] == "no-asr"
    assert brain.ear_status()["remote_listening"] is False


def test_opting_out_stops_the_phone_ear(brain, monkeypatch):
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: _fake_asr_engine())
    brain.config.remote_listen_enabled = True
    brain.hear_remote([0.0] * 4000)
    assert brain.ear_status()["remote_listening"] is True
    brain.apply_config({"remote_listen_enabled": False})     # the panel/phone off
    assert brain.ear_status()["remote_listening"] is False


def test_hear_body_stop_ends_the_remote_ear(brain):
    res = live_mod.hear(brain, b"", stop=True)
    assert res["ok"] is True and res["remote_listening"] is False


def test_stop_remote_ear_is_safe_when_idle(brain):
    brain.stop_remote_ear()                       # never started — must not raise
    assert brain.ear_status()["remote_listening"] is False
