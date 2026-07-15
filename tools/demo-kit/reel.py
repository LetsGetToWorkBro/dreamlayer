"""A punchy DreamLayer reel for Discord: the REAL HUD on the circular Halo
display, cycling its signature moments over a dim, illustrative world. Outputs
a square circular-lens frame sequence; ffmpeg encodes MP4 + GIF. Also drops a
few hero stills. Honesty rule holds: the interface is the real renderer.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen
from dreamlayer.demo.scene import Scene, Beat, _compose_frame, _overlay_for

OUT = Path(sys.argv[1]); (OUT/"frames").mkdir(parents=True, exist_ok=True)
S = 720                                   # square circular lens
ENV, MUL = "world", 0.5                   # the signature dusk-street world
FPS = 24

# the story: wake -> answer -> check -> remember -> brief -> protect
BEATS = [
    ("listening",     "Say the word — Juno wakes."),
    ("juno_reply",    "Ask anything; the answer lands on the glass."),
    ("fact_check",    "It flags a claim that doesn't hold up — live."),
    ("object_recall", "Where you left it, by place and time."),
    ("morning_brief", "Your day, the moment you put them on."),
    ("privacy_veil",  "One gesture and it keeps nothing."),
]
HOLD, FADE, GAP = 2.6, 0.4, 0.15
scene = Scene("dreamlayer_reel", size=(1080, 1080), fps=FPS)
t = 0.2
for key, _ in BEATS:
    scene.beats.append(Beat(key, t, t+FADE+HOLD, anchor=(0.5, 0.5), width=0.66, fade=FADE))
    t += FADE + HOLD + GAP
DUR = t

MODE = sys.argv[2] if len(sys.argv) > 2 else "world"   # "world" (glass) | "black" (device)
disc, dome, glint = gen._lens_maps(S)
dome_a = np.asarray(dome, np.float32)/255.0
glint_a = np.asarray(glint, np.float32)
disc_a = (np.asarray(disc, np.float32)/255.0)[..., None]
# a faint bezel ring so the black disc still reads as a round display
_yy, _xx = np.mgrid[0:S, 0:S].astype(np.float32)
_r = np.hypot(_xx-S/2, _yy-S/2)
bezel = np.clip(1.0 - np.abs(_r-(S/2-3))/2.0, 0, 1)[..., None] * np.array([28, 44, 48], np.float32)

def compose(t):
    if MODE == "black":
        plate = np.zeros((S, S, 3), np.float32)
        rgb = np.asarray(_compose_frame(plate, overlays, t, (S, S), 1.0), np.float32)
        rgb = rgb*disc_a + bezel                    # clean round display + thin bezel
        return np.clip(rgb, 0, 255)
    rgb = np.asarray(_compose_frame(world_plate, overlays, t, (S, S), 1.0), np.float32)
    rgb = rgb*dome_a; rgb = np.clip(rgb+glint_a*0.5, 0, 255); rgb = rgb*disc_a
    return np.clip(rgb, 0, 255)

world_plate = gen.photo_plate(ENV, (S, S), MUL, blur=3.2)
overlays = [(b, _overlay_for(b, S)) for b in scene.beats]
n = int(DUR*FPS)
for f in range(n):
    Image.fromarray(compose(f/FPS).astype(np.uint8), "RGB").save(OUT/"frames"/f"f_{f:04d}.png")
print("frames", n, "dur", round(DUR, 1), "S", S, "mode", MODE)

# hero stills: the held mid-frame of three signature cards
def still(key, name):
    global overlays
    b = Beat(key, 0.0, FADE+HOLD, anchor=(0.5, 0.5), width=0.66, fade=FADE)
    overlays = [(b, _overlay_for(b, S))]
    Image.fromarray(compose(FADE+HOLD*0.6).astype(np.uint8), "RGB").save(OUT/f"still_{name}.png")
for k, nm in [("fact_check", "factcheck"), ("object_recall", "recall"), ("juno_reply", "juno")]:
    still(k, nm)
print("stills done")
