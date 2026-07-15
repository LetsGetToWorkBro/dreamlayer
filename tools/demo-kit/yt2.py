"""Install video v2: real GH release page -> DMG -> drag to Applications ->
open -> full-depth tab tour. Screen-recording fidelity: macui menu bar/dock/
Finder, no caption overlays. Streams to ffmpeg.
Inputs: /tmp/yt/gh (seq+meta), /tmp/yt/tour2 (seq)
Usage: python yt2.py /tmp/yt/dreamlayer_010_install_v2.mp4
"""
from __future__ import annotations
import sys, json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices as D
import macui as M

GH=Path("/tmp/yt/gh"); TOUR=Path("/tmp/yt/tour2")
OUTMP4=sys.argv[1] if len(sys.argv)>1 else "/tmp/yt/dreamlayer_010_install_v2.mp4"
W,H=1920,1080; FPS=30; TEAL=(44,199,164)

def wallpaper():
    top=np.array((18,24,28),float); bot=np.array((6,9,11),float)
    ar=np.linspace(0,1,H)[:,None,None]
    base=Image.fromarray(np.repeat((top*(1-ar)+bot*ar).astype(np.uint8),W,axis=1),"RGB")
    glow=Image.new("L",(W,H),0)
    dg=ImageDraw.Draw(glow)
    dg.ellipse([W*0.15,-H*0.55,W*0.7,H*0.35],fill=60)
    dg.ellipse([W*0.55,H*0.4,W*1.25,H*1.3],fill=34)
    glow=glow.filter(ImageFilter.GaussianBlur(240))
    return Image.composite(Image.blend(base,Image.new("RGB",(W,H),TEAL),0.12),base,glow)
WALL=wallpaper()

def base(appname,running=("finder",)):
    im=WALL.convert("RGBA")
    M.menubar(im,appname,W)
    M.dock(im,W,H,running=running)
    return im

def cursor(im,x,y):
    d=ImageDraw.Draw(im,"RGBA")
    pts=[(4,2),(4,20),(8.6,15.4),(11.6,22),(14.4,20.8),(11.5,14.4),(18,14)]
    d.polygon([(x+px,y+py) for px,py in pts],fill=(255,255,255,255),outline=(11,11,11,255))
    return im

def ripple(im,x,y,t):
    d=ImageDraw.Draw(im,"RGBA")
    r=6+t*26; a=int(200*(1-t))
    d.ellipse([x-r,y-r,x+r,y+r],outline=(47,212,196,a),width=3)
    return im

def ease(t): return t*t*(3-2*t)

ff=subprocess.Popen(["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),
    "-i","-","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-movflags","+faststart",OUTMP4],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
NF=0
def emit(im):
    global NF
    ff.stdin.write(im.convert("RGB").tobytes()); NF+=1

# =============== phase A: the release page ===============
meta=json.loads((GH/"meta.json").read_text())
gfr=sorted((GH/"seq").glob("f_*.png"))
bw=D.browserwindow(Image.open(gfr[0]),url="github.com/LetsGetToWorkBro/dreamlayer/releases/tag/v0.1.0",win_w=1520)
BW,BH=bw.size; WX,WY=(W-BW)//2,40
SH=D.shadow(Image.new("RGBA",(BW,BH),(0,0,0,255)),blur=30,alpha=130); SPAD=(SH.width-BW)//2
A_BASE=base("Safari"); A_BASE.alpha_composite(SH,(WX-SPAD,WY-SPAD))
cur=[1720.0,940.0]
def a_frame(i,cx=None,cy=None,rip=None,shelf=None):
    im=A_BASE.copy()
    win=D.browserwindow(Image.open(gfr[i]),url="github.com/LetsGetToWorkBro/dreamlayer/releases/tag/v0.1.0",win_w=1520)
    im.alpha_composite(win,(WX,WY))
    if shelf is not None:
        d=ImageDraw.Draw(im,"RGBA")
        sx,sy,sw,sh=WX+BW-380,WY+70,352,64
        d.rounded_rectangle([sx,sy,sx+sw,sy+sh],radius=12,fill=(30,34,39,248),outline=(70,76,82,255),width=1)
        ic=M.ic_dreamlayer(40); im.alpha_composite(ic,(sx+12,sy+12))
        d.text((sx+64,sy+18),"DreamLayer.dmg",font=M.font(16),fill=(238,242,244),anchor="lm")
        if shelf<1.0:
            d.rounded_rectangle([sx+64,sy+38,sx+sw-16,sy+46],radius=4,fill=(52,58,64,255))
            d.rounded_rectangle([sx+64,sy+38,sx+64+int((sw-80)*shelf),sy+46],radius=4,fill=TEAL+(255,))
        else:
            d.text((sx+64,sy+44),"57.5 MB · Done",font=M.font(13,False),fill=(160,170,176),anchor="lm")
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    if cx is not None: cur[0],cur[1]=cx,cy
    return cursor(im,cur[0],cur[1])

for i in range(len(gfr)):
    emit(a_frame(i))
link=meta.get("link") or {"x":760,"y":600}
tx,ty=WX+link["x"],WY+62+link["y"]
sx0,sy0=cur[0],cur[1]
for k in range(1,23):
    e=ease(k/22)
    emit(a_frame(len(gfr)-1,cx=sx0+(tx-sx0)*e,cy=sy0+(ty-sy0)*e))
for k in range(9): emit(a_frame(len(gfr)-1,rip=k/9))
for k in range(56): emit(a_frame(len(gfr)-1,shelf=min(1.0,k/48)))
for k in range(22): emit(a_frame(len(gfr)-1,shelf=1.0))
print("A",NF)

# =============== phase B: DMG window, drag to Applications ===============
B_BASE=base("Finder")
DW,DH=780,470; DX,DY=(W-DW)//2,(H-DH)//2-40
dsh=D.shadow(Image.new("RGBA",(DW,DH),(0,0,0,255)),blur=30,alpha=140); dpad=(dsh.width-DW)//2
B_BASE.alpha_composite(dsh,(DX-dpad,DY-dpad))
ICON=M.ic_dreamlayer(120); APPF=M.folder_icon(124)
icon_home=(DX+160,DY+150); appf_pos=(DX+DW-290,DY+150)
def b_frame(icon_alpha=255,drag_ghost=None,progress=None,rip=None):
    im=B_BASE.copy()
    fw,_,bar=M.finder_window(DW,DH,"DreamLayer",sidebar=False)
    d=ImageDraw.Draw(fw)
    d.text((DW//2,DH//2+34),"→",font=M.font(66),fill=(130,140,146),anchor="mm")
    im.alpha_composite(fw,(DX,DY))
    d2=ImageDraw.Draw(im,"RGBA")
    ic=ICON.copy()
    if icon_alpha<255:
        ic.putalpha(ic.split()[-1].point(lambda p:int(p*icon_alpha/255)))
    im.alpha_composite(ic,icon_home)
    d2.text((icon_home[0]+60,icon_home[1]+142),"DreamLayer",font=M.font(15,False),fill=(225,230,234),anchor="mm")
    im.alpha_composite(APPF,appf_pos)
    d2.text((appf_pos[0]+62,appf_pos[1]+142),"Applications",font=M.font(15,False),fill=(225,230,234),anchor="mm")
    if drag_ghost:
        gh=ICON.copy(); gh.putalpha(gh.split()[-1].point(lambda p:int(p*0.6)))
        im.alpha_composite(gh,(int(drag_ghost[0]-60),int(drag_ghost[1]-60)))
    if progress is not None:
        pw,ph=440,92; px,py=(W-pw)//2,DY+DH+30
        d2.rounded_rectangle([px,py,px+pw,py+ph],radius=12,fill=(40,43,48,252),outline=(74,80,86,255),width=1)
        ic2=M.ic_dreamlayer(34); im.alpha_composite(ic2,(px+16,py+16))
        d2.text((px+62,py+26),"Copying “DreamLayer” to “Applications”",font=M.font(14,False),fill=(235,238,242),anchor="lm")
        d2.rounded_rectangle([px+62,py+52,px+pw-20,py+62],radius=5,fill=(58,64,70,255))
        d2.rounded_rectangle([px+62,py+52,px+62+int((pw-82)*progress),py+62],radius=5,fill=TEAL+(255,))
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    return cursor(im,cur[0],cur[1])

for k in range(26): emit(b_frame())
tx,ty=icon_home[0]+60,icon_home[1]+60
sx0,sy0=cur[0],cur[1]
for k in range(1,19):
    e=ease(k/18); cur[0],cur[1]=sx0+(tx-sx0)*e,sy0+(ty-sy0)*e
    emit(b_frame())
gx,gy=appf_pos[0]+62,appf_pos[1]+62
for k in range(1,33):
    e=ease(k/32); cx,cy=tx+(gx-tx)*e,ty+(gy-ty)*e
    cur[0],cur[1]=cx,cy
    emit(b_frame(icon_alpha=140,drag_ghost=(cx,cy)))
for k in range(9): emit(b_frame(rip=k/9))
for k in range(42): emit(b_frame(progress=min(1.0,k/34)))
for k in range(12): emit(b_frame())
print("B",NF)

# =============== phase C: Applications grid, double-click ===============
C_BASE=base("Finder")
AW,AH=980,560; AX,AY=(W-AW)//2,(H-AH)//2-40
ash=D.shadow(Image.new("RGBA",(AW,AH),(0,0,0,255)),blur=30,alpha=140); apad=(ash.width-AW)//2
C_BASE.alpha_composite(ash,(AX-apad,AY-apad))
GRID=[("Safari",M.ic_safari),("Mail",M.ic_mail),("Messages",M.ic_messages),("Photos",M.ic_photos),
      ("Calendar",M.ic_calendar),("Notes",M.ic_notes),("Music",M.ic_music),("Settings",M.ic_settings),
      ("DreamLayer",M.ic_dreamlayer)]
_ICONS={n:f(64) for n,f in GRID}
def c_frame(selected=False,rip=None):
    im=C_BASE.copy()
    fw,sb,bar=M.finder_window(AW,AH,"Applications",sidebar=True)
    d=ImageDraw.Draw(fw)
    cols=5; cw=(AW-sb-40)//cols
    dl_center=None
    for idx,(name,_) in enumerate(GRID):
        gx=sb+30+(idx%cols)*cw; gy=bar+34+(idx//cols)*150
        ic=_ICONS[name]
        if name=="DreamLayer" and selected:
            d.rounded_rectangle([gx-8,gy-8,gx+72,gy+72],radius=14,fill=(70,96,148,120))
            d.rounded_rectangle([gx+32-62,gy+80,gx+32+62,gy+102],radius=6,fill=(70,96,148,255))
        fw.alpha_composite(ic,(gx,gy))
        d.text((gx+32,gy+91),name,font=M.font(13,False),fill=(232,236,240),anchor="mm")
        if name=="DreamLayer": dl_center=(AX+gx+32,AY+gy+32)
    im.alpha_composite(fw,(AX,AY))
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    return cursor(im,cur[0],cur[1]),dl_center

fr,dlc=c_frame()
for k in range(20): emit(fr)
tx,ty=dlc
sx0,sy0=cur[0],cur[1]
for k in range(1,21):
    e=ease(k/20); cur[0],cur[1]=sx0+(tx-sx0)*e,sy0+(ty-sy0)*e
    emit(c_frame()[0])
for k in range(5): emit(c_frame(selected=True,rip=k/5)[0])
for k in range(5): emit(c_frame(selected=True)[0])
for k in range(5): emit(c_frame(selected=True,rip=k/5)[0])
for k in range(12): emit(c_frame(selected=True)[0])
print("C",NF)

# =============== phase D: the app, full-depth tour ===============
tfr=sorted((TOUR/"seq").glob("f_*.png"))
mw=D.macwindow(Image.open(tfr[0]),title="DreamLayer · Brain",win_w=1520)
MW,MH=mw.size; MX,MY=(W-MW)//2,36
msh=D.shadow(Image.new("RGBA",(MW,MH),(0,0,0,255)),blur=30,alpha=140); mpad=(msh.width-MW)//2
D_BASE=base("DreamLayer",running=("finder","dreamlayer")); D_BASE.alpha_composite(msh,(MX-mpad,MY-mpad))
first=D.macwindow(Image.open(tfr[0]),title="DreamLayer · Brain",win_w=1520)
for k in range(1,13):
    t=k/12; s=0.92+0.08*ease(t)
    im=base("DreamLayer",running=("finder","dreamlayer"))
    sw,sh=int(MW*s),int(MH*s)
    win=first.resize((sw,sh),Image.LANCZOS)
    win.putalpha(win.split()[-1].point(lambda p:int(p*t)))
    im.alpha_composite(win,(MX+(MW-sw)//2,MY+(MH-sh)//2))
    emit(im)
# per-tab frame boundaries (deterministic from yt_tour2.js) + extra holds so
# every tab has narration room; prints a timecode table for the VO script
SPANS={"home":437,"day":1304,"mind":1042,"reach":210,"privacy":0,"plugins":15,"caps":548,"learn":0,"advanced":489}
ORDER=["home","day","mind","reach","privacy","plugins","caps","learn","advanced"]
TARGET={"home":135,"day":180,"mind":180,"reach":120,"privacy":120,"plugins":120,"caps":150,"learn":120,"advanced":135}
import math
bounds=[]; idx=40   # settle frames at start of tour
for t in ORDER:
    n=20+24+math.ceil(SPANS[t]/16)+26
    bounds.append((t,idx,idx+n)); idx+=n
extra={t:max(0,TARGET[t]-(e-s)) for t,s,e in bounds}
hold_at={e-1:extra[t] for t,s,e in bounds}
timeline=[]
for i,fp in enumerate(tfr):
    im=D_BASE.copy()
    win=D.macwindow(Image.open(fp),title="DreamLayer · Brain",win_w=1520)
    im.alpha_composite(win,(MX,MY))
    emit(im)
    for t,s,e in bounds:
        if i==s: timeline.append((t,NF-1))
    if i in hold_at:
        for _ in range(hold_at[i]): emit(im)
print("D",NF)
print("TIMECODES (s):")
for t,f in timeline: print(f"  {t}: {f/FPS:.2f}")

# =============== end card ===============
for k in range(96):
    im=WALL.copy()
    d=ImageDraw.Draw(im)
    ic=M.ic_dreamlayer(96); im=im.convert("RGBA"); im.alpha_composite(ic,(W//2-48,H//2-170))
    d=ImageDraw.Draw(im)
    d.text((W//2,H//2-10),"github.com/LetsGetToWorkBro/dreamlayer",font=M.font(44),fill=(238,244,242),anchor="mm")
    d.text((W//2,H//2+58),"DreamLayer 0.1.0 · free · local · open",font=M.font(22,False),fill=(150,168,164),anchor="mm")
    emit(im)

ff.stdin.close(); ff.wait()
print("total",NF,"->",OUTMP4)
