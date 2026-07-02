#!/usr/bin/env python3
"""scripts/run_demo_ai_brain.py — Phase 1 of the AI brain (see docs/AI_BRAIN.md).

Runs the whole tiered pipeline with deterministic mock brains — no model
needed — to show the shape of the real thing:

  * look at anything -> an AI names + explains it (AI Object Lens)
  * "more" escalates from the on-device tier to the Mac mini brain
  * cloud stays gated until you opt in for the session
  * ask your own files -> answered from your own machine (folds into Lucid Recall)

Run:  python scripts/run_demo_ai_brain.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.ai_brain import (                                    # noqa: E402
    BrainRouter, MockVisionBrain, MockKnowledgeBrain,
)
from dreamlayer.object_lens import (                                 # noqa: E402
    ObjectLens, ObjectRecognizer, ProviderRegistry, AIProvider,
)

DEVICE = {"snake plant": "a snake plant", "wine bottle": "a bottle of wine"}
MACMINI = {"snake plant": "snake plant — water every 2-3 weeks, tolerates low "
                          "light; yours looks a touch overwatered",
           "wine bottle": "2018 Rioja Reserva — pairs with lamb, drink now"}
CLOUD = {"trilobite fossil": "Ordovician trilobite, ~450M years old, "
                             "common in Morocco"}


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def brain():
    r = BrainRouter()
    r.add_vision(MockVisionBrain("device", DEVICE, serves_deep=False))
    r.add_vision(MockVisionBrain("laptop", MACMINI, serves_deep=True))
    r.add_vision(MockVisionBrain("cloud", CLOUD, is_cloud=True))
    r.add_knowledge(MockKnowledgeBrain({
        "lease.pdf": "Rent is 2400 per month, due on the first.\n"
                     "The lease ends in June 2026.",
        "marcus.md": "Marcus prefers email; owes me the signed contract."}))
    return r


def explain(r, label, want="quick"):
    lens = ObjectLens(
        recognizer=ObjectRecognizer(classify_fn=lambda _f: (label, 0.92, {})),
        registry=ProviderRegistry([AIProvider(r, want=want)]))
    panel = lens.look(frame())
    row = next((x for x in panel.rows if x.label == "about"), None)
    return row


def main() -> int:
    r = brain()
    print("\nAI Brain — Phase 1 (mock tiers; the real Mac mini model plugs "
          "into the same seam)\n")

    print("  ▸ look at a snake plant")
    row = explain(r, "snake plant")
    print(f"    {row.detail}   [{row.source}]")
    print("  ▸ ask for more — escalates to the Mac mini brain")
    row = explain(r, "snake plant", want="more")
    print(f"    {row.detail}   [{row.source}]")

    print("\n  ▸ look at a fossil (only the cloud tier knows it)")
    print(f"    cloud off (default): "
          f"{explain(r, 'trilobite fossil') or 'no answer — stays on-device'}")
    r.opt_in_cloud(True)
    row = explain(r, "trilobite fossil")
    print(f"    after you opt in:    {row.detail}   [{row.source}]")

    print("\n  ▸ ask your own files (Lucid Recall over the Mac mini)")
    for q in ["how much is the rent", "what does Marcus owe me"]:
        ans = r.ask(q)
        print(f"    “{q}?”  ->  {ans.text}   [{ans.tier}: {ans.sources[0]}]")

    print("\n  Everything stayed on your devices except the one cloud call "
          "you opted into.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
