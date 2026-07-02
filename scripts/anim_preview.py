"""
scripts/anim_preview.py
Animation lifecycle previewer — renders each card’s ENTER → HOLD → EXIT
cycle as a GIF using the constants from animations.lua.

Produces:
  out/anim_<CardType>.gif   per card
  out/anim_all.gif           all cards end-to-end in priority order

Usage:
  uv run python scripts/anim_preview.py
  uv run python scripts/anim_preview.py --card ObjectRecallCard
  uv run python scripts/anim_preview.py --fps 30 --scale 2

Dependencies (already in venv via test_lab.py):
  Pillow

Display is 640x400 monochrome, simulated at 1x or 2x.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Animation constants (mirrors animations.lua exactly)
# ---------------------------------------------------------------------------

ENTER_DURATION_MS  = 180
ENTER_SCALE_FROM   = 0.94
ENTER_SCALE_TO     = 1.0
ENTER_OPACITY_FROM = 0.0
ENTER_OPACITY_TO   = 1.0

STAGGER_PRIMARY_MS  =  0
STAGGER_EYEBROW_MS  = 40
STAGGER_DETAIL_MS   = 60
STAGGER_FOOTER_MS   = 80

EXIT_DURATION_MS = 120

BREATHE_CYCLE_MS   = 3200
BREATHE_R_MIN      =  5
BREATHE_R_MAX      = 10

DRAWON_START_MS    = 100
DRAWON_DURATION_MS = 300

SPINNER_RPM_MS     = 900

DISMISS_MS: dict[str, int] = {
    "ReadyCard":            0,
    "SavedMemoryCard":   1200,
    "QueryListeningCard":   0,
    "LoadingCard":          0,
    "ObjectRecallCard":  3500,
    "CommitmentRecallCard": 4000,
    "ProactiveMemoryCard":  3500,
    "PersonContextCard":    3500,
    "PrivacyVeilCard":    0,
    "ErrorCard":         4000,
    "LowConfidenceCard": 3000,
}

# Priority order for all-cards GIF
CARD_ORDER = [
    "ObjectRecallCard",
    "CommitmentRecallCard",
    "ProactiveMemoryCard",
    "PersonContextCard",
    "SavedMemoryCard",
    "LowConfidenceCard",
    "ErrorCard",
    "ReadyCard",
    "QueryListeningCard",
    "LoadingCard",
    "PrivacyVeilCard",
]

# ---------------------------------------------------------------------------
# Easing functions
# ---------------------------------------------------------------------------

def ease_out_expo(t: float) -> float:
    return 1.0 if t >= 1.0 else 1.0 - math.pow(2, -10 * t)

def ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2

def ease_linear(t: float) -> float:
    return t

EASE = {
    "ease_out_expo":    ease_out_expo,
    "ease_in_out_sine": ease_in_out_sine,
    "linear":           ease_linear,
}


# ---------------------------------------------------------------------------
# Frame canvas
# ---------------------------------------------------------------------------

W, H = 640, 400  # Frame display resolution

def _font(size: int = 16):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        return ImageFont.load_default()


@dataclass
class CardSpec:
    card_type:  str
    label:      str          # eyebrow label
    primary:    str          # main text
    detail:     str  = ""
    footer:     str  = ""
    confidence: float = 1.0
    icon:       str  = "◆"   # unicode glyph used as card icon


CARD_SPECS: dict[str, CardSpec] = {
    "ObjectRecallCard":     CardSpec("ObjectRecallCard",     "OBJECT",    "KEYS",             "KITCHEN COUNTER",  "2h ago",    0.91, "◆"),
    "CommitmentRecallCard": CardSpec("CommitmentRecallCard", "PROMISE",   "Send report",      "You told Araceli", "Tomorrow",  0.88, "■"),
    "ProactiveMemoryCard":  CardSpec("ProactiveMemoryCard",  "LAST TIME", "Coffee w/ Marcus", "3 weeks ago",      "w/ Marcus", 0.80, "★"),
    "PersonContextCard":    CardSpec("PersonContextCard",    "PERSON",    "Marcus",           "PM @ Apple",       "London",    0.85, "●"),
    "SavedMemoryCard":      CardSpec("SavedMemoryCard",      "SAVED",     "Memory saved",     "",                 "",          1.00, "✓"),
    "LowConfidenceCard":    CardSpec("LowConfidenceCard",    "UNSURE",    "Not sure",         "",                 "",          0.20, "?"),
    "ErrorCard":            CardSpec("ErrorCard",            "ERROR",     "Try again",        "",                 "",          0.00, "⚠"),
    "ReadyCard":            CardSpec("ReadyCard",            "READY",     "DreamLayer",        "",                 "",          1.00, "○"),
    "QueryListeningCard":   CardSpec("QueryListeningCard",   "LISTENING", "∿∿∿∿∿",              "",                 "",          1.00, "◔"),
    "LoadingCard":          CardSpec("LoadingCard",          "LOADING",   "Thinking…",        "",                 "",          1.00, "↺"),
    "PrivacyVeilCard":    CardSpec("PrivacyVeilCard",    "PRIVACY",   "Privacy Veil",    "",                 "",          1.00, "▣"),
}


# ---------------------------------------------------------------------------
# Per-phase rendering helpers
# ---------------------------------------------------------------------------

def _brightness(opacity: float) -> int:
    return max(0, min(255, int(opacity * 255)))


def _render_frame(
    spec: CardSpec,
    phase: str,     # "enter" | "hold" | "exit"
    t: float,       # 0..1 progress within phase
    scale: int = 1,
    now_ms: float = 0.0,
) -> Image.Image:
    w, h = W * scale, H * scale
    img  = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ----- opacity -----
    if phase == "enter":
        opacity = ease_out_expo(t)
    elif phase == "exit":
        opacity = ease_linear(1.0 - t)
    else:
        opacity = 1.0

    # ----- scale transform (simulated via padding) -----
    if phase == "enter":
        sc = ENTER_SCALE_FROM + (ENTER_SCALE_TO - ENTER_SCALE_FROM) * ease_out_expo(t)
    else:
        sc = 1.0

    bright = _brightness(opacity)
    dim    = _brightness(opacity * 0.45)
    ghost  = _brightness(opacity * 0.18)
    col    = (bright, bright, bright)
    col_d  = (dim, dim, dim)
    col_g  = (ghost, ghost, ghost)

    cx, cy = w // 2, h // 2
    r_base = int(56 * scale * sc)

    # ----- card-type geometry -----
    ct = spec.card_type

    if ct == "LoadingCard":
        # Spinning arc
        arc_len = 80 + 180 * abs(math.sin(now_ms / 1800 * math.pi))
        angle   = (now_ms / SPINNER_RPM_MS) * 360 % 360
        bbox = [cx - r_base, cy - r_base, cx + r_base, cy + r_base]
        draw.arc(bbox, angle, angle + arc_len, fill=col, width=2 * scale)
        # Three echo arcs
        for i, alpha in enumerate([0.35, 0.18, 0.08]):
            ec = _brightness(opacity * alpha)
            draw.arc(bbox, angle - (i+1)*22, angle - (i+1)*22 + arc_len,
                     fill=(ec,ec,ec), width=max(1, scale))

    elif ct == "QueryListeningCard":
        # Sine waveform bars
        centers = [int(cx + (j - 3) * 14 * scale) for j in range(7)]
        for j, bx in enumerate(centers):
            phase_offset = j * 0.4 + now_ms / 300
            h_bar = int((8 + 14 * abs(math.sin(phase_offset))) * scale * sc)
            draw.rectangle([bx - scale, cy - h_bar, bx + scale, cy + h_bar], fill=col)

    elif ct == "ReadyCard":
        # Hexagon core + partial rings
        pts = []
        for i in range(6):
            a = math.radians(60 * i - 30)
            pts.append((cx + int(r_base * 0.5 * math.cos(a)),
                        cy + int(r_base * 0.5 * math.sin(a))))
        draw.polygon(pts, outline=col)
        for ri, alpha in [(0.75, 0.45), (1.0, 0.18)]:
            ec = _brightness(opacity * alpha)
            draw.arc([cx - int(r_base*ri), cy - int(r_base*ri),
                      cx + int(r_base*ri), cy + int(r_base*ri)],
                     -40, 200, fill=(ec,ec,ec), width=scale)

    elif ct == "PrivacyVeilCard":
        # Shield outline + breach halo + pause bars
        shield_pts = [
            (cx, cy - r_base),
            (cx + int(r_base*0.75), cy - int(r_base*0.4)),
            (cx + int(r_base*0.75), cy + int(r_base*0.3)),
            (cx, cy + r_base),
            (cx - int(r_base*0.75), cy + int(r_base*0.3)),
            (cx - int(r_base*0.75), cy - int(r_base*0.4)),
        ]
        draw.polygon(shield_pts, outline=col)
        draw.arc([cx - int(r_base*1.2), cy - int(r_base*1.2),
                  cx + int(r_base*1.2), cy + int(r_base*1.2)],
                 10, 350, fill=col_d, width=scale)
        # Pause bars
        bw = int(6 * scale)
        draw.rectangle([cx - bw*2, cy - int(12*scale), cx - bw, cy + int(12*scale)], fill=col)
        draw.rectangle([cx + bw, cy - int(12*scale), cx + bw*2, cy + int(12*scale)], fill=col)

    elif ct in ("ErrorCard", "LowConfidenceCard"):
        # Triangle + exclamation / question mark
        h_tri = int(r_base * 0.95)
        tri = [
            (cx, cy - h_tri),
            (cx - int(h_tri * 1.0), cy + int(h_tri * 0.6)),
            (cx + int(h_tri * 1.0), cy + int(h_tri * 0.6)),
        ]
        draw.polygon(tri, outline=col)
        mark = "!" if ct == "ErrorCard" else "?"
        fnt = _font(int(28 * scale))
        draw.text((cx, cy - 4*scale), mark, fill=col, font=fnt, anchor="mm")

    elif ct == "SavedMemoryCard":
        # Checkmark
        draw.line([(cx - int(r_base*0.5), cy),
                   (cx - int(r_base*0.1), cy + int(r_base*0.4)),
                   (cx + int(r_base*0.5), cy - int(r_base*0.4))],
                  fill=col, width=2*scale)
        draw.arc([cx - r_base, cy - r_base, cx + r_base, cy + r_base],
                 -30, 200, fill=col_d, width=scale)

    else:
        # Generic: draw-on circle + jewel
        draw_t = 1.0
        if phase == "enter":
            draw_t = max(0.0, (t * ENTER_DURATION_MS - DRAWON_START_MS) / DRAWON_DURATION_MS)
        arc_end = int(-90 + 360 * min(draw_t, 1.0))
        draw.arc([cx - r_base, cy - r_base, cx + r_base, cy + r_base],
                 -90, arc_end, fill=col, width=2 * scale)
        # Jewel at arc tip
        tip_a = math.radians(arc_end)
        jx = cx + int(r_base * math.cos(tip_a))
        jy = cy + int(r_base * math.sin(tip_a))
        jr = int(5 * scale)
        draw.ellipse([jx-jr, jy-jr, jx+jr, jy+jr], fill=col)
        draw.ellipse([jx-jr*2, jy-jr*2, jx+jr*2, jy+jr*2], outline=col_d)

    # ----- staggered text -----
    text_start_ms = STAGGER_PRIMARY_MS
    eyebrow_t = max(0.0, min(1.0, (now_ms - STAGGER_EYEBROW_MS) / ENTER_DURATION_MS)) if phase == "enter" else opacity
    detail_t  = max(0.0, min(1.0, (now_ms - STAGGER_DETAIL_MS)  / ENTER_DURATION_MS)) if phase == "enter" else opacity
    footer_t  = max(0.0, min(1.0, (now_ms - STAGGER_FOOTER_MS)  / ENTER_DURATION_MS)) if phase == "enter" else opacity

    ec_e = _brightness(ease_out_expo(eyebrow_t) * opacity)
    ec_d = _brightness(ease_out_expo(detail_t)  * opacity)
    ec_f = _brightness(ease_out_expo(footer_t)  * opacity)

    fnt_eyebrow = _font(int(11 * scale))
    fnt_primary = _font(int(22 * scale))
    fnt_detail  = _font(int(13 * scale))
    fnt_footer  = _font(int(11 * scale))

    margin = int(24 * scale)
    text_x = cx + int(r_base * 1.05)

    if spec.label:
        draw.text((text_x, cy - int(36 * scale)), spec.label,
                  fill=(ec_e, ec_e, ec_e), font=fnt_eyebrow, anchor="lm")
    if spec.primary:
        draw.text((text_x, cy - int(10 * scale)), spec.primary,
                  fill=(bright, bright, bright), font=fnt_primary, anchor="lm")
    if spec.detail:
        draw.text((text_x, cy + int(18 * scale)), spec.detail,
                  fill=(ec_d, ec_d, ec_d), font=fnt_detail, anchor="lm")
    if spec.footer:
        draw.text((text_x, cy + int(38 * scale)), spec.footer,
                  fill=(ec_f, ec_f, ec_f), font=fnt_footer, anchor="lm")

    # Phase label (debug)
    phase_col = {"enter": (60,60,60), "hold": (40,40,40), "exit": (60,30,30)}
    draw.text((margin, h - margin), f"{spec.card_type}  [{phase} {t:.2f}]",
              fill=phase_col.get(phase, (40,40,40)), font=_font(int(9*scale)))

    return img


# ---------------------------------------------------------------------------
# Build per-card GIF
# ---------------------------------------------------------------------------

FPS_DEFAULT    = 24
HOLD_FRAMES    = 18    # frames shown at full opacity before exit


def build_card_gif(
    spec:        CardSpec,
    fps:         int = FPS_DEFAULT,
    scale:       int = 1,
    hold_frames: int = HOLD_FRAMES,
) -> list[Image.Image]:
    frames: list[Image.Image] = []
    ms_per_frame = 1000 / fps

    # --- ENTER ---
    n_enter = max(1, round(ENTER_DURATION_MS / ms_per_frame))
    for i in range(n_enter):
        t      = (i + 1) / n_enter
        now_ms = t * ENTER_DURATION_MS
        frames.append(_render_frame(spec, "enter", t, scale, now_ms))

    # --- HOLD ---
    # For sticky cards (dismiss_ms==0) use hold_frames constant.
    # For timed cards cap hold to 2s of the real dismiss window so GIFs aren't huge.
    dm   = DISMISS_MS.get(spec.card_type, 0)
    hold = hold_frames if dm == 0 else max(hold_frames, min(round(dm * 0.4 / ms_per_frame), 60))
    for i in range(hold):
        now_ms = ENTER_DURATION_MS + i * ms_per_frame
        frames.append(_render_frame(spec, "hold", i / max(hold - 1, 1), scale, now_ms))

    # --- EXIT ---
    n_exit = max(1, round(EXIT_DURATION_MS / ms_per_frame))
    for i in range(n_exit):
        t      = (i + 1) / n_exit
        now_ms = ENTER_DURATION_MS + hold * ms_per_frame + t * EXIT_DURATION_MS
        frames.append(_render_frame(spec, "exit", t, scale, now_ms))

    # One black tail frame (gap between cards in all-cards GIF)
    frames.append(Image.new("RGB", (W * scale, H * scale), (0, 0, 0)))

    return frames


def save_gif(frames: list[Image.Image], path: Path, fps: int) -> None:
    duration_ms = int(1000 / fps)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=duration_ms,
        optimize=False,
    )
    print(f"  ✔  {path}  ({len(frames)} frames @ {fps}fps)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="DreamLayer animation lifecycle previewer")
    parser.add_argument("--card",  default=None, help="Single card type to render")
    parser.add_argument("--fps",   type=int, default=FPS_DEFAULT)
    parser.add_argument("--scale", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    out = Path("out")
    out.mkdir(exist_ok=True)

    cards_to_render = ([args.card] if args.card else CARD_ORDER)
    all_frames: list[Image.Image] = []

    print(f"Rendering {len(cards_to_render)} card(s) at {args.fps}fps scale={args.scale}x ...")
    for ct in cards_to_render:
        spec = CARD_SPECS.get(ct)
        if spec is None:
            print(f"  ! Unknown card type: {ct}")
            continue
        frames = build_card_gif(spec, fps=args.fps, scale=args.scale)
        save_gif(frames, out / f"anim_{ct}.gif", args.fps)
        all_frames.extend(frames)

    if len(cards_to_render) > 1 and all_frames:
        save_gif(all_frames, out / "anim_all.gif", args.fps)


if __name__ == "__main__":
    main()
