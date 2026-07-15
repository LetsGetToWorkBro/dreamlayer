"""Terminal types the plugin CLI flow, then the rendered lens 'pops up' (scale +
glow + fade) as the payoff of `dreamlayer plugins install`. Frames -> <out>/pop/.
Reuses the real terminal reveal frames and the real device-card render."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices as D

DEV=Path("/tmp/dev_out")
OUT=Path(sys.argv[1]); (OUT/"pop").mkdir(parents=True,exist_ok=True)
BRAND=D.BRAND; INK=D.INK; DIM=D.DIM

W,H=1500,1040
def canvas():
    b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
    d=ImageDraw.Draw(b)
    d.text((W//2,150),"Build a plugin",font=D.font(38),fill=INK,anchor="mm")
    d.text((W//2,200),"one command · watch it land on the glasses",font=D.font(20,False),fill=DIM,anchor="mm")
    return b
BASE=canvas()

term_frames=sorted((DEV/"term").glob("f_*.png"))
disc=Image.open(DEV/"dev_preview_disc.png").convert("RGB")

def place_term(canvas_img, term_img, dim=1.0):
    b=canvas_img.copy()
    tw=term_img.convert("RGB").resize((1120,683),Image.LANCZOS)
    if dim<1.0:
        tw=Image.eval(tw, lambda p:int(p*dim))
    sc=D.shadow(tw.convert("RGBA"),blur=32,alpha=int(140*dim))
    b.paste(sc,((W-sc.width)//2,258),sc)
    return b

def easeOutBack(t, s=1.70158):
    t=t-1
    return t*t*((s+1)*t+s)+1

fi=0
def emit(img,n=1):
    global fi
    for _ in range(n): img.save(OUT/"pop"/f"f_{fi:04d}.png"); fi+=1

# Phase A: typing (use every frame, they already encode holds)
for tf in term_frames:
    emit(place_term(BASE, Image.open(tf)))
last=Image.open(term_frames[-1])

# Phase B: pop the lens over a dimming terminal
POP=26; DSZ=560
cx,cy=W//2,560
for f in range(POP):
    t=(f+1)/POP
    dim=1.0-0.55*t
    b=place_term(BASE, last, dim=dim)
    e=max(0.0,easeOutBack(t))
    sz=max(8,int(DSZ*(0.12+0.88*e)))
    d2=disc.resize((sz,sz),Image.LANCZOS)
    # circular mask
    m=Image.new("L",(sz,sz),0); ImageDraw.Draw(m).ellipse([1,1,sz-2,sz-2],fill=int(255*min(1.0,t*1.5)))
    # glow bloom
    glow=d2.resize((int(sz*1.25),int(sz*1.25))).filter(ImageFilter.GaussianBlur(sz//8))
    gm=Image.new("L",glow.size,0); ImageDraw.Draw(gm).ellipse([0,0,glow.size[0]-1,glow.size[1]-1],fill=int(120*t))
    b.paste(glow,(cx-glow.size[0]//2,cy-glow.size[1]//2),gm)
    b.paste(d2,(cx-sz//2,cy-sz//2),m)
    emit(b)

# Phase C: hold the lens, caption
def final_frame():
    b=place_term(BASE, last, dim=0.45)
    sz=DSZ; d2=disc.resize((sz,sz),Image.LANCZOS)
    m=Image.new("L",(sz,sz),0); ImageDraw.Draw(m).ellipse([1,1,sz-2,sz-2],fill=255)
    glow=d2.resize((int(sz*1.22),int(sz*1.22))).filter(ImageFilter.GaussianBlur(sz//9))
    gm=Image.new("L",glow.size,0); ImageDraw.Draw(gm).ellipse([0,0,glow.size[0]-1,glow.size[1]-1],fill=120)
    b.paste(glow,(cx-glow.size[0]//2,cy-glow.size[1]//2),gm)
    b.paste(d2,(cx-sz//2,cy-sz//2),m)
    d=ImageDraw.Draw(b)
    d.text((cx,cy+sz//2+30),"live on the glasses",font=D.font(26),fill=BRAND,anchor="mm")
    d.text((cx,cy+sz//2+66),"the exact device render · no hardware needed",font=D.font(17,False),fill=DIM,anchor="mm")
    return b
ff=final_frame()
emit(ff,54)
print("pop frames",fi)
