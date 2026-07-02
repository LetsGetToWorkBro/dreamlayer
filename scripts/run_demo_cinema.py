#!/usr/bin/env python3
"""run_demo_cinema.py — Halo Cinema v1 demo reel.

Stitches four back-to-back scenes into a 45-second sequence exported as a
PNG frame sequence to out/cinema_reel/ (20 fps → 900 frames, 256×256):

  1. Dream Mode boot → palette weather forms → line field emerges   (10s)
  2. Person walks up → Social Lens ring → PersonContextCard v2      (10s)
  3. Same person tells a story → Truth Lens 9-ring gauge → verdict  (15s)
  4. Privacy Veil → shield slam → blackout w/ breathing hex glyph  (10s)

Timing constants mirror halo-lua/display/animations.lua (SIG_*). The
still-frame card layouts come from dreamlayer.hud.renderer so the reel and
the goldens can never diverge.

Usage:
    python scripts/run_demo_cinema.py            # full 900 frames
    python scripts/run_demo_cinema.py --stride 10  # quick preview (90)
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host-python", "src"))

from PIL import Image, ImageDraw  # noqa: E402

from dreamlayer.hud import themes as T                       # noqa: E402
from dreamlayer.hud.cards import ALL_SAMPLES                  # noqa: E402
from dreamlayer.hud.renderer import SIZE, CX, CY, CardRenderer, _mask  # noqa: E402

FPS = 20
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "cinema_reel")

# Mirrors animations.lua — one source of truth per platform, asserted equal
# by the SIG_* tables in phone-app/src/ui/theme/motion.ts
SIG_IRIS_MS, SIG_IRIS_R_FROM, SIG_IRIS_R_TO = 180, 112, 36
SIG_RIPPLE_MS, SIG_RIPPLE_R_MAX = 400, 120
SIG_RUMBLE_MS = 100
BREATHE_MS = 3200

SCENES = (("dream", 10), ("social", 10), ("truth", 15), ("privacy", 10))


def _rgb(hexval: int) -> tuple[int, int, int]:
    return T.to_rgb(hexval)


def out_expo(t: float) -> float:
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def vnoise(x: float) -> float:
    def h(n: int) -> float:
        n = (int(math.floor(n)) % 289 + 289) % 289
        return ((n * 34 + 1) * n % 289) / 144.5 - 1.0
    x0 = math.floor(x)
    f = x - x0
    u = f * f * (3 - 2 * f)
    return h(x0) + (h(x0 + 1) - h(x0)) * u


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    return img, ImageDraw.Draw(img, "RGBA")


def arc(d, cx, cy, r, a0, a1, color, alpha=255, w=1):
    rr, g, b = _rgb(color)
    d.arc([cx - r, cy - r, cx + r, cy + r], start=a0, end=a1,
          fill=(rr, g, b, alpha), width=w)


def iris_overlay(d, t, color):
    """S1 Iris Bloom ring collapsing from the safe edge to the core."""
    if t >= 1:
        return
    r = SIG_IRIS_R_FROM + (SIG_IRIS_R_TO - SIG_IRIS_R_FROM) * out_expo(t)
    arc(d, CX, CY, r, 0, 360, T.ACCENT_MEMORY, alpha=int(255 * (1 - t * 0.4)))


def blend_card(base: Image.Image, card_key: str, reveal: float) -> Image.Image:
    """Composite a settled card frame over the base with a reveal fade."""
    card_img = _RENDERER.render(ALL_SAMPLES[card_key]).convert("RGB")
    return Image.blend(base, card_img, max(0.0, min(1.0, reveal)))


_RENDERER = CardRenderer()
_MASK = _mask()


# ---------------------------------------------------------------------------
# Scene 1 — Dream Mode boot (palette weather + Line Field 2.0)
# ---------------------------------------------------------------------------

def scene_dream(t: float, dur: float) -> Image.Image:
    img, d = canvas()
    sec = t
    boot = min(1.0, sec / 2.0)                      # weather forms over 2s
    pressure = 0.5 + 0.5 * vnoise(sec * 0.11)
    energy = max(0.0, vnoise(sec * 0.31 + 40))
    amp = boot * (0.3 + 0.4 * pressure + 0.3 * energy)

    sky = (int(30 - 15 * pressure), int(160 - 40 * pressure), int(150 + 70 * pressure))
    ember = (int(120 + 120 * energy), int(110 - 20 * energy), 82)

    # sky wash rings
    for i, r in enumerate((110, 92, 74)):
        d.arc([CX - r, CY - r, CX + r, CY + r], 0, 360,
              fill=sky + (int(boot * (26 + i * 10)),), width=10)

    # Line Field 2.0 emerges after 4s
    field_t = max(0.0, min(1.0, (sec - 4.0) / 2.0))
    phase = sec * 0.05
    for i in range(12):
        a = phase + i * math.pi / 6
        ax, ay = CX + 78 * math.cos(a), CY + 78 * math.sin(a)
        n = vnoise(i * 3.7 + phase * 2.1)
        dn = vnoise(i * 3.7 + phase * 2.1 + 0.5) - n
        ca = a + math.pi / 2 + dn * 1.8
        ln = (14 + (n * 0.5 + 0.5) * 20) * field_t
        col = ember if i % 3 == 0 else sky
        d.line([ax - ln * math.cos(ca), ay - ln * math.sin(ca),
                ax + ln * math.cos(ca), ay + ln * math.sin(ca)],
               fill=col + (int(90 + amp * 140),))

    # breathing energy core
    breathe = (math.sin(sec * 2 * math.pi * 1000 / BREATHE_MS) + 1) / 2
    r = 14 + 10 * amp + 3 * breathe
    d.ellipse([CX - r, CY - r, CX + r, CY + r], outline=ember + (150,))
    d.ellipse([CX - 3, CY - 3, CX + 3, CY + 3], fill=ember + (255,))
    return img


# ---------------------------------------------------------------------------
# Scene 2 — Social Lens (chord ring → PersonContextCard v2)
# ---------------------------------------------------------------------------

def scene_social(t: float, dur: float) -> Image.Image:
    img, d = canvas()
    if t < 3.0:
        # approach: recognition ring arpeggio around a face zone
        for i, r in enumerate((32, 40, 48)):
            if t > 0.5 + i * 0.04 * 3:
                sweep = min(1.0, (t - 0.5) / 1.5) * 359
                arc(d, CX, 108, r, -90, -90 + sweep, T.ACCENT_MEMORY,
                    alpha=220 - i * 50)
        d.ellipse([CX - 14, 94, CX + 14, 122], outline=_rgb(T.BORDER_SUBTLE) + (200,))
        return img
    # card irises in over the ring
    enter = min(1.0, (t - 3.0) / (SIG_IRIS_MS / 1000 * 3))   # slowed 3x for reel
    img = blend_card(img, "person_context_v2", enter)
    d = ImageDraw.Draw(img, "RGBA")
    iris_overlay(d, enter, T.ACCENT_MEMORY)
    return img


# ---------------------------------------------------------------------------
# Scene 3 — Truth Lens (gauge fills stage by stage → verdict)
# ---------------------------------------------------------------------------

def scene_truth(t: float, dur: float) -> Image.Image:
    img, d = canvas()
    card = ALL_SAMPLES["truth_gauge"]
    stages = card["stages"]
    fill_t = min(1.0, t / 9.0)          # one ring per second
    dir_color = {"truthful": T.ACCENT_SUCCESS, "deceptive": T.ACCENT_ATTENTION,
                 "insufficient": T.TEXT_GHOST}

    # truth ripple at the eye landmark during the first 0.4s·3 (slowed)
    rip = t / (SIG_RIPPLE_MS / 1000 * 3)
    if rip < 1:
        r = out_expo(rip) * SIG_RIPPLE_R_MAX
        arc(d, 128, 96, max(2, r), 0, 360, T.ACCENT_ATTENTION,
            alpha=int(200 * (1 - rip)))
        if r > 12:
            arc(d, 128, 96, r - 12, 0, 360, T.ACCENT_ATTENTION,
                alpha=int(120 * (1 - rip)))

    for i in range(9):
        ring_gate = max(0.0, min(1.0, fill_t * 9 - i))
        r = 34 + i * 4
        arc(d, CX, CY, r, 0, 360, T.BORDER_SUBTLE, alpha=44)
        sweep = stages[i]["confidence"] * 360 * ring_gate
        if sweep > 4:
            arc(d, CX, CY, r, -90, -90 + sweep,
                dir_color[stages[i]["direction"]], alpha=235, w=2)

    if t > 9.5:   # verdict lands
        verdict_a = min(1.0, (t - 9.5) / 0.6)
        d.rectangle([CX - 52, CY - 15, CX + 52, CY + 4], fill=(0, 0, 0, 255))
        rr, g, b = _rgb(T.TEXT_PRIMARY)
        d.text((CX, CY - 6), card["verdict"], fill=(rr, g, b, int(255 * verdict_a)),
               anchor="mm")
        jr, jg, jb = _rgb(T.conf_color(card["confidence"]))
        d.ellipse([CX - 3, CY + 13, CX + 3, CY + 19],
                  fill=(jr, jg, jb, int(255 * verdict_a)))
    rr, g, b = _rgb(T.TEXT_GHOST)
    d.text((CX, 46), "TRUTH LENS", fill=(rr, g, b, 140), anchor="mm")
    d.text((CX, 208), "Jordan", fill=(rr, g, b, 150), anchor="mm")
    return img


# ---------------------------------------------------------------------------
# Scene 4 — Privacy Veil (rumble → shield slam → breathing blackout)
# ---------------------------------------------------------------------------

def scene_privacy(t: float, dur: float) -> Image.Image:
    img, d = canvas()
    slam_t = min(1.0, t / 0.8)
    if t < SIG_RUMBLE_MS / 1000 * 3:
        # sub-bass rumble: residual dream field dims out
        dim = 1 - t / (SIG_RUMBLE_MS / 1000 * 3)
        for r in (110, 92):
            arc(d, CX, CY, r, 0, 360, T.ACCENT_MEMORY_DIM, alpha=int(30 * dim), w=8)
    # rings slam outward
    ring = out_expo(slam_t)
    arc(d, CX, CY, 108 * ring, 10, 350, T.PRIVACY_DANGER, alpha=34)
    arc(d, CX, CY, 88 * ring, 0, 360, T.PRIVACY_DANGER, alpha=18)
    # shield glyph after rings land
    if slam_t >= 0.6:
        g_t = out_expo(min(1.0, (slam_t - 0.6) / 0.4))
        size = 52 * g_t
        pts = []
        for i in range(6):
            a = math.radians(60 * i - 30)
            pts.append((CX + size / 2 * math.cos(a), CY - 14 + size / 2 * math.sin(a)))
        pts.append(pts[0])
        rr, g, b = _rgb(T.PRIVACY_DANGER)
        d.line(pts, fill=(rr, g, b, 255), width=2)
        bh = int(size * 0.24)
        if bh > 2:
            d.rectangle([CX - 7, CY - 14 - bh, CX - 3, CY - 14 + bh], fill=(rr, g, b, 255))
            d.rectangle([CX + 3, CY - 14 - bh, CX + 7, CY - 14 + bh], fill=(rr, g, b, 255))
    if t > 1.2:
        rr, g, b = _rgb(T.PRIVACY_CAUTION)
        d.text((CX, CY + 32), "PRIVACY VEIL", fill=(rr, g, b, 220), anchor="mm")
        rr, g, b = _rgb(T.TEXT_GHOST)
        d.text((CX, CY + 48), "Nothing is captured", fill=(rr, g, b, 140), anchor="mm")
    # total blackout with breathing status_paused hex glyph
    if t > 4.0:
        fade = min(1.0, (t - 4.0) / 1.5)
        d.rectangle([0, 0, SIZE, SIZE], fill=(0, 0, 0, int(255 * fade)))
        breathe = (math.sin((t - 4.0) * 2 * math.pi * 1000 / BREATHE_MS) + 1) / 2
        rr, g, b = _rgb(T.STATUS_PAUSED)
        alpha = int(fade * (90 + 120 * breathe))
        pts = []
        for i in range(6):
            a = math.radians(60 * i - 30)
            pts.append((CX + 11 * math.cos(a), CY + 11 * math.sin(a)))
        pts.append(pts[0])
        d.line(pts, fill=(rr, g, b, alpha), width=1)
    return img


SCENE_FN = {"dream": scene_dream, "social": scene_social,
            "truth": scene_truth, "privacy": scene_privacy}


def main() -> None:
    parser = argparse.ArgumentParser(description="Halo Cinema v1 demo reel")
    parser.add_argument("--stride", type=int, default=1,
                        help="render every Nth frame (preview mode)")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    frame_idx = 0
    written = 0
    for name, secs in SCENES:
        fn = SCENE_FN[name]
        for f in range(secs * FPS):
            if frame_idx % args.stride == 0:
                img = fn(f / FPS, secs).convert("RGBA")
                img.putalpha(_MASK)
                img.save(os.path.join(args.out, f"frame_{frame_idx:04d}.png"))
                written += 1
            frame_idx += 1
    total_s = frame_idx / FPS
    print(f"cinema reel: {written} frames written to {args.out} "
          f"({frame_idx} total @ {FPS}fps = {total_s:.0f}s)")


if __name__ == "__main__":
    main()
