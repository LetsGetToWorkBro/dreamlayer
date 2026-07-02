from __future__ import annotations
import os
from .cards import ALL_SAMPLES
from .renderer import CardRenderer, draw_contact_sheet


def export_all(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    r = CardRenderer()
    paths = []
    card_images = []
    for name, payload in ALL_SAMPLES.items():
        p = os.path.join(out_dir, f"{name}.png")
        img = r.render(payload)
        img.save(p)
        paths.append(p)
        card_images.append((name, img))
    # Generate contact sheet
    sheet_dir = os.path.dirname(out_dir)  # assets/hud/
    sheet_path = os.path.join(sheet_dir, "contact_sheet.png")
    # 5x5 grid fits the full Halo Cinema v1 card library
    draw_contact_sheet(card_images, sheet_path, grid_cols=5, grid_rows=5)
    print("saved contact_sheet", sheet_path)
    return paths


if __name__ == "__main__":
    out = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "assets", "hud", "samples"
    )
    for p in export_all(os.path.abspath(out)):
        print("saved", p)
