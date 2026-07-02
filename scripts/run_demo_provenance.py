#!/usr/bin/env python3
"""scripts/run_demo_provenance.py — the Provenance Lens: where beliefs come from.

Builds a small memory of things you were told and things you saw, then traces
a few beliefs back to their origins and standing: who put it in your head,
when, and whether it's corroborated, firsthand, or already contested.

Run:  python scripts/run_demo_provenance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.memory.ring_buffer import SemanticRingBuffer          # noqa: E402
from dreamlayer.pipelines.ingest import MemoryEvent                   # noqa: E402
from dreamlayer.orchestrator.provenance import ProvenanceLens         # noqa: E402

NOW = 1_700_000_000.0
DAY = 86_400.0


def main() -> int:
    ring = SemanticRingBuffer(capacity=64)
    def remember(summary, ago_days, **meta):
        ring.append(MemoryEvent(kind="memory", summary=summary, confidence=0.8,
                                meta=meta), ts=NOW - ago_days * DAY)

    remember("the project deadline is Friday", 21, person="Maya", via="heard")
    remember("Friday is when the project is due", 4, person="Sam", via="heard")
    remember("the team standup is at 10", 9, person="Priya", via="heard")
    remember("the team standup is at 11", 1, person="Deshawn", via="heard")
    remember("saw the fire exit is behind the kitchen", 2, via="saw")

    lens = ProvenanceLens(ring)
    print("\nProvenance Lens — the genealogy of a belief\n")
    for claim in ["the project deadline is Friday",
                  "the team standup is at 10",
                  "the fire exit is behind the kitchen"]:
        r = lens.trace(claim, now=NOW)
        print(f"  “{claim}”")
        if not r.found:
            print("     no source in your memory — unknown\n")
            continue
        print(f"     origin:  {r.origin.attribution(NOW)}")
        print(f"     standing: {r.status.upper()}"
              + (f"  ({r.corroboration} sources)" if r.corroboration >= 2 else ""))
        if r.contradiction:
            print(f"     but also recorded: “{r.contradiction}”")
        print()
    print("  (nothing left the device — it only read your own memory)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
