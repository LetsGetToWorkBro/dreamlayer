#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host-python", "src"))
from dreamlayer.simulator import scenarios
from dreamlayer.hud.renderer import render
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "hud", "samples")
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    _, card = scenarios.commitment_multi()
    print("HUD:", card)
    render(card).save(os.path.join(OUT, "commitment_marcus.png"))
    print("Exported commitment_marcus.png")
