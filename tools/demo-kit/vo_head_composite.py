"""Overlay all lip-synced webcam bubbles onto the voiced cut in one encode.
Reads /tmp/blocks_t2.json + /tmp/yt/sections.json + /tmp/yt/heads/<name>.mp4.
Usage: vo_head_composite.py <voiced.mp4> <out.mp4> [crop=340] [y0=324]"""
from __future__ import annotations
import json, subprocess, sys

VID, OUT = sys.argv[1], sys.argv[2]
CROP = int(sys.argv[3]) if len(sys.argv) > 3 else 340
Y0 = int(sys.argv[4]) if len(sys.argv) > 4 else 324
PAD = 0.25
blocks = {b["name"]: b for b in json.load(open("/tmp/blocks_t2.json"))}
sects = json.load(open("/tmp/yt/sections.json"))
order = sorted(sects.items(), key=lambda kv: kv[1])

ins = ["-i", VID]
for name, _ in order:
    ins += ["-i", f"/tmp/yt/heads/{name}.mp4"]
ins += ["-loop", "1", "-i", "/tmp/yt/mask300.png", "-loop", "1", "-i", "/tmp/yt/ring308.png"]
N = len(order)
mi, ri = N + 1, N + 2

f = [f"[{mi}:v]format=gray,split={N}" + "".join(f"[mk{k}]" for k in range(N)),
     f"[{ri}:v]split={N}" + "".join(f"[rg{k}]" for k in range(N))]
cur = "[0:v]"
for k, (name, vstart) in enumerate(order):
    b = blocks[name]
    ss = max(0.0, b["s"] - 0.12)
    dur = (b["e"] - ss) + 0.10
    S = vstart + PAD
    E = S + dur
    f.append(f"[{k+1}:v]crop={CROP}:{CROP}:0:{Y0},scale=300:300,setpts=PTS+{S:.2f}/TB[hv{k}]")
    f.append(f"[hv{k}][mk{k}]alphamerge[ha{k}]")
    f.append(f"{cur}[ha{k}]overlay=1580:696:enable='between(t,{S:.2f},{E:.2f})':eof_action=pass[o{k}]")
    f.append(f"[o{k}][rg{k}]overlay=1576:692:enable='between(t,{S:.2f},{E:.2f})'[p{k}]")
    cur = f"[p{k}]"
fc = ";".join(f)
cmd = ["ffmpeg", "-y", *ins, "-filter_complex", fc,
       "-map", cur, "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
       "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", "-t", "92.47", OUT]
r = subprocess.run(cmd, capture_output=True)
if r.returncode: print(r.stderr.decode()[-1200:]); sys.exit(1)
print("composited ->", OUT)
for name, vstart in order:
    print(f"  {name:>13} bubble @ {vstart+PAD:6.2f}s")
