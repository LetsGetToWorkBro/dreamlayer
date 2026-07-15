"""PIL-drawn macOS chrome for the install video: menu bar, dock with
recognizable app icons, and Finder windows (toolbar + sidebar + icon grid).
Aimed at screen-recording fidelity at 1080p."""
from __future__ import annotations
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

def font(px, bold=True):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, px)

# ---------------- app icons (sz x sz RGBA, macOS squircle-ish) --------------
def _tile(sz, fill, grad=None):
    im = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(sz * 0.235)
    if grad:
        top, bot = grad
        g = Image.new("RGBA", (sz, sz))
        gd = ImageDraw.Draw(g)
        for y in range(sz):
            t = y / sz
            gd.line([(0, y), (sz, y)], fill=tuple(int(top[i]*(1-t)+bot[i]*t) for i in range(3))+(255,))
        m = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, sz-1, sz-1], radius=r, fill=255)
        im.paste(g, (0, 0), m)
    else:
        d.rounded_rectangle([0, 0, sz-1, sz-1], radius=r, fill=fill)
    return im, ImageDraw.Draw(im)

def ic_finder(sz):
    im, d = _tile(sz, None, grad=((60, 140, 235), (28, 92, 190)))
    d.rectangle([sz//2, int(sz*0.06), sz-int(sz*0.06), sz-int(sz*0.06)], fill=(235, 242, 250, 70))
    y0 = int(sz*0.30)
    d.ellipse([int(sz*0.30)-3, y0, int(sz*0.30)+3, y0+int(sz*0.14)], fill=(20, 40, 80, 255))
    d.ellipse([int(sz*0.70)-3, y0, int(sz*0.70)+3, y0+int(sz*0.14)], fill=(20, 40, 80, 255))
    d.arc([int(sz*0.22), int(sz*0.38), int(sz*0.78), int(sz*0.80)], 25, 155, fill=(20, 40, 80, 255), width=max(2, sz//24))
    return im

def ic_safari(sz):
    im, d = _tile(sz, None, grad=((90, 175, 250), (25, 105, 215)))
    c = sz//2; r = int(sz*0.36)
    d.ellipse([c-r, c-r, c+r, c+r], fill=(245, 248, 252, 255))
    for a in range(0, 360, 15):
        x1 = c+math.cos(math.radians(a))*(r-3); y1 = c+math.sin(math.radians(a))*(r-3)
        x2 = c+math.cos(math.radians(a))*(r-7); y2 = c+math.sin(math.radians(a))*(r-7)
        d.line([x1, y1, x2, y2], fill=(120, 130, 140, 255), width=1)
    ang = math.radians(-45)
    p1 = (c+math.cos(ang)*r*0.82, c+math.sin(ang)*r*0.82)
    p2 = (c+math.cos(ang+math.pi)*r*0.82, c+math.sin(ang+math.pi)*r*0.82)
    off = (math.cos(ang+math.pi/2)*sz*0.05, math.sin(ang+math.pi/2)*sz*0.05)
    d.polygon([p1, (c+off[0], c+off[1]), (c-off[0], c-off[1])], fill=(235, 60, 50, 255))
    d.polygon([p2, (c+off[0], c+off[1]), (c-off[0], c-off[1])], fill=(230, 234, 240, 255))
    return im

def ic_messages(sz):
    im, d = _tile(sz, None, grad=((110, 230, 120), (40, 190, 70)))
    b = [int(sz*0.16), int(sz*0.18), int(sz*0.84), int(sz*0.70)]
    d.rounded_rectangle(b, radius=int(sz*0.20), fill=(255, 255, 255, 255))
    d.polygon([(int(sz*0.30), int(sz*0.66)), (int(sz*0.24), int(sz*0.84)), (int(sz*0.44), int(sz*0.70))], fill=(255, 255, 255, 255))
    return im

def ic_mail(sz):
    im, d = _tile(sz, None, grad=((90, 175, 250), (30, 110, 220)))
    b = [int(sz*0.14), int(sz*0.26), int(sz*0.86), int(sz*0.74)]
    d.rounded_rectangle(b, radius=int(sz*0.05), fill=(248, 250, 252, 255))
    d.line([b[0]+2, b[1]+2, sz//2, int(sz*0.52)], fill=(160, 175, 190, 255), width=max(2, sz//30))
    d.line([b[2]-2, b[1]+2, sz//2, int(sz*0.52)], fill=(160, 175, 190, 255), width=max(2, sz//30))
    return im

def ic_photos(sz):
    im, d = _tile(sz, (252, 252, 252, 255))
    c = sz//2; rr = int(sz*0.30)
    cols = [(255, 90, 80), (255, 150, 60), (250, 210, 60), (120, 210, 80), (60, 190, 170), (70, 140, 245), (150, 100, 235), (235, 90, 180)]
    for i, col in enumerate(cols):
        a = math.radians(i*45)
        ex, ey = c+math.cos(a)*rr*0.52, c+math.sin(a)*rr*0.52
        w, h = rr*0.62, rr*0.30
        petal = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        pd = ImageDraw.Draw(petal)
        pd.ellipse([ex-w/2, ey-h/2, ex+w/2, ey+h/2], fill=col+(210,))
        petal = petal.rotate(-i*45, center=(ex, ey))
        im.alpha_composite(petal)
    return im

def ic_music(sz):
    im, d = _tile(sz, None, grad=((252, 90, 120), (235, 45, 80)))
    x1, y1 = int(sz*0.36), int(sz*0.66)
    x2, y2 = int(sz*0.64), int(sz*0.60)
    r = int(sz*0.09)
    d.ellipse([x1-r, y1-r, x1+r, y1+r], fill=(255, 255, 255, 255))
    d.ellipse([x2-r, y2-r, x2+r, y2+r], fill=(255, 255, 255, 255))
    w = max(2, sz//26)
    d.line([x1+r-1, y1-1, x1+r-1, int(sz*0.30)], fill=(255, 255, 255, 255), width=w)
    d.line([x2+r-1, y2-1, x2+r-1, int(sz*0.26)], fill=(255, 255, 255, 255), width=w)
    d.line([x1+r-2, int(sz*0.30), x2+r-1, int(sz*0.26)], fill=(255, 255, 255, 255), width=w+2)
    return im

def ic_notes(sz):
    im, d = _tile(sz, (250, 250, 248, 255))
    d.rounded_rectangle([0, 0, sz-1, int(sz*0.26)], radius=int(sz*0.235), fill=(250, 210, 70, 255))
    d.rectangle([0, int(sz*0.14), sz-1, int(sz*0.26)], fill=(250, 210, 70, 255))
    for i in range(3):
        y = int(sz*0.42)+i*int(sz*0.15)
        d.line([int(sz*0.18), y, int(sz*0.82), y], fill=(200, 202, 205, 255), width=max(2, sz//30))
    return im

def ic_calendar(sz):
    im, d = _tile(sz, (252, 252, 252, 255))
    d.rounded_rectangle([0, 0, sz-1, int(sz*0.30)], radius=int(sz*0.235), fill=(245, 70, 60, 255))
    d.rectangle([0, int(sz*0.16), sz-1, int(sz*0.30)], fill=(245, 70, 60, 255))
    d.text((sz//2, int(sz*0.15)), "WED", font=font(int(sz*0.13)), fill=(255, 255, 255, 255), anchor="mm")
    d.text((sz//2, int(sz*0.62)), "15", font=font(int(sz*0.34)), fill=(40, 44, 48, 255), anchor="mm")
    return im

def ic_settings(sz):
    im, d = _tile(sz, None, grad=((150, 155, 165), (95, 100, 110)))
    c = sz//2; r1 = int(sz*0.30); r2 = int(sz*0.19); r3 = int(sz*0.08)
    for a in range(0, 360, 45):
        ar = math.radians(a)
        x, y = c+math.cos(ar)*r1, c+math.sin(ar)*r1
        d.rounded_rectangle([x-sz*0.055, y-sz*0.055, x+sz*0.055, y+sz*0.055], radius=int(sz*0.02), fill=(225, 228, 232, 255))
    d.ellipse([c-r1+2, c-r1+2, c+r1-2, c+r1-2], fill=(225, 228, 232, 255))
    d.ellipse([c-r2, c-r2, c+r2, c+r2], fill=(120, 125, 135, 255))
    d.ellipse([c-r3, c-r3, c+r3, c+r3], fill=(225, 228, 232, 255))
    return im

def ic_dreamlayer(sz):
    im, d = _tile(sz, (10, 16, 17, 255))
    c = sz//2; r = int(sz*0.28)
    d.ellipse([c-r, c-r, c+r, c+r], outline=(44, 199, 164, 255), width=max(2, sz//16))
    r2 = int(sz*0.10)
    d.ellipse([c-r2, c-r2, c+r2, c+r2], fill=(44, 199, 164, 255))
    return im

def ic_trash(sz):
    im = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    top = int(sz*0.24); bot = sz-int(sz*0.10)
    d.polygon([(int(sz*0.22), top), (sz-int(sz*0.22), top), (sz-int(sz*0.28), bot), (int(sz*0.28), bot)],
              fill=(200, 205, 212, 200), outline=(150, 156, 164, 255))
    d.rounded_rectangle([int(sz*0.18), top-int(sz*0.06), sz-int(sz*0.18), top], radius=3, fill=(210, 214, 220, 220))
    for i in range(3):
        x = int(sz*0.36)+i*int(sz*0.14)
        d.line([x, top+int(sz*0.08), x, bot-int(sz*0.08)], fill=(150, 156, 164, 255), width=max(2, sz//30))
    return im

def folder_icon(sz):
    im = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([int(sz*0.06), int(sz*0.30), sz-int(sz*0.06), sz-int(sz*0.14)], radius=int(sz*0.10), fill=(96, 174, 235, 255))
    d.rounded_rectangle([int(sz*0.06), int(sz*0.22), int(sz*0.44), int(sz*0.40)], radius=int(sz*0.07), fill=(120, 190, 245, 255))
    d.rounded_rectangle([int(sz*0.06), int(sz*0.34), sz-int(sz*0.06), sz-int(sz*0.14)], radius=int(sz*0.10), fill=(110, 184, 242, 255))
    return im

# ---------------- menu bar ----------------
def apple_logo(h):
    im = Image.new("RGBA", (h, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = h//2
    d.ellipse([2, 4, h-3, h-1], fill=(225, 228, 232, 255))
    d.ellipse([h-9, 1, h+3, h//2+2], fill=(0, 0, 0, 0))
    bite = Image.new("L", (h, h), 0)
    ImageDraw.Draw(bite).ellipse([h-8, h*0.18, h+5, h*0.62], fill=255)
    black = Image.new("RGBA", (h, h), (0, 0, 0, 0))
    im.paste(black, (0, 0), bite)
    d.ellipse([c-2, -1, c+4, 5], fill=(225, 228, 232, 255))
    return im

def menubar(im, appname, W):
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([0, 0, W, 28], fill=(24, 26, 30, 220))
    logo = apple_logo(15)
    im.paste(logo, (20, 6), logo)
    x = 48
    d.text((x, 14), appname, font=font(14), fill=(240, 242, 244), anchor="lm")
    x += d.textlength(appname, font=font(14))+24
    for m in ["File", "Edit", "View", "Go", "Window", "Help"]:
        d.text((x, 14), m, font=font(13, False), fill=(222, 226, 230), anchor="lm")
        x += d.textlength(m, font=font(13, False))+20
    d.text((W-20, 14), "Wed Jul 15  9:41 AM", font=font(13, False), fill=(222, 226, 230), anchor="rm")
    bx = W-206
    d.rounded_rectangle([bx, 8, bx+24, 20], radius=3, outline=(210, 214, 220, 255), width=1)
    d.rectangle([bx+24, 11, bx+26, 17], fill=(210, 214, 220, 255))
    d.rectangle([bx+2, 10, bx+18, 18], fill=(210, 214, 220, 255))
    wx = W-244
    for i, r in enumerate([3, 6, 9]):
        d.arc([wx-r, 16-r, wx+r, 16+r], 225, 315, fill=(210, 214, 220, 255), width=2)
    d.ellipse([wx-1, 14, wx+2, 17], fill=(210, 214, 220, 255))
    sx = W-282
    d.ellipse([sx, 8, sx+9, 17], outline=(210, 214, 220, 255), width=2)
    d.line([sx+8, 16, sx+12, 20], fill=(210, 214, 220, 255), width=2)
    return im

# ---------------- dock ----------------
_DOCK_CACHE = {}
def dock(im, W, H, running=("finder",), with_dl=True):
    key = (running, with_dl)
    if key not in _DOCK_CACHE:
        isz = 52
        icons = [("finder", ic_finder(isz)), ("safari", ic_safari(isz)), ("messages", ic_messages(isz)),
                 ("mail", ic_mail(isz)), ("photos", ic_photos(isz)), ("calendar", ic_calendar(isz)),
                 ("notes", ic_notes(isz)), ("music", ic_music(isz)), ("settings", ic_settings(isz))]
        if with_dl:
            icons.append(("dreamlayer", ic_dreamlayer(isz)))
        gap = 10
        total = len(icons)*(isz+gap)+gap + 26 + isz + 18
        x0 = (W-total)//2
        y0 = H-70
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([x0, y0, x0+total, H-8], radius=18, fill=(38, 40, 46, 168), outline=(255, 255, 255, 26), width=1)
        x = x0+gap
        pos = {}
        for name, ic in icons:
            layer.paste(ic, (x, y0+6), ic)
            pos[name] = x+isz//2
            x += isz+gap
        d.line([x+4, y0+12, x+4, H-16], fill=(255, 255, 255, 40), width=1)
        x += 26
        tr = ic_trash(isz)
        layer.paste(tr, (x, y0+6), tr)
        for name in running:
            if name in pos:
                cx = pos[name]
                d.ellipse([cx-2, H-13, cx+2, H-9], fill=(200, 205, 212, 230))
        _DOCK_CACHE[key] = layer
    im.alpha_composite(_DOCK_CACHE[key])
    return im

# ---------------- Finder windows ----------------
def _toolbar(d, w, title, bar=52):
    d.rounded_rectangle([0, 0, w-1, bar+12], radius=12, fill=(44, 46, 52, 255))
    d.rectangle([0, bar, w-1, bar+1], fill=(28, 30, 34, 255))
    for i, cc in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([18+i*22-6, bar//2-6, 18+i*22+6, bar//2+6], fill=cc)
    for i, ch in enumerate(["‹", "›"]):
        d.text((96+i*28, bar//2), ch, font=font(22, False), fill=(150, 155, 162), anchor="mm")
    d.text((160, bar//2), title, font=font(15), fill=(235, 238, 242), anchor="lm")
    sx = w-190
    d.rounded_rectangle([sx, bar//2-12, w-18, bar//2+12], radius=7, fill=(30, 32, 37, 255))
    d.ellipse([sx+9, bar//2-5, sx+18, bar//2+4], outline=(150, 155, 162), width=2)
    d.line([sx+17, bar//2+3, sx+21, bar//2+7], fill=(150, 155, 162), width=2)
    d.text((sx+28, bar//2), "Search", font=font(13, False), fill=(130, 135, 142), anchor="lm")

def finder_window(w, h, title, sidebar=True, active_item="Applications"):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w-1, h-1], radius=12, fill=(34, 36, 41, 255), outline=(70, 74, 80, 160), width=1)
    bar = 52
    _toolbar(d, w, title, bar)
    if sidebar:
        sb = 178
        d.rectangle([0, bar+1, sb, h-12], fill=(40, 42, 48, 255))
        d.rounded_rectangle([0, h-24, sb, h-1], radius=12, fill=(40, 42, 48, 255))
        d.rectangle([sb, bar+1, sb+1, h-1], fill=(26, 28, 32, 255))
        d.text((16, bar+22), "Favorites", font=font(11), fill=(130, 135, 142), anchor="lm")
        items = ["AirDrop", "Recents", "Applications", "Desktop", "Documents", "Downloads"]
        y = bar+44
        for it in items:
            if it == active_item:
                d.rounded_rectangle([8, y-11, sb-8, y+11], radius=6, fill=(70, 96, 148, 255))
            fi = folder_icon(16)
            im.paste(fi, (18, y-8), fi)
            d.text((42, y), it, font=font(13, False), fill=(230, 233, 238) if it == active_item else (200, 204, 210), anchor="lm")
            y += 30
        return im, sb, bar
    return im, 0, bar
