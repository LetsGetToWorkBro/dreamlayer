"""make_installer_art.py — the Inno Setup wizard art, from the shared packaging art.

    cd host-python/packaging/windows
    python make_installer_art.py     # -> wizard.bmp, wizard-small.bmp

The installer is Windows' first-run "boot screen", so it wears the same
Platinum identity as everything else: the dusk gradient sampled from the
little-Mac icon itself, a sparse starfield, the icon, and the wordmark in
Chicago (pulled from the repo's own ChicagoFLF.ttf when the full checkout is
present; silently omitted otherwise — the art degrades, it never fails a
build). Pillow only, deterministic, generated at build time next to
dreamlayer.ico — neither binary is committed.

Sizes are Inno Setup 6's WizardStyle=modern maximums (497x360 banner,
138x140 small mark); Inno scales them down for lower DPI. BMP has no alpha,
so everything is flattened onto the dusk ground.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ART = HERE.parent                        # host-python/packaging
ROOT = HERE.parents[2]                   # repo root (full checkout)
CHICAGO = ROOT / "phone-app" / "assets" / "fonts" / "ChicagoFLF.ttf"

BANNER = (497, 360)                      # WizardImageFile, modern style
SMALL = (138, 140)                       # WizardSmallImageFile, modern style

# deterministic "stars" — hand-placed like the icon's, not random
STARS = [(0.08, 0.12), (0.22, 0.05), (0.86, 0.09), (0.66, 0.18),
         (0.12, 0.42), (0.93, 0.38), (0.05, 0.72), (0.90, 0.80),
         (0.30, 0.88), (0.74, 0.93)]


def _dusk(size: tuple[int, int], icon: Image.Image) -> Image.Image:
    """A vertical dusk gradient sampled from the icon art itself, so the
    installer ground always matches the shipped icon exactly."""
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
        d.rectangle((x, y, x + 1, y + 1), fill=(214, 224, 228))
    return img


def _wordmark(canvas: Image.Image, text: str, cy: int, px_size: int) -> None:
    """The wordmark in Chicago, centered at cy. Skipped (with a note) when the
    font isn't in this checkout — never a build failure."""
    if not CHICAGO.exists():
        print(f"note: {CHICAGO.name} not found — wizard art ships without the wordmark")
        return
    from PIL import ImageFont
    font = ImageFont.truetype(str(CHICAGO), px_size)
    d = ImageDraw.Draw(canvas)
    wbox = d.textbbox((0, 0), text, font=font)
    x = (canvas.width - (wbox[2] - wbox[0])) // 2 - wbox[0]
    # a hard 1px drop shadow, the Platinum way — no soft blurs
    d.text((x + 2, cy + 2), text, font=font, fill=(6, 14, 16))
    d.text((x, cy), text, font=font, fill=(236, 240, 241))


def main() -> int:
    icon = Image.open(ART / "icon.png").convert("RGBA")

    # ---- the tall welcome banner -------------------------------------
    banner = _dusk(BANNER, icon)
    mac = icon.resize((176, 176), Image.LANCZOS)
    banner.paste(mac, ((BANNER[0] - 176) // 2, 58), mac)
    _wordmark(banner, "DREAMLAYER", 262, 30)
    _wordmark(banner, "Private by architecture.", 306, 14)
    banner.save(HERE / "wizard.bmp", format="BMP")

    # ---- the small header mark ---------------------------------------
    small = _dusk(SMALL, icon)
    ring = Image.open(ART / "icon_small.png").convert("RGBA")
    ring = ring.resize((108, 108), Image.LANCZOS)
    small.paste(ring, ((SMALL[0] - 108) // 2, (SMALL[1] - 108) // 2), ring)
    small.save(HERE / "wizard-small.bmp", format="BMP")

    print(f"wrote wizard.bmp {BANNER} and wizard-small.bmp {SMALL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
