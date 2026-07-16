"""make_dmg_art.py — the .dmg Finder-window background, from the shared packaging art.

    cd host-python/packaging
    python make_dmg_art.py     # -> dmg-background.png, dmg-background@2x.png

The mounted .dmg is the Mac's first-run "boot screen" — the one window every
installer sees — so it wears the same Platinum identity as the Windows wizard
(windows/make_installer_art.py): the dusk gradient sampled from the little-Mac
icon itself, a sparse starfield, the wordmark in Chicago (pulled from the
repo's own ChicagoFLF.ttf when the full checkout is present; silently omitted
otherwise — the art degrades, it never fails a build), and a hard-shadowed
drag arrow between where create-dmg pins the app and the Applications link.

Geometry is contract-coupled to build-macos-app.yml's create-dmg call:
window 600x380, 128px icons centered at (150,180) and (450,180). Drawn once
per scale (crisp at both), then CI staples 1x+2x into a HiDPI tiff with
tiffutil. Pillow only, deterministic, generated at build time — not committed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent          # host-python/packaging
ROOT = HERE.parents[1]                          # repo root (full checkout)
CHICAGO = ROOT / "phone-app" / "assets" / "fonts" / "ChicagoFLF.ttf"

WINDOW = (600, 380)                             # create-dmg --window-size
ICON_Y = 180                                    # icon row centerline
APP_X, DROP_X = 150, 450                        # icon centers (128px icons)

INK_HI = (236, 240, 241)                        # platinum light
INK_DIM = (168, 182, 188)                       # footer
SHADOW = (6, 14, 16)                            # hard 1px drop, never a blur

# deterministic "stars" — hand-placed like the icon's, clear of the icon row,
# the labels under it, and the centered footer line
STARS = [(0.06, 0.08), (0.20, 0.14), (0.36, 0.05), (0.55, 0.11),
         (0.70, 0.04), (0.87, 0.12), (0.94, 0.30), (0.04, 0.33),
         (0.10, 0.88), (0.91, 0.86)]


def _dusk(size: tuple[int, int], icon: Image.Image, s: int) -> Image.Image:
    """A vertical dusk gradient sampled from the icon art itself, so the
    window ground always matches the shipped icon exactly."""
    w, h = size
    def px(x: int, y: int) -> tuple[int, int, int]:
        r, g, b, _ = icon.getpixel((x, y))
        return (r, g, b)
    top, bot = px(512, 60), px(512, 964)
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)],
               fill=tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    for fx, fy in STARS:
        x, y = round(fx * (w - 2)), round(fy * (h - 2))
        d.rectangle((x, y, x + s, y + s), fill=(214, 224, 228))
    return img


def _text(canvas: Image.Image, text: str, top: int, px_size: int, s: int,
          fill: tuple[int, int, int] = INK_HI) -> None:
    """Centered Chicago with the Platinum hard drop shadow. Skipped (with a
    note) when the font isn't in this checkout — never a build failure."""
    if not CHICAGO.exists():
        print(f"note: {CHICAGO.name} not found — dmg art ships without '{text}'")
        return
    from PIL import ImageFont
    font = ImageFont.truetype(str(CHICAGO), px_size * s)
    d = ImageDraw.Draw(canvas)
    box = d.textbbox((0, 0), text, font=font)
    x = (canvas.width - (box[2] - box[0])) // 2 - box[0]
    d.text((x + s, top * s + s), text, font=font, fill=SHADOW)
    d.text((x, top * s), text, font=font, fill=fill)


def _arrow(canvas: Image.Image, s: int) -> None:
    """The drag path: a dashed platinum line with a hard triangular head,
    running the gap between the app icon and the Applications link."""
    d = ImageDraw.Draw(canvas)
    y = ICON_Y * s
    x0, x1 = 232 * s, 352 * s
    dash, gap, wd = 9 * s, 7 * s, 3 * s
    head = [(x1, y - 8 * s), (x1, y + 8 * s), (x1 + 15 * s, y)]
    # shadow pass first (offset one hard step down-right), then the light pass
    for off, fill in ((s, SHADOW), (0, INK_HI)):
        x = x0
        while x < x1 - 2 * s:
            d.line([(x + off, y + off), (min(x + dash, x1 - 2 * s) + off, y + off)],
                   fill=fill, width=wd)
            x += dash + gap
        d.polygon([(px + off, py + off) for px, py in head], fill=fill)


def _compose(s: int, icon: Image.Image) -> Image.Image:
    img = _dusk((WINDOW[0] * s, WINDOW[1] * s), icon, s)
    _text(img, "DREAMLAYER", 30, 30, s)
    _text(img, "drag DreamLayer into Applications. that's the whole install.", 74, 13, s)
    _arrow(img, s)
    _text(img, "Private by architecture. Yours to run, yours to keep.", 348, 12, s, INK_DIM)
    return img


def main() -> int:
    icon = Image.open(HERE / "icon.png").convert("RGBA")
    _compose(1, icon).save(HERE / "dmg-background.png")
    _compose(2, icon).save(HERE / "dmg-background@2x.png")
    print(f"wrote dmg-background.png {WINDOW} and dmg-background@2x.png "
          f"({WINDOW[0] * 2}, {WINDOW[1] * 2})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
