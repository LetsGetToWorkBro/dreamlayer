"""Driver: build framed hero posters, montages, and animated scroll demos for
the iPhone app and the Mac Brain panel from the real screenshots.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import devices as D

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
(OUT/"iphone").mkdir(exist_ok=True); (OUT/"mac").mkdir(exist_ok=True)
(OUT/"iphone/seq").mkdir(exist_ok=True); (OUT/"mac/seq").mkdir(exist_ok=True)

# ---- feature selections (key screens, human labels) ------------------------
PHONE_TOUR = [
    ("now",          "Now",          "the one thing that matters, right now"),
    ("brief",        "Morning Brief","your whole day, the moment you wake"),
    ("memories",     "Memories",     "everything it kept, searchable by meaning"),
    ("people",       "People",       "who they are and what you last talked about"),
    ("look",         "Look",         "point the glasses; ask about what you see"),
    ("settings_juno","Juno",         "your assistant, tuned to your voice"),
]
MAC_TOUR = [
    ("view_home",    "Home",         "the Mac mini is the brain — files, memory, reach"),
    ("view_mind",    "Intelligence", "pick the model; it all runs on your hardware"),
    ("view_day",     "Your Day",     "the brief it builds overnight while charging"),
    ("view_privacy", "Privacy",      "fails closed — you hold every switch"),
    ("view_caps",    "Capabilities", "turn features on one at a time"),
    ("view_reach",   "Connections",  "pair the phone, the glasses, the rest"),
]

def load(dirp, key): return Image.open(D.__dict__[dirp] / f"{key}.png")

# ============================ iPhone ========================================
print("iphone frames...")
iph_cards = {}
for key, title, sub in PHONE_TOUR:
    card = D.iphone(load("PHONE", key), scr_w=430)
    iph_cards[key] = card
    poster = D.scene(card, 1080, 1350, title=title, sub=sub)
    poster.save(OUT/"iphone"/f"{key}.png")

# hero montage: 3 phones fanned
def montage_phones(keys, W=1600, H=1000):
    base = D.scene(Image.new("RGBA",(1,1),(0,0,0,0)), W, H)  # bg only w/ header
    base = base.convert("RGB")
    cards = [iph_cards[k] for k in keys]
    ch = int(H*0.82); scaled=[]
    for c in cards:
        s = ch / c.height
        scaled.append(c.resize((int(c.width*s), ch), Image.LANCZOS))
    gap = -60
    tot = sum(s.width for s in scaled) + gap*(len(scaled)-1)
    x = (W-tot)//2; y = (H-ch)//2 + 20
    order = list(range(len(scaled)))
    mid = len(order)//2
    for i in sorted(order, key=lambda k: -abs(k-mid)):  # center on top
        s = scaled[i]
        sc = D.shadow(s, blur=34, alpha=130)
        xi = x + sum(scaled[j].width for j in range(i)) + gap*i - 36
        dy = int(abs(i-mid)*26)
        base.paste(sc, (xi-36, y+dy-36), sc)
    return base
montage_phones(["brief","now","people"]).save(OUT/"iphone_montage.png")

# tour: phone stays fixed & centered; screens crossfade in place (never off-screen)
print("iphone crossfade seq...")
W,H = 1080,1350
fps=30; hold=24; cf=12
pbg = D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
def phone_on_bg(card, title=None, sub=None):
    b = pbg.copy()
    sc = D.shadow(card, blur=36, alpha=140)
    cap=150; rt=96
    cy = rt + (H-cap-rt-sc.height)//2
    b.paste(sc, ((W-sc.width)//2, max(rt-40, cy)), sc)
    if title:
        dd=ImageDraw.Draw(b); dd.text((W//2,H-cap+66),title,font=D.font(30),fill=D.BRAND,anchor="mm")
        if sub: dd.text((W//2,H-cap+106),sub,font=D.font(19,False),fill=D.DIM,anchor="mm")
    return b
prendered={k:phone_on_bg(iph_cards[k],t,s) for k,t,s in PHONE_TOUR}
pkeys=[k for k,_,_ in PHONE_TOUR]
fi=0
for idx,key in enumerate(pkeys):
    cur=prendered[key]
    for f in range(hold): cur.save(OUT/"iphone/seq"/f"f_{fi:04d}.png"); fi+=1
    nxt=prendered[pkeys[(idx+1)%len(pkeys)]]
    for f in range(cf):
        t=(f+1)/(cf+1)
        Image.blend(cur,nxt,t).save(OUT/"iphone/seq"/f"f_{fi:04d}.png"); fi+=1
print("iphone seq frames",fi)

# ============================ Mac ===========================================
print("mac frames...")
mac_cards={}
for key,title,sub in MAC_TOUR:
    card=D.macwindow(load("PANEL",key),title="DreamLayer",win_w=1240)
    mac_cards[key]=card
    poster=D.scene(card,1680,1400,title=title,sub=sub)
    poster.save(OUT/"mac"/f"{key}.png")

# mac hero montage: two stacked windows
def montage_mac(a,b,W=1600,H=1120):
    base=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
    for i,(k,dx,dy) in enumerate([(b,210,-40),(a,-140,40)]):
        c=mac_cards[k]; s=(W*0.58)/c.width
        cc=c.resize((int(c.width*s),int(c.height*s)),Image.LANCZOS)
        sc=D.shadow(cc,blur=38,alpha=150)
        base.paste(sc,((W-sc.width)//2+dx,(H-sc.height)//2+dy),sc)
    return base
montage_mac("view_home","view_reach").save(OUT/"mac_montage.png")

# mac scroll: crossfade between views
print("mac crossfade seq...")
W,H=1680,1400
mbg=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),W,H).convert("RGB")
def mac_on_bg(card,title=None,sub=None):
    b=mbg.copy(); sc=D.shadow(card,blur=40,alpha=150)
    cap=150; rt=96
    cy=rt+(H-cap-rt-sc.height)//2
    b.paste(sc,((W-sc.width)//2,max(rt-40,cy)),sc)
    if title:
        dd=ImageDraw.Draw(b); dd.text((W//2,H-cap+66),title,font=D.font(30),fill=D.BRAND,anchor="mm")
        if sub: dd.text((W//2,H-cap+106),sub,font=D.font(19,False),fill=D.DIM,anchor="mm")
    return b
rendered={k:mac_on_bg(mac_cards[k],t,s) for k,t,s in MAC_TOUR}
fi=0; hold=20; cf=10
keys=[k for k,_,_ in MAC_TOUR]
for idx,key in enumerate(keys):
    cur=rendered[key]
    for f in range(hold): cur.save(OUT/"mac/seq"/f"f_{fi:04d}.png"); fi+=1
    nxt=rendered[keys[(idx+1)%len(keys)]]
    for f in range(cf):
        t=(f+1)/(cf+1)
        Image.blend(cur,nxt,t).save(OUT/"mac/seq"/f"f_{fi:04d}.png"); fi+=1
print("mac seq frames",fi)
print("DONE")
