#!/usr/bin/env python3
"""scripts/run_demo_object_lens.py — look at a thing, get a panel.

Wires the Object Lens with its on-device memory provider plus a few
integration seams (laptop / car / plant) fed by fixed demo data, then
"looks at" several objects and prints the contextual panel each produces.

Run:  python scripts/run_demo_object_lens.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.memory.ring_buffer import SemanticRingBuffer          # noqa: E402
from dreamlayer.pipelines.ingest import MemoryEvent                   # noqa: E402
from dreamlayer.object_lens import (                                  # noqa: E402
    ObjectLens, ObjectRecognizer, ProviderRegistry,
    MemoryProvider, NoteProvider, LaptopProvider, CarProvider, PlantProvider,
)

NOW = 1_700_000_000.0


def build_lens():
    ring = SemanticRingBuffer(capacity=64)
    ring.append(MemoryEvent(kind="object", summary="laptop on the desk",
                            confidence=0.8,
                            meta={"object": "laptop", "place": "the desk"}), ts=NOW)
    ring.append(MemoryEvent(kind="object", summary="my copy of Dune on the shelf",
                            confidence=0.8,
                            meta={"object": "book", "owned": True}), ts=NOW)

    reg = ProviderRegistry([
        MemoryProvider(ring),
        NoteProvider({"mug": ["return this to Sam"]}),
        # integration seams — a real build wires these callables to a
        # companion agent / OBD dongle / soil sensor; here: fixed demo data
        LaptopProvider(lambda: {"recent_files": ["Q3-plan.md", "budget.xlsx"],
                                "battery": 82}),
        CarProvider(lambda: {"tire_pressure": 31, "fuel": 55}),
        PlantProvider(lambda: {"last_watered": "6 days ago", "needs_water": True}),
    ])
    return ObjectLens(ring=ring, registry=reg)


# a fixed recogniser output per scene, so the demo is deterministic
def scripted(label, **attrs):
    return ObjectRecognizer(classify_fn=lambda _f: (label, 0.9, attrs))


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def show(lens, label, **attrs):
    lens.recognizer = scripted(label, **attrs)
    panel = lens.look(frame(), now=NOW)
    conf = round(panel.sighting.confidence * 100)
    head = panel.title + (f" · {panel.subtitle}" if panel.subtitle else "")
    print(f"\n  ▸ you look at a {label}")
    print(f"    ┌ {head}  ({conf}%)")
    if panel.is_empty():
        print("    └ (recognised — nothing else known)")
        return
    for r in panel.rows:
        val = f"  {r.value}" if r.value else ""
        det = f" — {r.detail}" if r.detail else ""
        print(f"    · {r.label}{val}{det}   [{r.source}]")
    print(f"    └ sources: {', '.join(panel.sources)}")


def main() -> int:
    lens = build_lens()
    print("\nObject Lens — look at a thing, get a contextual panel\n")
    show(lens, "laptop")
    show(lens, "book")
    show(lens, "mug", brand="blue enamel")
    show(lens, "car")
    show(lens, "houseplant")
    print("\n  A person? The lens declines — people are Social Lens's "
          "consented domain.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
