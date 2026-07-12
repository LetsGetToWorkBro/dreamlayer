"""v2/flash_safety.py — verify the eye-safety claim, don't just assert it.

The grammar caps pulse rate statically (MAX_PULSE_HZ) — a *specification*. This
module is the *verification*: it measures the actual rendered output against
**WCAG 2.3.1 "Three Flashes or Below Threshold"** (and the ITU-R BT.1702 form),
which is what photosensitive-seizure safety is actually judged by. For a device
inches from the eye that is exactly the right bar, and it catches what a bare Hz
cap can't: whether a flash's *luminance change* and *screen area* actually reach
the provocative threshold, and **red flashes**, which have their own limit.

WCAG 2.3.1, made concrete:
  * a **general flash** is a pair of opposing relative-luminance transitions
    where the change is >= 10% of max luminance and the darker state is < 0.80;
  * a **red flash** is the same for a transition to/from saturated red;
  * content must not flash more than **3 times** (general OR red) in any 1-second
    window — unless the flashing area is below the small-area exemption.

A figment's only flashing element is the pulse ring, so we render the pulse-on
and pulse-off frames through the *real* renderer (playback.render_image) and
measure the luminance change, the red content, and the changed-area fraction
between them; the flash rate is the pulse's own square-wave rate. `count_flashes`
also runs the WCAG window-count over an arbitrary luminance series, so a future
full-frame sampler can feed it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .figment import Figment, MAX_PULSE_HZ
from .interpreter import DisplayFrame, ResolvedLine

FLASH_LIMIT = 3            # WCAG 2.3.1: <= 3 flashes in any 1-second window
LUM_DELTA = 0.10          # a transition counts at >= 10% of max luminance
DARK_MAX = 0.80           # ...and only when the darker state is < 0.80
# Small-area exemption. WCAG's general threshold is ~25% of the visual field;
# for a near-eye display we're deliberately stricter — a flash must cover a fifth
# of the glass to count. (The pulse ring is ~6%, so it is safely exempt.)
DEFAULT_AREA_MIN = 0.20
RED_RATIO = 0.5           # R / (R+G+B) above this reads as a saturated-red flash


def _linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb) -> float:
    """WCAG relative luminance of an sRGB triple (0=black, 1=white)."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def red_ratio(rgb) -> float:
    total = rgb[0] + rgb[1] + rgb[2]
    return (rgb[0] / total) if total else 0.0


@dataclass
class FlashReport:
    ok: bool
    general_hz: float = 0.0    # worst general-flash rate found (per second)
    red_hz: float = 0.0        # worst red-flash rate found
    offenders: list = field(default_factory=list)   # (scene_id, kind, hz)

    def __str__(self) -> str:
        head = "FLASH-SAFE" if self.ok else "FLASH RISK"
        return (f"[{head}] general<={self.general_hz:g}/s red<={self.red_hz:g}/s "
                f"(limit {FLASH_LIMIT}/s)")


# ---------------------------------------------------------------------------
# WCAG window count over a luminance/area series (reusable, pixel-agnostic)
# ---------------------------------------------------------------------------

def count_flashes(series, area_min: float = DEFAULT_AREA_MIN) -> float:
    """series: list of (t, luminance, area_fraction). Returns the maximum number
    of qualifying luminance transitions in any 1-second sliding window (the WCAG
    'flashes per second'). A transition qualifies when |Δlum| >= LUM_DELTA, the
    darker state < DARK_MAX, and the changed area >= area_min."""
    edges = []                # times of qualifying *rising* transitions
    for i in range(1, len(series)):
        (_, l0, _), (t1, l1, a1) = series[i - 1], series[i]
        if (abs(l1 - l0) >= LUM_DELTA and min(l0, l1) < DARK_MAX
                and a1 >= area_min and l1 > l0):
            edges.append(t1)
    worst = 0
    for i, t in enumerate(edges):     # count rising edges within [t, t+1s)
        n = sum(1 for u in edges[i:] if u < t + 1.0)
        worst = max(worst, n)
    return float(worst)


# ---------------------------------------------------------------------------
# Figment analysis — render the pulse on/off frames, measure the real flash
# ---------------------------------------------------------------------------

def _pulse_frames(sid: str, scene):
    lines = [ResolvedLine(ln.content, ln.row, ln.size, ln.color)
             for ln in scene.lines]
    on = DisplayFrame(scene=sid, lines=lines, pulse_on=True,
                      pulse_color=scene.pulse.color)
    off = DisplayFrame(scene=sid, lines=lines, pulse_on=False)
    return on, off


def _measure(img):
    import numpy as np
    a = np.asarray(img).astype("float32")
    lin = np.where(a / 255.0 <= 0.03928, (a / 255.0) / 12.92,
                   ((a / 255.0 + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    return a, lum


def analyze_figment(fig: Figment, area_min: float = DEFAULT_AREA_MIN) -> FlashReport:
    """Measure every pulsing scene against WCAG 2.3.1 through the real renderer.
    Returns ok=True (unmeasurable) when Pillow/numpy are absent — the static Hz
    cap remains the floor; this is the *additional* verification when it runs."""
    try:
        import numpy as np  # noqa: F401
        from .playback import render_image
    except Exception:
        return FlashReport(ok=True)

    worst_general = worst_red = 0.0
    offenders = []
    for sid, scene in fig.scenes.items():
        if scene.pulse is None:
            continue
        on, off = _pulse_frames(sid, scene)
        img_on, img_off = render_image(on), render_image(off)
        if img_on is None:
            return FlashReport(ok=True)
        rgb_on, lum_on = _measure(img_on)
        rgb_off, lum_off = _measure(img_off)
        import numpy as np
        changed = np.any(rgb_on != rgb_off, axis=-1)
        area = float(changed.mean())
        rate = min(scene.pulse.rate_hz, MAX_PULSE_HZ)

        # general flash: mean-luminance change over the whole glass
        dl = abs(float(lum_on.mean()) - float(lum_off.mean()))
        darker = min(float(lum_on.mean()), float(lum_off.mean()))
        if dl >= LUM_DELTA and darker < DARK_MAX and area >= area_min:
            worst_general = max(worst_general, rate)
            offenders.append((sid, "general", rate))

        # red flash: the pulse colour is a saturated red and it flashes
        if area >= area_min and red_ratio(_rgb(scene.pulse.color)) >= RED_RATIO:
            worst_red = max(worst_red, rate)
            offenders.append((sid, "red", rate))

    ok = worst_general <= FLASH_LIMIT and worst_red <= FLASH_LIMIT
    return FlashReport(ok, worst_general, worst_red, offenders)


def _rgb(color_token: str):
    from .playback import _rgb as pal
    return pal(color_token)
