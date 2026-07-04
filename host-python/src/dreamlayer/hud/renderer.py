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


def _ellipsize(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


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
# Primitive drawing functions
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
    r, g, b = _hex_to_rgb(color)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    seg_count = len(pts) - 1
    for i in range(seg_count):
        frac = i / seg_count
        seg_idx = int(frac * seg_count + dash_offset) % 12
        if seg_idx < 6:
            seg_alpha = int(0x66 + (alpha - 0x66) * frac)
            draw.line([pts[i], pts[i + 1]], fill=(r, g, b, seg_alpha), width=stroke)


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    stroke: int,
    color: int,
    alpha: int = 255,
    progressive: float = 1.0,
) -> None:
    r, g, b = _hex_to_rgb(color)
    total = len(points) - 1
    end_idx = max(1, int(math.ceil(total * progressive)))
    for i in range(min(end_idx, total)):
        draw.line([points[i], points[i + 1]], fill=(r, g, b, alpha), width=stroke)


# ---------------------------------------------------------------------------
# Meridian Solid material twins (mirror halo-lua/display/materials.lua).
# Same scanline rows, NO alpha — if 4bpp can't do it, the mirror can't
# either (docs/cinema_v2/solid.md).
# ---------------------------------------------------------------------------

RAMP_MEMORY = (T.MEMORY_TRACE, T.ACCENT_MEMORY_STATIC,
               T.ACCENT_MEMORY_DIM, T.BORDER_SUBTLE)
RAMP_SUCCESS = (T.ACCENT_SUCCESS, T.ACCENT_SUCCESS_DIM, T.BORDER_SUBTLE)
PANE = T.SURFACE

_BLOOM_DIM = {
    T.MEMORY_TRACE: T.ACCENT_MEMORY_DIM,
    T.ACCENT_MEMORY_STATIC: T.ACCENT_MEMORY_DIM,
    T.ACCENT_MEMORY: T.ACCENT_MEMORY_DIM,
    T.ACCENT_SUCCESS: T.ACCENT_SUCCESS_DIM,
    T.ACCENT_ATTENTION: T.ACCENT_ATTENTION_DIM,
    T.WARNING_AMBER: T.WARNING_AMBER_DIM,
    T.CONFIDENCE_HIGH: T.ACCENT_MEMORY_DIM,
    T.CONFIDENCE_MED: T.ACCENT_MEMORY_DIM,
    T.CONFIDENCE_LOW: T.WARNING_AMBER_DIM,
    T.TEXT_GHOST_STATIC: T.BORDER_SUBTLE,
}


def glass_disc(draw, cx, cy, r, color=PANE, row_gap=3):
    row_gap = max(2, row_gap)
    rgb = _hex_to_rgb(color)
    for y in range(cy - r + row_gap, cy + r, row_gap):
        dy = y - cy
        half = math.sqrt(max(0, r * r - dy * dy)) - 2
        if half >= 1:
            draw.line([(cx - half, y), (cx + half, y)], fill=rgb, width=1)


def glass_capsule(draw, x, y, w, h, color=PANE, row_gap=3):
    row_gap = max(2, row_gap)
    rgb = _hex_to_rgb(color)
    hr = h / 2
    for ry in range(y + row_gap, y + h, row_gap):
        dy = ry - y
        cap = min(dy, h - dy)
        inset = 0.0
        if cap < hr:
            inset = hr - math.sqrt(max(0.0, hr * hr - (hr - cap) ** 2))
        x0, x1 = x + inset + 1, x + w - inset - 1
        if x1 > x0:
            draw.line([(x0, ry), (x1, ry)], fill=rgb, width=1)


def grad_line(draw, x0, y0, x1, y1, ramp=RAMP_MEMORY, stroke=1):
    n = len(ramp)
    px, py = x0, y0
    for i, color in enumerate(ramp, start=1):
        t = i / n
        nx, ny = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        draw.line([(px, py), (nx, ny)], fill=_hex_to_rgb(color), width=stroke)
        px, py = nx, ny


def grad_arc(draw, cx, cy, r, a0, a1, ramp=RAMP_MEMORY, steps=32, stroke=1):
    sweep = a1 - a0
    def pt(deg):
        rd = math.radians(deg)
        return cx + r * math.cos(rd), cy + r * math.sin(rd)
    x0, y0 = pt(a0)
    for i in range(1, steps + 1):
        x1, y1 = pt(a0 + sweep * i / steps)
        ci = min(len(ramp) - 1, math.ceil(i / steps * len(ramp)) - 1)
        draw.line([(x0, y0), (x1, y1)], fill=_hex_to_rgb(ramp[ci]),
                  width=stroke)
        x0, y0 = x1, y1


def grad_bezier(draw, p0, p1, p2, ramp=RAMP_MEMORY, steps=24, stroke=1):
    px, py = p0
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        ci = min(len(ramp) - 1, math.ceil(i / steps * len(ramp)) - 1)
        draw.line([(px, py), (x, y)], fill=_hex_to_rgb(ramp[ci]), width=stroke)
        px, py = x, y


def bloom_ring(draw, cx, cy, r, color):
    dim = _BLOOM_DIM.get(color, T.BORDER_SUBTLE)
    draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2],
                 outline=_hex_to_rgb(dim), width=1)
    draw.ellipse([cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5],
                 outline=_hex_to_rgb(T.BORDER_SUBTLE), width=1)


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
    cx, cy = center
    r_, g_, b_ = _hex_to_rgb(color)
    hw = size / 2
    pts = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        pts.append((cx + hw * math.cos(angle), cy + hw * math.sin(angle)))
    pts.append(pts[0])
    draw.line(pts, fill=(r_, g_, b_, alpha), width=stroke)
    if pause_bars:
        bar_h = int(size * 0.24)
        bar_w = max(3, int(size * 0.08))
        gap = max(2, int(size * 0.07))
        draw.rectangle(
            [cx - gap - bar_w, cy - bar_h, cx - gap, cy + bar_h],
            fill=(r_, g_, b_, alpha)
        )
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
    skip_indices: list[int] | None = None,
) -> None:
    r_, g_, b_ = _hex_to_rgb(color)
    step = 360.0 / count
    for i in range(count):
        if skip_indices and i in skip_indices:
            continue
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
    import random
    r_, g_, b_ = _hex_to_rgb(color)
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
        bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
        bg.paste(img, (0, 0), img)
        sheet.paste(bg, (ox, oy))
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
        self._extra: dict = {}     # plugin-registered card renderers (type -> fn)

    def register(self, card_type: str, fn) -> None:
        """Register a renderer for a plugin's own card type. fn(draw, card)
        draws onto the round canvas exactly like the built-in `_layout_card`."""
        self._extra[card_type] = fn

    def render(self, card: dict) -> Image.Image:
        # RGB canvas: Pillow's "RGBA" draw mode only alpha-BLENDS on RGB
        # images. On an RGBA base the ink alpha is stored, not blended, and
        # was then discarded by putalpha() — so every alpha= dim in this
        # file rendered fully opaque (vision pass 3 finding: the commitment
        # card's alpha-18 link fill was a solid pill hiding the due text).
        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
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
            "PrivacyVeilCard":    self._privacy_veil,
            "ErrorCard":            self._error_card,
            "LowConfidenceCard":    self._low_confidence,
            # Halo Cinema v1
            "TruthLensCard":        self._truth_gauge,
            "WorldAnchorCard":      self._world_anchor,
            "SynesthesiaCard":      self._synesthesia,
            # Meridian: the three cards v1's dispatch forgot — their
            # committed goldens were black discs (CINEMA_V1_JUDGMENT.md
            # Wrong #1) while the device drew them fine
            "CommitmentDriftCard":  self._commitment_drift,
            "TimeScrubNodeCard":    self._time_scrub_node,
            "DeviationAlertCard":   self._deviation_alert,
            # …and the four layout-driven cards NEITHER side drew (a
            # consent prompt rendered as a black screen on device; found
            # during the Meridian golden pass)
            "ForgetLastCard":       self._layout_card,
            "PrivateZoneCard":      self._layout_card,
            "ConsentRequiredCard":  self._layout_card,
            "LiveCaptionCard":      self._layout_card,
            # Conversation ledger: live transcript + dossier on greet
            "SpokenCaptionCard":    self._layout_card,
            "PersonDossierCard":    self._layout_card,
            "MorningBriefCard":     self._layout_card,
            "ListeningCard":        self._layout_card,
            # Meridian Solid: the O3 conversation cards get the full material
            # treatment (glass pane, gradient strokes, bloom, hero type).
            "HarkCard":             self._hark,
            "OracleReplyCard":      self._oracle_reply,
            "FactCheckCard":        self._fact_check,
            "AnswerAheadCard":      self._answer_ahead,
            "ScholarCard":          self._scholar,
            "GlanceChoiceCard":     self._scholar,
            "TasteCard":            self._scholar,
        }
        if self._extra:
            dispatch.update(self._extra)   # plugin card renderers
        fn = dispatch.get(card.get("type", ""))
        if fn:
            fn(draw, card)
        img = img.convert("RGBA")
        img.putalpha(self._mask)
        return img

    def save(self, card: dict, path: str | Path) -> None:
        self.render(card).save(str(path))

    # ------------------------------------------------------------------
    # Helpers
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
    # Cards
    # ------------------------------------------------------------------

    def _ready(self, draw, card):
        hex_pts = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            hex_pts.append((CX + 8 * math.cos(angle), CY + 8 * math.sin(angle)))
        hex_pts.append(hex_pts[0])
        r_, g_, b_ = _hex_to_rgb(T.MEMORY_TRACE)
        draw.polygon(hex_pts[:6], fill=(r_, g_, b_, 255))
        grad_arc(draw, CX, CY, 24, 180, 360, RAMP_MEMORY, 32)
        draw_elliptical_arc(draw, CX, CY, 36, 36, 0, 270, 1, T.MEMORY_TRACE, alpha=34)
        draw_elliptical_arc(draw, CX, CY, 48, 48, 270, 90, 1, T.MEMORY_TRACE, alpha=17)
        for angle_deg in [0, 90, 180, 270]:
            ax = CX + 24 * math.cos(math.radians(angle_deg))
            ay = CY + 24 * math.sin(math.radians(angle_deg))
            self._dot(draw, ax, ay, 2, T.MEMORY_TRACE, alpha=180)

    def _saved_memory(self, draw, card):
        # Meridian Solid v2: giant double-struck check jewel inside
        # concentric gradient rings over a soft pane (mirrors the Lua).
        glass_disc(draw, CX, 124, 66, PANE, 4)
        self._circle(draw, CX, 124, 70, 1, T.BORDER_SUBTLE, alpha=255)
        self._arc(draw, CX, 124, 62, 0, 360, 1, T.BORDER_SUBTLE, alpha=255)
        self._arc(draw, CX, 124, 54, 0, 360, 1, T.ACCENT_SUCCESS_DIM, alpha=255)
        self._arc(draw, CX, 124, 46, 0, 360, 1, T.ACCENT_SUCCESS, alpha=255)
        draw_check_glyph(draw, (CX, 120), 72, 2, T.ACCENT_SUCCESS,
                         alpha=255, progressive=1.0)
        draw_check_glyph(draw, (CX, 121), 72, 2, T.ACCENT_SUCCESS,
                         alpha=255, progressive=1.0)
        self._text_rgba(draw, CX, 42, "SAVED", "hero", T.ACCENT_SUCCESS,
                        alpha=255)
        self._text_rgba(draw, CX, 206, card.get("primary", ""), "md",
                        T.TEXT_PRIMARY, alpha=255)

    def _query_listening(self, draw, card):
        mic_cx, mic_cy = 84, CY
        r_, g_, b_ = _hex_to_rgb(T.MEMORY_TRACE)
        draw.line([(mic_cx, mic_cy - 6), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        draw.line([(mic_cx, mic_cy + 6), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        draw.line([(mic_cx - 4, mic_cy), (mic_cx + 10, mic_cy)], fill=(r_, g_, b_, 255), width=1)
        self._dot(draw, mic_cx + 10, mic_cy, 2, T.MEMORY_TRACE)
        bar_count = 32
        bar_w = 2
        gap = 1
        total_w = bar_count * (bar_w + gap) - gap
        start_x = CX - total_w // 2 + 12
        bar_cy = CY
        r_a, g_a, b_a = _hex_to_rgb(T.ACCENT_ATTENTION)
        for i in range(bar_count):
            envelope = math.sin(math.pi * i / (bar_count - 1))
            phase = math.sin(math.pi * 2 * i / bar_count * 3 + 1.2)
            bh = max(2, int(22 * envelope * abs(phase)))
            bx = start_x + i * (bar_w + gap)
            a_val = int(180 + 75 * envelope)
            draw.rectangle(
                [bx, bar_cy - bh // 2, bx + bar_w - 1, bar_cy + bh // 2],
                fill=(r_a, g_a, b_a, a_val)
            )

    def _loading(self, draw, card):
        # Lumen mirror: the rotating arc is gone on device — 12 static
        # segments around r=40 that the palette chase lights in turn
        # (halo-lua draw_loading). The mirror shows the chase mid-cycle.
        for ghost_r in [16, 28, 52]:
            self._circle(draw, CX, CY, ghost_r, 1, T.GHOST_WHITE, alpha=8)
        n, gap = 12, 6
        span = 360 / n
        for i in range(n):
            a0 = -90 + i * span + gap / 2
            # brightness chases: the lead segment glows, trail dims behind
            alpha = 255 - ((i * 3) % n) * 18
            self._arc(draw, CX, CY, 40, a0, a0 + span - gap, 2,
                      T.MEMORY_TRACE, alpha=max(40, alpha))
        self._dot(draw, CX, CY, 3, T.MEMORY_TRACE, alpha=255)
        self._dot(draw, CX, CY, 6, T.MEMORY_TRACE, alpha=40)

    def _object_recall(self, draw, card):
        """Meridian Solid v3 — a spatial scene, not a text list.

        The place is a translucent field; the object is a jewel in it;
        you are a dot at the bottom; a gradient trace (dim at you,
        bright at the jewel) connects the two. Mirrors the device Lua
        draw_object_recall exactly (same geometry, no alpha tricks on
        the load-bearing strokes)."""
        def _name(v) -> str:
            if isinstance(v, dict):
                return str(v.get("name") or v.get("near") or "")
            return str(v or "")

        obj_name = _name(card.get("object") or card.get("primary")).upper()
        place    = _name(card.get("place"))
        detail   = _name(card.get("detail"))
        footer   = _name(card.get("last_seen") or card.get("footer"))
        conf     = card.get("confidence")
        jewel_color = T.conf_color(conf)

        # the place, as a translucent field
        glass_disc(draw, CX, 112, 62, PANE, 3)

        # gradient trace: you -> object, cooling away from the jewel
        grad_bezier(draw, (128, 192), (168, 140), (132, 102),
                    ramp=(T.BORDER_SUBTLE, T.ACCENT_MEMORY_DIM,
                          T.ACCENT_MEMORY_STATIC, T.MEMORY_TRACE),
                    steps=24)

        # the object jewel: layered diamonds + orbit arcs + bloom
        jx, jy = 128, 88
        rj, gj, bj = _hex_to_rgb(jewel_color)
        draw.polygon([(jx, jy - 9), (jx + 9, jy), (jx, jy + 9),
                      (jx - 9, jy)], outline=(rj, gj, bj, 255))
        rt_, gt_, bt_ = _hex_to_rgb(T.MEMORY_TRACE)
        draw.polygon([(jx, jy - 4), (jx + 4, jy), (jx, jy + 4),
                      (jx - 4, jy)], outline=(rt_, gt_, bt_, 255))
        for phase in [0, 120, 240]:
            draw_elliptical_arc(draw, jx, jy, 14, 14, phase, 90, 1,
                                jewel_color, alpha=255)
        bloom_ring(draw, jx, jy, 14, jewel_color)

        # you, at the bottom of the scene
        self._dot(draw, 128, 198, 3, T.MEMORY_TRACE, alpha=255)
        bloom_ring(draw, 128, 198, 3, T.MEMORY_TRACE)

        # type: time eyebrow, object label, HERO place, bracketed detail
        self._text_rgba(draw, CX, 50, footer, "xs", T.TEXT_GHOST, alpha=255)
        self._text_rgba(draw, CX, 66, obj_name, "md", T.MEMORY_TRACE,
                        alpha=255)
        place_size = "hero" if len(place) * 12 <= 170 else (
            "xl" if len(place) * 11 <= 170 else "lg")
        self._text_rgba(draw, CX, 150, place, place_size, T.TEXT_PRIMARY,
                        alpha=255)
        if detail:
            self._text_rgba(draw, CX, 176, f"[ {detail} ]", "md",
                            T.TEXT_SECONDARY, alpha=255)

    def _commitment_recall(self, draw, card):
        person = card.get("person") or ""
        task   = card.get("primary") or ""
        due    = card.get("due") or ""
        conf   = card.get("confidence")
        self._text_rgba(draw, CX, 68, f"YOU PROMISED {person.upper()}",
                        "xs", T.MEMORY_TRACE, alpha=200)
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
                # Solid: the live link glows from within (scanline pane)
                glass_capsule(draw, lx + 4, ly + 1, chain_w - 8, link_h - 2,
                              PANE, 3)
        # Solid: gradient connectors falling toward the live link
        grad_line(draw, CX, 84 + link_h, CX, 108,
                  (T.BORDER_SUBTLE, T.ACCENT_MEMORY_DIM))
        grad_line(draw, CX, 108 + link_h, CX, 132,
                  (T.ACCENT_MEMORY_DIM, T.ACCENT_MEMORY_STATIC))
        self._text_rgba(draw, CX, 108 + link_h // 2, task, "sm", T.TEXT_PRIMARY, alpha=230)
        self._text_rgba(draw, CX, 132 + link_h // 2, due, "sm", T.MEMORY_TRACE, alpha=255)
        self._dot(draw, CX, 168, 2, T.conf_color(conf))

    def _proactive_memory(self, draw, card):
        summary = card.get("primary") or ""
        person  = card.get("person")
        self._text_rgba(draw, CX, 62, "LAST TIME HERE", "xs", T.TEXT_GHOST, alpha=160)
        lengths = [38.0, 52.0, 44.0, 30.0, 46.0]
        draw_radial_rays(draw, CX, CY - 10, 5, lengths,
                         T.MEMORY_TRACE, alpha=160, tip_bloom=True, stroke=1)
        self._dot(draw, CX, CY - 10, 3, T.MEMORY_TRACE, alpha=200)
        bloom_ring(draw, CX, CY - 10, 3, T.MEMORY_TRACE)
        self._multiline_text(draw, CX, CY + 50, summary, "md", T.TEXT_SECONDARY, max_width=180)
        if person:
            self._text_rgba(draw, CX, CY + 78, f"With {person}",
                            "sm", T.MEMORY_TRACE, alpha=200)

    def _person_context(self, draw, card):
        """PersonContextCard — Meridian Solid centerpiece: avatar ring
        with bloom under an enlarged crown over a soft pane, name in
        hero-class type. `why` stays the one primary line; chord arcs
        ring the avatar zone when has_avatar (registered contacts only).
        Mirrors the device Lua draw_person_context."""
        name     = card.get("primary") or ""
        headline = card.get("headline") or ""
        why      = card.get("why") or ""
        detail   = card.get("detail") or ""
        conf     = card.get("confidence")

        glass_disc(draw, CX, 96, 56, PANE, 3)
        self._circle(draw, CX, 84, 18, 1, T.BORDER_SUBTLE, alpha=255)
        bloom_ring(draw, CX, 84, 18, T.ACCENT_MEMORY_STATIC)
        draw_polar_segments(draw, CX, 84, 26, 44, 12, [0, 1, 2],
                            T.MEMORY_TRACE, alpha_lit=255, alpha_dim=35,
                            skip_indices=[5, 6, 7])
        if card.get("has_avatar"):
            sweep = (conf or 1.0) * 360
            for i, r in enumerate((32, 40, 48)):
                self._arc(draw, CX, 84, r, -90, -90 + sweep, 1,
                          T.ACCENT_MEMORY, alpha=200 - i * 55)
            self._text_rgba(draw, CX, 84, name[:1].upper(), "md",
                            T.TEXT_PRIMARY, alpha=230)

        name_size = "hero" if len(name) * 12 <= 170 else "xl"
        self._text(draw, CX, 148, name, name_size, T.MEMORY_TRACE)
        grad_line(draw, 76, 164, 180, 164)
        line = why if why else headline
        if len(line) > 34:
            line = line[:33] + "…"
        self._text(draw, CX, 180, line, "md", T.TEXT_PRIMARY)
        if why and headline:
            self._text_rgba(draw, CX, 196, headline, "sm",
                            T.TEXT_SECONDARY, alpha=255)
        self._text_rgba(draw, CX, 210, detail, "sm", T.TEXT_GHOST, alpha=255)

    def _privacy_veil(self, draw, card):
        self._arc(draw, CX, CY, 108, 10, 350, 1, T.PRIVACY_DANGER, alpha=34)
        self._circle(draw, CX, CY, 88, 1, T.PRIVACY_DANGER, alpha=18)
        draw_shield_glyph(draw, (CX, CY - 14), 52, 2, T.PRIVACY_DANGER, alpha=255, pause_bars=True)
        self._text_rgba(draw, CX, CY + 32, "PRIVACY VEIL", "sm", T.PRIVACY_CAUTION, alpha=220)
        self._text_rgba(draw, CX, CY + 48, "Nothing is captured", "xs", T.TEXT_GHOST, alpha=140)

    def _error_card(self, draw, card):
        self._circle(draw, CX, CY, 116, 1, T.WARNING_AMBER, alpha=64)
        tri_size = 56
        tri_cy = CY - 8
        tri_pts = [
            (CX,               tri_cy - tri_size // 2),
            (CX + int(tri_size * 0.577), tri_cy + tri_size // 2),
            (CX - int(tri_size * 0.577), tri_cy + tri_size // 2),
            (CX,               tri_cy - tri_size // 2),
        ]
        r_, g_, b_ = _hex_to_rgb(T.WARNING_AMBER)
        draw.line(tri_pts, fill=(r_, g_, b_, 255), width=2)
        self._dot(draw, CX, tri_cy - 6, 2, T.WARNING_AMBER)
        draw.line([(CX, tri_cy + 2), (CX, tri_cy + 14)],
                  fill=(r_, g_, b_, 255), width=2)
        err_msg = card.get("primary", "Try again")
        self._text_rgba(draw, CX, CY + 52, err_msg, "xs", T.TEXT_GHOST, alpha=180)

    # ------------------------------------------------------------------
    # Halo Cinema v1 cards
    # ------------------------------------------------------------------

    _GAUGE_DIR_COLOR = {
        "truthful":     T.ACCENT_SUCCESS,
        "deceptive":    T.ACCENT_ATTENTION,
        "insufficient": T.TEXT_GHOST,
    }

    # Testimony Thread geometry — mirrors halo-lua/display/renderer.lua
    # draw_testimony and animations.lua TESTIMONY_* (keep in lockstep)
    _THREAD_R        = 64
    _THREAD_SLOT_DEG = 40
    _THREAD_TEAR_PX  = 3

    def _truth_gauge(self, draw, card):
        """TruthLensCard — the Testimony Thread (Meridian,
        docs/cinema_v2/testimony.md; replaces the v1 9-ring gauge,
        CINEMA_V2_DELTAS.md §5). One arc at r=64, nine 40° slots clockwise
        from 12 in pipeline order: truthful = continuous accent_success
        stroke, deceptive = torn (3 dashes, ±3px radial jitter) in
        accent_attention, insufficient = an honest empty slot between the
        ghost boundary ticks. Center: verdict + capsule + confidence dot.
        (Truth Ripple entry is device-side motion; the golden shows the
        settled frame.)"""
        import math as _math
        stages  = card.get("stages") or []
        verdict = card.get("verdict") or card.get("primary") or ""
        conf    = card.get("confidence")

        # slot boundary ticks: the compass rose of the pipeline
        for i in range(9):
            a = _math.radians(-90 + i * self._THREAD_SLOT_DEG)
            x1 = CX + (self._THREAD_R - 2) * _math.cos(a)
            y1 = CY + (self._THREAD_R - 2) * _math.sin(a)
            x2 = CX + (self._THREAD_R + 2) * _math.cos(a)
            y2 = CY + (self._THREAD_R + 2) * _math.sin(a)
            draw.line([(x1, y1), (x2, y2)], fill=T.to_rgba(T.BORDER_SUBTLE, 0.9),
                      width=1)

        for i in range(9):
            stage = stages[i] if i < len(stages) else {}
            direction = stage.get("direction", "insufficient")
            if direction == "insufficient":
                continue   # absence of evidence is displayed, never faked
            sconf = max(0.0, min(1.0, stage.get("confidence", 0.0)))
            a0 = -90 + i * self._THREAD_SLOT_DEG + 2
            span = sconf * (self._THREAD_SLOT_DEG - 4)
            if span <= 1:
                continue
            # Solid: only the newest revealed stage is bright; older
            # testimony cools to its dim twin (recency is a visible bit)
            newest = max(idx for idx in range(9)
                         if idx < len(stages)
                         and (stages[idx] or {}).get("direction",
                                                     "insufficient")
                         != "insufficient")
            if direction == "truthful":
                color = T.ACCENT_SUCCESS if i >= newest else T.ACCENT_SUCCESS_DIM
                self._arc(draw, CX, CY, self._THREAD_R, a0, a0 + span, 2,
                          color, alpha=235)
            else:
                color = (T.ACCENT_ATTENTION if i >= newest
                         else T.ACCENT_ATTENTION_DIM)
                # torn: 3 dashes alternating -3/+3/-3 px radial offset
                dash = span / 4
                for d, off in enumerate((-self._THREAD_TEAR_PX,
                                         self._THREAD_TEAR_PX,
                                         -self._THREAD_TEAR_PX)):
                    da0 = a0 + d * (dash + dash / 2)
                    da1 = min(da0 + dash, a0 + span)
                    if da1 > da0:
                        self._arc(draw, CX, CY, self._THREAD_R + off, da0, da1,
                                  2, color, alpha=235)

        # Solid: the verdict sits in a glass capsule in hero-class type
        vsize = ("hero" if len(verdict) * 12 <= 130
                 else "xl" if len(verdict) * 11 <= 130 else "lg")
        adv = {"hero": 12, "xl": 11, "lg": 10}[vsize]
        hw = max(26, int(len(verdict) * adv / 2) + 10)
        draw.rectangle([CX - hw, CY - 16, CX + hw, CY + 17],
                       fill=(0, 0, 0, 255))
        glass_capsule(draw, CX - hw, CY - 16, hw * 2, 32, PANE, 3)
        cr = 16
        rgb_b = _hex_to_rgb(T.BORDER_SUBTLE)
        draw.line([(CX - hw + cr, CY - 16), (CX + hw - cr, CY - 16)],
                  fill=rgb_b, width=1)
        draw.line([(CX - hw + cr, CY + 16), (CX + hw - cr, CY + 16)],
                  fill=rgb_b, width=1)
        self._arc(draw, CX - hw + cr, CY, cr, 90, 270, 1,
                  T.BORDER_SUBTLE, alpha=255)
        self._arc(draw, CX + hw - cr, CY, cr, -90, 90, 1,
                  T.BORDER_SUBTLE, alpha=255)
        self._text(draw, CX, CY, verdict, vsize, T.TEXT_PRIMARY)
        if conf is not None:
            self._dot(draw, CX, CY + 26, 3, T.conf_color(conf))
        footer = card.get("footer") or ""
        if footer:
            self._text_rgba(draw, CX, 208, footer, "xs", T.TEXT_GHOST, alpha=150)
        self._text_rgba(draw, CX, 46, "TRUTH LENS", "xs", T.TEXT_GHOST, alpha=140)

    def _world_anchor(self, draw, card):
        """WorldAnchorCard — ghost-tier memory echo at the bottom of the
        display (Ghost Wake settles to this frame on-device)."""
        # Rows 192/208/222 and a 22-char cap keep every glyph inside the
        # circular safe chord — the old 196/214/230 rows clipped the detail
        # line at the display edge (pass-1 vision fix).
        summary = _ellipsize(card.get("primary") or "", 22)
        detail  = _ellipsize(card.get("detail") or "", 22)
        self._text_rgba(draw, CX, 192, "• MEMORY ECHO •", "xs",
                        T.TEXT_GHOST, alpha=120)
        self._text_rgba(draw, CX, 208, summary, "sm", T.TEXT_GHOST, alpha=170)
        if detail:
            self._text_rgba(draw, CX, 222, detail, "xs", T.TEXT_GHOST, alpha=110)

    def _synesthesia(self, draw, card):
        """SynesthesiaCard. v1: hero phrase. v2 (Halo Cinema v1): phrase in
        the top half at ghost tier + the 3-shape gestural sprite composed
        into the bottom half."""
        desc = card.get("primary") or ""
        if card.get("version") != 2:
            self._text_rgba(draw, CX, 100, "DREAM", "xs", T.ACCENT_MEMORY, alpha=200)
            self._hline(draw, 64, 192, 116, T.BORDER_SUBTLE)
            self._multiline_text(draw, CX, 148, desc, "md", T.TEXT_PRIMARY,
                                 max_width=176)
            return

        # v2 composition
        self._text_rgba(draw, CX, 64, "DREAM", "xs", T.TEXT_GHOST, alpha=140)
        self._multiline_text(draw, CX, 96, desc, "md", T.TEXT_PRIMARY,
                             max_width=176)
        self._hline(draw, 48, 208, 126, T.BORDER_SUBTLE)

        dom = card.get("dominant_color") or T.ACCENT_MEMORY
        r_, g_, b_ = _hex_to_rgb(dom)
        dim = (r_ // 3, g_ // 3, b_ // 3, 255)
        for s in (card.get("shapes") or [])[:3]:
            # sprite space is 128×128 anchored at (64, 128)
            x = 64 + s.get("x", 64)
            y = 128 + s.get("y", 64) * 0.75   # keep inside the circle
            size = s.get("size", 24)
            half = size / 2
            kind = s.get("kind", "circle")
            if kind == "circle":
                draw.ellipse([x - half, y - half, x + half, y + half],
                             outline=(r_, g_, b_, 255), width=2)
                draw.ellipse([x - half - 4, y - half - 4, x + half + 4, y + half + 4],
                             outline=dim, width=1)
            elif kind == "line":
                draw.line([x - half, y, x + half, y], fill=(r_, g_, b_, 255), width=2)
                draw.line([x - half, y + 4, x + half, y + 4], fill=dim, width=1)
            elif kind == "rect":
                draw.rectangle([x - half, y - half / 2, x + half, y + half / 2],
                               outline=(r_, g_, b_, 255), width=2)
            else:  # triangle
                pts = [(x, y - half), (x + half, y + half), (x - half, y + half)]
                draw.polygon(pts, outline=(r_, g_, b_, 255))

    # ------------------------------------------------------------------
    # The three cards the v1 dispatch forgot (docs/CINEMA_V1_JUDGMENT.md,
    # Wrong #1): their committed goldens were 100% black discs while the
    # device drew them fine. Mirrored 1:1 from halo-lua/display/renderer.lua.
    # ------------------------------------------------------------------

    def _commitment_drift(self, draw, card):
        """CommitmentDriftCard — mirrors draw_commitment_drift (renderer.lua):
        left decay rail, DRIFT DETECTED eyebrow, task, person chain, footer,
        urgency dot (the hold-phase pulse settles to its mid size)."""
        task   = card.get("primary") or card.get("task") or ""
        person = card.get("person") or ""
        detail = card.get("footer") or card.get("detail") or ""
        conf   = card.get("confidence") or 0.5
        decay  = card.get("decay") or 0.0

        urgency = T.PRIVACY_DANGER if decay >= 0.6 else T.WARNING_AMBER

        rail_x, rail_y0, rail_y1 = 44, 68, 192
        self._vbar(draw, rail_x, rail_y0, rail_y1, 1, T.BORDER_SUBTLE, alpha=160)
        live_frac = max(0.0, min(1.0, conf * (1.0 - decay)))
        live_h = int((rail_y1 - rail_y0) * live_frac)
        if live_h > 0:
            self._vbar(draw, rail_x, rail_y1 - live_h, rail_y1, 1, urgency)
        self._dot(draw, rail_x, rail_y0, 2, T.BORDER_SUBTLE, alpha=160)
        self._dot(draw, rail_x, rail_y1, 3, urgency)
        bloom_ring(draw, rail_x, rail_y1, 3, urgency)

        self._text_rgba(draw, CX, 72, "DRIFT DETECTED", "xs", T.MEMORY_TRACE,
                        alpha=200)
        self._multiline_text(draw, CX, CY - 12, task, "md", T.TEXT_PRIMARY,
                             max_width=160)
        if person:
            for i in range(3):
                self._dot(draw, CX - 20 + i * 8, CY + 16, 2, T.BORDER_SUBTLE,
                          alpha=140)
            self._text_rgba(draw, CX, CY + 32, f"→ {person}", "sm",
                            T.MEMORY_TRACE, alpha=220)
        if detail:
            self._text_rgba(draw, CX, 184, detail, "xs", T.TEXT_GHOST, alpha=150)
        self._dot(draw, CX, 200, 3, urgency)

    def _time_scrub_node(self, draw, card):
        """TimeScrubNodeCard — mirrors draw_time_scrub_node (renderer.lua):
        horizontal timeline with node dots, current node enlarged + tick,
        timestamp eyebrow, summary, place, prev/next ghost labels."""
        summary   = card.get("primary") or card.get("summary") or ""
        place     = card.get("place") or ""
        timestamp = card.get("eyebrow") or card.get("timestamp") or ""
        idx       = int(card.get("index") or 1)
        total     = int(card.get("total") or 1)
        prev_lbl  = card.get("prev_label") or ""
        next_lbl  = card.get("next_label") or ""

        bar_y, bar_x0, bar_x1 = 82, 40, 216
        self._hline(draw, bar_x0, bar_x1, bar_y, T.BORDER_SUBTLE, alpha=160)
        for i in range(1, total + 1):
            nx = bar_x0 + (bar_x1 - bar_x0) * (i - 1) // max(total - 1, 1)
            if i == idx:
                self._dot(draw, nx, bar_y, 5, T.MEMORY_TRACE)
                draw.line([(nx, bar_y + 6), (nx, bar_y + 11)],
                          fill=T.to_rgba(T.MEMORY_TRACE, 1.0), width=1)
            else:
                self._dot(draw, nx, bar_y, 2 if i < idx else 1,
                          T.BORDER_SUBTLE, alpha=170)

        crumb = timestamp if timestamp else f"{idx} / {total}"
        self._text_rgba(draw, CX, 66, crumb, "xs", T.TEXT_GHOST, alpha=160)
        self._multiline_text(draw, CX, CY - 4, summary, "md", T.TEXT_PRIMARY,
                             max_width=168)
        if place:
            self._text_rgba(draw, CX, CY + 22, place, "sm", T.MEMORY_TRACE,
                            alpha=210)
        if prev_lbl:
            self._text_rgba(draw, 66, 182, f"◀ {prev_lbl}", "xs", T.TEXT_GHOST,
                            alpha=120)
        if next_lbl:
            self._text_rgba(draw, 190, 182, f"{next_lbl} ▶", "xs", T.TEXT_GHOST,
                            alpha=120)

    def _deviation_alert(self, draw, card):
        """DeviationAlertCard — mirrors draw_deviation_alert (renderer.lua):
        amber attention ring, SOUNDS DIFFERENT eyebrow, prior summary above
        a dashed divider, new summary below, score dot. (The hold-phase
        ripple is device-side motion; the golden shows the settled frame.)"""
        prior = card.get("prior_summary") or card.get("footer") or ""
        new   = card.get("new_summary") or card.get("primary") or ""
        score = float(card.get("score") or 0.0)

        score_col = (T.PRIVACY_DANGER if score >= 0.75
                     else T.WARNING_AMBER if score >= 0.50
                     else T.CONFIDENCE_MED)

        self._circle(draw, CX, CY, 108, 1, T.WARNING_AMBER, alpha=90)
        self._text_rgba(draw, CX, 66, "SOUNDS DIFFERENT", "xs",
                        T.WARNING_AMBER, alpha=220)
        self._hline(draw, 52, 204, 78, T.BORDER_SUBTLE, alpha=140)
        self._text_rgba(draw, CX, 100, prior, "sm", T.TEXT_GHOST, alpha=150)
        x = 80
        while x < 176:
            self._hline(draw, x, min(x + 6, 176), 120, T.BORDER_SUBTLE, alpha=170)
            x += 10
        self._multiline_text(draw, CX, 142, new, "sm", T.TEXT_PRIMARY,
                             max_width=160)
        self._dot(draw, CX, 170, max(2, int(2 + score * 3)), score_col)

    # ------------------------------------------------------------------
    # Meridian Solid — the O3 conversation cards (Veritas / answer-ahead /
    # Oracle reply / Listen!). Same material language as the hero cards:
    # a surface-luma glass pane, gradient separators, bloom on the status
    # cue, hero-class type via the fit ladder, secondary text cooled to a
    # dim twin. Panes are additive (richer, not brighter); text is never in
    # the pane color (solid.md).
    # ------------------------------------------------------------------

    _FIT_ADV = {"hero": 12, "xl": 11, "lg": 10, "md": 8, "sm": 6, "xs": 5}

    def _fit(self, text, max_px=196, ladder=("hero", "xl", "lg", "md")):
        """Largest size in `ladder` whose advance fits `text` in `max_px`
        (mirrors typography.fit_size — drop, never clip the circular panel)."""
        t = str(text or "")
        for s in ladder:
            if len(t) * self._FIT_ADV[s] <= max_px:
                return s
        return ladder[-1]

    def _pane(self, draw, cy=128, r=76, rim=T.BORDER_SUBTLE):
        """The shared soft glass pane + a faint rim — the material bed every
        message card sits on."""
        glass_disc(draw, CX, cy, r, PANE, 4)
        self._circle(draw, CX, cy, r + 4, 1, rim, alpha=90)

    def _oracle_reply(self, draw, card):
        """OracleReplyCard — Oracle's answer/confirmation. Memory-toned pane,
        ORACLE eyebrow with a bloom cue, the reply in hero type (or wrapped)."""
        action = card.get("kind") == "action"
        accent = T.ACCENT_SUCCESS if action else T.ACCENT_MEMORY
        body = str(card.get("primary") or "")
        self._pane(draw, 132, 78)
        # eyebrow with a bloomed status dot
        bloom_ring(draw, CX - 40, 64, 3, accent)
        self._dot(draw, CX - 40, 64, 3, accent)
        self._text_rgba(draw, CX + 6, 64, "ORACLE",
                        "xs", accent, alpha=235)
        grad_line(draw, 60, 82, 196, 82, RAMP_SUCCESS if action else RAMP_MEMORY)
        if len(body) <= 20:
            self._text(draw, CX, 132, body, self._fit(body, 200), T.TEXT_PRIMARY)
        else:
            self._multiline_text(draw, CX, 132, body, "md", T.TEXT_PRIMARY,
                                 max_width=182)

    def _answer_ahead(self, draw, card):
        """AnswerAheadCard — the pre-fetched answer. Quiet memory tone: the
        answer in hero type over a pane, the question cooled beneath it."""
        answer = str(card.get("primary") or "")
        question = str(card.get("detail") or "")
        footer = str(card.get("footer") or "")
        self._pane(draw, 128, 78)
        # dot sits clear of the 25-char eyebrow (its bloom was grazing the first
        # glyph — the golden eyeball pass in #87; mirrors the Lua CX-88 nudge)
        bloom_ring(draw, CX - 88, 70, 3, T.ACCENT_MEMORY)
        self._dot(draw, CX - 88, 70, 3, T.ACCENT_MEMORY)
        self._text_rgba(draw, CX + 4, 70, "ON THE TIP OF YOUR TONGUE",
                        "xs", T.ACCENT_MEMORY, alpha=225)
        grad_line(draw, 52, 88, 204, 88, RAMP_MEMORY)
        self._text(draw, CX, 126, answer, self._fit(answer, 196), T.TEXT_PRIMARY)
        if question:
            self._text_rgba(draw, CX, 166, question, "sm",
                            T.ACCENT_MEMORY_DIM, alpha=235)
        if footer:
            self._text_rgba(draw, CX, 198, footer, "xs", T.TEXT_GHOST, alpha=170)

    def _scholar(self, draw, card):
        """ScholarCard / GlanceChoiceCard — the World-lens material family:
        a memory-toned pane, an eyebrow over a gradient separator, the primary
        (answer / gist / summary / the chooser) in hero type, and up to a few
        items stacked beneath (form fields, key points, or the chooser's
        options). Honest 'connect a Brain' state when unavailable."""
        eyebrow = str(card.get("eyebrow") or "")
        primary = str(card.get("primary") or "")
        detail = str(card.get("detail") or "")
        items = card.get("items") or []
        unavailable = bool(card.get("unavailable"))
        accent = T.TEXT_GHOST if unavailable else T.ACCENT_MEMORY
        self._pane(draw, 128, 78)
        if eyebrow:
            self._text_rgba(draw, CX, 60, eyebrow, "xs", accent, alpha=230)
            grad_line(draw, 44, 76, 212, 76,
                      RAMP_MEMORY if not unavailable else RAMP_MEMORY)
        if primary:
            self._text(draw, CX, 104, primary, self._fit(primary, 200), T.TEXT_PRIMARY)
        # stacked items (form fields / key points / chooser options)
        y = 138 if primary else 108
        for it in items[:4]:
            self._text_rgba(draw, CX, y, str(it), "sm", T.TEXT_SECONDARY, alpha=235)
            y += 22
        if detail and not primary:
            self._text_rgba(draw, CX, 150, detail, "sm", T.TEXT_GHOST, alpha=200)

    def _fact_check(self, draw, card):
        """FactCheckCard — Veritas verdict, in the Truth-Lens material family.
        A bloomed status ring in the verdict hue, the claim in hero type over a
        pane, the basis cooled to the verdict's dim twin, the fused footer in
        ghost."""
        verdict = card.get("verdict") or ""
        _dim = {
            "supported":          T.ACCENT_SUCCESS_DIM,
            "disputed":           T.WARNING_AMBER_DIM,
            "self_contradiction": T.ACCENT_ATTENTION_DIM,
            "unverified":         T.BORDER_SUBTLE,
        }
        color = {
            "supported":          T.ACCENT_SUCCESS,
            "disputed":           T.WARNING_AMBER,
            "self_contradiction": T.ACCENT_ATTENTION,
            "unverified":         T.TEXT_GHOST_STATIC,
        }.get(verdict, T.TEXT_GHOST_STATIC)
        dim = _dim.get(verdict, T.BORDER_SUBTLE)
        eyebrow = str(card.get("eyebrow") or "")
        claim = str(card.get("primary") or "")
        basis = str(card.get("detail") or "")
        footer = str(card.get("footer") or "")

        self._pane(draw, 134, 74)
        # the status cue: a bloomed ring in the verdict hue
        bloom_ring(draw, CX, 54, 9, color)
        self._circle(draw, CX, 54, 9, 2, color, alpha=255)
        self._text_rgba(draw, CX, 82, eyebrow, "xs", color, alpha=240)
        grad_line(draw, 44, 96, 212, 96,
                  (color, dim, T.BORDER_SUBTLE))
        if len(claim) <= 22:
            self._text(draw, CX, 130, claim, self._fit(claim, 200), T.TEXT_PRIMARY)
        else:
            self._multiline_text(draw, CX, 128, claim, "md", T.TEXT_PRIMARY,
                                 max_width=188)
        if basis:
            self._text_rgba(draw, CX, 170, basis, "sm", dim, alpha=235)
        if footer:
            self._text_rgba(draw, CX, 200, footer, "xs", T.TEXT_GHOST, alpha=170)

    def _hark(self, draw, card):
        """HarkCard — Oracle's "Listen!" A bloomed ring pierces the eye, the one
        thing worth hearing in hero type, the trailing detail cooled. Urgent
        (watch-out) burns amber, a plain listen stays memory-teal."""
        urgent = card.get("importance") == "urgent"
        color = T.WARNING_AMBER if urgent else T.ACCENT_MEMORY
        dim = T.WARNING_AMBER_DIM if urgent else T.ACCENT_MEMORY_DIM
        clue = str(card.get("primary") or "")
        detail = str(card.get("detail") or "")
        self._pane(draw, 134, 74)
        bloom_ring(draw, CX, 58, 12, color)
        self._circle(draw, CX, 58, 12, 2, color, alpha=255)
        self._dot(draw, CX, 58, 3, color)
        self._text_rgba(draw, CX, 84, "LISTEN", "xs", color, alpha=245)
        grad_line(draw, 48, 98, 208, 98, (color, dim, T.BORDER_SUBTLE))
        if len(clue) <= 22:
            self._text(draw, CX, 132, clue, self._fit(clue, 200), T.TEXT_PRIMARY)
        else:
            self._multiline_text(draw, CX, 130, clue, "md", T.TEXT_PRIMARY,
                                 max_width=188)
        if detail:
            self._text_rgba(draw, CX, 172, detail, "sm", dim, alpha=230)

    def _layout_card(self, draw, card):
        """Generic renderer for the layout-driven cards (ForgetLast /
        PrivateZone / ConsentRequired / LiveCaption): the payload
        self-describes rows via card['layout'] (built in cards.py).
        Mirrors halo-lua/display/renderer.lua draw_layout_card."""
        layout = card.get("layout") or {}

        sep = layout.get("separator")
        if sep:
            self._hline(draw, sep.get("x1", 48), sep.get("x2", 208),
                        sep.get("y", 80), T.BORDER_SUBTLE, alpha=170)

        glyph = layout.get("shield") or layout.get("lock")
        if glyph:
            import math as _math
            gx, gy = glyph.get("x", CX), glyph.get("y", 44)
            gr = glyph.get("r", 10)
            color = glyph.get("color", T.PRIVACY_CAUTION)
            pts = []
            for i in range(6):
                a = _math.radians(60 * i - 30)
                pts.append((gx + gr * _math.cos(a), gy + gr * _math.sin(a)))
            draw.polygon(pts, outline=T.to_rgba(color, 1.0))
            if layout.get("shield"):
                bh = max(3, int(gr * 0.5))
                bw = max(2, int(gr * 0.18))
                gap = max(2, int(gr * 0.15))
                draw.rectangle([gx - gap - bw, gy - bh / 2, gx - gap, gy + bh / 2],
                               fill=T.to_rgba(color, 1.0))
                draw.rectangle([gx + gap, gy - bh / 2, gx + gap + bw, gy + bh / 2],
                               fill=T.to_rgba(color, 1.0))

        def row(name, text, fallback_y, fallback_color, size="sm"):
            if not text:
                return
            spec = layout.get(name) or {}
            self._text(draw, spec.get("x", CX), spec.get("y", fallback_y),
                       text, spec.get("size", size),
                       spec.get("color", fallback_color))

        row("eyebrow", card.get("eyebrow"), 64, T.TEXT_SECONDARY, "xs")
        row("primary", card.get("primary"), 112, T.TEXT_PRIMARY, "md")
        row("detail",  card.get("detail"),  144, T.TEXT_SECONDARY)
        row("footer",  card.get("footer"),  168, T.TEXT_GHOST, "xs")

        conf = card.get("confidence")
        if conf is not None and layout.get("conf_dot"):
            d = layout["conf_dot"]
            self._dot(draw, d.get("x", CX), d.get("y", 185), d.get("r", 3),
                      T.conf_color(conf))

    def _low_confidence(self, draw, card):
        draw_point_cloud_text(
            draw, "Not sure", CX, CY - 14,
            font_size=20, density=0.15,
            color=T.TEXT_SECONDARY, alpha=200
        )
        draw_point_cloud_text(
            draw, "Try rephrasing", CX, CY + 16,
            font_size=11, density=0.25,
            color=T.TEXT_GHOST, alpha=160
        )
        self._dot(draw, 107, 180, 2, T.TEXT_GHOST, alpha=80)
        self._dot(draw, 128, 184, 2, T.TEXT_GHOST, alpha=60)
        self._dot(draw, 149, 180, 2, T.TEXT_GHOST, alpha=80)


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------
# The Cinema refactor moved rendering into CardRenderer and silently dropped
# the module-level render() that the legacy demo scripts were built on.
# Restore it as a thin delegate over one shared renderer.

_default_renderer: "CardRenderer | None" = None


def render(card: dict) -> Image.Image:
    """Render one HUD card dict to a 256x256 image."""
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = CardRenderer()
    return _default_renderer.render(card)
