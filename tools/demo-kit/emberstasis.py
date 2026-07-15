"""AAA card faces for the reworked Ember (4 spaced-repetition states) and the new
Stasis lens, drawn through the real renderer's helpers. A flame that grows across
the Ember arc (dim ember -> flare -> steady -> consolidated glow) in EMBER_GLOW;
a ribbon/bookmark holding a verbatim, dash-ended thought for Stasis. Renders 256px
faces; gen.render_lens applies the glass treatment.
"""
from __future__ import annotations
import sys, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
from PIL import Image, ImageDraw
from dreamlayer.hud.renderer import CardRenderer, CX, CY, SIZE
from dreamlayer.hud import themes as T

R = CardRenderer()
AMBER, AMBER_DIM = T.EMBER_GLOW, T.EMBER_GLOW_DIM
TEAL = T.ACCENT_MEMORY

def _rgba(hx, a=1.0): return T.to_rgba(hx, a)

def flame(draw, cx, cy, w, h, color, a=1.0):
    pts = [(cx, cy-h), (cx+0.55*w, cy-0.12*h), (cx+0.48*w, cy+0.36*h),
           (cx+0.2*w, cy+0.6*h), (cx, cy+0.62*h), (cx-0.2*w, cy+0.6*h),
           (cx-0.48*w, cy+0.36*h), (cx-0.55*w, cy-0.12*h)]
    draw.polygon(pts, fill=_rgba(color, a))

def flame_stack(draw, cx, cy, w, h, glow=False):
    if glow:
        flame(draw, cx, cy+2, w*1.5, h*1.5, AMBER, 0.18)   # outer bloom
    flame(draw, cx, cy, w, h, AMBER, 0.95)                 # body
    flame(draw, cx, cy+h*0.10, w*0.5, h*0.55, 0xFFE6B0, 0.95)  # bright core

def sparks(draw, cx, cy, color):
    for dx, dy, r in [(-14, 6, 2), (0, 10, 2.5), (13, 5, 2), (-6, 14, 1.6), (7, 15, 1.6)]:
        R._dot(draw, cx+dx, cy+dy, r, color)

def reps_dots(draw, cx, y, n, color, on=None):
    on = n if on is None else on
    gap = 9; total = (n-1)*gap; x0 = cx - total//2
    for i in range(n):
        R._dot(draw, x0+i*gap, y, 2.4 if i < on else 2, color if i < on else T.BORDER_SUBTLE)

def ribbon(draw, cx, cy, w, h, color, a=1.0):
    pts = [(cx-w, cy-h), (cx-w, cy+h), (cx, cy+h*0.42), (cx+w, cy+h), (cx+w, cy-h)]
    draw.line(pts + [pts[0]], fill=_rgba(color, a), width=3, joint="curve")

# ---- Ember: the four states of tending a memory ----------------------------
def draw_prompt(draw, card):
    R._text(draw, CX, 50, "EMBER", "sm", AMBER)
    R._hline(draw, 60, 196, 68, T.BORDER_SUBTLE, alpha=150)
    flame(draw, CX, 104, 20, 26, AMBER_DIM, 0.9); sparks(draw, CX, 108, AMBER_DIM)
    R._multiline_text(draw, CX, 156, card["cue"], "md", T.TEXT_PRIMARY, max_width=196)
    R._text(draw, CX, 200, card["place"], "sm", T.TEXT_GHOST)

def draw_flare(draw, card):
    R._text(draw, CX, 50, "EMBER", "sm", AMBER)
    flame_stack(draw, CX, 108, 30, 40, glow=True)
    R._text(draw, CX, 168, card["primary"], "xl", AMBER)   # "It's yours."
    R._text(draw, CX, 200, card["footer"], "sm", T.TEXT_GHOST)  # next in ~12d

def draw_reveal(draw, card):
    R._text(draw, CX, 50, card["eyebrow"], "sm", AMBER_DIM)   # the cue (dim)
    R._hline(draw, 60, 196, 68, T.BORDER_SUBTLE, alpha=150)
    flame(draw, CX, 100, 18, 24, AMBER, 0.92)
    flame(draw, CX, 101, 9, 13, 0xFFE6B0, 0.9)
    R._multiline_text(draw, CX, 150, card["answer"], "md", T.TEXT_PRIMARY, max_width=200)
    R._text(draw, CX, 200, "it will come back around", "sm", T.TEXT_GHOST)

def draw_graduated(draw, card):
    R._text(draw, CX, 50, card["eyebrow"], "sm", AMBER)      # the cue
    R._hline(draw, 60, 196, 68, T.BORDER_SUBTLE, alpha=150)
    R._arc(draw, CX, 104, 22, 0, 360, 3, AMBER, alpha=210)   # consolidated ring
    flame(draw, CX, 108, 12, 16, AMBER, 0.95)
    reps_dots(draw, CX, 132, card["reps"], AMBER)
    R._multiline_text(draw, CX, 162, card["primary"], "md", AMBER, max_width=200)
    R._text(draw, CX, 202, card["footer"], "sm", T.TEXT_GHOST)  # kept 94d · recalled ×7

# ---- Stasis: the held moment, verbatim -------------------------------------
def draw_stasis(draw, card):
    R._text(draw, CX, 50, "STASIS", "sm", TEAL)
    R._hline(draw, 60, 196, 68, T.BORDER_SUBTLE, alpha=150)
    R._arc(draw, CX, 106, 26, 0, 360, 2, TEAL, alpha=90)     # the soft offer glow
    ribbon(draw, CX, 100, 12, 20, TEAL)
    R._multiline_text(draw, CX, 156, card["primary"], "md", T.TEXT_PRIMARY, max_width=200)
    R._text(draw, CX, 202, card["footer"], "sm", T.TEXT_GHOST)

R.register("EmberPromptCard", draw_prompt)
R.register("EmberFlareCard", draw_flare)
R.register("EmberRevealCard", draw_reveal)
R.register("EmberGraduatedCard", draw_graduated)
R.register("StasisCard", draw_stasis)

def build():
    from dreamlayer.hud.cards import ALL_SAMPLES
    L = []
    for k in ("ember_prompt", "ember_flare", "ember_reveal", "ember_graduated"):
        L.append((k, "park" if k != "ember_flare" else "world", dict(ALL_SAMPLES[k])))
    L.append(("stasis", "answer", {
        "type": "StasisCard",
        "primary": "…and the torque spikes right when—",
        "footer": "held 4 min · tilt to resume"}))
    return L

if __name__ == "__main__":
    OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
    items = build()
    for key, env, card in items:
        R.render(card).convert("RGB").save(OUT / f"{key}.png")
    S = 256; sh = Image.new("RGB", (S*len(items), S), (8, 8, 10)); d = ImageDraw.Draw(sh)
    for i, (key, env, card) in enumerate(items):
        im = Image.open(OUT/f"{key}.png").convert("RGB"); sh.paste(im, (i*S, 0))
        d.text((i*S+4, 4), key, fill=(150, 200, 210))
    sh.save(OUT/"_sheet.png"); print("rendered", len(items))
