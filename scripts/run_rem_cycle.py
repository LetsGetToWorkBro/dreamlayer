#!/usr/bin/env python3
"""scripts/run_rem_cycle.py — one night of functional dreaming, end to end.

Synthesizes a plausible day (memories, people, promises across hours),
runs the REM cycle, prints the consolidation report, applies the bias,
and shows the Horizon difference: which marks wake up brighter because
the glasses dreamed about them. Frames export to out/rem/.

Run:  python scripts/run_rem_cycle.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.memory.ring_buffer import SemanticRingBuffer   # noqa: E402
from dreamlayer.pipelines.ingest import MemoryEvent            # noqa: E402
from dreamlayer.orchestrator.horizon_composer import HorizonComposer  # noqa: E402
from dreamlayer.rem import REMCycle, RetrievalBias, render_reel  # noqa: E402

OUT = REPO_ROOT / "out" / "rem"
NOW = time.time()
H = 3600.0


def build_day() -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=64)
    day = [
        (9,  "memory",  "left the car on level 3 at the office garage", .8),
        (10, "person",  "met Maya about the contract deadline",         .9),
        (11, "promise", "send Marcus the contract by Friday",           .9),
        (12, "memory",  "lunch at the corner cafe",                     .5),
        (13, "memory",  "keys on the kitchen counter",                  .7),
        (15, "memory",  "a grey cat on the studio windowsill",          .4),
        (18, "person",  "rolled with Dre at the gym",                   .8),
        (18, "memory",  "the gym clock is seven minutes fast",          .6),
        (20, "memory",  "watered the plants",                           .35),
        (21, "memory",  "mother called about the weekend",              .7),
    ]
    for hour, kind, summary, conf in day:
        ring.append(MemoryEvent(kind=kind, summary=summary,
                                confidence=conf),
                    ts=NOW - (22 - hour) * H)
    # one private moment: never dreamed, never scored
    ring.append(MemoryEvent(kind="memory", summary="private note to self",
                            confidence=0.9, meta={"private": True}),
                ts=NOW - 4 * H)
    return ring


def main() -> None:
    ring = build_day()
    cycle = REMCycle(ring, seed=42, now_fn=lambda: NOW)
    reel = cycle.run(sweeps=3)

    print("=" * 64)
    print(reel.report())
    print("=" * 64)

    assert all("private" not in s.phrase for s in reel.scenes)

    bias = reel.apply_to(RetrievalBias())
    written = render_reel(reel, OUT)
    print(f"reel: {len(written)} frames + transcript → {OUT}")

    # the morning difference: same day, with and without the night
    plain = HorizonComposer(ring, None, now_fn=lambda: NOW)
    dreamt = HorizonComposer(ring, None, now_fn=lambda: NOW, rem=bias)
    v0, v1 = plain.compose(NOW)["v"], dreamt.compose(NOW)["v"]
    brighter = sum(1 for a, b in zip(v0[1::2], v1[1::2]) if b > a)
    print(f"horizon: {brighter} marks wake up brighter because "
          "the glasses dreamed about them")


if __name__ == "__main__":
    main()
