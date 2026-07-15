"""Regenerate the terminal frames with true character-by-character typing:
each command line is typed one char at a time, then its output appears, then the
next command types. Writes /tmp/dev_out/term/f_*.png (consumed by build_popup)."""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT=Path("/tmp/dev_out/term"); OUT.mkdir(parents=True,exist_ok=True)
for old in OUT.glob("f_*.png"): old.unlink()

TEAL=(44,199,164); INK=(226,238,235); DIM=(129,156,151); GREEN=(86,211,100)
GOLD=(232,193,90); CORAL=(224,107,82); GREY=(120,140,140)
def mono(px):
    try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",px)
    except: return ImageFont.load_default()
F=mono(19)

def win_chrome(W,H,title):
    im=Image.new("RGB",(W,H),(13,16,19)); d=ImageDraw.Draw(im); bar=44
    d.rectangle([0,0,W,bar],fill=(30,35,40)); d.line([(0,bar),(W,bar)],fill=(16,20,24))
    for i,cc in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        d.ellipse([16+i*20-6,bar//2-6,16+i*20+6,bar//2+6],fill=cc)
    d.text((W//2,bar//2),title,font=mono(15),fill=(178,196,200),anchor="mm")
    return im,d,bar

# transcript: kind, spans   (kind: type=char-typed command, out=appears at once, gap)
TR=[
 ("type",[("$ ",DIM),("dreamlayer plugins new hello-lens",INK)]),
 ("out",[("  scaffolding API v2 plugin  ",DIM),("✓",GREEN)]),
 ("out",[("  hello-lens/plugin.py  ·  plugin.json  ·  test_plugin.py",GREY)]),
 ("gap",[]),
 ("type",[("$ ",DIM),("dreamlayer plugins validate .",INK)]),
 ("out",[("  integrity  ",DIM),("✓",GREEN),("   capability scan  ",DIM),("✓",GREEN),("   smoke test  ",DIM),("✓",GREEN)]),
 ("out",[("  requires: ",DIM),("cards",GOLD),("   ·   min_sdk ",DIM),("1.0.0",INK),("   ·   ",DIM),("safe to run",GREEN)]),
 ("gap",[]),
 ("type",[("$ ",DIM),("dreamlayer plugins preview .",INK)]),
 ("out",[("  rendered the device path in software  →  ",DIM),("hello-lens-preview.png",TEAL),("  (256×256)",GREY)]),
 ("gap",[]),
 ("type",[("$ ",DIM),("dreamlayer plugins pack .",INK)]),
 ("out",[("  signed  →  ",DIM),("hello-lens-0.1.0.json",TEAL)]),
 ("gap",[]),
 ("type",[("$ ",DIM),("dreamlayer plugins install .  --brain http://localhost:8765",INK)]),
 ("out",[("  Brain re-ran the gate  ",DIM),("✓",GREEN),("   installed  ",DIM),("·  live on the glasses",INK)]),
]
W,Hh=1180,720; LH=33; X0=34; Y0=44+26

def render(lines, typing=None, k=0, cursor=True):
    """lines: list of ('line', spans) or ('gap',). typing: spans being typed to k chars."""
    im,d,bar=win_chrome(W,Hh,"hello-lens — dreamlayer plugins")
    y=Y0
    for kind,spans in lines:
        if kind=="gap": y+=LH//2; continue
        x=X0
        for t,c in spans:
            d.text((x,y),t,font=F,fill=c); x+=d.textlength(t,font=F)
        y+=LH
    curx=X0
    if typing is not None:
        x=X0; left=k
        for t,c in typing:
            if left<=0: break
            seg=t[:left]
            d.text((x,y),seg,font=F,fill=c); x+=d.textlength(seg,font=F); left-=len(seg)
        curx=x; cury=y
    else:
        cury=y
    if cursor:
        d.rectangle([curx,cury+4,curx+11,cury+LH-6],fill=TEAL)
    return im

fi=0
def emit(im,n=1):
    global fi
    for _ in range(n): im.save(OUT/f"f_{fi:04d}.png"); fi+=1

done=[]
for kind,spans in TR:
    if kind=="gap":
        done.append(("gap",None)); continue
    if kind=="type":
        total=sum(len(t) for t,_ in spans)
        # small pause with cursor before typing
        emit(render(done,typing=spans,k=0),2)
        for kk in range(1,total+1):
            emit(render(done,typing=spans,k=kk),1)
        done.append(("line",spans))
        emit(render(done),4)          # brief pause after Enter
    else:  # out
        done.append(("line",spans))
        emit(render(done),3)
emit(render(done),10)                 # final hold
print("typed term frames",fi)
