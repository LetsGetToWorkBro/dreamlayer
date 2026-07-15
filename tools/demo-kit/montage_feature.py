"""Coding-montage generator: a developer 'builds' a DreamLayer feature in the
terminal (branch → write the card renderer → run tests → preview), and the real
rendered lens pops up as the payoff. One spec per feature.
Usage: montage_feature.py <feature_key> <outdir>
Real device cards are rendered through the actual renderer / emberstasis draws.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"host-python/src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import devices as D
import gen
from dreamlayer.demo.scene import Beat,_compose_frame
from dreamlayer.hud.cards import ALL_SAMPLES

TEAL=(44,199,164); INK=(226,238,235); DIM=(129,156,151); GREEN=(86,211,100)
GOLD=(232,193,90); CORAL=(224,107,82); GREY=(120,140,140); BLUE=(120,170,235); PURP=(190,150,235)
def mono(px):
    try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",px)
    except: return ImageFont.load_default()
F=mono(19)

# ---- device card render (real renderer / emberstasis) ----
def render_face(spec):
    key=spec["card"]
    if key in ("ember_flare","ember_prompt","ember_reveal","ember_graduated","stasis"):
        import emberstasis as E
        if key=="stasis":
            card={"type":"StasisCard","primary":"…and the torque spikes right when—","footer":"held 4 min · tilt to resume"}
        else:
            card=dict(ALL_SAMPLES[key])
        return E.R.render(card).convert("RGB")
    from dreamlayer.hud import renderer as R
    return R.render(ALL_SAMPLES[key]).convert("RGB")

def render_disc(face, S=560):
    ov=gen._overlay_from_image(face,int(S*0.7))
    b=Beat({"type":"x"},0.0,1.0,anchor=(0.5,0.5),width=0.7,fade=0.0,glow=True)
    disc,_,_=gen._lens_maps(S); disc_a=(np.asarray(disc,np.float32)/255.0)[...,None]
    yy,xx=np.mgrid[0:S,0:S].astype(np.float32); r=np.hypot(xx-S/2,yy-S/2)
    bez=np.clip(1.0-np.abs(r-(S/2-3))/2.0,0,1)[...,None]*np.array([26,42,46],np.float32)
    rgb=np.asarray(_compose_frame(np.zeros((S,S,3),np.float32),[(b,ov)],0.5,(S,S),1.0),np.float32)
    return Image.fromarray(np.clip(rgb*disc_a+bez,0,255).astype(np.uint8),"RGB")

# ---- terminal (char-typed, scrolling) ----
W,Hh=1180,720; LH=32; X0=34; Y0=70; MAXLINES=18
def win_chrome(title):
    im=Image.new("RGB",(W,Hh),(13,16,19)); d=ImageDraw.Draw(im); bar=44
    d.rectangle([0,0,W,bar],fill=(30,35,40)); d.line([(0,bar),(W,bar)],fill=(16,20,24))
    for i,cc in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        d.ellipse([16+i*20-6,bar//2-6,16+i*20+6,bar//2+6],fill=cc)
    d.text((W//2,bar//2),title,font=mono(15),fill=(178,196,200),anchor="mm")
    return im,d
def render_term(title, lines, typing=None, k=0, cursor=True):
    im,d=win_chrome(title)
    vis=lines[-(MAXLINES-(1 if typing is not None else 0)):]
    y=Y0
    for kind,spans in vis:
        if kind=="gap": y+=LH//2; continue
        x=X0
        for t,c in spans:
            d.text((x,y),t,font=F,fill=c); x+=d.textlength(t,font=F)
        y+=LH
    curx,cury=X0,y
    if typing is not None:
        x=X0; left=k
        for t,c in typing:
            if left<=0: break
            seg=t[:left]; d.text((x,y),seg,font=F,fill=c); x+=d.textlength(seg,font=F); left-=len(seg)
        curx,cury=x,y
    if cursor: d.rectangle([curx,cury+4,curx+11,cury+LH-6],fill=TEAL)
    return im

# ---- feature specs ----  (kind: type=char-typed line, out, gap)
def sp(*x): return list(x)
SPECS={
 "veritas": {
   "card":"fact_check","title":"veritas — live fact-check",
   "ptitle":"Building the live fact-checker","psub":"it remembers what was said — so when the story changes, you know",
   "tr":[
    ("type",sp(("$ ",DIM),("git checkout -b feature/veritas",INK))),
    ("out", sp(("  Switched to a new branch 'feature/veritas'",GREY))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("$EDITOR ",DIM),("host-python/src/dreamlayer/lenses/veritas.py",INK))),
    ("code",sp(("  def ",CORAL),("check",TEAL),("(claim, memory):",INK))),
    ("code",sp(("      prior = memory.recall(claim.subject)",INK))),
    ("code",sp(("      if ",CORAL),("contradicts(claim, prior):",INK))),
    ("code",sp(("          ",INK),("return ",CORAL),("Verdict.CONFLICT",GOLD))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("pytest tests/test_veritas.py -q",INK))),
    ("out", sp(("  ........  ",GREEN),("[100%]",GREY))),
    ("out", sp(("  9 passed in 0.38s",GREEN))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("dreamlayer lens preview veritas",INK))),
    ("out", sp(("  offline · veil-gated · rendered  →  ",DIM),("veritas-preview.png",TEAL))),
   ],
 },
 "retrace": {
   "card":"object_recall","title":"retrace — where you left it",
   "ptitle":"Building passive object recall","psub":"it quietly notices where you set things down, and hands it back",
   "tr":[
    ("type",sp(("$ ",DIM),("git checkout -b feature/retrace",INK))),
    ("out", sp(("  Switched to a new branch 'feature/retrace'",GREY))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("$EDITOR ",DIM),("host-python/src/dreamlayer/ops/sightings.py",INK))),
    ("code",sp(("  def ",CORAL),("on_sighting",TEAL),("(obj, place, t):",INK))),
    ("code",sp(("      store.note(obj, place, t)   ",INK),("# passive, no photos",GREY))),
    ("code",sp(("  def ",CORAL),("recall",TEAL),("(obj):",INK))),
    ("code",sp(("      ",INK),("return ",CORAL),("store.last(obj)",INK))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("pytest tests/test_sightings.py -q",INK))),
    ("out", sp(("  ......  ",GREEN),("[100%]",GREY))),
    ("out", sp(("  6 passed in 0.21s",GREEN))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("dreamlayer lens preview object_recall",INK))),
    ("out", sp(("  on-device · rendered  →  ",DIM),("retrace-preview.png",TEAL))),
   ],
 },
 "ember": {
   "card":"ember_flare","title":"ember — tend a memory",
   "ptitle":"Building spaced-repetition memory","psub":"it brings a moment back on a curve until it's really yours",
   "tr":[
    ("type",sp(("$ ",DIM),("git checkout -b feature/ember",INK))),
    ("out", sp(("  Switched to a new branch 'feature/ember'",GREY))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("$EDITOR ",DIM),("host-python/src/dreamlayer/lenses/ember.py",INK))),
    ("code",sp(("  def ",CORAL),("next_due",TEAL),("(card):",INK))),
    ("code",sp(("      gap = SPACING[card.reps]        ",INK),("# 1,3,7,14,30d",GREY))),
    ("code",sp(("      ",INK),("return ",CORAL),("card.last + timedelta(days=gap)",INK))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("pytest tests/test_ember.py -q",INK))),
    ("out", sp(("  .......  ",GREEN),("[100%]",GREY))),
    ("out", sp(("  7 passed in 0.29s",GREEN))),
    ("gap",[]),
    ("type",sp(("$ ",DIM),("dreamlayer lens preview ember_flare",INK))),
    ("out", sp(("  spaced · quiet · rendered  →  ",DIM),("ember-preview.png",TEAL))),
   ],
 },
}

# ---- compose canvas + pop ----
CW,CH=1500,1040
def canvas(ptitle,psub):
    b=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),CW,CH).convert("RGB"); d=ImageDraw.Draw(b)
    d.text((CW//2,150),ptitle,font=D.font(36),fill=INK,anchor="mm")
    d.text((CW//2,200),psub,font=D.font(19,False),fill=DIM,anchor="mm")
    return b
TW_W,TW_H=1120,683
def _shadow_base(base):
    # terminal is an opaque rectangle -> its drop shadow is constant; bake it once
    rect=Image.new("RGBA",(TW_W,TW_H),(0,0,0,255))
    sc=D.shadow(rect,blur=32,alpha=140)
    b=base.copy(); b.paste(sc,((CW-sc.width)//2,258),sc)
    pad=(sc.width-TW_W)//2
    return b, ((CW-sc.width)//2+pad, 258+pad)
def place_term_fast(shadow_base, pos, term_img, dim=1.0):
    b=shadow_base.copy()
    tw=term_img.convert("RGB").resize((TW_W,TW_H),Image.LANCZOS)
    if dim<1.0: tw=Image.eval(tw,lambda p:int(p*dim))
    b.paste(tw,pos); return b
def easeOutBack(t,s=1.70158):
    t=t-1; return t*t*((s+1)*t+s)+1

def main(key,outroot):
    spec=SPECS[key]; out=Path(outroot)/key; (out/"f").mkdir(parents=True,exist_ok=True)
    BASE=canvas(spec["ptitle"],spec["psub"])
    SB,POS=_shadow_base(BASE)
    disc=render_disc(render_face(spec))
    title=spec["title"]
    fi=0
    def emit(im,n=1):
        nonlocal fi
        for _ in range(n): im.save(out/"f"/f"f_{fi:04d}.png"); fi+=1
    done=[]
    for kind,spans in spec["tr"]:
        if kind=="gap": done.append(("gap",None)); continue
        if kind in ("type","code"):
            total=sum(len(t) for t,_ in spans)
            emit(place_term_fast(SB,POS,render_term(title,done,typing=spans,k=0)),2)
            for kk in range(1,total+1):
                emit(place_term_fast(SB,POS,render_term(title,done,typing=spans,k=kk)),1)
            done.append(("line",spans))
            emit(place_term_fast(SB,POS,render_term(title,done)), 5 if kind=="type" else 2)
        else:
            done.append(("line",spans)); emit(place_term_fast(SB,POS,render_term(title,done)),3)
    last=render_term(title,done)
    # pop
    POP=26; DSZ=560; cx,cy=CW//2,560
    for f in range(POP):
        t=(f+1)/POP; dim=1.0-0.55*t
        b=place_term_fast(SB,POS,last,dim=dim); e=max(0.0,easeOutBack(t))
        sz=max(8,int(DSZ*(0.12+0.88*e))); d2=disc.resize((sz,sz),Image.LANCZOS)
        m=Image.new("L",(sz,sz),0); ImageDraw.Draw(m).ellipse([1,1,sz-2,sz-2],fill=int(255*min(1,t*1.5)))
        glow=d2.resize((int(sz*1.25),int(sz*1.25))).filter(ImageFilter.GaussianBlur(sz//8))
        gm=Image.new("L",glow.size,0); ImageDraw.Draw(gm).ellipse([0,0,glow.size[0]-1,glow.size[1]-1],fill=int(120*t))
        b.paste(glow,(cx-glow.size[0]//2,cy-glow.size[1]//2),gm); b.paste(d2,(cx-sz//2,cy-sz//2),m)
        emit(b)
    # hold
    b=place_term_fast(SB,POS,last,dim=0.45); sz=DSZ; d2=disc.resize((sz,sz),Image.LANCZOS)
    m=Image.new("L",(sz,sz),0); ImageDraw.Draw(m).ellipse([1,1,sz-2,sz-2],fill=255)
    glow=d2.resize((int(sz*1.22),int(sz*1.22))).filter(ImageFilter.GaussianBlur(sz//9))
    gm=Image.new("L",glow.size,0); ImageDraw.Draw(gm).ellipse([0,0,glow.size[0]-1,glow.size[1]-1],fill=120)
    b.paste(glow,(cx-glow.size[0]//2,cy-glow.size[1]//2),gm); b.paste(d2,(cx-sz//2,cy-sz//2),m)
    d=ImageDraw.Draw(b)
    d.text((cx,cy+sz//2+30),"live on the glasses",font=D.font(26),fill=TEAL,anchor="mm")
    d.text((cx,cy+sz//2+66),"the exact device render · no hardware needed",font=D.font(17,False),fill=DIM,anchor="mm")
    emit(b,54)
    print(key,"frames",fi)

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else "/tmp/montage_out")
