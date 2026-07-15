"""Per-feature content in two channel themes, real HUD on the black device display.
  Theme A  "Feature Spotlight"  -> #demo-vids  : animated, titled, one-line explainer
  Theme B  "Sim Window"         -> #building-in-public : the Halo Simulator window + dev note
Usage: feature_kit.py <outdir> <feature_key>
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
from dreamlayer.demo.scene import Beat, _compose_frame, _overlay_for

# feature -> (card_key, NAME, tagline, explainer, dev_note)
FEAT = {
 "fact_check":   ("fact_check","VERITAS","Live fact-check","Flags a claim that contradicts what was said before — quietly, just for you.","truth_lens.py · 9-stage credibility"),
 "juno_reply":   ("juno_reply","JUNO","Ask anything","Ask out loud; the answer lands on the glass in Juno's own voice.","ai_brain/router.py · device→Mac→cloud"),
 "object_recall":("object_recall","RETRACE","Where you left it","Recall by place and time — “keys · kitchen table · 7:42pm.”","ops_commitments.py · passive sightings"),
 "morning_brief":("morning_brief","MORNING BRIEF","Your day, on wake","The moment you put them on: meetings, messages, what matters.","rem/ · overnight consolidation"),
 "privacy_veil": ("privacy_veil","PRIVACY VEIL","Keeps nothing","One gesture and it goes fully deaf and blind. Privacy is the build.","memory/privacy.py · fails closed"),
 "saved_memory": ("saved_memory","KEEP","Save a moment","Save what matters in a blink — it's yours, on-device, forever.","ingest · pinned, never expires"),
 "spoken_caption":("spoken_caption","CAPTIONS","Every word, at the rim","Live transcription of the room, drawn at the edge of your eye.","social_lens · on-device ASR"),
 "person_dossier":("person_dossier","DOSSIER","Who is this","A glance names them and surfaces your history together.","social_lens · own contacts only"),
 "hark":         ("hark","HARK","A tap on the shoulder","Listen — the one thing worth hearing, right now.","attention · single-item"),
 "truth_gauge":  ("truth_gauge","TRUTH LENS","Read the room","Delivery signals fused into one credibility read.","truth_lens/analyzer.py"),
}
BRAND = (44,199,164); INK=(234,243,241); DIM=(138,165,160); BG=(7,16,15)

def font(px, bold=True):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(p, px)
    except: return ImageFont.load_default()

def wrap(d, text, fnt, maxw):
    words=text.split(); lines=[]; cur=""
    for w in words:
        t=(cur+" "+w).strip()
        if d.textlength(t, font=fnt)<=maxw: cur=t
        else: lines.append(cur); cur=w
    if cur: lines.append(cur)
    return lines

# --- render the round black device display for a feature (frames) -----------
def display_frames(card_key, S=640, fps=24, hold=3.0, fade=0.4):
    b = Beat(card_key, 0.0, fade+hold+fade, anchor=(0.5,0.5), width=0.66, fade=fade)
    ov=_overlay_for(b, S); overlays=[(b,ov)]
    disc,_,_=gen._lens_maps(S); disc_a=(np.asarray(disc,np.float32)/255.0)[...,None]
    yy,xx=np.mgrid[0:S,0:S].astype(np.float32); r=np.hypot(xx-S/2,yy-S/2)
    bez=np.clip(1.0-np.abs(r-(S/2-3))/2.0,0,1)[...,None]*np.array([26,42,46],np.float32)
    dur=fade+hold+fade; n=int(dur*fps); out=[]
    for f in range(n):
        rgb=np.asarray(_compose_frame(np.zeros((S,S,3),np.float32),overlays,f/fps,(S,S),1.0),np.float32)
        rgb=rgb*disc_a+bez
        out.append(Image.fromarray(np.clip(rgb,0,255).astype(np.uint8),"RGB"))
    return out, fps

# --- Theme A: Feature Spotlight (demo-vids) ---------------------------------
def spotlight(frame, name, tagline, explainer):
    W=1080; H=1080; c=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(c)
    disp=frame.resize((760,760)); c.paste(disp,((W-760)//2,60))
    d.text((44,40),"DreamLayer",font=font(24),fill=INK)
    d.text((W-44,52),"for Brilliant Labs Halo",font=font(16,False),fill=DIM,anchor="rm")
    y=856; d.line([(120,y),(W-120,y)],fill=(28,60,56),width=2)
    d.text((W//2,y+34),name+"  ·  "+tagline,font=font(30),fill=BRAND,anchor="mm")
    for i,ln in enumerate(wrap(d,explainer,font(24,False),W-200)):
        d.text((W//2,y+80+i*34),ln,font=font(24,False),fill=DIM,anchor="mm")
    return c

# --- Theme B: Sim Window (building-in-public) -------------------------------
def sim_window(frame, name, explainer, dev_note):
    circ=frame.resize((680,680)); D=680; pad=36; title_h=50; cap_h=96
    W=D+pad*2; H=title_h+D+cap_h+pad
    win=Image.new("RGB",(W,H),(9,11,13)); d=ImageDraw.Draw(win)
    d.rounded_rectangle([0,0,W-1,H-1],radius=16,outline=(30,42,46),width=1)
    d.line([(0,title_h),(W,title_h)],fill=(22,32,36),width=1)
    for i,cc in enumerate([(224,95,95),(224,181,74),(86,211,100)]):
        d.ellipse([18+i*20,title_h//2-5,28+i*20,title_h//2+5],fill=cc)
    d.text((W//2,title_h//2),"DreamLayer · Halo Simulator",font=font(17),fill=(180,200,205),anchor="mm")
    win.paste(circ,(pad,title_h+pad//2))
    cy=title_h+pad//2+D+18
    d.text((pad,cy),name,font=font(20),fill=BRAND)
    for i,ln in enumerate(wrap(d,explainer,font(16,False),W-2*pad)):
        d.text((pad,cy+28+i*22),ln,font=font(16,False),fill=DIM)
    d.text((pad,H-30),"▸ "+dev_note+"  ·  on-device  ·  0 cloud calls",font=font(14,False),fill=(90,130,125))
    return win

if __name__=="__main__":
    OUT=Path(sys.argv[1]); OUT.mkdir(parents=True,exist_ok=True)
    key=sys.argv[2]; card,NAME,TAG,EXP,DEV=FEAT[key]
    frames,fps=display_frames(card)
    mid=frames[int(len(frames)*0.62)]
    # Theme A frames -> saved as sequence for ffmpeg
    (OUT/"a").mkdir(exist_ok=True)
    for i,fr in enumerate(frames): spotlight(fr,NAME,TAG,EXP).save(OUT/"a"/f"f_{i:04d}.png")
    # Theme B still
    sim_window(mid,NAME+" — "+TAG,EXP,DEV).save(OUT/f"{key}_simwindow.png")
    print("frames",len(frames),"fps",fps,"key",key)
