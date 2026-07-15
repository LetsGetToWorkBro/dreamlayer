"""Assemble the Plugin Store / Lens Builder / Dev+SDK deliverables:
framed browser posters, dev-story posters, and hero montages. Animated demos
(scroll pages, background cycle, terminal typing) are encoded by ffmpeg after.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import devices as D

WEB = Path("/tmp/web_out/raw"); BG = Path("/tmp/web_out/bgseq"); DEV = Path("/tmp/dev_out")
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
for s in ["store","builder","dev"]:(OUT/s).mkdir(exist_ok=True)

def poster(card, W, H, title, sub, dev_shadow=True):
    b = D.scene(Image.new("RGBA",(1,1),(0,0,0,0)), W, H).convert("RGB")
    d = ImageDraw.Draw(b)
    sc = D.shadow(card, blur=44, alpha=150) if dev_shadow else card
    cap=150; rt=104
    cy = rt + (H-cap-rt-sc.height)//2
    b.paste(sc, ((W-sc.width)//2, max(rt-30, cy)), sc)
    d.text((W//2, H-cap+70), title, font=D.font(32), fill=D.BRAND, anchor="mm")
    d.text((W//2, H-cap+112), sub, font=D.font(19,False), fill=D.DIM, anchor="mm")
    return b

# ---------------- Plugin Store ----------------
store_card = D.browserwindow(Image.open(WEB/"store_top.png"),
                             url="dreamlayer.app/plugins.html", win_w=1500)
poster(store_card, 1800, 1250, "Plugin Store",
       "browse lenses, controllers, connectors — every one passes the safety gate").save(OUT/"store"/"store_hero.png")

# ---------------- Lens Builder ----------------
build_card = D.browserwindow(Image.open(WEB/"builder_top.png"),
                             url="dreamlayer.app/lens-builder.html", win_w=1560)
poster(build_card, 1840, 1320, "Lens Builder",
       "describe it in plain words · watch your glasses re-prove it's safe · ship it").save(OUT/"builder"/"builder_hero.png")

# builder preview on the round glass, framed as a device-ish disc poster
prev = Image.open(WEB/"builder_preview.png").convert("RGB")
pv = D.scene(prev.resize((760,int(760*prev.height/prev.width))), 1080, 1080, dev_shadow=False) \
      if False else None
# simpler: center the preview crop on a poster
def disc_poster(img, title, sub):
    W=H=1080; b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
    im=img.convert("RGB"); s=760/im.width; im=im.resize((760,int(im.height*s)))
    b.paste(im,((W-im.width)//2,120)); dd=ImageDraw.Draw(b)
    dd.text((W//2,H-140),title,font=D.font(30),fill=D.BRAND,anchor="mm")
    dd.text((W//2,H-100),sub,font=D.font(18,False),fill=D.DIM,anchor="mm")
    return b
disc_poster(Image.open(BG/"bg_00.png"),"Live preview",
            "your lens on the round glasses display — exactly what ships").save(OUT/"builder"/"builder_preview.png")

# ---------------- Dev / SDK ----------------
def devwin(img_path, url_title, W, H, title, sub):
    card = D.shadow(Image.open(img_path).convert("RGB").convert("RGBA"), blur=40, alpha=150)
    return poster(Image.open(img_path).convert("RGB").convert("RGBA"), W, H, title, sub)
poster(Image.open(DEV/"dev_terminal.png").convert("RGBA"), 1500, 1080,
       "Build a plugin", "one import surface, one command — new · validate · preview · pack · install").save(OUT/"dev"/"dev_terminal.png")
poster(Image.open(DEV/"dev_code.png").convert("RGBA"), 1500, 960,
       "The SDK surface", "import from dreamlayer.sdk · a HUD card in a dozen lines · typed, versioned").save(OUT/"dev"/"dev_code.png")
disc_poster(Image.open(DEV/"dev_preview_disc.png"),"plugins preview",
            "the exact device render — no hardware needed · snapshot-test it").save(OUT/"dev"/"dev_preview.png")

# dev hero: terminal + code + device preview composited
def dev_hero():
    W,H=1800,1200; b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
    term=D.shadow(Image.open(DEV/"dev_terminal.png").convert("RGB").resize((980,598)).convert("RGBA"),blur=34,alpha=150)
    code=D.shadow(Image.open(DEV/"dev_code.png").convert("RGB").resize((820,390)).convert("RGBA"),blur=30,alpha=140)
    b.paste(term,(60,210),term)
    b.paste(code,(900,210),code)
    # device preview masked to a circle so no black box shows
    disc=Image.open(DEV/"dev_preview_disc.png").convert("RGB").resize((440,440))
    m=Image.new("L",(440,440),0); ImageDraw.Draw(m).ellipse([2,2,438,438],fill=255)
    dsh=D.shadow(Image.merge("RGBA",(*disc.split(),m)),blur=36,alpha=140)
    b.paste(dsh,(1140,660),dsh)
    d=ImageDraw.Draw(b)
    d.text((44,96),"Build on DreamLayer",font=D.font(40),fill=D.INK)
    d.text((44,150),"a plugin is code · a figment is data · both pass the same safety gate",font=D.font(20,False),fill=D.DIM)
    d.text((1360,1130),"dreamlayer.sdk · dreamlayer plugins",font=D.font(17,False),fill=D.DIM,anchor="mm")
    return b
dev_hero().save(OUT/"dev"/"dev_hero.png")
print("posters done")
