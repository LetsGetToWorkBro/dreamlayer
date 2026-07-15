"""Author representative HUD cards for the Innovation-pass lenses, drawn through
the REAL DreamLayer renderer (dedicated draws / generic rows) with a few faithful
custom draws that reuse the renderer's own text/arc/dot helpers. Outputs 256px
card PNGs; the glass-lens pass (gen.render_lens) turns them into gitbook webp.
"""
from __future__ import annotations
import sys, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
from PIL import Image
from dreamlayer.hud.renderer import CardRenderer, _font, CX, CY, SIZE, _ellipsize
from dreamlayer.hud import themes as T
from dreamlayer.hud import cards as C

R = CardRenderer()

# ---- custom draws (reuse R._text / R._arc / R._dot / R._hline) --------------
def _swatch(draw, x, y, w, h, rgb):
    draw.rectangle([x, y, x + w, y + h], fill=rgb)

def draw_thread(draw, card):
    sw = card["swatches"]
    R._text(draw, CX, 66, "THREAD", "sm", T.ACCENT_MEMORY)
    R._hline(draw, 60, 196, 82, T.BORDER_SUBTLE, alpha=160)
    n = len(sw); gap = 6; bw = 26; total = n*bw + (n-1)*gap
    x0 = CX - total//2
    for i, hx in enumerate(sw):
        rgb = (hx >> 16 & 255, hx >> 8 & 255, hx & 255)
        _swatch(draw, x0 + i*(bw+gap), 100, bw, 44, rgb)
    R._text(draw, CX, 164, card["primary"], "md", T.TEXT_PRIMARY)
    R._text(draw, CX, 186, card["footer"], "xs", T.TEXT_GHOST)

def draw_candor(draw, card):
    R._text(draw, CX, 60, "CANDOR", "sm", T.ACCENT_MEMORY)
    # a calm pace arc (how fast you were talking) — never alarming
    R._arc(draw, CX, 108, 30, 150, 150+card["pace"]*2.4, 4, T.ACCENT_MEMORY, alpha=230)
    R._arc(draw, CX, 108, 30, 150, 390, 4, T.BORDER_SUBTLE, alpha=120)
    R._text(draw, CX, 108, card["primary"], "lg", T.TEXT_PRIMARY)
    R._text(draw, CX, 150, card["detail"], "sm", T.TEXT_SECONDARY)
    for i, ln in enumerate(card["lines"]):
        R._text(draw, CX, 172 + i*20, ln, "xs", T.TEXT_GHOST)

def draw_waypath(draw, card):
    R._text(draw, CX, 60, "WAYPATH", "sm", T.ACCENT_MEMORY)
    # a faint ring + one bright dot at a bearing — "that way", minimal by design
    ring_r = 46
    R._arc(draw, CX, 120, ring_r, 0, 360, 2, T.BORDER_SUBTLE, alpha=150)
    a = math.radians(card["bearing"] - 90)
    dx, dy = CX + ring_r*math.cos(a), 120 + ring_r*math.sin(a)
    R._dot(draw, dx, dy, 6, T.ACCENT_MEMORY)
    R._dot(draw, CX, 120, 2, T.TEXT_GHOST)
    R._text(draw, CX, 178, card["primary"], "lg", T.TEXT_PRIMARY)
    R._text(draw, CX, 200, card["footer"], "xs", T.TEXT_GHOST)

def draw_sous(draw, card):
    R._text(draw, CX, 58, "SOUS", "sm", T.ACCENT_MEMORY)
    R._hline(draw, 56, 200, 74, T.BORDER_SUBTLE, alpha=150)
    for i, (label, tleft, frac) in enumerate(card["timers"]):
        y = 96 + i*34
        R._text(draw, 74, y, label, "md", T.TEXT_PRIMARY, anchor="lm")
        R._text(draw, 182, y, tleft, "md", T.CONFIDENCE_MED if frac > 0.25 else T.WARNING_AMBER, anchor="rm")
        draw.rectangle([74, y+12, 182, y+15], fill=T.to_rgba(T.BORDER_SUBTLE, 1.0))
        draw.rectangle([74, y+12, 74+int(108*frac), y+15],
                       fill=T.to_rgba(T.ACCENT_MEMORY if frac > 0.25 else T.WARNING_AMBER, 1.0))
    R._text(draw, CX, 196, card["footer"], "xs", T.TEXT_GHOST)

def draw_session(draw, card):
    R._text(draw, CX, 58, "SESSION", "sm", T.ACCENT_MEMORY)
    R._text(draw, CX, 104, card["primary"], "hero", T.TEXT_PRIMARY)
    # metronome pulse dots
    for i in range(4):
        on = (i == card["beat"])
        R._dot(draw, CX-33+i*22, 138, 4 if on else 3,
               T.ACCENT_MEMORY if on else T.BORDER_SUBTLE)
    R._text(draw, CX, 170, card["detail"], "sm", T.TEXT_SECONDARY)
    R._text(draw, CX, 192, card["footer"], "xs", T.TEXT_GHOST)

R.register("ThreadCard", draw_thread)
R.register("CandorCard", draw_candor)
R.register("WaypathLensCard", draw_waypath)
R.register("SousCard", draw_sous)
R.register("SessionCard", draw_session)

# ---- the new-lens catalog: (key, env, card) ---------------------------------
def build():
    L = []
    # reuse real constructors (same card type, lens-specific content)
    L.append(("retrace", "alt", C.object_recall(
        {"object": "Your bike", "place": "north rack",
         "detail": "you locked it", "last_seen": "north rack · 8:12am",
         "confidence": 0.9})))
    doc = C.scholar(mode="answer",
                    primary="Tinguely, 1960",
                    detail="kinetic sculpture — motor-driven steel")
    doc["eyebrow"] = "DOCENT"
    if "layout" in doc and "eyebrow" in doc["layout"]:
        pass
    L.append(("docent", "answer", doc))
    L.append(("rosetta_live", "face", C.live_caption_card(
        original="¿Nos vemos el jueves?", translation="See you Thursday?",
        src_lang="es", dst_lang="en")))
    # generic-rows cards (unknown type → clean eyebrow/primary/detail/footer)
    L.append(("ember", "park", {
        "type": "EmberCard",
        "eyebrow": "A YEAR AGO TODAY",
        "primary": "First snow",
        "detail": "on this corner — you stopped to watch",
        "footer": "a memory you chose to keep"}))
    L.append(("kiln", "alt", {
        "type": "KilnCard",
        "eyebrow": "KILN · OFFLINE",
        "primary": "Cone 6 — 8h left",
        "detail": "bisque · radios off",
        "footer": "firing log kept"}))
    # custom-draw cards
    L.append(("candor", "face", {
        "type": "CandorCard", "pace": 62, "primary": "162 wpm",
        "detail": "a little quicker than Tuesday",
        "lines": ["9 “basically”", "the story drifted, gently"]}))
    L.append(("thread", "brief", {
        "type": "ThreadCard", "primary": "Palette kept",
        "footer": "from the light in this room",
        "swatches": [0x2C7A6B, 0x8FB9A8, 0xE8D9B5, 0xC08457, 0x3A4A55]}))
    L.append(("waypath", "park", {
        "type": "WaypathLensCard", "bearing": 40,
        "primary": "240 m", "footer": "north rack"}))
    L.append(("sous", "alt", {
        "type": "SousCard",
        "timers": [("Sear", "0:30", 0.15), ("Rest", "4:00", 0.7)],
        "footer": "hands-free · say “flip in ninety”"}))
    L.append(("session", "alt", {
        "type": "SessionCard", "primary": "112 BPM", "beat": 1,
        "detail": "in time · +4¢ sharp", "footer": "practice log writing itself"}))
    return L


if __name__ == "__main__":
    OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
    items = build()
    for key, env, card in items:
        img = R.render(card).convert("RGB")
        img.save(OUT / f"{key}.png")
    # contact sheet
    S = 200; cols = 5; rows = (len(items)+cols-1)//cols
    sheet = Image.new("RGB", (cols*S, rows*S), (8, 8, 10))
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    for i, (key, env, card) in enumerate(items):
        im = Image.open(OUT/f"{key}.png").convert("RGB").resize((S, S))
        x, y = (i % cols)*S, (i//cols)*S
        sheet.paste(im, (x, y)); d.text((x+4, y+4), key, fill=(150, 200, 210))
    sheet.save(OUT/"_sheet.png")
    print("rendered", len(items), "->", OUT)
