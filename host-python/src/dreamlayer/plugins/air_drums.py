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
    DrumHit and, when a MIDI sink is wired, sends it. `sensitivity` scales how
    hard a given gesture hits (a persisted v2 setting; 1.0 = as-played)."""

    def __init__(self, midi_out: Optional[Callable[[tuple], None]] = None,
                 sensitivity: float = 1.0):
        self._midi_out = midi_out
        self.sensitivity = sensitivity
        self.last: Optional[DrumHit] = None

    def strike(self, zone: str, intensity: float = 0.8) -> Optional[DrumHit]:
        hit = hit_for(zone, intensity * self.sensitivity)
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


class AirDrumsPlugin:
    """API v2 plugin (lifecycle + settings). register() wires the kit + card as
    v1; start() restores the wearer's persisted `sensitivity`, and set_sensitivity()
    saves a new one. requires=('midi',) — dormant until a MIDI bridge is present."""
    name = "air-drums"
    version = "0.1.0"
    requires = ("midi",)

    def __init__(self, midi_out: Optional[Callable] = None):
        self._midi_out = midi_out
        self.kit: Optional[AirDrums] = None
        self._settings = None            # name-bound settings (captured in register)

    def register(self, ctx):
        self._settings = ctx.settings    # scoped to this plugin during load
        self.kit = AirDrums(midi_out=self._midi_out)
        ctx.config["air_drums"] = self.kit
        ctx.add_card_renderer("AirDrumCard", _draw_air_drum_card)

    def start(self, ctx):
        if self.kit is not None and self._settings is not None:
            self.kit.sensitivity = float(self._settings.get("sensitivity", 1.0))

    def set_sensitivity(self, value: float) -> None:
        """Set (and persist) how hard gestures hit (0..~2, 1.0 = as-played)."""
        value = max(0.1, min(2.0, float(value)))
        if self.kit is not None:
            self.kit.sensitivity = value
        if self._settings is not None:
            self._settings.set("sensitivity", value)


def air_drums_plugin(midi_out: Optional[Callable] = None):
    """Air Drums as an API v2 plugin (lifecycle + settings). requires=('midi',)."""
    return AirDrumsPlugin(midi_out=midi_out)
