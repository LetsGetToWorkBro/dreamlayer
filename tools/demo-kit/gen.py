"""Regenerate DreamLayer gitbook HUD assets as ANIMATED webp, using the codebase's
own animation (demo.scene easing + emissive add-over), composited over a dim,
blurred lens ENVIRONMENT plate (the same landing/assets/sim/lens_*.webp used on
the site). No fisheye. Upscaled for gitbook quality. The interface is the real
renderer; the environment behind it is illustrative.
"""
from __future__ import annotations
import sys, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host-python/src"))
SIM = ROOT / "landing/assets/sim"
HELP = Path(__file__).resolve().parent / "docimg"

from dreamlayer.hud import renderer as R          # noqa: E402
from dreamlayer.hud.cards import ALL_SAMPLES       # noqa: E402
from dreamlayer.demo.emissive import emissive, glow  # noqa: E402
from dreamlayer.demo.scene import _compose_frame, Beat, _overlay_for, _ease  # noqa: E402
from dreamlayer.demo.catalog import feature_scenes, master_scene, FEATURES   # noqa: E402

LENS = {"world": SIM/"lens_world.webp", "face": SIM/"lens_face.webp",
        "park": SIM/"lens_park.webp", "answer": SIM/"lens_answer.webp",
        "fact": SIM/"lens_fact.webp", "brief": SIM/"lens_brief.webp",
        "alt": SIM/"lens_alt.webp"}


def photo_plate(kind: str, size, mul: float, blur: float = 3.0) -> np.ndarray:
    """A dim, blurred, teal-graded environment plate at `size` = (w,h)."""
    w, h = int(size[0]), int(size[1])
    im = Image.open(LENS[kind]).convert("RGB")
    tar = w / h
    if im.width / im.height > tar:                 # crop width
        nw = int(round(im.height * tar)); x = (im.width - nw)//2
        im = im.crop((x, 0, x+nw, im.height))
    else:                                          # crop height
        nh = int(round(im.width / tar)); y = (im.height - nh)//2
        im = im.crop((0, y, im.width, y+nh))
    im = im.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(im, dtype=np.float32)
    # gentle contrast + teal push, then dim
    a = (a - 128.0) * 1.16 + 128.0
    a[..., 2] *= 1.06                              # a touch of blue/teal
    a[..., 0] *= 0.98
    a *= mul
    return np.clip(a, 0, 255)


def _save_webp(frames, path, durations, quality=86):
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, quality=quality, method=4)


# ---- demo catalog: real multi-beat scene over a portrait environment ----------
def render_demo(scene, kind, out, scale, fps, mul):
    w, h = int(scene.size[0]*scale), int(scene.size[1]*scale)
    plate = photo_plate(kind, (w, h), mul, blur=max(2.0, 3.0*scale/0.4))
    overlays = [(b, _overlay_for(b, scene.size[0])) for b in scene.beats]
    n = max(1, int(scene.duration()*fps))
    frames = [_compose_frame(plate, overlays, f/fps, (w, h), scale) for f in range(n)]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _save_webp(frames, out, int(1000/fps))
    return len(frames), w, h


# ---- circular glass lens: a single real card, eased in + held + out -----------
_DISC = _DOME = _GLINT = None
def _lens_maps(S):
    global _DISC, _DOME, _GLINT
    if _DISC is None or _DISC.size != (S, S):
        _DISC = Image.open(HELP/"mask2.png").convert("L").resize((S, S), Image.LANCZOS)
        _DOME = Image.open(HELP/"sphere3.png").convert("RGB").resize((S, S), Image.LANCZOS)
        _GLINT = Image.open(HELP/"glint2.png").convert("RGB").resize((S, S), Image.LANCZOS)
    return _DISC, _DOME, _GLINT


def _overlay_from_image(img_rgb, target_w):
    em = glow(emissive(img_rgb))
    s = target_w / em.width
    return em.resize((target_w, max(1, int(em.height*s))), Image.LANCZOS)


def render_lens(card_img, kind, out, mul, S=480, hold=2.0, fade=0.34, fps=12):
    """card_img: PIL RGB of the real HUD render. Ease-in→hold→ease-out loop,
    masked to a glass disc with dome shading + glint. No fisheye."""
    disc, dome, glint = _lens_maps(S)
    dome_a = np.asarray(dome, dtype=np.float32)/255.0
    glint_a = np.asarray(glint, dtype=np.float32)
    disc_a = (np.asarray(disc, dtype=np.float32)/255.0)[..., None]
    plate = photo_plate(kind, (S, S), mul, blur=3.4)
    beat = Beat(card={"type": "x"}, t_in=0.0, t_out=fade+hold+fade, anchor=(0.5, 0.5),
                width=0.9, fade=fade, glow=True)
    ov = _overlay_from_image(card_img, int(S*0.9))
    dur = fade+hold+fade
    n = max(1, int(dur*fps))
    frames, durs = [], int(1000/fps)
    for f in range(n):
        t = f/fps
        rgb = np.asarray(_compose_frame(plate, [(beat, ov)], t, (S, S), 1.0),
                         dtype=np.float32)
        rgb = rgb * dome_a                          # dome shading (multiply)
        rgb = np.clip(rgb + glint_a*0.5, 0, 255)     # specular glint (add)
        rgb = rgb * disc_a                           # mask to disc (opaque black outside)
        frames.append(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _save_webp(frames, out, durs)
    return len(frames), S


def render_demo_lens(scene, kind, out, mul, S=512, fps=12, anchor=(0.5, 0.5),
                     width=0.72):
    """Same real scene animation as render_demo, but framed as a circular glass
    lens (square, dome shading + glint, no fisheye) to match the cards."""
    disc, dome, glint = _lens_maps(S)
    dome_a = np.asarray(dome, dtype=np.float32)/255.0
    glint_a = np.asarray(glint, dtype=np.float32)
    disc_a = (np.asarray(disc, dtype=np.float32)/255.0)[..., None]
    plate = photo_plate(kind, (S, S), mul, blur=3.4)
    # re-anchor/scale the real beats into the square lens frame
    beats = []
    for b in scene.beats:
        beats.append(Beat(card=b.card, t_in=b.t_in, t_out=b.t_out, anchor=anchor,
                          width=width, fade=b.fade, glow=b.glow, label=b.label))
    overlays = [(b, _overlay_for(b, S)) for b in beats]
    n = max(1, int(scene.duration()*fps))
    frames, durs = [], int(1000/fps)
    for f in range(n):
        rgb = np.asarray(_compose_frame(plate, overlays, f/fps, (S, S), 1.0),
                         dtype=np.float32)
        rgb = rgb * dome_a
        rgb = np.clip(rgb + glint_a*0.5, 0, 255)
        rgb = rgb * disc_a
        frames.append(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _save_webp(frames, out, durs)
    return len(frames), S


# feature id -> environment (mirrors the static-card mapping)
FEAT_ENV = {
    "veritas":"fact","truth_gauge":"fact","deviation":"fact",
    "dossier":"face","rim_faces":"face","captions":"face","consent":"face",
    "oracle_wake":"answer","oracle_do":"answer","answer_ahead":"answer","wake":"brief",
    "hark":"world","anchor":"park","ready":"world",
    "veil":"alt","zone":"alt",
    "commitment":"alt","drift":"alt","object":"alt","proactive":"alt",
    "saved":"alt","rewind":"alt","inner":"alt",
}
FEAT_MUL = {"fact":0.6,"face":0.58,"answer":0.5,"brief":0.5,"world":0.5,"park":0.54,"alt":0.44}


# card/device basename -> (environment, plate brightness) — ported from the
# original static-lens mapping so each feature keeps its fitting backdrop.
def card_env(base: str):
    A=("answer",0.5); F=("fact",0.6); FA=("face",0.58); BR=("brief",0.5)
    W=("world",0.5); PK=("park",0.54); AL=("alt",0.46)
    m = {
      "answer_ahead":A,"answer_ahead_device":A,"oracle_reply":A,"scholar_answer":A,
      "scholar_explain":A,"scholar_form":A,"scholar_device":A,"scholar_unavailable_device":A,
      "glance_choice":A,"glance_choice_device":A,
      "fact_check":F,"fact_check_device":F,"truth_gauge":F,"deviation_alert":F,
      "testimony_elevated":F,"testimony_truthful":F,"live_caption":F,
      "person_context":FA,"person_context_v2":FA,"person_dossier":FA,"person_dossier_device":FA,
      "consent_required":FA,"taste":FA,"taste_device":FA,"spoken_caption":FA,"spoken_caption_device":FA,
      "morning_brief":BR,"morning_brief_device":BR,
      "hark":W,"hark_device":W,"ready":W,"horizon_idle_day":W,
      "world_anchor":PK,
      "privacy_veil":("alt",0.24),"horizon_idle_paused":("alt",0.24),
      "private_zone":("alt",0.3),
    }
    return m.get(base, AL)


def build_all(out_root: Path, hi=True):
    from dreamlayer.hud.cards import ALL_SAMPLES
    cards_dir = ROOT/"docs/gitbook/assets/cards"
    dev_dir = ROOT/"docs/gitbook/assets/device"
    (out_root/"cards").mkdir(parents=True, exist_ok=True)
    (out_root/"device").mkdir(parents=True, exist_ok=True)
    (out_root/"demo/catalog/master").mkdir(parents=True, exist_ok=True)
    import subprocess
    def clean_png(relpath):
        p = subprocess.run(["git","-C",str(ROOT),"show",f"d58edd7~1:{relpath}"],
                           capture_output=True)
        if p.returncode != 0: return None
        from io import BytesIO
        return Image.open(BytesIO(p.stdout)).convert("RGB")
    S = 512 if hi else 384
    # lens cards + device
    for kind, d in (("cards", cards_dir), ("device", dev_dir)):
        for f in sorted(d.glob("*.png")):
            base = f.stem
            env, mul = card_env(base)
            if base in ALL_SAMPLES:
                img = R.render(ALL_SAMPLES[base]).convert("RGB")
            else:
                img = clean_png(f"docs/gitbook/assets/{kind}/{base}.png")
                if img is None:
                    print("  !! no clean source for", kind, base); continue
            render_lens(img, env, out_root/kind/f"{base}.webp", mul=mul, S=S)
        print(f"{kind}: done")
    # demo features (real scenes) + master
    fs = feature_scenes()
    for fid, scene in fs.items():
        env = FEAT_ENV.get(fid, "alt"); mul = FEAT_MUL[env]
        (out_root/"demo/catalog/features"/fid).mkdir(parents=True, exist_ok=True)
        render_demo(scene, env, out_root/"demo/catalog/features"/fid/"preview.webp",
                    scale=0.5, fps=12, mul=mul)
    print("features: done")
    render_demo(master_scene(), "world", out_root/"demo/catalog/master/preview.webp",
                scale=0.42, fps=11, mul=0.5)
    print("master: done")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if what == "all":
        OUTALL = Path(sys.argv[2])
        build_all(OUTALL)
        sys.exit(0)
    if what in ("demolens", "demolens-sample"):
        OUTD = Path(sys.argv[2])
        fs = feature_scenes()
        if what == "demolens-sample":
            for fid in ("veritas", "dossier", "oracle_do"):
                env = FEAT_ENV.get(fid, "alt")
                print(fid, render_demo_lens(fs[fid], env, OUTD/f"{fid}.webp",
                                            mul=FEAT_MUL[env]))
            print("master", render_demo_lens(master_scene(), "world",
                                             OUTD/"master.webp", mul=0.5, fps=11))
            sys.exit(0)
        for fid, scene in fs.items():
            env = FEAT_ENV.get(fid, "alt")
            render_demo_lens(scene, env,
                             OUTD/"demo/catalog/features"/fid/"preview.webp",
                             mul=FEAT_MUL[env])
        print("features: done")
        render_demo_lens(master_scene(), "world",
                         OUTD/"demo/catalog/master/preview.webp", mul=0.5, fps=11)
        print("master: done")
        sys.exit(0)
    OUT = Path("/tmp/demo-kit-out")
    if what == "sample":
        # master hero (portrait, real scene, upscaled)
        print("master:", render_demo(master_scene(), "world", OUT/"master.webp",
                                      scale=0.42, fps=11, mul=0.5))
        # a couple of lens cards, rendered fresh from the real renderer
        for key, env in [("fact_check","fact"), ("oracle_reply","answer"),
                          ("morning_brief","brief")]:
            img = R.render(ALL_SAMPLES[key]).convert("RGB")
            print(key, render_lens(img, env, OUT/f"{key}.webp",
                                   mul=FEAT_MUL[env], S=480))
        # one feature clip (real scene)
        fs = feature_scenes()
        print("feat veritas:", render_demo(fs["veritas"], "fact",
                                            OUT/"feat_veritas.webp", scale=0.5, fps=12, mul=0.6))
