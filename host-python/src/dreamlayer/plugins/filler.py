"""plugins/filler.py — Filler-Word Counter (perception + cards).

A quiet coach for public speaking: it listens to your own words and tallies the
"um / uh / like / you know / basically" as you go, so you can hear yourself.
The count sits in the corner of your HUD; nothing is recorded or sent anywhere.

Demonstrates: an on-glass `Perceptor` (the perception tier) + a HUD card. The
perceptor's `listen()` seam takes the transcribed line (ASR is a device seam),
so the whole thing tests offline with plain strings.
"""
from __future__ import annotations

import re
from typing import Optional

from dreamlayer.ai_brain.perception import AudioPercept
from dreamlayer.plugins import make_plugin

# multi-word fillers first so they win over their own words ("you know" before
# a bare "know" — which isn't a filler anyway)
FILLERS = ("you know", "i mean", "sort of", "kind of", "um", "uh", "er",
           "like", "basically", "literally", "actually", "right")
_FILLER_RE = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in FILLERS) + r")\b", re.I)


def count_fillers(text: str) -> int:
    """How many filler words/phrases are in one line."""
    return len(_FILLER_RE.findall(text or ""))


class FillerCounter:
    """A perceptor that tallies fillers across a talk. Returns an AudioPercept
    (keyword='filler') on any line that had one, so the router can flash the
    card; the running total lives here for the HUD."""
    tier = "filler"
    is_npu = False

    def __init__(self):
        self.total = 0
        self.lines = 0

    def perceive(self, frame):
        return None                       # not a vision perceptor

    def listen(self, audio) -> Optional[AudioPercept]:
        # `audio` is the transcribed line (device ASR seam); ignore non-text
        if not isinstance(audio, str):
            return None
        self.lines += 1
        n = count_fillers(audio)
        if n == 0:
            return None
        self.total += n
        return AudioPercept(speaking=True, keyword="filler", tier=self.tier)

    def rate(self) -> float:
        """Fillers per line so far — a rough 'per sentence' pace."""
        return round(self.total / self.lines, 2) if self.lines else 0.0


def _draw_filler_card(draw, card) -> None:
    """fn(draw, card): the running tally."""
    try:
        draw.text((128, 110), str(card.get("count", 0)), anchor="mm",
                  fill=(255, 255, 255))
        draw.text((128, 150), "fillers", anchor="mm", fill=(150, 170, 170))
    except Exception:
        pass


def filler_plugin():
    """Register the counter perceptor + its card. requires=('perception','cards').
    prefer=False so it never shadows the real wake/vision tiers — it only adds a
    tally, deferring (returns None) on everything else."""
    def register(ctx):
        counter = FillerCounter()
        ctx.config["filler_counter"] = counter
        ctx.add_perceptor(counter, prefer=False)
        ctx.add_card_renderer("FillerCard", _draw_filler_card)
    return make_plugin("filler-word-counter", register,
                       requires=("perception", "cards"), version="0.1.0")
