"""Playground hero + a portrait (9:16) 'build -> prove -> ship' reel, built from
the real captured assets. Reel frames -> <out>/reel/ ; playground hero -> <out>/."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import devices as D

WEB=Path("/tmp/web_out/raw"); BG=Path("/tmp/web_out/bgseq"); DEV=Path("/tmp/dev_out")
OUT=Path(sys.argv[1]); OUT.mkdir(parents=True,exist_ok=True)
(OUT/"reel").mkdir(exist_ok=True)
BRAND=D.BRAND; INK=D.INK; DIM=D.DIM

# ---------- Playground hero ----------
pg=Image.open(WEB/"playground_top.png").convert("RGB").crop((0,0,2880,1080))
pgcard=D.browserwindow(pg, url="dreamlayer.app/playground.html", win_w=1500)
def poster(card,W,H,title,sub):
    b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB"); d=ImageDraw.Draw(b)
    sc=D.shadow(card,blur=44,alpha=150); cap=150; rt=104
    cy=rt+(H-cap-rt-sc.height)//2
    b.paste(sc,((W-sc.width)//2,max(rt-30,cy)),sc)
    d.text((W//2,H-cap+70),title,font=D.font(32),fill=BRAND,anchor="mm")
    d.text((W//2,H-cap+112),sub,font=D.font(19,False),fill=DIM,anchor="mm")
    return b
poster(pgcard,1800,1050,"WebBLE Playground",
       "drive the HUD from your browser over Bluetooth · a Lua REPL to the glasses").save(OUT/"playground_hero.png")
print("playground hero done")

# ---------- Portrait reel ----------
PW,PH=1080,1920
def pbg():
    top=np.array((13,18,20),float); bot=np.array((6,9,10),float)
    ar=np.linspace(0,1,PH)[:,None,None]
    grad=(top*(1-ar)+bot*ar).astype(np.uint8)
    base=Image.fromarray(np.repeat(grad,PW,axis=1),"RGB")
    glow=Image.new("L",(PW,PH),0)
    ImageDraw.Draw(glow).ellipse([-PW//2,-PH//4,PW+PW//2,PH//2],fill=55)
    glow=glow.filter(ImageFilter.GaussianBlur(180))
    return Image.composite(Image.blend(base,Image.new("RGB",(PW,PH),BRAND),0.09),base,glow)
BASE=pbg()

def header(d):
    d.text((44,52),"DreamLayer",font=D.font(26),fill=INK)
    d.text((PW-44,60),"for Brilliant Labs Halo",font=D.font(15,False),fill=DIM,anchor="rm")

def frame_chip(d,x,y,text,active=True):
    f=D.font(20); w=d.textlength(text,font=f)+40
    d.rounded_rectangle([x,y,x+w,y+46],radius=23,fill=(20,44,40) if active else (16,20,22),
                        outline=BRAND if active else (40,54,52),width=2)
    d.text((x+20,y+23),text,font=f,fill=BRAND if active else DIM,anchor="lm"); return w

def step_line(d,n,label,active_n):
    y=1640
    labels=["BUILD","PROVE","SHIP"]
    x=90
    for i,lb in enumerate(labels):
        on=(i+1)<=active_n
        col=BRAND if on else (70,86,84)
        d.ellipse([x,y,x+40,y+40],outline=col,width=3,
                  fill=(20,44,40) if (i+1)==active_n else None)
        d.text((x+20,y+20),str(i+1),font=D.font(20),fill=col,anchor="mm")
        d.text((x+20,y+62),lb,font=D.font(15),fill=col,anchor="mm")
        x+=40
        if i<2:
            d.line([x+12,y+20,x+150-12,y+20],fill=(50,64,62) if not on else BRAND,width=3); x+=150

def card_center(img, maxw, top):
    im=img.convert("RGB"); s=maxw/im.width; im=im.resize((maxw,int(im.height*s)),Image.LANCZOS)
    return im

def compose(kind, payload, title, sub, step):
    b=BASE.copy(); d=ImageDraw.Draw(b); header(b if False else d)
    d.text((PW//2,150),title,font=D.font(40),fill=INK,anchor="mm")
    d.text((PW//2,206),sub,font=D.font(21,False),fill=DIM,anchor="mm")
    if kind=="disc":
        im=card_center(payload,760,0); sc=D.shadow(im.convert("RGBA"),blur=30,alpha=120)
        b.paste(sc,((PW-sc.width)//2,300),sc)
    elif kind=="panel":
        im=card_center(payload,720,0)
        m=Image.new("L",im.size,0); ImageDraw.Draw(m).rounded_rectangle([0,0,im.width-1,im.height-1],radius=20,fill=255)
        im.putalpha(m); sc=D.shadow(im,blur=34,alpha=140)
        b.paste(sc,((PW-sc.width)//2,300),sc)
    elif kind=="win":
        im=card_center(payload,940,0); sc=D.shadow(im.convert("RGBA"),blur=30,alpha=130)
        b.paste(sc,((PW-sc.width)//2,340),sc)
    step_line(d,step,None,step)
    return b

# assets
disc_frames=sorted(BG.glob("bg_*.png"))
proof=Image.open("/tmp/crop_proof.png")
term=Image.open(DEV/"dev_terminal.png")
store=Image.open(WEB/"store_top.png").crop((0,0,2880,1500))
storecard=D.browserwindow(store,url="dreamlayer.app/plugins.html",win_w=1200)

fi=0
def emit(img,n):
    global fi
    for _ in range(n): img.save(OUT/"reel"/f"f_{fi:04d}.png"); fi+=1

# intro
intro=BASE.copy(); di=ImageDraw.Draw(intro)
di.text((PW//2,PH//2-120),"BUILD ON",font=D.font(64),fill=INK,anchor="mm")
di.text((PW//2,PH//2-40),"DREAMLAYER",font=D.font(64),fill=BRAND,anchor="mm")
di.text((PW//2,PH//2+60),"describe it · prove it's safe · ship it",font=D.font(24,False),fill=DIM,anchor="mm")
di.text((PW//2,PH//2+120),"no code required",font=D.font(20,False),fill=(90,120,116),anchor="mm")
emit(intro,44)

# BUILD: cycle a few backgrounds of the live preview
build_labels=["Black","Street","Park","Dawn"]
for i,idx in enumerate([0,1,2,6]):
    fr=compose("disc",Image.open(disc_frames[idx]),"1 · Build",
               "a lens is data — pick words, not code",1)
    emit(fr,30)
# PROVE
prove=compose("panel",proof,"2 · Prove",
              "your glasses re-check every rule before it runs",2)
emit(prove,96)
# SHIP: terminal + store glimpse
ship=compose("win",term,"3 · Ship",
             "a link anyone can open — or one-click to your glasses",3)
emit(ship,80)
ship2=compose("win",Image.open(WEB/"store_top.png").crop((0,0,2880,1400)),"3 · Ship",
              "…and it lands in the store, safety-gated",3)
emit(ship2,60)
# outro
outro=BASE.copy(); do=ImageDraw.Draw(outro)
do.text((PW//2,PH//2-60),"dreamlayer.app",font=D.font(52),fill=INK,anchor="mm")
do.text((PW//2,PH//2+20),"build a lens · build a plugin",font=D.font(24,False),fill=BRAND,anchor="mm")
do.text((PW//2,PH//2+72),"the same safety gate re-runs everywhere",font=D.font(19,False),fill=DIM,anchor="mm")
emit(outro,44)
print("reel frames",fi)
