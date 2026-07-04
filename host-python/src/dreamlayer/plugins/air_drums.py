"""plugins/air_drums.py — Air Drums (midi + cards).

Play a drum kit in the air: a quick head-nod or hand-tap in a zone fires a
General-MIDI drum — kick, snare, hi-hat, tom, crash — on MIDI channel 10, so it
drives any DAW or drum machine. No sticks, no pads.

Demonstrates: the `midi` capability (a plugin that emits MIDI, like Face Synth)
+ a HUD card. Pure mapping logic; the host feeds it gestures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from dreamlayer.plugins import make_plugin

DRUM_CHANNEL = 9                 # 0-based MIDI channel 10 — the GM drum channel

# zone → (General MIDI drum note, label)
KIT = {
    "down":   (36, "kick"),      # nod down
    "left":   (38, "snare"),     # tap/lean left
    "right":  (42, "hihat"),     # tap/lean right
    "up":     (49, "crash"),     # head up
    "center": (45, "tom"),       # centre tap
}


@dataclass
class DrumHit:
    note: int
    velocity: int
    label: str
    channel: int = DRUM_CHANNEL

    def as_midi(self) -> tuple:
        """(status, note, velocity) for a Note-On on the drum channel."""
        return (0x90 | self.channel, self.note, self.velocity)


def hit_for(zone: str, intensity: float = 0.8) -> Optional[DrumHit]:
    """Map a gesture zone + intensity (0..1) to a drum hit, or None if the zone
    isn't in the kit. Velocity is clamped to a musical 1..127."""
    entry = KIT.get(zone)
    if entry is None:
        return None
    note, label = entry
    vel = max(1, min(127, int(round(intensity * 127))))
    return DrumHit(note=note, velocity=vel, label=label)


class AirDrums:
    """Live worker stashed on ctx.config. `strike(zone, intensity)` returns the
    DrumHit and, when a MIDI sink is wired, sends it."""

    def __init__(self, midi_out: Optional[Callable[[tuple], None]] = None):
        self._midi_out = midi_out
        self.last: Optional[DrumHit] = None

    def strike(self, zone: str, intensity: float = 0.8) -> Optional[DrumHit]:
        hit = hit_for(zone, intensity)
        if hit is None:
            return None
        self.last = hit
        if self._midi_out is not None:
            try:
                self._midi_out(hit.as_midi())
            except Exception:
                pass
        return hit


def _draw_air_drum_card(draw, card) -> None:
    """fn(draw, card): the drum you just hit."""
    try:
        draw.text((128, 128), str(card.get("drum", "")), anchor="mm",
                  fill=(255, 255, 255))
    except Exception:
        pass


def air_drums_plugin(midi_out: Optional[Callable] = None):
    """Register the kit + its card. requires=('midi',) — dormant until a MIDI
    bridge is present."""
    def register(ctx):
        ctx.config["air_drums"] = AirDrums(midi_out=midi_out)
        ctx.add_card_renderer("AirDrumCard", _draw_air_drum_card)
    return make_plugin("air-drums", register, requires=("midi",), version="0.1.0")
