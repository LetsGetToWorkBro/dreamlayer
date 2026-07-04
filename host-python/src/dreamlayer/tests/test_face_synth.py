"""test_face_synth.py — Face Synth: the glasses as a MIDI instrument, and the
first real plugin on the extension API.

Pins the scale quantiser (you can't play a wrong note), the head→MIDI mapping,
the distributed band's stable channels + mesh packing, and the plugin loading
through the registry with its capability gate.
"""
from __future__ import annotations

from dreamlayer.plugins.face_synth import (
    FaceSynth, FaceSynthBand, MidiEvent, quantize_to_scale, SCALES,
    CC_EXPRESSION, face_synth_plugin, note_name,
)
from dreamlayer.plugins import PluginContext, PluginRegistry
from dreamlayer.hud.renderer import CardRenderer


# -- the quantiser: land on a scale degree, never between keys ----------------

def test_quantize_locks_to_the_scale():
    # every output is a C-major degree (no accidentals)
    majors = {0, 2, 4, 5, 7, 9, 11}
    for i in range(21):
        n = quantize_to_scale(i / 20, SCALES["major"], root=60)
        assert (n - 60) % 12 in majors
    assert quantize_to_scale(0.0, SCALES["major"], 60) == 60      # low = root
    assert quantize_to_scale(1.0, SCALES["major"], 60) > 60       # high = up


def test_pentatonic_has_no_semitone_clashes():
    got = {quantize_to_scale(i / 30, SCALES["pentatonic"], 60) % 12 for i in range(31)}
    assert got <= {0, 3, 5, 7, 10}


# -- head → MIDI --------------------------------------------------------------

def test_a_tap_plays_the_note_the_head_points_at():
    fs = FaceSynth(scale="major", root=60)
    events = fs.control(yaw=-90, taps=["single"], mic=1.0)   # far left = root
    notes = [e for e in events if e.kind == "note_on"]
    assert notes and notes[0].num == 60 and notes[0].value == 127


def test_pitch_drives_the_expression_cc():
    fs = FaceSynth()
    up = fs.control(pitch=45)[0]
    down = fs.control(pitch=-45)[0]
    assert up.kind == "cc" and up.num == CC_EXPRESSION and up.value == 127
    assert down.value == 0


def test_a_new_tap_releases_the_previous_note():
    fs = FaceSynth()
    fs.control(yaw=-90, taps=["single"])          # play one
    ev = fs.control(yaw=90, taps=["single"])      # play another
    kinds = [e.kind for e in ev]
    assert "note_off" in kinds and "note_on" in kinds
    assert fs.release()[0].kind == "note_off"     # and release lets it go


def test_no_tap_no_note():
    fs = FaceSynth()
    assert not any(e.kind == "note_on" for e in fs.control(yaw=0, taps=[]))


def test_midi_out_seam_receives_events():
    got = []
    fs = FaceSynth(midi_out=got.append)
    fs.control(yaw=0, taps=["single"])
    assert any(e.kind == "note_on" for e in got)


# -- the distributed band -----------------------------------------------------

def test_band_gives_each_member_a_stable_channel():
    band = FaceSynthBand(me="me")
    assert band.voice_for("me") == 0
    a, b = band.voice_for("A"), band.voice_for("B")
    assert a == 1 and b == 2 and band.voice_for("A") == 1     # stable


def test_band_packs_and_rechannels_peer_notes():
    band = FaceSynthBand(me="me")
    events = [MidiEvent("note_on", 64, 100), MidiEvent("cc", 74, 10)]
    body = band.to_packet_body(events)
    assert body == {"notes": [[1, 64, 100]]}                  # only notes cross
    peer = band.from_packet("A", body)
    assert peer[0].kind == "note_on" and peer[0].channel == band.voice_for("A")


def test_note_name():
    assert note_name(60) == "C4" and note_name(69) == "A4"


# -- it loads as a plugin, gated by capability --------------------------------

def test_face_synth_loads_only_with_a_midi_capability():
    r = CardRenderer()
    # no 'midi' capability → skipped, dormant
    ctx0 = PluginContext(renderer=r, capabilities=frozenset())
    reg0 = PluginRegistry(ctx0)
    reg0.load(face_synth_plugin())
    assert reg0.result.skipped and "midi" in reg0.result.skipped[0][1]

    # with 'midi' → loads, registers its card + exposes the controller
    ctx = PluginContext(renderer=r, capabilities=frozenset({"midi"}))
    reg = PluginRegistry(ctx)
    reg.load(face_synth_plugin())
    assert reg.result.loaded == ["face-synth"]
    assert isinstance(ctx.config["face_synth"], FaceSynth)
    r.render({"type": "FaceSynthCard", "note": "C4"})         # renderer wired
