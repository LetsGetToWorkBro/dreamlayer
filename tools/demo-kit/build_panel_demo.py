"""Frame the captured Brain-panel 'Your API' feature as the Mac app + phase
captions, and encode. Input: /tmp/panel_shots/seq/*.png  Output: <out>/frames + note."""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image, ImageDraw
import devices as D

SEQ=Path("/tmp/panel_shots/seq")
OUT=Path(sys.argv[1]); (OUT/"frames").mkdir(parents=True,exist_ok=True)
frames=sorted(SEQ.glob("f_*.png")); N=len(frames)
CW,CH=1240,1560
BRAND=D.BRAND; INK=D.INK; DIM=D.DIM

def caption(fi):
    if fi<10:   return ("Your API","point the Brain at any chat API — it becomes your primary answerer")
    if fi<36:   return ("Plug in a local agent","LM Studio · Hermes · vLLM — anything OpenAI-compatible")
    if fi<64:   return ("On your device","questions never leave · keeps working in incognito")
    if fi<116:  return ("Or a cloud provider","OpenAI · Anthropic · Gemini · OpenRouter — one dropdown")
    if fi<149:  return ("A local box on your LAN","point at a vLLM endpoint — back on-device")
    return ("Local stays private","remote is flagged, counted, and off in incognito")

# precompute the branded background + window shadow position (window size constant)
sample=D.macwindow(Image.open(frames[0]).convert("RGB"), title="DreamLayer · Brain", win_w=760)
WINSZ=sample.size
sh=D.shadow(sample, blur=34, alpha=140)
BASE=D.scene(Image.new("RGBA",(1,1),(0,0,0,0)),CW,CH).convert("RGB")
d0=ImageDraw.Draw(BASE)
d0.text((CW//2,150),"Plug in any API as your brain",font=D.font(36),fill=INK,anchor="mm")
WIN_X=(CW-sh.width)//2; WIN_Y=210

for i,fp in enumerate(frames):
    win=D.macwindow(Image.open(fp).convert("RGB"), title="DreamLayer · Brain", win_w=760)
    sc=D.shadow(win, blur=34, alpha=140)
    b=BASE.copy()
    b.paste(sc,(WIN_X,WIN_Y),sc)
    d=ImageDraw.Draw(b)
    t,s=caption(i)
    d.text((CW//2,CH-118),t,font=D.font(30),fill=BRAND,anchor="mm")
    d.text((CW//2,CH-78),s,font=D.font(19,False),fill=DIM,anchor="mm")
    b.save(OUT/"frames"/f"f_{i:04d}.png")
print("panel demo frames",N,"winsize",WINSZ)
