"""renderer.py — Pillow-based 256x256 HUD renderer (transformative pass)."""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from . import themes as T

SIZE = 256
CX = SIZE // 2   # 128
CY = SIZE // 2   # 128

FONT_PX = {
    "hero": 22,
    "xl":   19,
    "lg":   17,
    "md":   13,
    "sm":   10,
    "xs":    8,
    "mono":  8,
}


def _hex_to_rgb(h: int) -> tuple[int, int, int]:
    return T.to_rgb(h)


def _font(size_token: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = FONT_PX.get(size_token, 13)
    candidates = [
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, px)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _mask() -> Image.Image:
    m = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(m).ellipse([0, 0, SIZE - 1, SIZE - 1], fill=255)
    return m


# ---------------------------------------------------------------------------
# Primitive drawing functions (added for transformative pass)
# ---------------------------------------------------------------------------

def draw_quadratic_bezier(
    draw: ImageDraw.ImageDraw,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    stroke: int,
    color: int,
    alpha: int = 255,
    dash_offset: float = 0.0,
    steps: int = 64,
) -> None:
    """Draw a quadratic Bezier curve with optional gradient alpha (simulated)."""
    r, g, b = _hex_to_rgb(color)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    # Gradient: alpha fades in from 0x33 at start to full at end
    seg_count = len(pts) - 1
    for i in range(seg_count):
        frac = i / seg_count
        # dash pattern: skip every other ~8px segment (frozen offset)
        seg_idx = int(frac * seg_count + dash_offset) % 12
        if seg_idx < 6:  # dash on
            seg_alpha = int(0x33 + (alpha - 0x33) * frac)
            draw.line([pts[i], pts[i + 1]], fill=(r, g, b, seg_alpha), width=stroke)


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    stroke: int,
    color: int,
    alpha: int = 255,
    progressive: float = 1.0,
) -> None:
    """Draw a polyline; progressive 0.0-1.0 controls draw fraction."""
    r, g, b = _hex_to_rgb(color)
    total = len(points) - 1
    end_idx = max(1, int(math.ceil(total * progressive)))
    for i in range(min(end_idx, total)):
        draw.line([points[i], points[i + 1]], fill=(r, g, b, alpha), width=stroke)


def draw_elliptical_arc(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    rx: float, ry: float,
    start_deg: float, sweep_deg: float,
    stroke: int,
    color: int,
    alpha: int = 255,
    rotation: float = 0.0,
    steps: int = 64,
) -> None:
    """Draw an elliptical arc as polyline segments."""
    r, g, b = _hex_to_rgb(color)
    pts = []
    for i in range(steps + 1):
        angle_deg = start_deg + sweep_deg * i / steps
        angle_rad = math.radians(angle_deg + rotation)
        x = cx + rx * math.cos(angle_rad)
        y = cy + ry * math.sin(angle_rad)
        pts.append((x, y))
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=(r, g, b, alpha), width=stroke)


def draw_check_glyph(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    size: float,
    stroke: int,
    color: int,
    alpha: int = 255,
    progressive: float = 1.0,
) -> None:
    """Draw checkmark via 3-point polyline; progressive=0.6 = mid-completion."""
    cx, cy = center
    scale = size / 60.0
    raw_pts = [
        (cx - 21 * scale, cy),
        (cx - 3 * scale,  cy + 18 * scale),
        (cx + 21 * scale, cy - 22 * scale),
    ]
    draw_polyline(draw, raw_pts, stroke, color, alpha, progressive)


def draw_shield_glyph(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    size: float,
    stroke: int,
    color: int,
    alpha: int = 255,
    pause_bars: bool = True,
) -> None:
    """Draw a rounded hexagon shield + optional pause bars inside."""
    cx, cy = center
    r_, g_, b_ = _hex_to_rgb(color)
    hw = size / 2
    # Hexagon (pointy-top) via 6 vertices
    pts = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        pts.append((cx + hw * math.cos(angle), cy + hw * math.sin(angle)))
    pts.append(pts[0])  # close
    draw.line(pts, fill=(r_, g_, b_, alpha), width=stroke)
    if pause_bars:
        bar_h = int(size * 0.24)
        bar_w = max(3, int(size * 0.08))
        gap = max(2, int(size * 0.07))
        # Left bar
        draw.rectangle(
            [cx - gap - bar_w, cy - bar_h, cx - gap, cy + bar_h],
            fill=(r_, g_, b_, alpha)
        )
        # Right bar
        draw.rectangle(
            [cx + gap, cy - bar_h, cx + gap + bar_w, cy + bar_h],
            fill=(r_, g_, b_, alpha)
        )


def draw_polar_segments(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    r_inner: float, r_outer: float,
    count: int,
    lit_indices: list[int],
    color: int,
    alpha_lit: int = 255,
    alpha_dim: int = 35,
) -> None:
    """Draw count radial segments (like a clock); lit_indices are bright."""
    r_, g_, b_ = _hex_to_rgb(color)
    step = 360.0 / count
    for i in range(count):
        angle = math.radians(i * step - 90)
        xi = cx + r_inner * math.cos(angle)
        yi = cy + r_inner * math.sin(angle)
        xo = cx + r_outer * math.cos(angle)
        yo = cy + r_outer * math.sin(angle)
        a = alpha_lit if i in lit_indices else alpha_dim
        w = 2 if i in lit_indices else 1
        draw.line([(xi, yi), (xo, yo)], fill=(r_, g_, b_, a), width=w)


def draw_radial_rays(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    count: int,
    lengths: list[float],
    color: int,
    alpha: int = 255,
    tip_bloom: bool = True,
    stroke: int = 1,
) -> None:
    """Draw count lines radiating from center; lengths controls each ray."""
    r_, g_, b_ = _hex_to_rgb(color)
    step = 360.0 / count
    for i in range(count):
        angle = math.radians(i * step - 90)
        length = lengths[i % len(lengths)]
        x1, y1 = cx, cy
        x2 = cx + length * math.cos(angle)
        y2 = cy + length * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=(r_, g_, b_, alpha), width=stroke)
        if tip_bloom and length > 0:
            bloom_r = max(2, int(length * 0.06))
            draw.ellipse(
                [x2 - bloom_r, y2 - bloom_r, x2 + bloom_r, y2 + bloom_r],
                fill=(r_, g_, b_, max(40, alpha // 3))
            )


def draw_point_cloud_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: float, cy: float,
    font_size: int,
    density: float,
    color: int,
    alpha: int = 255,
) -> None:
    """Render text as a particle cloud; density 0-1 controls scatter."""
    import random
    r_, g_, b_ = _hex_to_rgb(color)
    # Draw the text onto a temp image, sample non-black pixels, scatter them
    tmp = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    try:
        font_path_candidates = [
            "DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
        ]
        font = None
        for fp in font_path_candidates:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except (OSError, IOError):
                continue
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    tmp_draw.text((cx, cy), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    pixels = tmp.load()
    rng = random.Random(42)
    scatter = int((1.0 - density) * 12)
    for px in range(SIZE):
        for py in range(SIZE):
            if pixels[px, py][3] > 128:
                dx = rng.randint(-scatter, scatter) if scatter > 0 else 0
                dy = rng.randint(-scatter, scatter) if scatter > 0 else 0
                nx, ny = px + dx, py + dy
                if 0 <= nx < SIZE and 0 <= ny < SIZE:
                    dot_alpha = int(alpha * (0.3 + 0.7 * density))
                    draw.point((nx, ny), fill=(r_, g_, b_, dot_alpha))


def draw_contact_sheet(
    cards_images: list[tuple[str, Image.Image]],
    out_path: str,
    grid_cols: int = 4,
    grid_rows: int = 3,
    cell_padding: int = 4,
    label_height: int = 14,
) -> None:
    """Generate a 4x3 contact sheet of all 11 cards + 1 blank cell."""
    cell_size = SIZE + cell_padding * 2
    cell_h = cell_size + label_height
    sheet_w = grid_cols * cell_size
    sheet_h = grid_rows * cell_h
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        lf_candidates = [
            "DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        ]
        label_font = None
        for fp in lf_candidates:
            try:
                label_font = ImageFont.truetype(fp, 10)
                break
            except (OSError, IOError):
                continue
        if label_font is None:
            label_font = ImageFont.load_default()
    except Exception:
        label_font = ImageFont.load_default()

    for idx, (name, img) in enumerate(cards_images[:grid_cols * grid_rows]):
        col = idx % grid_cols
        row = idx // grid_cols
        ox = col * cell_size + cell_padding
        oy = row * cell_h + cell_padding
        # Paste card (composite over black alpha bg)
        bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
        bg.paste(img, (0, 0), img)
        sheet.paste(bg, (ox, oy))
        # Label
        label_y = oy + SIZE + 2
        label_x = ox + SIZE // 2
        draw.text(
            (label_x, label_y),
            name,
            font=label_font,
            fill=(255, 255, 255, 68),
            anchor="mt",
        )
    sheet.save(out_path)


# ---------------------------------------------------------------------------
# CardRenderer
# ---------------------------------------------------------------------------

class CardRenderer:
    def __init__(self):
        self._mask = _mask()

    def render(self, card: dict) -> Image.Image:
        img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img, "RGBA")
        dispatch = {
            "ReadyCard":            self._ready,
            "SavedMemoryCard":      self._saved_memory,
            "QueryListeningCard":   self._query_listening,
            "LoadingCard":          self._loading,
            "ObjectRecallCard":     self._object_recall,
            "CommitmentRecallCard": self._commitment_recall,
            "ProactiveMemoryCard":  self._proactive_memory,
            "PersonContextCard":    self._person_context,
            "PrivacyPausedCard":    self._privacy_paused,
            "ErrorCard":            self._error_card,
            "LowConfidenceCard":    self._low_confidence,
        }
        fn = dispatch.get(card.get("type", ""))
        if fn:
            fn(draw, card)
        img.putalpha(self._mask)
        return img

    def save(self, card: dict, path: str | Path) -> None:
        self.render(card).save(str(path))

    # ------------------------------------------------------------------
    # Internal helpers (kept + extended)
    # ------------------------------------------------------------------

    def _text(self, draw, x, y, text, size, color, anchor="mm"):
        draw.text((x, y), str(text), font=_font(size),
                  fill=_hex_to_rgb(color), anchor=anchor)

    def _text_rgba(self, draw, x, y, text, size, color, alpha=255, anchor="mm"):
        r, g, b = _hex_to_rgb(color)
        draw.text((x, y), str(text), font=_font(size),
                  fill=(r, g, b, alpha), anchor=anchor)

    def _multiline_text(self, draw, x, y, text, size, color, max_width=192):
        font = _font(size)
        words = str(text).split()
        lines: list[str] = []
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            try:
                w = font.getlength(test)
            except AttributeError:
                w = len(test) * FONT_PX.get(size, 13) * 0.6
            if w <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if not lines:
            return
        line_h = FONT_PX.get(size, 13) + 5
        total_h = len(lines) * line_h
        start_y = y - total_h / 2 + line_h / 2
        for i, line in enumerate(lines):
            draw.text((x, start_y + i * line_h), line, font=font,
                      fill=_hex_to_rgb(color), anchor="mm")

    def _hline(self, draw, x1, x2, y, color, alpha=255):
        r, g, b = _hex_to_rgb(color)
        draw.line([(x1, y), (x2, y)], fill=(r, g, b, alpha), width=1)

    def _vbar(self, draw, x, y1, y2, width, color, alpha=255):
        r, g, b = _hex_to_rgb(color)
        draw.rectangle([x, y1, x + width - 1, y2], fill=(r, g, b, alpha))

    def _dot(self, draw, x, y, r, color, alpha=255):
        r_, g_, b_ = _hex_to_rgb(color)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(r_, g_, b_, alpha))

    def _circle(self, draw, cx, cy, r, stroke, color, alpha=255):
        r_, g_, b_ = _hex_to_rgb(color)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     outline=(r_, g_, b_, alpha), width=stroke)

    def _arc(self, draw, cx, cy, r, start_deg, end_deg, stroke, color, alpha=255):
        r_, g_, b_ = _hex_to_rgb(color)
        draw.arc([cx - r, cy - r, cx + r, cy + r],
                 start=start_deg, end=end_deg,
                 fill=(r_, g_, b_, alpha), width=stroke)

    # ------------------------------------------------------------------
    # Cards — transformative pass
    # ------------------------------------------------------------------

    def _ready(self, draw, card):
        """Living Memory Core: hexagon + 3 asymmetric partial-arc rings + 4 satellite dots."""
        # Central hexagon (8px, #00FF88)
        hex_pts = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            hex_pts.append((CX + 8 * math.cos(angle), CY + 8 * math.sin(angle)))
        hex_pts.append(hex_pts[0])
        r_, g_, b_ = _hex_to_rgb(T.MEMORY_TRACE)
        draw.polygon(hex_pts[:6], fill=(r_, g_, b_, 255))

        # Ring 1: 180° arc, 24px major, CCW
        draw_elliptical_arc(draw, CX, CY, 24, 24, 180, 180, 1, T.MEMORY_TRACE, alpha=68)
        # Ring 2: 270° arc, 36px, CW (positive sweep)
        draw_elliptical_arc(draw, CX, CY, 36, 36, 0, 270, 1, T.MEMORY_TRACE, alpha=34)
        # Ring 3: 90° arc, 48px, CCW (sweep reversed via 270 start)
        draw_elliptical_arc(draw, CX, CY, 48, 48, 270, 90, 1, T.MEMORY_TRACE, alpha=17)

        # 4 satellite micro-dots at Ring 1 endpoints (0° and 180°)
        for angle_deg in [0, 90, 180, 270]:
            ax = CX + 24 * math.cos(math.radians(angle_deg))
            ay = CY + 24 * math.sin(math.radians(angle_deg))
            self._dot(draw, ax, ay, 2, T.MEMORY_TRACE, alpha=180)

    def _saved_memory(self, draw, card):
        """Satisfying completion: mid-draw checkmark + seal arc + inline SAVED text."""
        # Seal arc (360° ring, bright 90° segment at top)
        self._arc(draw, CX, CY, 48, 0, 360, 1, T.ACCENT_SUCCESS, alpha=51)
        self._arc(draw, CX, CY, 48, -90, 0, 2, T.ACCENT_SUCCESS, alpha=255)  # bright top 90°

        # Mid-draw checkmark (progressive=0.6)
        draw_check_glyph(draw, (CX, CY - 8), 56, 3, T.ACCENT_SUCCESS, alpha=255, progressive=0.6)

        # "SAVED" micro-text INSIDE the arc, just above center
        self._text_rgba(draw, CX, CY - 48 + 6, "SAVED", "xs", T.ACCENT_SUCCESS, alpha=255)

        # Primary label below
        self._multiline_text(draw, CX, CY + 22, card.get("primary", ""),
                             "lg", T.TEXT_PRIMARY, max_width=188)

    def _query_listening(self, draw, card):
        """Intentional listening: sine-envelope waveform + cardioid mic glyph. No text."""
        # Cardioid mic glyph — 3 converging lines at left of waveform
        mic_cx, mic_cy = 84, CY
        r_, g_, b_ = _hex_to_rgb(T.MEMORY_TRACE)
        # Center line
        draw.line([(mic_cx, mic_cy - 6), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        draw.line([(mic_cx, mic_cy + 6), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        draw.line([(mic_cx - 4, mic_cy), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        # Mic dot
        self._dot(draw, mic_cx + 10, mic_cy, 2, T.MEMORY_TRACE)

        # Sine-envelope waveform: 32 bars, 2px wide, 1px gap
        bar_count = 32
        bar_w = 2
        gap = 1
        total_w = bar_count * (bar_w + gap) - gap
        start_x = CX - total_w // 2 + 12  # offset right to make room for mic
        bar_cy = CY
        r_a, g_a, b_a = _hex_to_rgb(T.ACCENT_ATTENTION)
        for i in range(bar_count):
            envelope = math.sin(math.pi * i / (bar_count - 1))  # 0..1..0
            phase = math.sin(math.pi * 2 * i / bar_count * 3 + 1.2)
            bh = max(2, int(22 * envelope * abs(phase)))
            bx = start_x + i * (bar_w + gap)
            a_val = int(180 + 75 * envelope)
            draw.rectangle(
                [bx, bar_cy - bh // 2, bx + bar_w - 1, bar_cy + bh // 2],
                fill=(r_a, g_a, b_a, a_val)
            )

    def _loading(self, draw, card):
        """Retrieving memory: ghost rings + bright arc with 3 echoes + pulsing center dot."""
        # Ghost rings (4 concentric, very dim)
        for ghost_r in [16, 28, 40, 52]:
            self._circle(draw, CX, CY, ghost_r, 1, T.GHOST_WHITE, alpha=8)

        # Active arc on ring 3 (40px) — 120° bright
        self._arc(draw, CX, CY, 40, -70, 50, 3, T.MEMORY_TRACE, alpha=255)
        # Fading echoes behind it at -30, -60, -90 degrees
        self._arc(draw, CX, CY, 40, -100, -70, 2, T.MEMORY_TRACE, alpha=140)
        self._arc(draw, CX, CY, 40, -130, -100, 1, T.MEMORY_TRACE, alpha=70)
        self._arc(draw, CX, CY, 40, -160, -130, 1, T.MEMORY_TRACE, alpha=30)

        # Center: pulsing dot (frozen at phase A = teal)
        self._dot(draw, CX, CY, 3, T.MEMORY_TRACE, alpha=255)
        self._dot(draw, CX, CY, 6, T.MEMORY_TRACE, alpha=40)  # soft bloom

    def _object_recall(self, draw, card):
        """The Hero: Bezier trace, confidence jewel+orbit, place at curve endpoint."""
        obj_name = (card.get("object") or card.get("primary") or "").upper()
        place    = card.get("place") or ""
        detail   = card.get("detail") or ""
        footer   = card.get("last_seen") or card.get("footer") or ""
        conf     = card.get("confidence")

        # Eyebrow: object name, upper rail, small tracking
        self._text(draw, CX, 68, obj_name, "sm", T.MEMORY_TRACE)

        # Memory trace: quadratic Bezier from 3-o'clock rail edge → place text baseline
        p0 = (228.0, 128.0)   # 3-o'clock rail edge
        p1 = (180.0, 92.0)    # control point
        p2 = (128.0, 148.0)   # place text baseline (curve endpoint)
        draw_quadratic_bezier(draw, p0, p1, p2,
                              stroke=2, color=T.MEMORY_TRACE, alpha=255, dash_offset=3.0)

        # Confidence jewel: 4px diamond at curve apex (~t=0.5)
        apex_x = (1 - 0.5) ** 2 * p0[0] + 2 * (1 - 0.5) * 0.5 * p1[0] + 0.5 ** 2 * p2[0]
        apex_y = (1 - 0.5) ** 2 * p0[1] + 2 * (1 - 0.5) * 0.5 * p1[1] + 0.5 ** 2 * p2[1]
        jewel_color = T.conf_color(conf)
        # Diamond (4 points)
        jd = 4
        r_, g_, b_ = _hex_to_rgb(jewel_color)
        draw.polygon([
            (apex_x, apex_y - jd), (apex_x + jd, apex_y),
            (apex_x, apex_y + jd), (apex_x - jd, apex_y)
        ], fill=(r_, g_, b_, 255))
        # Orbit arcs: 3 × 120° arcs at 120° phase offsets, radius 8
        for phase in [0, 120, 240]:
            draw_elliptical_arc(draw, apex_x, apex_y, 8, 8,
                                phase, 100, 1, jewel_color, alpha=160)

        # Place: set at curve endpoint, not centered — hero size, slight offset left
        self._text(draw, 112, 150, place, "hero", T.TEXT_PRIMARY, anchor="mm")
        # Glow hint behind place text
        r_t, g_t, b_t = _hex_to_rgb(T.MEMORY_TRACE)
        draw.text((112, 150), place, font=_font("hero"),
                  fill=(r_t, g_t, b_t, 28), anchor="mm")

        # Detail: inside dashed bracket, 8px micro-text
        self._text_rgba(draw, CX, 180, f"[ {detail} ]", "xs", T.TEXT_SECONDARY, alpha=180)

        # Footer (last seen)
        self._text_rgba(draw, CX, 200, footer, "xs", T.TEXT_GHOST, alpha=160)

        # Confidence dot
        self._dot(draw, CX, 218, 3, jewel_color)

    def _commitment_recall(self, draw, card):
        """Linked chain: 3 rounded rects connected by curves, last link bright."""
        person = card.get("person") or ""
        task   = card.get("primary") or ""
        due    = card.get("due") or ""
        conf   = card.get("confidence")

        # Header
        self._text_rgba(draw, CX, 68, f"YOU PROMISED {person.upper()}",
                        "xs", T.MEMORY_TRACE, alpha=200)

        # Chain links: 3 rounded rects at different y positions, connected
        chain_x = 64
        chain_w = 128
        link_positions = [(CX - chain_w // 2, 84), (CX - chain_w // 2, 108), (CX - chain_w // 2, 132)]
        link_h = 18
        r_, g_, b_ = _hex_to_rgb(T.MEMORY_TRACE)
        for li, (lx, ly) in enumerate(link_positions):
            is_last = li == 2
            stroke_alpha = 255 if is_last else 100
            lw = 2 if is_last else 1
            draw.rounded_rectangle([lx, ly, lx + chain_w, ly + link_h],
                                   radius=4, outline=(r_, g_, b_, stroke_alpha), width=lw)
            if is_last:
                # bright fill for last link
                draw.rounded_rectangle([lx, ly, lx + chain_w, ly + link_h],
                                       radius=4, fill=(r_, g_, b_, 18))

        # Connector curves between links
        for lx, ly in link_positions[:2]:
            # Small vertical connector line
            draw.line(
                [(CX, ly + link_h), (CX, ly + link_h + (link_positions[1][1] - link_positions[0][1] - link_h))],
                fill=(r_, g_, b_, 60), width=1
            )

        # Task text inside second link
        self._text_rgba(draw, CX, 108 + link_h // 2, task, "sm", T.TEXT_PRIMARY, alpha=230)

        # Due (inside last link, bright)
        self._text_rgba(draw, CX, 132 + link_h // 2, due, "sm", T.MEMORY_TRACE, alpha=255)

        # Confidence dot
        self._dot(draw, CX, 168, 2, T.conf_color(conf))

    def _proactive_memory(self, draw, card):
        """Radial ray field: 5 rays from center, lengths=relevance, tip bloom."""
        summary = card.get("primary") or ""
        person  = card.get("person")

        # Eyebrow
        self._text_rgba(draw, CX, 62, "LAST TIME HERE", "xs", T.TEXT_GHOST, alpha=160)

        # Radial ray field — 5 rays at 72° apart, varying lengths
        lengths = [38.0, 52.0, 44.0, 30.0, 46.0]
        draw_radial_rays(draw, CX, CY - 10, 5, lengths,
                         T.MEMORY_TRACE, alpha=160, tip_bloom=True, stroke=1)

        # Inner dot at center of rays
        self._dot(draw, CX, CY - 10, 3, T.MEMORY_TRACE, alpha=200)

        # Summary text below rays
        self._multiline_text(draw, CX, CY + 50, summary,
                             "md", T.TEXT_SECONDARY, max_width=180)
        if person:
            self._text_rgba(draw, CX, CY + 78, f"With {person}",
                            "sm", T.MEMORY_TRACE, alpha=200)

    def _person_context(self, draw, card):
        """Polar segment array: 12 micro-segments, 3 lit = confidence. Name on chord."""
        name    = card.get("primary") or ""
        headline = card.get("headline") or ""
        detail  = card.get("detail") or ""

        # Polar segment ring (12 segs, first 3 lit)
        draw_polar_segments(draw, CX, 100, 38, 56, 12, [0, 1, 2],
                            T.MEMORY_TRACE, alpha_lit=255, alpha_dim=35)

        # Name text — placed on chord tangent (slightly left-offset)
        self._text(draw, CX, 100, name, "lg", T.MEMORY_TRACE)

        # Separator line
        self._hline(draw, 72, 184, 116, T.BORDER_SUBTLE)

        # Headline
        self._multiline_text(draw, CX, 140, headline, "md", T.TEXT_PRIMARY, max_width=192)
        # Detail
        self._text_rgba(draw, CX, 164, detail, "sm", T.TEXT_SECONDARY, alpha=200)

    def _privacy_paused(self, draw, card):
        """Safety-critical: shield+pause-bars glyph, breach-halo (90° gap), red palette. Zero teal."""
        # Outer halo ring with missing 90° segment at top (breach)
        self._arc(draw, CX, CY, 108, 10, 350, 1, T.PRIVACY_DANGER, alpha=34)  # 340° arc
        # Inner ghost ring
        self._circle(draw, CX, CY, 88, 1, T.PRIVACY_DANGER, alpha=18)

        # Shield glyph (52px hexagon + pause bars)
        draw_shield_glyph(draw, (CX, CY - 14), 52, 2, T.PRIVACY_DANGER, alpha=255, pause_bars=True)

        # Status text (caution amber, minimal)
        self._text_rgba(draw, CX, CY + 32, "PAUSED", "sm", T.PRIVACY_CAUTION, alpha=220)
        self._text_rgba(draw, CX, CY + 48, "Nothing is captured", "xs", T.TEXT_GHOST, alpha=140)

    def _error_card(self, draw, card):
        """Calm amber outline: equilateral triangle + minimal exclamation + curved telemetry text."""
        # Outer ring (amber, thin)
        self._circle(draw, CX, CY, 116, 1, T.WARNING_AMBER, alpha=64)

        # Outline triangle — equilateral, 56px, vertices at 12/4/8 o'clock
        tri_size = 56
        tri_cy = CY - 8
        tri_pts = [
            (CX,               tri_cy - tri_size // 2),          # 12 o'clock
            (CX + int(tri_size * 0.577), tri_cy + tri_size // 2), # 4 o'clock
            (CX - int(tri_size * 0.577), tri_cy + tri_size // 2), # 8 o'clock
            (CX,               tri_cy - tri_size // 2),           # close
        ]
        r_, g_, b_ = _hex_to_rgb(T.WARNING_AMBER)
        draw.line(tri_pts, fill=(r_, g_, b_, 255), width=2)

        # Inner exclamation: dot + line
        self._dot(draw, CX, tri_cy - 6, 2, T.WARNING_AMBER)
        draw.line([(CX, tri_cy + 2), (CX, tri_cy + 14)],
                  fill=(r_, g_, b_, 255), width=2)

        # Error code / telemetry text — below triangle, mono style
        err_msg = card.get("primary", "Try again")
        self._text_rgba(draw, CX, CY + 52, err_msg, "xs", T.TEXT_GHOST, alpha=180)

    def _low_confidence(self, draw, card):
        """Point cloud text: place name as particle cloud, density=confidence."""
        # "Not sure" rendered as point cloud (confidence=0 → maximum scatter)
        draw_point_cloud_text(
            draw, "Not sure", CX, CY - 14,
            font_size=20, density=0.15,
            color=T.TEXT_SECONDARY, alpha=200
        )
        # Subtitle as point cloud too, slightly denser
        draw_point_cloud_text(
            draw, "Try rephrasing", CX, CY + 16,
            font_size=11, density=0.25,
            color=T.TEXT_GHOST, alpha=160
        )
        # Scatter dots (low-energy signal)
        self._dot(draw, 107, 180, 2, T.TEXT_GHOST, alpha=80)
        self._dot(draw, 128, 184, 2, T.TEXT_GHOST, alpha=60)
        self._dot(draw, 149, 180, 2, T.TEXT_GHOST, alpha=80)
