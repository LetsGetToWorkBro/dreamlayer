"""Frame the whole-app walkthrough (landscape viewport + caps.json) in the Mac
window with captions. Output -> <out>/frames."""
from __future__ import annotations
import sys, json
from pathlib import Path
from PIL import Image, ImageDraw
import devices as D

SEQ=Path("/tmp/panel_shots3/seq")
caps=json.loads(Path("/tmp/panel_shots3/caps.json").read_text())
OUT=Path(sys.argv[1]); (OUT/"frames").mkdir(parents=True,exist_ok=True)
frames=sorted(SEQ.glob("f_*.png")); N=len(frames)
CW,CH=1560,1330
BRAND=D.BRAND; INK=D.INK; DIM=D.DIM

sample=D.macwindow(Image.open(frames[0]).convert("RGB"), title="DreamLayer · Brain", win_w=1180)
sh0=D.shadow(sample, blur=34, alpha=140)
BASE=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),CW,CH).convert("RGB")
ImageDraw.Draw(BASE).text((CW//2,128),"Connect any agent — one tap",font=D.font(34),fill=INK,anchor="mm")
WIN_X=(CW-sh0.width)//2; WIN_Y=186

for i,fp in enumerate(frames):
    win=D.macwindow(Image.open(fp).convert("RGB"), title="DreamLayer · Brain", win_w=1180)
    sc=D.shadow(win, blur=34, alpha=140)
    b=BASE.copy(); b.paste(sc,(WIN_X,WIN_Y),sc)
    d=ImageDraw.Draw(b)
    t,s=(caps[i] if i<len(caps) else ["",""])
    if t: d.text((CW//2,CH-116),t,font=D.font(30),fill=BRAND,anchor="mm")
    if s: d.text((CW//2,CH-76),s,font=D.font(19,False),fill=DIM,anchor="mm")
    b.save(OUT/"frames"/f"f_{i:04d}.png")
print("frames",N)
