"""Animated demo frames: scroll the store + builder full pages inside a browser
window, cycle the builder preview backgrounds, and a disc for the terminal typing
(terminal frames already exist in /tmp/dev_out/term)."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import devices as D

WEB=Path("/tmp/web_out/raw"); BG=Path("/tmp/web_out/bgseq")
OUT=Path(sys.argv[1]); OUT.mkdir(parents=True,exist_ok=True)
for s in ["store_scroll","builder_scroll","bgcycle"]:(OUT/s).mkdir(exist_ok=True)

def scroll_frames(full_png, url, outdir, win_w=1500, view_ar=0.66, nframes=150, pad_top=0.06):
    """Pan a tall full-page screenshot through a fixed browser window viewport."""
    full=Image.open(full_png).convert("RGB")
    scale=win_w/full.width
    full=full.resize((win_w,int(full.height*scale)),Image.LANCZOS)
    view_h=int(win_w*view_ar)
    max_off=max(1, full.height-view_h)
    # frame the viewport once to get chrome; we paste crops into it
    W=H=None
    fi=0
    # easing pan down then a short hold
    pan=int(nframes*0.82); hold=nframes-pan
    for f in range(nframes):
        t=min(1.0, f/max(1,pan))
        e=t*t*(3-2*t)  # smoothstep
        off=int(e*max_off)
        crop=full.crop((0,off,win_w,off+view_h))
        card=D.browserwindow(crop, url=url, win_w=win_w)
        # poster bg
        Wp,Hp=1600,1120
        b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),Wp,Hp).convert("RGB")
        sc=D.shadow(card,blur=34,alpha=140)
        b.paste(sc,((Wp-sc.width)//2,(Hp-sc.height)//2),sc)
        b.save(outdir/f"f_{fi:04d}.png"); fi+=1
    return fi

n1=scroll_frames(WEB/"store_full.png","dreamlayer.app/plugins.html",OUT/"store_scroll",nframes=150)
print("store_scroll",n1)
n2=scroll_frames(WEB/"builder_full.png","dreamlayer.app/lens-builder.html",OUT/"builder_scroll",nframes=150)
print("builder_scroll",n2)

# background cycle: same lens, every world behind the glass
LABELS=["Black","Street","Park","Desk","Room","Table","Dawn","Dim"]
bgs=sorted(BG.glob("bg_*.png"))
W=H=1080; fi=0; hold=16; cf=8
def bg_poster(img,label):
    b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
    im=img.convert("RGB"); s=780/im.width; im=im.resize((780,int(im.height*s)))
    b.paste(im,((W-im.width)//2,96)); d=ImageDraw.Draw(b)
    d.text((W//2,H-150),"Live preview · "+label,font=D.font(28),fill=D.BRAND,anchor="mm")
    d.text((W//2,H-112),"same lens, any world behind the glass",font=D.font(18,False),fill=D.DIM,anchor="mm")
    return b
rendered=[bg_poster(Image.open(p),LABELS[i%len(LABELS)]) for i,p in enumerate(bgs)]
for i,cur in enumerate(rendered):
    for _ in range(hold): cur.save(OUT/"bgcycle"/f"f_{fi:04d}.png"); fi+=1
    nxt=rendered[(i+1)%len(rendered)]
    for f in range(cf):
        Image.blend(cur,nxt,(f+1)/(cf+1)).save(OUT/"bgcycle"/f"f_{fi:04d}.png"); fi+=1
print("bgcycle",fi)
