"""dreamlayer.rem — the glasses literally dream, and the dreaming is functional.

At night, on the charger, DreamLayer enters its own sleep cycle. The
memory engine replays the day *recombined* — anchors from different
hours collide, the poet free-associates across them, palette weathers
blend — and the replay is not decoration: it IS the retrieval-ranking
consolidation pass, made visible. Memories that survive the dream gain
retrieval priority; memories that never surface are let go. Promises
that recur in dreams wake up brighter on the Horizon.

    from dreamlayer.rem import REMCycle

    cycle = REMCycle(ring, drift=drift_engine, seed=night_seed)
    reel  = cycle.run(sweeps=3)        # the night's dreams + bias deltas
    reel.bias.save(vault_dir)          # consumed by retrieval + Horizon

Everything is deterministic under a seed, fully offline, and honors the
privacy contract: veiled or private events are never dreamed, never
scored, never rendered.
"""
from .cycle import REMCycle, DreamReel, DreamScene
from .poet import DreamPoet
from .bias import RetrievalBias, event_key
from .reel import render_reel, reel_transcript
from .nightly import NightWatch

__all__ = [
    "REMCycle", "DreamReel", "DreamScene",
    "DreamPoet",
    "RetrievalBias", "event_key",
    "render_reel", "reel_transcript",
    "NightWatch",
]
