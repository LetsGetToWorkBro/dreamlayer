"""rem/reel.py — the morning reel: last night's dreams, rendered.

One 256px circular frame per dream. The two source memories sit at the
rim at the hours they actually happened (Meridian geometry: the dream
keeps the day's body); their traces converge toward the center where
the woven phrase floats; the frame's tint blends the two hours' light
by the scene's weather_blend. A luma footer states the consolidation
verdict so the reel reads as a report, not a screensaver.

Pillow is optional (headless CI renders nothing, transcript still works).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from .cycle import DreamReel, DreamScene

SIZE = 256
CX = CY = SIZE // 2

# same dial law as the Horizon: hour → angle, now at -90°
def _hour_deg(hour: int) -> float:
    return -90.0 + (hour % 24) * 15.0


def _rim_xy(deg: float, r: float = 112.0) -> tuple[float, float]:
    rad = math.radians(deg)
    return CX + r * math.cos(rad), CY + r * math.sin(rad)


def render_scene(scene: DreamScene, path: str,
                 promoted: bool = True) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    from ..hud import themes as T

    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    # the dreaming rim: dimmer than waking Meridian
    a_deg, b_deg = _hour_deg(scene.a_hour), _hour_deg(scene.b_hour)
    blend = scene.weather_blend
    teal = T.to_rgb(T.ACCENT_MEMORY)
    coral = T.to_rgb(T.ACCENT_ATTENTION)
    tint = tuple(int(teal[i] * (1 - blend) + coral[i] * blend)
                 for i in range(3))

    draw.ellipse([8, 8, SIZE - 9, SIZE - 9],
                 outline=(*T.to_rgb(T.BORDER_SUBTLE), 120), width=1)

    # source marks at their true hours, traces converging inward
    for deg, summary in ((a_deg, scene.a_summary),
                         (b_deg, scene.b_summary)):
        x, y = _rim_xy(deg)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(*tint, 220))
        ix, iy = _rim_xy(deg, r=52.0)
        steps = 14
        for i in range(steps):
            t0, t1 = i / steps, (i + 1) / steps
            alpha = int(30 + 120 * t0)
            draw.line([(x + (ix - x) * t0, y + (iy - y) * t0),
                       (x + (ix - x) * t1, y + (iy - y) * t1)],
                      fill=(*tint, alpha), width=1)

    # the woven phrase, centered
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
        small = ImageFont.truetype("DejaVuSans.ttf", 9)
    except Exception:
        font = small = ImageFont.load_default()
    words = scene.phrase.split()
    mid = (len(words) + 1) // 2
    draw.text((CX, CY - 10), " ".join(words[:mid]),
              fill=(*T.to_rgb(T.TEXT_PRIMARY), 235), anchor="mm", font=font)
    if words[mid:]:
        draw.text((CX, CY + 10), " ".join(words[mid:]),
                  fill=(*T.to_rgb(T.TEXT_PRIMARY), 235), anchor="mm",
                  font=font)

    verdict = "kept" if promoted else "let go"
    draw.text((CX, SIZE - 34), f"{scene.a_hour:02d}h × "
              f"{scene.b_hour:02d}h · {verdict}",
              fill=(*T.to_rgb(T.TEXT_GHOST), 170), anchor="mm", font=small)

    img.save(path)
    return path


def render_reel(reel: DreamReel, outdir: Path | str) -> list[str]:
    """Export the whole night. Returns written paths (empty headless)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for i, scene in enumerate(reel.scenes):
        promoted = reel.deltas.get(scene.a_key, 0) > 0 or \
            reel.deltas.get(scene.b_key, 0) > 0
        path = render_scene(scene, str(outdir / f"dream_{i:02d}.png"),
                            promoted=promoted)
        if path:
            written.append(path)
    (outdir / "reel.txt").write_text(reel_transcript(reel) + "\n")
    return written


def reel_transcript(reel: DreamReel) -> str:
    return reel.report()
