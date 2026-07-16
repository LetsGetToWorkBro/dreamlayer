#!/usr/bin/env python3
"""Generate the Android-only brand assets from the canonical app icon.

Android needs two marks iOS doesn't:
  * assets/notification-icon.png — the status-bar small icon. Android renders
    only the alpha channel, tinted by the system, so it must be a white-on-
    transparent glyph (expo-notifications rejects colored icons at build time).
  * assets/adaptive-icon-monochrome.png — the Android 13+ themed-icon layer,
    same rule: pure alpha silhouette, centered in the adaptive-icon safe zone
    (the middle ~66% of the canvas survives every launcher mask).

Both are derived from the teal halo-gear on the little Mac's screen in
assets/icon.png — the brand ring mark — so the three icons stay one drawing.
Regenerate after changing icon.png:  python3 scripts/make-android-brand-assets.py
(requires Pillow: pip install pillow)
"""
from PIL import Image
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(ROOT, "assets", "icon.png")


def gear_mask() -> Image.Image:
    """Lift the teal gear glyph out of icon.png as an alpha mask."""
    im = Image.open(ICON).convert("RGB")
    w, h = im.size
    px = im.load()
    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            # teal = green-dominant; excludes the grey chassis and the starfield
            if g > 90 and g > r * 1.6 and g > b * 1.15:
                mp[x, y] = 255
    bbox = mask.getbbox()
    # crop to the gear on the screen only — the little power LED lower on the
    # chassis also matches the teal test and must not ride along
    gear = mask.crop((bbox[0], bbox[1], bbox[2], 620))
    return gear.crop(gear.getbbox())


def white_glyph(mask: Image.Image) -> Image.Image:
    out = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    out.putalpha(mask)
    white = Image.new("RGBA", mask.size, (255, 255, 255, 255))
    return Image.composite(white, Image.new("RGBA", mask.size, (0, 0, 0, 0)), mask)


def save_centered(glyph: Image.Image, canvas_px: int, glyph_px: int, path: str) -> None:
    scale = glyph_px / max(glyph.size)
    size = (round(glyph.size[0] * scale), round(glyph.size[1] * scale))
    resized = glyph.resize(size, Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    canvas.paste(resized, ((canvas_px - size[0]) // 2, (canvas_px - size[1]) // 2), resized)
    canvas.save(path)
    print("wrote", os.path.relpath(path, ROOT), canvas.size)


def main() -> None:
    glyph = white_glyph(gear_mask())
    # status-bar small icon: glyph fills most of the canvas (Android shows ~24dp)
    save_centered(glyph, 96, 84, os.path.join(ROOT, "assets", "notification-icon.png"))
    # themed-icon layer: keep the glyph inside the 66% safe circle with margin
    save_centered(glyph, 1024, 560, os.path.join(ROOT, "assets", "adaptive-icon-monochrome.png"))


if __name__ == "__main__":
    main()
