"""Dev / API+SDK story visuals for DreamLayer, built from the REAL documented
surface (docs/SDK.md) and the REAL renderer. Produces:
  dev_terminal.png  - the 5-minute plugin flow in a macOS terminal
  dev_code.png      - plugin.py (SDK surface) + plugin.json manifest, side by side
  dev_preview.png   - `dreamlayer plugins preview` -> the exact 256px device output
  dev_hero.png      - the three, composed as a poster
Also renders terminal 'typing' frames for a short animated demo.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices as D
from dreamlayer.hud.renderer import CardRenderer, CX, CY
from dreamlayer.hud import themes as T

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
(OUT/"term").mkdir(exist_ok=True)
TEAL=(44,199,164); INK=(226,238,235); DIM=(129,156,151); GREEN=(86,211,100); GOLD=(232,193,90); CORAL=(224,107,82); GREY=(120,140,140)

def mono(px, bold=False):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]:
        try: return ImageFont.truetype(p, px)
        except: pass
    return ImageFont.load_default()

def win_chrome(W, H, title):
    im = Image.new("RGB", (W, H), (13, 16, 19)); d = ImageDraw.Draw(im)
    bar = 44
    d.rectangle([0, 0, W, bar], fill=(30, 35, 40))
    d.line([(0, bar), (W, bar)], fill=(16, 20, 24))
    for i, cc in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([16+i*20-6, bar//2-6, 16+i*20+6, bar//2+6], fill=cc)
    d.text((W//2, bar//2), title, font=mono(15), fill=(178, 196, 200), anchor="mm")
    return im, d, bar

# ---- the real CLI flow (from docs/SDK.md), as a colored terminal transcript ----
# each line: (indent, [(text,color),...])
def L(*spans): return spans
PROMPT=[("➜ ", GREEN), ("hello-lens ", TEAL), ("$ ", DIM)]
TERM = [
  ("prompt", [("$ ", DIM), ("dreamlayer plugins new hello-lens", INK)]),
  ("out",    [("  scaffolding API v2 plugin  ", DIM), ("✓", GREEN)]),
  ("out",    [("  hello-lens/plugin.py  ·  plugin.json  ·  test_plugin.py", GREY)]),
  ("gap", []),
  ("prompt", [("$ ", DIM), ("dreamlayer plugins validate .", INK)]),
  ("out",    [("  integrity  ", DIM), ("✓", GREEN), ("   capability scan  ", DIM), ("✓", GREEN), ("   smoke test  ", DIM), ("✓", GREEN)]),
  ("out",    [("  requires: ", DIM), ("cards", GOLD), ("   ·   min_sdk ", DIM), ("1.0.0", INK), ("   ·   ", DIM), ("safe to run", GREEN)]),
  ("gap", []),
  ("prompt", [("$ ", DIM), ("dreamlayer plugins preview .", INK)]),
  ("out",    [("  rendered the device path in software  →  ", DIM), ("hello-lens-preview.png", TEAL), ("  (256×256)", GREY)]),
  ("gap", []),
  ("prompt", [("$ ", DIM), ("dreamlayer plugins pack .", INK)]),
  ("out",    [("  signed  →  ", DIM), ("hello-lens-0.1.0.json", TEAL)]),
  ("gap", []),
  ("prompt", [("$ ", DIM), ("dreamlayer plugins install .  --brain http://localhost:8765", INK)]),
  ("out",    [("  Brain re-ran the gate  ", DIM), ("✓", GREEN), ("   installed  ", DIM), ("·  live on the glasses", INK)]),
]

def draw_terminal(reveal=None):
    W, H = 1180, 720
    im, d, bar = win_chrome(W, H, "hello-lens — dreamlayer plugins")
    f = mono(19); x0 = 34; y = bar + 26; lh = 33
    n = len(TERM) if reveal is None else reveal
    for i, (kind, spans) in enumerate(TERM[:n]):
        if kind == "gap": y += lh//2; continue
        x = x0
        for text, col in spans:
            d.text((x, y), text, font=f, fill=col); x += d.textlength(text, font=f)
        y += lh
    # blinking cursor block at end
    d.rectangle([x0 if not TERM else x, y-lh+4, (x0 if not TERM else x)+11, y-6], fill=TEAL)
    return im

# ---- the code: plugin.py + plugin.json (verbatim from the SDK guide) ----
PLUGIN_PY = [
 ("from ", CORAL), ("dreamlayer.sdk ", INK), ("import ", CORAL), ("make_plugin\n\n", INK),
 ("def ", CORAL), ("draw_hello", TEAL), ("(draw, card):\n", INK),
 ("    ", INK), ("# paint a 256×256 additive HUD card\n", GREY),
 ("    draw.text((CX, CY), card[", INK), ('"text"', GOLD), ("], anchor=", INK), ('"mm"', GOLD), (")\n\n", INK),
 ("def ", CORAL), ("register", TEAL), ("(ctx):\n", INK),
 ("    ctx.add_card_renderer(", INK), ('"HelloCard"', GOLD), (", draw_hello)\n\n", INK),
 ("def ", CORAL), ("plugin", TEAL), ("():\n", INK),
 ("    ", INK), ("return ", CORAL), ("make_plugin(", INK), ('"hello-lens"', GOLD),
 (", register, requires=(", INK), ('"cards"', GOLD), (",))\n", INK),
]
PLUGIN_JSON = [
 ("{\n", INK),
 ('  "name"', TEAL), (": ", INK), ('"hello-lens"', GOLD), (",\n", INK),
 ('  "version"', TEAL), (": ", INK), ('"0.1.0"', GOLD), (",\n", INK),
 ('  "entry"', TEAL), (": ", INK), ('"plugin:plugin"', GOLD), (",\n", INK),
 ('  "min_sdk"', TEAL), (": ", INK), ('"1.0.0"', GOLD), (",\n", INK),
 ('  "requires"', TEAL), (": [", INK), ('"cards"', GOLD), ("],\n", INK),
 ('  "preview_card"', TEAL), (": {", INK), ('"type"', GOLD), (": ", INK), ('"HelloCard"', GOLD), ("},\n", INK),
 ('  "description"', TEAL), (": ", INK), ('"A hello card on the HUD."', GOLD), ("\n", INK),
 ("}\n", INK),
]
def draw_code_col(d, tokens, x0, y0, f, lh):
    x, y = x0, y0
    for text, col in tokens:
        for ch in text:
            if ch == "\n": x = x0; y += lh; continue
            d.text((x, y), ch, font=f, fill=col); x += d.textlength(ch, font=f)
    return y

def draw_code():
    W, H = 1180, 560
    im, d, bar = win_chrome(W, H, "hello-lens — your first plugin")
    f = mono(18); lh = 27
    colw = W//2
    d.line([(colw, bar), (colw, H)], fill=(24, 30, 34))
    d.text((26, bar+14), "plugin.py", font=mono(14), fill=DIM)
    d.text((colw+26, bar+14), "plugin.json", font=mono(14), fill=DIM)
    draw_code_col(d, PLUGIN_PY, 26, bar+48, f, lh)
    draw_code_col(d, PLUGIN_JSON, colw+26, bar+48, f, lh)
    return im

# ---- the real device output: render a genuine card via the renderer ----
def draw_hello(draw, card):
    R._text(draw, CX, 52, "HELLO-LENS", "sm", T.ACCENT_MEMORY)
    R._hline(draw, 60, 196, 70, T.BORDER_SUBTLE, alpha=150)
    R._arc(draw, CX, 118, 30, 0, 360, 3, T.ACCENT_MEMORY, alpha=200)
    R._text(draw, CX, 118, card.get("text", "hi"), "xl", T.TEXT_PRIMARY)
    R._multiline_text(draw, CX, 168, "your card, on the glass", "md", T.TEXT_SECONDARY, max_width=200)
    R._text(draw, CX, 206, "256 × 256 · additive", "sm", T.TEXT_GHOST)
R = CardRenderer(); R.register("HelloCard", draw_hello)

def device_preview(S=560):
    face = R.render({"type": "HelloCard", "text": "hi"}).convert("RGB")
    ov = D.__dict__  # not used; compose via emissive path
    import numpy as np
    from dreamlayer.demo.scene import Beat, _compose_frame
    import gen
    o = gen._overlay_from_image(face, int(S*0.7))
    b = Beat({"type":"x"}, 0.0, 1.0, anchor=(0.5,0.5), width=0.7, fade=0.0, glow=True)
    disc,_,_ = gen._lens_maps(S); disc_a=(np.asarray(disc,np.float32)/255.0)[...,None]
    yy,xx=np.mgrid[0:S,0:S].astype(np.float32); r=np.hypot(xx-S/2,yy-S/2)
    bez=np.clip(1.0-np.abs(r-(S/2-3))/2.0,0,1)[...,None]*np.array([26,42,46],np.float32)
    rgb=np.asarray(_compose_frame(np.zeros((S,S,3),np.float32),[(b,o)],0.5,(S,S),1.0),np.float32)
    return Image.fromarray(np.clip(rgb*disc_a+bez,0,255).astype(np.uint8),"RGB")

if __name__ == "__main__":
    draw_terminal().save(OUT/"dev_terminal.png")
    draw_code().save(OUT/"dev_code.png")
    device_preview().save(OUT/"dev_preview_disc.png")
    # animated terminal: reveal lines progressively
    steps = list(range(1, len(TERM)+1))
    fi = 0
    for s in steps:
        img = draw_terminal(reveal=s)
        # hold longer on prompt lines
        holds = 10 if TERM[s-1][0]=="prompt" else 6
        for _ in range(holds):
            img.save(OUT/"term"/f"f_{fi:04d}.png"); fi += 1
    for _ in range(18):  # final hold
        draw_terminal().save(OUT/"term"/f"f_{fi:04d}.png"); fi += 1
    print("dev visuals done; term frames", fi)
