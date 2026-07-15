"""Place each VO block (sliced from the chosen take) at its video section start
and mux onto the re-timed render.
Usage: vo_mix.py <take.mp3> <video.mp4> <out.mp4>"""
from __future__ import annotations
import json, subprocess, sys

TAKE, VIDEO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BLOCKS = sys.argv[4] if len(sys.argv) > 4 else "/tmp/blocks_t2.json"
SECTS_PATH = sys.argv[5] if len(sys.argv) > 5 else "/tmp/yt/sections.json"
blocks = {b["name"]: b for b in json.load(open(BLOCKS))}
sects = json.load(open(SECTS_PATH))
PAD = 0.25          # breath after each section starts before speech lands
PRE = 0.12          # pre-roll kept before each block's first word

ins, filts, mixes = ["-i", VIDEO], [], []
n = 1
for name, vstart in sorted(sects.items(), key=lambda kv: kv[1]):
    b = blocks[name]
    ss = max(0.0, b["s"] - PRE)
    dur = (b["e"] - ss) + 0.15
    ins += ["-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", TAKE]
    delay = int((vstart + PAD) * 1000)
    filts.append(f"[{n}:a]adelay={delay}|{delay},apad=whole_dur=200[a{n}]")
    mixes.append(f"[a{n}]")
    n += 1
fc = ";".join(filts) + f";{''.join(mixes)}amix=inputs={n-1}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
cmd = ["ffmpeg", "-y", *ins, "-filter_complex", fc,
       "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
       "-shortest", OUT]
subprocess.run(cmd, check=True, capture_output=True)
print("muxed ->", OUT)
for name, vstart in sorted(sects.items(), key=lambda kv: kv[1]):
    print(f"  {name:>13} @ {vstart+PAD:6.2f}s  ({blocks[name]['dur']:.2f}s)")
