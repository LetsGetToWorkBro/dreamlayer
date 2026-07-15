"""Composite the 1080p install-and-tour video:
  real GH release page (download the dmg) -> Finder drag to Applications ->
  open the app -> full tab tour of the real panel. Frames stream to ffmpeg.
Inputs: /tmp/yt/gh (seq + meta.json), /tmp/yt/tour (seq + caps.json)
Usage:  python yt.py /tmp/yt/dreamlayer_010_install.mp4
"""
from __future__ import annotations
import sys, json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices as D

GH=Path("/tmp/yt/gh"); TOUR=Path("/tmp/yt/tour")
OUTMP4=sys.argv[1] if len(sys.argv)>1 else "/tmp/yt/dreamlayer_010_install.mp4"
W,H=1920,1080; FPS=30
INK=(235,242,240); DIM=(150,168,164); TEAL=(44,199,164)

def font(px,bold=True):
    p="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p,px)

# ---------------- desktop ----------------
def wallpaper():
    top=np.array((16,22,24),float); bot=np.array((5,8,9),float)
    ar=np.linspace(0,1,H)[:,None,None]
    base=Image.fromarray(np.repeat((top*(1-ar)+bot*ar).astype(np.uint8),W,axis=1),"RGB")
    glow=Image.new("L",(W,H),0)
    ImageDraw.Draw(glow).ellipse([W*0.25,-H*0.5,W*0.75,H*0.35],fill=70)
    glow=glow.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(Image.blend(base,Image.new("RGB",(W,H),TEAL),0.10),base,glow)

def dl_icon(sz):
    im=Image.new("RGBA",(sz,sz),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle([0,0,sz-1,sz-1],radius=int(sz*0.22),fill=(10,16,17,255),outline=(40,60,58,255),width=max(1,sz//64))
    c=sz//2; r=int(sz*0.28)
    d.ellipse([c-r,c-r,c+r,c+r],outline=TEAL+(255,),width=max(2,sz//18))
    r2=int(sz*0.10); d.ellipse([c-r2,c-r2,c+r2,c+r2],fill=TEAL+(255,))
    return im

def menubar(im,appname):
    d=ImageDraw.Draw(im,"RGBA")
    d.rectangle([0,0,W,30],fill=(12,16,18,235))
    x=18
    d.text((x,15),appname,font=font(15),fill=INK,anchor="lm"); x+=d.textlength(appname,font=font(15))+26
    for m in ["File","Edit","View","Go","Window","Help"]:
        d.text((x,15),m,font=font(14,False),fill=(200,212,210),anchor="lm"); x+=d.textlength(m,font=font(14,False))+22
    d.text((W-24,15),"Wed 9:41 AM",font=font(14,False),fill=(200,212,210),anchor="rm")
    bx=W-140
    d.rounded_rectangle([bx,9,bx+26,21],radius=3,outline=(190,200,200,255),width=2)
    d.rounded_rectangle([bx+2,11,bx+18,19],radius=2,fill=(190,200,200,255))
    for i,hh in enumerate([4,7,10]):
        d.rounded_rectangle([bx-38+i*9,20-hh,bx-32+i*9,20],radius=1,fill=(190,200,200,255))
    return im

def dock(im,with_dl=False):
    d=ImageDraw.Draw(im,"RGBA")
    icons=7+(1 if with_dl else 0)
    iw=44; gap=14; total=icons*iw+(icons-1)*gap+36
    x0=(W-total)//2; y0=H-64
    d.rounded_rectangle([x0,y0,x0+total,H-10],radius=16,fill=(18,24,26,170),outline=(60,72,70,120),width=1)
    cols=[(90,110,200),(190,120,90),(110,170,120),(170,100,160),(120,150,190),(200,170,90),(120,120,130)]
    x=x0+18
    for c in cols:
        d.rounded_rectangle([x,y0+10,x+iw,y0+10+iw],radius=10,fill=c+(120,))
        x+=iw+gap
    if with_dl:
        im.paste(dl_icon(iw),(x,y0+10),dl_icon(iw))
    return im

def cursor(im,x,y,scale=1.0):
    d=ImageDraw.Draw(im,"RGBA")
    pts=[(4,2),(4,20),(8.6,15.4),(11.6,22),(14.4,20.8),(11.5,14.4),(18,14)]
    pts=[(x+px*scale,y+py*scale) for px,py in pts]
    d.polygon(pts,fill=(255,255,255,255),outline=(11,11,11,255))
    return im

def ripple(im,x,y,t):
    d=ImageDraw.Draw(im,"RGBA")
    r=6+t*26; a=int(200*(1-t))
    d.ellipse([x-r,y-r,x+r,y+r],outline=(47,212,196,a),width=3)
    return im

def narr(im,line):
    if not line: return im
    d=ImageDraw.Draw(im,"RGBA")
    f=font(23,False); pad=14
    w=d.textlength(line,font=f)
    x0,y0=54,H-64-46
    d.rounded_rectangle([x0-pad,y0-pad,x0+w+pad,y0+34],radius=10,fill=(8,12,13,200))
    d.text((x0,y0+10),line,font=f,fill=INK,anchor="lm")
    return im

def ease(t): return t*t*(3-2*t)

# ---------------- ffmpeg pipe ----------------
ff=subprocess.Popen(["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),
    "-i","-","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-movflags","+faststart",OUTMP4],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
NF=0
def emit(im):
    global NF
    ff.stdin.write(im.tobytes()); NF+=1

WALL=wallpaper()
def base(appname,with_dl=False):
    return dock(menubar(WALL.copy(),appname),with_dl)

# =============== phase A: the release page ===============
meta=json.loads((GH/"meta.json").read_text())
gfr=sorted((GH/"seq").glob("f_*.png"))
bw_probe=D.browserwindow(Image.open(gfr[0]),url="github.com/LetsGetToWorkBro/dreamlayer/releases",win_w=1520)
BW,BH=bw_probe.size; WX,WY=(W-BW)//2,42
shadow_rect=Image.new("RGBA",(BW,BH),(0,0,0,255))
SH=D.shadow(shadow_rect,blur=30,alpha=120); SPAD=(SH.width-BW)//2
A_BASE=base("Browser"); A_BASE.paste(SH,(WX-SPAD,WY-SPAD),SH)

cur=[1700.0,900.0]
def a_frame(i,narrline,cx=None,cy=None,rip=None,shelf=None):
    im=A_BASE.copy()
    win=D.browserwindow(Image.open(gfr[i]),url="github.com/LetsGetToWorkBro/dreamlayer/releases/tag/v0.1.0",win_w=1520)
    im.paste(win,(WX,WY),win)
    if shelf is not None:
        t=shelf
        d=ImageDraw.Draw(im,"RGBA")
        sx,sy,sw,sh=WX+BW-380,WY+70,352,64
        d.rounded_rectangle([sx,sy,sx+sw,sy+sh],radius=12,fill=(24,30,33,245),outline=(60,72,70,255),width=1)
        ic=dl_icon(40); im.paste(ic,(sx+12,sy+12),ic)
        d.text((sx+64,sy+18),"DreamLayer.dmg",font=font(16),fill=INK,anchor="lm")
        if t<1.0:
            d.rounded_rectangle([sx+64,sy+36,sx+sw-16,sy+44],radius=4,fill=(40,52,50,255))
            d.rounded_rectangle([sx+64,sy+36,sx+64+int((sw-80)*t),sy+44],radius=4,fill=TEAL+(255,))
        else:
            d.text((sx+64,sy+42),"57.5 MB · Done",font=font(13,False),fill=DIM,anchor="lm")
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    if cx is not None: cur[0],cur[1]=cx,cy
    cursor(im,cur[0],cur[1])
    return narr(im,narrline)

L_A1="0.1.0 just went up. installing it like a normal user, no dev tools, watch"
L_A2="one dmg. 57 megs. signed and notarized so gatekeeper doesn’t scream"
hold_assets=meta["holds"]["assets"]
for i in range(hold_assets+20):
    emit(a_frame(min(i,len(gfr)-1), L_A1 if i<hold_assets else L_A2))
# cursor moves to the dmg link and clicks
link=meta.get("link") or {"x":760,"y":600}
tx,ty=WX+link["x"],WY+62+link["y"]
sx,sy=cur[0],cur[1]
for k in range(1,19):
    e=ease(k/18)
    emit(a_frame(len(gfr)-1,L_A2,cx=sx+(tx-sx)*e,cy=sy+(ty-sy)*e))
for k in range(8):
    emit(a_frame(len(gfr)-1,L_A2,rip=k/8))
# download shelf fills
for k in range(46):
    emit(a_frame(len(gfr)-1,L_A2,shelf=min(1.0,k/38)))
for k in range(16):
    emit(a_frame(len(gfr)-1,L_A2,shelf=1.0))
print("phase A", NF)

# =============== phase B: dmg -> Applications ===============
def folder_icon(sz,label=None):
    im=Image.new("RGBA",(sz,sz),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle([2,int(sz*0.28),sz-2,sz-4],radius=int(sz*0.12),fill=(72,150,190,255))
    d.rounded_rectangle([2,int(sz*0.18),int(sz*0.45),int(sz*0.38)],radius=int(sz*0.08),fill=(90,168,208,255))
    return im

def finder_window(w,h,title):
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle([0,0,w-1,h-1],radius=12,fill=(30,34,38,255),outline=(58,64,68,255),width=1)
    d.rectangle([0,40,w-1,h-12],fill=(22,26,30,255))
    d.rounded_rectangle([0,h-24,w-1,h-1],radius=12,fill=(22,26,30,255))
    for i,cc in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        d.ellipse([16+i*22-7,20-7,16+i*22+7,20+7],fill=cc)
    d.text((w//2,20),title,font=font(15),fill=(205,215,213),anchor="mm")
    return im

B_BASE=base("Finder",with_dl=False)
DW,DH=760,430; DX,DY=(W-DW)//2,(H-DH)//2-30
dsh=D.shadow(Image.new("RGBA",(DW,DH),(0,0,0,255)),blur=30,alpha=130); dpad=(dsh.width-DW)//2
B_BASE.paste(dsh,(DX-dpad,DY-dpad),dsh)
ICON=dl_icon(120); APPF=folder_icon(120)
icon_home=(DX+150,DY+150); appf_pos=(DX+DW-270,DY+150)

def b_frame(narrline,icon_at=None,drag_ghost=None,progress=None,rip=None):
    im=B_BASE.copy()
    fw=finder_window(DW,DH,"DreamLayer")
    d=ImageDraw.Draw(fw)
    d.text((DW//2,DH//2+20),"→",font=font(64),fill=(120,134,132),anchor="mm")
    d.text((150+60,DY and 0 or 0),"",font=font(10),fill=DIM)
    im.paste(fw,(DX,DY),fw)
    im.paste(APPF,appf_pos,APPF)
    d2=ImageDraw.Draw(im)
    d2.text((appf_pos[0]+60,appf_pos[1]+140),"Applications",font=font(15,False),fill=(205,215,213),anchor="mm")
    pos=icon_at or icon_home
    im.paste(ICON,(int(pos[0]),int(pos[1])),ICON)
    d2.text((int(pos[0])+60,int(pos[1])+140),"DreamLayer",font=font(15,False),fill=(205,215,213),anchor="mm")
    if drag_ghost:
        gh=ICON.copy(); gh.putalpha(gh.split()[-1].point(lambda p:int(p*0.55)))
        im.paste(gh,(int(drag_ghost[0]-60),int(drag_ghost[1]-60)),gh)
    if progress is not None:
        pw,ph=420,86; px,py=(W-pw)//2,DY+DH+26
        d2.rounded_rectangle([px,py,px+pw,py+ph],radius=10,fill=(30,34,38,250),outline=(58,64,68,255),width=1)
        d2.text((px+18,py+24),"Copying “DreamLayer” to “Applications”",font=font(14,False),fill=INK,anchor="lm")
        d2.rounded_rectangle([px+18,py+50,px+pw-18,py+60],radius=5,fill=(46,56,54,255))
        d2.rounded_rectangle([px+18,py+50,px+18+int((pw-36)*progress),py+60],radius=5,fill=TEAL+(255,))
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    cursor(im,cur[0],cur[1])
    return narr(im,narrline)

L_B="drag. drop. that’s the install"
for k in range(14): emit(b_frame(L_B))
tx,ty=icon_home[0]+60,icon_home[1]+60
sx,sy=cur[0],cur[1]
for k in range(1,15):
    e=ease(k/14); cur[0],cur[1]=sx+(tx-sx)*e,sy+(ty-sy)*e
    emit(b_frame(L_B))
gx,gy=appf_pos[0]+60,appf_pos[1]+60
for k in range(1,25):
    e=ease(k/24); cx,cy=tx+(gx-tx)*e,ty+(gy-ty)*e
    cur[0],cur[1]=cx,cy
    emit(b_frame(L_B,drag_ghost=(cx,cy)))
for k in range(8): emit(b_frame(L_B,rip=k/8))
for k in range(34): emit(b_frame(L_B,progress=min(1.0,k/28)))
for k in range(8): emit(b_frame(L_B))
print("phase B", NF)

# =============== phase C: Applications, double-click ===============
C_BASE=base("Finder")
AW,AH=820,470; AX,AY=(W-AW)//2,(H-AH)//2-30
ash=D.shadow(Image.new("RGBA",(AW,AH),(0,0,0,255)),blur=30,alpha=130); apad=(ash.width-AW)//2
C_BASE.paste(ash,(AX-apad,AY-apad),ash)
APPS=["Automator","Books","Calculator","Calendar","DreamLayer","Font Book","Freeform","Mail"]
def c_frame(narrline,selected=False,rip=None):
    im=C_BASE.copy()
    fw=finder_window(AW,AH,"Applications")
    d=ImageDraw.Draw(fw)
    y=64
    for a in APPS:
        if a=="DreamLayer":
            if selected: d.rounded_rectangle([14,y-6,AW-14,y+30],radius=8,fill=(28,62,56,255))
            ic=dl_icon(28); fw.paste(ic,(26,y-2),ic)
        else:
            ic=folder_icon(26); fw.paste(ic,(27,y),ic)
        d.text((70,y+12),a,font=font(15,False),fill=INK if a=="DreamLayer" else (185,196,194),anchor="lm")
        y+=44
    im.paste(fw,(AX,AY),fw)
    if rip is not None: ripple(im,cur[0],cur[1],rip)
    cursor(im,cur[0],cur[1])
    return narr(im,narrline)
L_C="applications. there it is"
row_y=AY+64+4*44+12
tx,ty=AX+240,row_y
sx,sy=cur[0],cur[1]
for k in range(1,17):
    e=ease(k/16); cur[0],cur[1]=sx+(tx-sx)*e,sy+(ty-sy)*e
    emit(c_frame(L_C))
for k in range(5): emit(c_frame(L_C,selected=True,rip=k/5))
for k in range(4): emit(c_frame(L_C,selected=True))
for k in range(5): emit(c_frame(L_C,selected=True,rip=k/5))
for k in range(10): emit(c_frame(L_C,selected=True))
print("phase C", NF)

# =============== phase D: the app, full tour ===============
tfr=sorted((TOUR/"seq").glob("f_*.png"))
tcaps=json.loads((TOUR/"caps.json").read_text())
mw_probe=D.macwindow(Image.open(tfr[0]),title="DreamLayer · Brain",win_w=1520)
MW,MH=mw_probe.size; MX,MY=(W-MW)//2,38
msh=D.shadow(Image.new("RGBA",(MW,MH),(0,0,0,255)),blur=30,alpha=130); mpad=(msh.width-MW)//2
D_BASE=base("DreamLayer"); D_BASE.paste(msh,(MX-mpad,MY-mpad),msh)
# scale-in
first=D.macwindow(Image.open(tfr[0]),title="DreamLayer · Brain",win_w=1520)
for k in range(1,11):
    t=k/10; s=0.92+0.08*ease(t)
    im=base("DreamLayer")
    sw,sh=int(MW*s),int(MH*s)
    win=first.resize((sw,sh),Image.LANCZOS)
    a=win.split()[-1].point(lambda p:int(p*t))
    win.putalpha(a)
    im.paste(win,(MX+(MW-sw)//2,MY+(MH-sh)//2),win)
    emit(narr(im,"first open. nothing is set up, nothing has phoned home"))
for i,fp in enumerate(tfr):
    im=D_BASE.copy()
    win=D.macwindow(Image.open(fp),title="DreamLayer · Brain",win_w=1520)
    im.paste(win,(MX,MY),win)
    emit(narr(im,tcaps[i] if i<len(tcaps) else ""))
print("phase D", NF)

# =============== end card ===============
for k in range(84):
    im=WALL.copy()
    d=ImageDraw.Draw(im)
    d.text((W//2,H//2-40),"github.com/LetsGetToWorkBro/dreamlayer",font=font(44),fill=INK,anchor="mm")
    d.text((W//2,H//2+30),"break it, tell me how",font=font(24,False),fill=TEAL,anchor="mm")
    emit(im)

ff.stdin.close(); ff.wait()
print("total frames",NF,"->",OUTMP4)
