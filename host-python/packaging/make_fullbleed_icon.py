#!/usr/bin/env python3
"""make_fullbleed_icon.py — turn the app icon full-bleed.

The source art (icon.png / icon_small.png) is a retro-Macintosh mark with the
teal Juno eye on a dusk starfield — charming, and worth keeping. But it paints
its OWN rounded rectangle: a bright grey bevel ring, a dark outer stroke, and
transparent rounded corners. macOS then masks its squircle over that, so on the
Dock/DMG/Finder the icon reads as a small bordered box floating among the
full-bleed icons next to it — and the transparent corners flash black on a dark
menu bar (the "grey border + black box" the screenshots show).

This keeps the exact pixel art but makes it full-bleed:

  1. rebuild the ground as an OPAQUE dusk→navy gradient sampled from the art
     itself (plus a faint starfield), edge to edge — no rounded corners, no
     bevel, no transparency;
  2. lift ONLY the interior (the mac + the teal Juno eye, well inside the bevel)
     and composite it, enlarged and centred, over that ground with a feathered
     edge so it melts into the identical gradient — seamless, and none of the
     grey ring / dark stroke / transparent corner comes along for the ride.

Because the bevel follows the rounded corner, a plain scale-and-crop leaves the
grey ring at the diagonals; lifting the interior and repainting the ground fixes
it everywhere. macOS then applies its own squircle to a clean, edge-to-edge
square, exactly as Apple's icon guidance wants. Regenerate when the art changes:

    python packaging/make_fullbleed_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
# fraction of the canvas the lifted interior fills (bigger = the mac fills more)
MAC_FRAC = 0.94
# inset (fraction) at which we lift the interior — safely past the bevel (~5%)
# and the dark stroke, but not so deep it clips the mac's base
INSET_FRAC = 0.115


def _interior_color(src: Image.Image, fy: float) -> tuple[int, int, int]:
    """Median dusk colour of the starfield at a KNOWN-interior row (a fraction of
    height), sampled from columns left+right of the centred mac and clear of the
    bevel. Rows are chosen inside the frame so the bright bevel / dark stroke that
    rings the art never contaminates the sample."""
    w, h = src.size
    px = src.load()
    y = int(fy * h)
    cols = list(range(int(w * 0.10), int(w * 0.22))) + \
           list(range(int(w * 0.78), int(w * 0.90)))
    got = [px[x, y] for x in cols if px[x, y][3] > 250]
    got.sort(key=lambda c: c[0] + c[1] + c[2])
    r, g, b, _ = got[len(got) // 2] if got else (60, 64, 104, 255)
    return (r, g, b)


def _bg(src: Image.Image, size: int) -> Image.Image:
    """A clean, edge-to-edge dusk→navy vertical gradient: a straight interpolation
    between two interior samples, so no bevel/stroke banding leaks in. Plus the
    faint starfield, so the ground reads as sky."""
    top = _interior_color(src, 0.20)
    bot = _interior_color(src, 0.86)
    bg = Image.new("RGBA", (size, size))
    bpx = bg.load()
    for y in range(size):
        t = y / (size - 1)
        row = (round(top[0] + (bot[0] - top[0]) * t),
               round(top[1] + (bot[1] - top[1]) * t),
               round(top[2] + (bot[2] - top[2]) * t), 255)
        for x in range(size):
            bpx[x, y] = row
    _starfield(bg)
    return bg


# a sparse, deterministic starfield (no RNG so the build is reproducible) — the
# same teal + pale motes the source art scatters, so the ground reads as sky, not
# a flat gradient. Positions are fractions of the canvas, kept clear of centre.
_STARS = [
    (0.12, 0.14, 0), (0.83, 0.10, 1), (0.19, 0.42, 0), (0.90, 0.36, 0),
    (0.07, 0.63, 1), (0.93, 0.62, 0), (0.15, 0.86, 0), (0.86, 0.83, 1),
    (0.34, 0.08, 0), (0.66, 0.12, 0), (0.05, 0.30, 0), (0.95, 0.50, 1),
    (0.10, 0.75, 0), (0.88, 0.72, 0), (0.28, 0.92, 1), (0.72, 0.90, 0),
]


def _starfield(bg: Image.Image) -> None:
    size = bg.size[0]
    bpx = bg.load()
    teal, pale = (52, 224, 196, 255), (222, 222, 221, 255)
    d = max(2, size // 190)                       # a 5px mote on 1024
    for fx, fy, kind in _STARS:
        x0, y0 = int(fx * size), int(fy * size)
        col = teal if kind else pale
        for x in range(x0, min(size, x0 + d)):
            for y in range(y0, min(size, y0 + d)):
                bpx[x, y] = col


def _feather_mask(size: int, feather: int) -> Image.Image:
    """An L mask: opaque in the middle, ramping to 0 over `feather` px at every
    edge, so a pasted tile melts into an identical background gradient."""
    m = Image.new("L", (size, size), 255)
    mpx = m.load()
    for i in range(feather):
        a = int(255 * i / feather)
        for j in range(size):
            for x, y in ((i, j), (size - 1 - i, j), (j, i), (j, size - 1 - i)):
                if mpx[x, y] > a:
                    mpx[x, y] = a
    return m


def full_bleed(src_path: Path, out_path: Path) -> None:
    src = Image.open(src_path).convert("RGBA")
    size = src.size[0]
    out = _bg(src, size)
    # lift the interior (mac + eye), strictly inside the bevel — no border pixels
    inset = int(size * INSET_FRAC)
    interior = src.crop((inset, inset, size - inset, size - inset))
    # flatten over a matching gradient tile so any stray transparency is filled
    tile = _bg(src, interior.size[0]).crop((0, 0, interior.size[0], interior.size[1]))
    interior = Image.alpha_composite(tile, interior)
    target = int(size * MAC_FRAC)
    interior = interior.resize((target, target), Image.NEAREST)
    mask = _feather_mask(target, feather=max(8, int(target * 0.05)))
    pos = ((size - target) // 2, (size - target) // 2)
    out.paste(interior, pos, mask)
    out.save(out_path)
    alpha = out.split()[3]
    assert alpha.getextrema()[0] == 255, f"{out_path} still has transparent pixels"
    print(f"wrote {out_path} ({size}x{size}, full-bleed, opaque)")


def main() -> None:
    full_bleed(HERE / "icon.png", HERE / "icon.png")
    full_bleed(HERE / "icon_small.png", HERE / "icon_small.png")
    # the web panel + native window use a byte copy of the big icon
    app_icon = HERE.parent / "src" / "dreamlayer" / "ai_brain" / "server" / "assets" / "app_icon.png"
    if app_icon.exists():
        import shutil
        shutil.copyfile(HERE / "icon.png", app_icon)
        print(f"copied icon.png -> {app_icon}")


if __name__ == "__main__":
    main()
