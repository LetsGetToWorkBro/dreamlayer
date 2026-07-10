"""plugins/face_synth.py — Face Synth: your head is a MIDI controller.

The first real plugin on the extension API (docs/PLATFORM.md) — and proof the
platform can host things the core team never imagined. It turns the glasses'
own sensors into an instrument:

    head yaw   → which note (quantised to a scale, so you can't play wrong)
    head pitch → a filter/expression CC (tilt up = open, down = closed)
    a tap      → play the note; mic loudness sets how hard (velocity)

Multiple wearers on a GhostMode circle become a **distributed band**: each
wearer is a voice on their own MIDI channel, their notes gossiped over the mesh
so everyone's rig hears the whole ensemble.

Everything here is pure and offline-testable. The one seam is `midi_out(event)`
— a python-rtmidi / OSC bridge on the host. As a plugin it declares
`requires=("midi",)`, so it simply doesn't load until a MIDI bridge is present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# a few scales as semitone offsets from the root
SCALES = {
    "major":      (0, 2, 4, 5, 7, 9, 11),
    "minor":      (0, 2, 3, 5, 7, 8, 10),
    "pentatonic": (0, 3, 5, 7, 10),
    "chromatic":  tuple(range(12)),
}

CC_EXPRESSION = 74          # filter cutoff / brightness, the classic expression CC


@dataclass
class MidiEvent:
    kind: str                # "note_on" | "note_off" | "cc" | "pitch"
    num: int                 # note number / CC number
    value: int               # velocity / CC value / bend (0..127, pitch 0..16383)
    channel: int = 0


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def quantize_to_scale(pos: float, scale=SCALES["major"], root: int = 60,
                      octaves: int = 2) -> int:
    """Map a 0..1 position to a MIDI note locked to a scale — you land on a
    scale degree, never between the keys. `pos` spans `octaves` above `root`."""
    steps = len(scale) * max(1, octaves)
    idx = int(round(_clamp(pos, 0.0, 1.0) * (steps - 1)))
    octave, degree = divmod(idx, len(scale))
    return int(_clamp(root + 12 * octave + scale[degree], 0, 127))


class FaceSynth:
    """Head pose + taps + mic → MIDI. Stateless per call except the last note,
    so a tap plays the note the head is currently pointing at and releases the
    previous one."""

    def __init__(self, scale: str = "major", root: int = 60, channel: int = 0,
                 midi_out: Optional[Callable[[MidiEvent], None]] = None):
        self.scale = SCALES.get(scale, SCALES["major"])
        self.root = root
        self.channel = channel
        self._out = midi_out
        self._last_note: Optional[int] = None

    def control(self, yaw: float = 0.0, pitch: float = 0.0,
                taps: Optional[list] = None, mic: float = 0.5) -> list:
        """yaw ∈ [-90,90] picks the note; pitch ∈ [-45,45] drives the
        expression CC; each tap plays the current note with velocity from `mic`
        (0..1). Returns the MidiEvents (also emitted through midi_out)."""
        events: list = []
        # expression from head tilt (down = closed, up = open)
        cc = int(_clamp((pitch + 45.0) / 90.0, 0.0, 1.0) * 127)
        events.append(MidiEvent("cc", CC_EXPRESSION, cc, self.channel))
        # note from head yaw, locked to the scale
        pos = _clamp((yaw + 90.0) / 180.0, 0.0, 1.0)
        note = quantize_to_scale(pos, self.scale, self.root)
        vel = int(_clamp(mic, 0.0, 1.0) * 126) + 1     # 1..127
        for t in (taps or []):
            if self._last_note is not None:
                events.append(MidiEvent("note_off", self._last_note, 0, self.channel))
            events.append(MidiEvent("note_on", note, vel, self.channel))
            self._last_note = note
        for e in events:
            self._emit(e)
        return events

    def release(self) -> list:
        """Let the held note go (lift the button)."""
        if self._last_note is None:
            return []
        e = MidiEvent("note_off", self._last_note, 0, self.channel)
        self._last_note = None
        self._emit(e)
        return [e]

    def _emit(self, e: MidiEvent) -> None:
        if self._out is not None:
            try:
                self._out(e)
            except Exception:
                pass


class FaceSynthBand:
    """Several wearers, one ensemble. Each member gets a stable MIDI channel;
    their note events (gossiped over the GhostMode mesh) are re-channelled so
    every rig plays the whole band. Channel 0 is you."""

    def __init__(self, me: str = "me", max_voices: int = 16):
        self.me = me
        self.max_voices = max_voices
        self._channels: dict[str, int] = {me: 0}

    def voice_for(self, member_id: str) -> int:
        """Stable channel per member — you are 0, others fill 1.. in join order,
        wrapping at max_voices."""
        if member_id not in self._channels:
            self._channels[member_id] = len(self._channels) % self.max_voices
        return self._channels[member_id]

    def to_packet_body(self, events: list) -> dict:
        """Pack local note events for the mesh (only note on/off crosses — the
        smallest possible: kind, note, velocity)."""
        notes = [[1 if e.kind == "note_on" else 0, e.num, e.value]
                 for e in events if e.kind in ("note_on", "note_off")]
        return {"notes": notes}

    def from_packet(self, member_id: str, body: dict) -> list:
        """Turn a peer's packet into MidiEvents on that peer's channel."""
        ch = self.voice_for(member_id)
        out = []
        for on, num, vel in (body or {}).get("notes", []):
            out.append(MidiEvent("note_on" if on else "note_off",
                                  int(num), int(vel), ch))
        return out


class FaceSynthPlugin:
    """API v2 plugin (lifecycle + settings). register() stashes a live FaceSynth
    on ctx.config and registers the FaceSynthCard renderer, exactly as v1;
    start() restores the wearer's chosen scale from ctx.settings, and set_scale()
    persists a new one. requires=('midi',) so it stays dormant until a MIDI
    bridge is available."""
    name = "face-synth"
    version = "0.1.0"
    requires = ("midi",)

    def __init__(self, midi_out: Optional[Callable] = None, scale: str = "major"):
        self._midi_out = midi_out
        self._default_scale = scale
        self.synth: Optional[FaceSynth] = None
        self._settings = None            # name-bound settings (captured in register)

    def register(self, ctx):
        self._settings = ctx.settings    # scoped to this plugin during load
        self.synth = FaceSynth(scale=self._default_scale, midi_out=self._midi_out)
        ctx.config["face_synth"] = self.synth
        ctx.add_card_renderer("FaceSynthCard", _draw_face_synth_card)

    def start(self, ctx):
        name = str(self._settings.get("scale", self._default_scale)
                   if self._settings else self._default_scale)
        if self.synth is not None:
            self.synth.scale = SCALES.get(name, SCALES["major"])

    def set_scale(self, name: str) -> None:
        """Set (and persist) the scale every note is locked to."""
        if self.synth is not None:
            self.synth.scale = SCALES.get(name, SCALES["major"])
        if self._settings is not None:
            self._settings.set("scale", name)


def face_synth_plugin(midi_out: Optional[Callable] = None, scale: str = "major"):
    """Face Synth as an API v2 plugin (lifecycle + settings). requires=('midi',)."""
    return FaceSynthPlugin(midi_out=midi_out, scale=scale)


def _draw_face_synth_card(draw, card) -> None:
    """A minimal performance HUD: the note name, centred. fn(draw, card) — the
    plugin card-renderer contract."""
    note = str(card.get("note", ""))
    try:
        draw.text((128, 120), note, anchor="mm", fill=(255, 255, 255))
    except Exception:
        pass


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(num: int) -> str:
    return f"{NOTE_NAMES[num % 12]}{num // 12 - 1}"
