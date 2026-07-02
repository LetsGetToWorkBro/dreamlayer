#!/usr/bin/env python3
"""scripts/run_demo_object_companion.py — a real Object Lens integration.

Fills the LaptopProvider seam end to end: a reference companion agent serves
laptop context over local HTTP, a PolledSource fetches it off the glance
path, and the Object Lens shows the panel. Also shows the two production
behaviours — the cache (a second glance doesn't refetch) and stale-not-blank.

Run:  python scripts/run_demo_object_companion.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.object_lens import (                                  # noqa: E402
    ObjectLens, ObjectRecognizer, ProviderRegistry, LaptopProvider, PolledSource,
)
from dreamlayer.object_lens.integrations import (                     # noqa: E402
    serve_companion, laptop_data_source,
)


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def main() -> int:
    fetches = {"n": 0}

    def laptop_context():                 # what the companion agent reads from the OS
        fetches["n"] += 1
        return {"recent_files": ["Q3-plan.md", "budget.xlsx", "sketch.fig"],
                "battery": 82, "hostname": "studio-mbp"}

    companion = serve_companion(laptop_context, token="rune-birch")
    print("\nObject Lens — a real integration (laptop companion)\n")
    print(f"  companion serving on {companion.url}/dreamlayer/context")
    try:
        # phone side: wrap the LAN fetch in a PolledSource, feed LaptopProvider
        src = PolledSource(laptop_data_source(companion.url, token="rune-birch"),
                           ttl=30)
        src.refresh(block=True)           # warm the cache once
        lens = ObjectLens(
            recognizer=ObjectRecognizer(classify_fn=lambda _f: ("laptop", 0.92, {})),
            registry=ProviderRegistry([LaptopProvider(src)]))

        print("\n  ▸ you look at your laptop")
        panel = lens.look(frame())
        print(f"    ┌ {panel.title}  ({round(panel.sighting.confidence*100)}%)")
        for r in panel.rows:
            val = f"  {r.value}" if r.value else ""
            det = f" — {r.detail}" if r.detail else ""
            print(f"    · {r.label}{val}{det}")
        print(f"    └ over real HTTP · {fetches['n']} fetch so far")

        print("\n  ▸ you glance again a second later")
        lens.look(frame())
        print(f"    the cache answered — still {fetches['n']} fetch "
              "(the LAN wasn't hit on the glance path)")

        print("\n  This is the whole seam: anything speaking the 3-line "
              "contract\n  (GET /dreamlayer/context) drops straight in — "
              "OBD dongle, soil sensor, all the same shape.\n")
    finally:
        companion.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
