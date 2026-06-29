from __future__ import annotations
import os
from .cards import ALL_SAMPLES
from .renderer import CardRenderer

def export_all(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    r = CardRenderer()
    paths = []
    for name, payload in ALL_SAMPLES.items():
        p = os.path.join(out_dir, f"{name}.png")
        r.save(payload, p)
        paths.append(p)
    return paths

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "assets", "hud", "samples")
    for p in export_all(os.path.abspath(out)):
        print("saved", p)
