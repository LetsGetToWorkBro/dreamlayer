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


# --- the two HUD features the ear can now produce -----------------------------
# `spoken_caption()` ("Live captions") and `listening()` ("Hey Juno") have been
# in `hud/cards.py` since the beginning, and nothing a shipped Brain could reach
# ever called either — decisions/0001 at the card layer. Both are wired here, so
# these pin the wiring AND the gates on it: a card that draws captured speech is
# exactly the kind of thing that must not arrive as a side effect of an unrelated
# opt-in.

def _pushes(brain):
    """Collect what the Brain pushes to the glass, without a live SSE client."""
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


def test_captions_are_off_until_asked_for(brain):
    """The default. An existing wearer who turned Listening on gets NO new
    behaviour — remembering speech and displaying it are separate decisions and
    `captions_enabled` is its own switch."""
    assert brain.config.captions_enabled is False
    ear = EarHost(brain)
    seen = _pushes(brain)
    ear.ingest_caption("the roof needs looking at before winter")
    assert not [c for k, c in seen if k == "caption"]
    assert ear.heard_count == 1          # …but it still REMEMBERED it


def test_captions_draw_the_utterance_when_enabled(brain):
    brain.config.captions_enabled = True
    ear = EarHost(brain)
    seen = _pushes(brain)
    ear.ingest_caption("the roof needs looking at before winter")
    cards = [c for k, c in seen if k == "caption"]
    assert len(cards) == 1
    assert cards[0]["type"] == "SpokenCaptionCard"
    assert "roof" in cards[0]["primary"]


def test_the_caption_carries_the_redacted_text_not_the_raw(brain):
    """The push sits AFTER the PII scrub, so the card can never carry more than
    the store does. Ordering, not intention — moving the push above the scrub
    would silently draw the unredacted line."""
    pytest.importorskip("presidio_analyzer")
    brain.config.captions_enabled = True
    ear = EarHost(brain)
    seen = _pushes(brain)
    ear.ingest_caption("call me on 555-123-4567 about Berlin")
    card = next(c for k, c in seen if k == "caption")
    assert "555-123-4567" not in card["primary"]
    assert "Berlin" in card["primary"]           # names and places survive


def test_the_veil_suppresses_the_caption_too(brain):
    """Incognito means "logs nothing" — and drawing the room's speech on a
    screen is not exempt from that. The utterance is dropped before the push,
    so there is nothing to blank."""
    brain.config.captions_enabled = True
    brain.config.network_mode = "lan_only"       # incognito
    ear = EarHost(brain)
    seen = _pushes(brain)
    ear.ingest_caption("a secret spoken while incognito")
    assert not seen
    assert ear.heard_count == 0


def test_a_failing_caption_push_never_costs_the_memory(brain):
    """A card is never worth an utterance. The write must survive a push that
    raises — the same rule brain_waypath's ObjectRecall push follows."""
    brain.config.captions_enabled = True
    ear = EarHost(brain)

    def _boom(*a, **k):
        raise RuntimeError("no client")
    brain.push_event = _boom
    ear.ingest_caption("remember the boiler service is due")
    assert ear.heard_count == 1
    assert "boiler" in ear.last_heard


def test_opening_the_mic_says_so_on_the_glass(brain, monkeypatch):
    """"Hey Juno" — the reassurance cue. Its `source` is "tap", not "voice":
    this Brain ships no wake-word engine, so claiming it was woken by speech
    would be a card that lies about how it got there."""
    import dreamlayer.orchestrator.asr_select as asrmod
    monkeypatch.setattr(asrmod, "make_asr", lambda *a, **k: _fake_asr_engine())
    brain.config.listen_enabled = True
    seen = _pushes(brain)
    res = brain.start_ear(mic=SyntheticMicSource(pcm=[0.0] * 320))
    assert res["ok"] is True
    card = next(c for k, c in seen if k == "listening")
    assert card["type"] == "ListeningCard"
    assert card["source"] == "tap"
    # no borrowed alarm furniture: the one card that earns a sound in this
    # product is a safety tap, and a settings toggle is not that
    assert not card["earcon"] and not card["haptic"]
    # stays until replaced — the ring must not expire while the mic is open
    assert card["dismiss_ms"] == 0
    brain.stop_ear()


def test_the_captions_switch_is_actually_reachable(brain):
    """`apply_config` has an ALLOWLIST. A config field missing from it is
    settable by nothing — a switch in the panel that silently does nothing,
    which is the same importable-but-unreachable failure this whole audit is
    about, one layer down."""
    brain.apply_config({"captions_enabled": True})
    assert brain.config.captions_enabled is True
    assert brain.config.public()["captions_enabled"] is True
    brain.apply_config({"captions_enabled": False})
    assert brain.config.captions_enabled is False


def test_captions_are_their_own_switch_not_a_consequence_of_listening(brain):
    """Turning Listening on must not turn captions on. Two opt-ins, two
    decisions — an existing wearer's posture cannot change under them."""
    brain.apply_config({"listen_enabled": True})
    assert brain.config.captions_enabled is False
