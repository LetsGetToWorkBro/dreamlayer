"""Batch the full DreamLayer content kit: every feature in two channel themes,
real HUD on the black device display, human copy (no em dashes, no jargon).
  Theme A "Feature Spotlight" -> demo-vids (animated frames -> mp4/gif)
  Theme B "Sim Window"        -> building-in-public (still png)
Writes outdir/<key>/a/*.png (spotlight frames) + outdir/<key>/<key>_sim.png
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen
import emberstasis                      # registers Ember*/Stasis custom draws on emberstasis.R
from dreamlayer.hud.cards import ALL_SAMPLES
from dreamlayer.demo.scene import Beat, _compose_frame

# key -> (NAME, tagline, on-screen line, sim status line)   [human, no em dashes]
FEAT = {
 "fact_check":    ("VERITAS","live fact check","It remembers what people said, so when the story changes, you know.","runs on the glasses · nothing leaves unless you say so"),
 "juno_reply":    ("JUNO","your voice assistant","Talk to it and the answer lands right on the glass.","answers from your own stuff first · on device"),
 "object_recall": ("RETRACE","where you left it","It quietly notices where you set things down, and hands it back.","passive, no photos · kept on the glasses"),
 "morning_brief": ("MORNING BRIEF","your day on wake","Put them on and your whole day is already waiting.","built overnight while charging · all local"),
 "privacy_veil":  ("PRIVACY VEIL","one gesture, it stops","One move and it sees nothing, hears nothing, keeps nothing.","built to fail closed · you hold the switch"),
 "saved_memory":  ("KEEP","save a moment","Keep something in a blink, and it is yours, on the glasses.","pinned so cleanup never touches it · on device"),
 "spoken_caption":("CAPTIONS","every word, at the rim","The whole room, written out at the edge of your eye.","transcribed on device · nothing streamed out"),
 "person_dossier":("DOSSIER","who is this again","A glance reminds you who they are and what you last talked about.","your own contacts only, never strangers · local"),
 "hark":          ("HARK","a tap on the shoulder","One nudge for the single thing worth catching right now.","picks one thing, drops the rest · on the glasses"),
 "truth_gauge":   ("TRUTH LENS","read the room","A quiet read on how something is being said, not a verdict.","a nudge, never a lie detector · all local"),
 "ember_flare":   ("EMBER","tend a memory","It brings a moment back on a curve until it is really yours.","spaced out over time · quiet, on device"),
 "stasis":        ("STASIS","hold that thought","Get pulled away and a nod freezes exactly where your head was.","your own words back, never rewritten · no cloud"),
}
CUSTOM = ("ember_flare", "stasis")      # rendered via emberstasis' custom draws
BRAND=(44,199,164); INK=(234,243,241); DIM=(138,165,160); BG=(7,16,15)

def font(px, bold=True):
    p="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(p, px)
    except: return ImageFont.load_default()
def wrap(d,t,f,mw):
    out=[]; cur=""
    for w in t.split():
        s=(cur+" "+w).strip()
        if d.textlength(s,font=f)<=mw: cur=s
        else: out.append(cur); cur=w
    if cur: out.append(cur)
    return out

def face_for(key, S256=256):
    if key in CUSTOM:
        if key=="stasis":
            card={"type":"StasisCard","primary":"…and the torque spikes right when—","footer":"held 4 min · tilt to resume"}
        else:
            card=dict(ALL_SAMPLES[key])
        return emberstasis.R.render(card).convert("RGB")
    from dreamlayer.hud import renderer as R
    return R.render(ALL_SAMPLES[key]).convert("RGB")

def display_frames(key, S=640, fps=24, hold=3.0, fade=0.4):
    face=face_for(key)
    ov=gen._overlay_from_image(face, int(S*0.66))
    b=Beat({"type":"x"},0.0,fade+hold+fade,anchor=(0.5,0.5),width=0.66,fade=fade,glow=True)
    overlays=[(b,ov)]
    disc,_,_=gen._lens_maps(S); disc_a=(np.asarray(disc,np.float32)/255.0)[...,None]
    yy,xx=np.mgrid[0:S,0:S].astype(np.float32); r=np.hypot(xx-S/2,yy-S/2)
    bez=np.clip(1.0-np.abs(r-(S/2-3))/2.0,0,1)[...,None]*np.array([26,42,46],np.float32)
    dur=fade+hold+fade; n=int(dur*fps); out=[]
    for f in range(n):
        rgb=np.asarray(_compose_frame(np.zeros((S,S,3),np.float32),overlays,f/fps,(S,S),1.0),np.float32)
        out.append(Image.fromarray(np.clip(rgb*disc_a+bez,0,255).astype(np.uint8),"RGB"))
    return out,fps

def spotlight_bg(name,tag,line):
    W=H=1080; c=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(c)
    d.text((44,40),"DreamLayer",font=font(24),fill=INK)
    d.text((W-44,52),"for Brilliant Labs Halo",font=font(16,False),fill=DIM,anchor="rm")
    y=856; d.line([(120,y),(W-120,y)],fill=(28,60,56),width=2)
    d.text((W//2,y+34),name+"   "+tag,font=font(30),fill=BRAND,anchor="mm")
    for i,ln in enumerate(wrap(d,line,font(24,False),W-200)):
        d.text((W//2,y+82+i*34),ln,font=font(24,False),fill=DIM,anchor="mm")
    return c

def sim_window(frame,name,tag,line,note):
    circ=frame.resize((680,680)); D=680; pad=36; th=50; cap=100
    W=D+pad*2; H=th+D+cap+pad; win=Image.new("RGB",(W,H),(9,11,13)); d=ImageDraw.Draw(win)
    d.rounded_rectangle([0,0,W-1,H-1],radius=16,outline=(30,42,46),width=1)
    d.line([(0,th),(W,th)],fill=(22,32,36),width=1)
    for i,cc in enumerate([(224,95,95),(224,181,74),(86,211,100)]): d.ellipse([18+i*20,th//2-5,28+i*20,th//2+5],fill=cc)
    d.text((W//2,th//2),"DreamLayer · Halo Simulator",font=font(17),fill=(180,200,205),anchor="mm")
    win.paste(circ,(pad,th+pad//2)); cy=th+pad//2+D+18
    d.text((pad,cy),name+"  ·  "+tag,font=font(20),fill=BRAND)
    for i,ln in enumerate(wrap(d,line,font(16,False),W-2*pad)): d.text((pad,cy+30+i*22),ln,font=font(16,False),fill=DIM)
    d.text((pad,H-28),"▸ "+note,font=font(14,False),fill=(90,130,125))
    return win

if __name__=="__main__":
    OUT=Path(sys.argv[1]); keys=sys.argv[2:] or list(FEAT)
    for key in keys:
        NAME,TAG,LINE,NOTE=FEAT[key]
        frames,fps=display_frames(key)
        bg=spotlight_bg(NAME,TAG,LINE); disp_y=60
        ad=(OUT/key/"a"); ad.mkdir(parents=True,exist_ok=True)
        for i,fr in enumerate(frames):
            c=bg.copy(); c.paste(fr.resize((760,760)),((1080-760)//2,disp_y)); c.save(ad/f"f_{i:04d}.png")
        mid=frames[int(len(frames)*0.62)]
        sim_window(mid,NAME,TAG,LINE,NOTE).save(OUT/key/f"{key}_sim.png")
        print("done",key,len(frames),"frames")
