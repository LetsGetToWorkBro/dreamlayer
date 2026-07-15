"""Frame the real DreamLayer app screenshots in clean device mockups (iPhone +
macOS window), then build hero montages and animated scroll-through demos.
Everything is the ACTUAL current UI — we only add the device chrome around it.
Outputs to <outdir>/ . No GitHub writes.
"""
from __future__ import annotations
import sys, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
PHONE = ROOT / "docs/gitbook/assets/phone"
PANEL = ROOT / "docs/gitbook/assets/panel"
BG = (9, 12, 14)
INK = (234, 243, 241); DIM = (138, 165, 160); BRAND = (44, 199, 164)

def font(px, bold=True):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(p, px)
    except: return ImageFont.load_default()

def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=radius, fill=255)
    return m

# ---------- iPhone frame -----------------------------------------------------
def iphone(screen, scr_w=430):
    """Wrap a screenshot in an iPhone 15-ish frame. Returns RGBA."""
    shot = screen.convert("RGB")
    ar = shot.height / shot.width
    sw = scr_w; shot_h = int(sw * ar)
    shot = shot.resize((sw, shot_h), Image.LANCZOS)
    # status band above the app content so the Dynamic Island never overlaps UI
    band = int(sw * 0.115)
    src = Image.new("RGB", (sw, shot_h + band), (0, 0, 0))
    src.paste(shot, (0, band))
    sd = ImageDraw.Draw(src)
    sd.text((int(sw*0.09), band//2), "9:41", font=font(int(sw*0.052)), fill=(236, 244, 242), anchor="lm")
    # signal / wifi / battery glyphs at right
    bx = sw - int(sw*0.085)
    sd.rounded_rectangle([bx, band//2-int(sw*0.018), bx+int(sw*0.05), band//2+int(sw*0.018)],
                         radius=int(sw*0.008), outline=(210, 224, 222), width=2)
    sd.rounded_rectangle([bx+2, band//2-int(sw*0.012), bx+int(sw*0.05)*0.72, band//2+int(sw*0.012)],
                         radius=int(sw*0.004), fill=(210, 224, 222))
    for i, hh in enumerate([0.010, 0.016, 0.022, 0.028]):
        gx = bx - int(sw*0.14) + i*int(sw*0.020)
        sd.rounded_rectangle([gx, band//2-int(sw*hh), gx+int(sw*0.012), band//2+int(sw*0.014)],
                             radius=2, fill=(210, 224, 222))
    sh = shot_h + band
    # screen corner rounding
    scr_r = int(sw * 0.11)
    src.putalpha(rounded_mask((sw, sh), scr_r))
    bezel = int(sw * 0.035)
    body_r = scr_r + bezel
    W = sw + bezel*2; H = sh + bezel*2
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    # titanium rim + black body
    d.rounded_rectangle([0, 0, W-1, H-1], radius=body_r, fill=(28, 32, 36, 255))
    d.rounded_rectangle([2, 2, W-3, H-3], radius=body_r-2, fill=(9, 10, 12, 255))
    card.paste(src, (bezel, bezel), src)
    # Dynamic Island
    iw, ih = int(sw*0.30), int(sw*0.085)
    ix = (W - iw)//2; iy = bezel + int(sh*0.018)
    d.rounded_rectangle([ix, iy, ix+iw, iy+ih], radius=ih//2, fill=(0, 0, 0, 255))
    d.ellipse([ix+iw-ih-2, iy+3, ix+iw-5, iy+ih-3], fill=(11, 20, 22, 255))
    # side buttons
    bt = (18, 21, 24, 255)
    d.rounded_rectangle([-1, int(H*0.22), 2, int(H*0.30)], radius=2, fill=bt)
    d.rounded_rectangle([-1, int(H*0.34), 2, int(H*0.44)], radius=2, fill=bt)
    d.rounded_rectangle([W-3, int(H*0.26), W+1, int(H*0.40)], radius=2, fill=bt)
    return card

# ---------- macOS window frame ----------------------------------------------
def macwindow(screen, title="DreamLayer", win_w=1280):
    src = screen.convert("RGB")
    ar = src.height / src.width
    sw = win_w; sh = int(sw * ar)
    src = src.resize((sw, sh), Image.LANCZOS)
    bar = 46
    W = sw; H = sh + bar
    win = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(win)
    r = 16
    d.rounded_rectangle([0, 0, W-1, H-1], radius=r, fill=(22, 26, 30, 255))
    # title bar gradient-ish
    d.rounded_rectangle([0, 0, W-1, bar+r], radius=r, fill=(30, 35, 40, 255))
    d.rectangle([0, bar-1, W-1, bar], fill=(16, 20, 24, 255))
    # traffic lights
    for i, cc in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 26 + i*22
        d.ellipse([cx-7, bar//2-7, cx+7, bar//2+7], fill=cc+(255,))
    d.text((W//2, bar//2), title, font=font(16), fill=(190, 205, 210), anchor="mm")
    # screen with bottom rounding
    body = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    body.paste(src, (0, 0))
    bm = Image.new("L", (sw, sh), 0)
    bd = ImageDraw.Draw(bm)
    bd.rectangle([0, 0, sw, sh-r], fill=255)
    bd.rounded_rectangle([0, sh-r*2, sw, sh-1], radius=r, fill=255)
    body.putalpha(bm)
    win.paste(body, (0, bar), body)
    # subtle outer border
    d.rounded_rectangle([0, 0, W-1, H-1], radius=r, outline=(48, 56, 62, 255), width=1)
    return win

def browserwindow(screen, url="dreamlayer.app/plugins.html", win_w=1400, crop_h=None):
    """Wrap a web screenshot in a macOS browser window (traffic lights + URL bar)."""
    src = screen.convert("RGB")
    if crop_h and src.height > crop_h:
        src = src.crop((0, 0, src.width, crop_h))
    ar = src.height / src.width
    sw = win_w; sh = int(sw * ar)
    src = src.resize((sw, sh), Image.LANCZOS)
    bar = 62
    W = sw; H = sh + bar
    win = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(win)
    r = 16
    d.rounded_rectangle([0, 0, W-1, H-1], radius=r, fill=(20, 24, 28, 255))
    d.rounded_rectangle([0, 0, W-1, bar+r], radius=r, fill=(28, 33, 38, 255))
    d.rectangle([0, bar-1, W-1, bar], fill=(14, 18, 22, 255))
    for i, cc in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 30 + i*24
        d.ellipse([cx-8, bar//2-8, cx+8, bar//2+8], fill=cc+(255,))
    # URL pill
    ux0, ux1 = 130, W-130
    d.rounded_rectangle([ux0, bar//2-17, ux1, bar//2+17], radius=17, fill=(16, 20, 24, 255))
    d.ellipse([ux0+16, bar//2-6, ux0+28, bar//2+6], outline=(120, 140, 145, 255), width=2)  # lock
    d.line([ux0+22, bar//2-6, ux0+22, bar//2-11], fill=(120,140,145,255), width=2)
    d.text((ux0+44, bar//2), url, font=font(16, False), fill=(150, 172, 176), anchor="lm")
    # screen with bottom rounding
    body = Image.new("RGBA", (sw, sh), (0, 0, 0, 0)); body.paste(src, (0, 0))
    bm = Image.new("L", (sw, sh), 0); bd = ImageDraw.Draw(bm)
    bd.rectangle([0, 0, sw, sh-r], fill=255)
    bd.rounded_rectangle([0, sh-r*2, sw, sh-1], radius=r, fill=255)
    body.putalpha(bm)
    win.paste(body, (0, bar), body)
    d.rounded_rectangle([0, 0, W-1, H-1], radius=r, outline=(48, 56, 62, 255), width=1)
    return win

def shadow(card, blur=40, grow=8, alpha=150, off=(0, 18)):
    W, H = card.size
    pad = blur + grow + max(abs(off[0]), abs(off[1])) + 10
    canvas = Image.new("RGBA", (W+pad*2, H+pad*2), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    a = card.split()[-1].point(lambda p: alpha if p > 8 else 0)
    solid = Image.new("RGBA", card.size, (0, 0, 0, 255)); solid.putalpha(a)
    sh.paste(solid, (pad+off[0], pad+off[1]), solid)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas = Image.alpha_composite(canvas, sh)
    canvas.paste(card, (pad, pad), card)
    return canvas

def scene(card, W, H, bg_top=(13, 18, 20), bg_bot=(6, 9, 10), title=None, sub=None):
    """Place a framed device on a branded gradient poster."""
    base = Image.new("RGB", (W, H), bg_bot)
    top = np.array(bg_top, float); bot = np.array(bg_bot, float)
    ar = np.linspace(0, 1, H)[:, None, None]
    grad = (top*(1-ar) + bot*ar).astype(np.uint8)
    base = Image.fromarray(np.repeat(grad, W, axis=1), "RGB")
    d = ImageDraw.Draw(base)
    # faint teal vignette glow center-top
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W//2-W//2, -H//3, W//2+W//2, H//2], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    tint = Image.new("RGB", (W, H), BRAND)
    base = Image.composite(Image.blend(base, tint, 0.10), base, glow)
    d = ImageDraw.Draw(base)
    d.text((44, 40), "DreamLayer", font=font(26), fill=INK)
    d.text((W-44, 53), "for Brilliant Labs Halo", font=font(15, False), fill=DIM, anchor="rm")
    sc = shadow(card)
    if title:
        cap_band = 150
        # center the device in the space above the caption band, under the header
        region_top = 96; region_bot = H - cap_band
        cy_dev = region_top + (region_bot - region_top - sc.height)//2
        base.paste(sc, ((W-sc.width)//2, max(region_top-40, cy_dev)), sc)
        cy = H - cap_band + 66
        d.text((W//2, cy), title, font=font(30), fill=BRAND, anchor="mm")
        if sub:
            d.text((W//2, cy+40), sub, font=font(19, False), fill=DIM, anchor="mm")
    else:
        base.paste(sc, ((W-sc.width)//2, (H-sc.height)//2), sc)
    return base

if __name__ == "__main__":
    OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
    print("devices.py ready ->", OUT)
