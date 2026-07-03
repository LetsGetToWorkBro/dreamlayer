"""demo/scene.py — turn a storyboard into export-ready HUD overlays.

A Scene is a timed list of Beats; each Beat is a *real* HUD card placed on the
frame for a stretch of time. `render_scene` exports, for a compositor (DaVinci /
After Effects / Premiere):

  overlays/beat_NN.png   the real card as an emissive, transparent overlay
  manifest.json          the EDL — when/where each overlay appears, with fades
  preview.gif            a ready-to-watch preview over a synthetic plate
  poster.png             a single key frame

Drop your first-person footage under the overlays, blend Screen/Add, and match
the manifest timing — the HUD is your actual UI, pixel-for-pixel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

from .emissive import emissive, glow, add_over
from .plate import synth_plate


@dataclass
class Beat:
    """One HUD element on screen: a real card, when it shows, where, and how big."""
    card: Union[dict, str]          # a card dict, or an ALL_SAMPLES key
    t_in: float                     # seconds — appears
    t_out: float                    # seconds — clears
    anchor: tuple = (0.5, 0.44)     # fractional center on the frame (x, y)
    width: float = 0.42             # card width as a fraction of frame width
    fade: float = 0.3               # fade in/out seconds
    glow: bool = True
    label: str = ""                 # optional note for the manifest / storyboard


@dataclass
class Scene:
    name: str
    beats: list = field(default_factory=list)
    size: tuple = (1080, 1920)      # 9:16 by default
    fps: int = 30
    note: str = "Drop POV footage under the overlays; blend Screen/Add."

    def duration(self) -> float:
        return max((b.t_out for b in self.beats), default=0.0)


def _resolve_card(card: Union[dict, str]) -> dict:
    if isinstance(card, dict):
        return card
    from ..hud.cards import ALL_SAMPLES
    if card not in ALL_SAMPLES:
        raise KeyError(f"unknown card sample: {card!r}")
    return ALL_SAMPLES[card]


def _overlay_for(beat: Beat, frame_w: int) -> Image.Image:
    """The real card → emissive, glowed, scaled to the beat's on-screen width."""
    from ..hud import renderer as R
    card = _resolve_card(beat.card)
    em = emissive(R.render(card))
    if beat.glow:
        em = glow(em)
    target_w = max(8, int(frame_w * beat.width))
    scale = target_w / em.width
    return em.resize((target_w, max(1, int(em.height * scale))), Image.LANCZOS)


def _fade_gain(t: float, beat: Beat) -> float:
    if beat.fade <= 0:
        return 1.0
    up = min(1.0, (t - beat.t_in) / beat.fade)
    down = min(1.0, (beat.t_out - t) / beat.fade)
    return max(0.0, min(up, down))


def render_scene(scene: Scene, out_dir, preview_scale: float = 0.25,
                 preview_fps: int = 10) -> dict:
    """Export overlays + manifest + preview.gif + poster.png. Returns the manifest."""
    out = Path(out_dir)
    (out / "overlays").mkdir(parents=True, exist_ok=True)
    fw, fh = scene.size

    overlays = []          # (beat, full-res emissive overlay)
    beats_manifest = []
    for i, beat in enumerate(scene.beats):
        ov = _overlay_for(beat, fw)
        name = f"overlays/beat_{i:02d}.png"
        ov.save(out / name)
        overlays.append((beat, ov))
        beats_manifest.append({
            "id": f"beat_{i:02d}",
            "overlay": name,
            "card_type": _resolve_card(beat.card).get("type", ""),
            "t_in": round(beat.t_in, 3),
            "t_out": round(beat.t_out, 3),
            "anchor": [round(beat.anchor[0], 4), round(beat.anchor[1], 4)],
            "width": beat.width,
            "fade": beat.fade,
            "label": beat.label,
        })

    manifest = {
        "name": scene.name,
        "size": [fw, fh],
        "fps": scene.fps,
        "duration": round(scene.duration(), 3),
        "blend": "screen",
        "note": scene.note,
        "beats": beats_manifest,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    _write_preview(scene, overlays, out / "preview.gif",
                   preview_scale, preview_fps)
    _write_poster(scene, overlays, out / "poster.png")
    return manifest


def _compose_frame(plate_rgb: np.ndarray, overlays, t: float,
                   size, scale: float) -> Image.Image:
    w, h = size
    acc = plate_rgb.copy()
    for beat, ov in overlays:
        if beat.t_in <= t < beat.t_out:
            gain = _fade_gain(t, beat)
            if gain <= 0:
                continue
            sov = ov.resize((max(1, int(ov.width * scale)),
                             max(1, int(ov.height * scale))), Image.LANCZOS)
            cx, cy = beat.anchor[0] * w, beat.anchor[1] * h
            acc = add_over(acc, sov, (cx, cy), gain)
    return Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8), "RGB")


def _write_preview(scene: Scene, overlays, path, scale: float, fps: int) -> None:
    w, h = int(scene.size[0] * scale), int(scene.size[1] * scale)
    plate = np.asarray(synth_plate((w, h)), dtype=np.float32)
    dur = scene.duration()
    n = max(1, int(dur * fps))
    frames = [_compose_frame(plate, overlays, f / fps, (w, h), scale)
              for f in range(n)]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, disposal=2, optimize=True)


def _write_poster(scene: Scene, overlays, path) -> None:
    w, h = scene.size
    plate = np.asarray(synth_plate((w, h)), dtype=np.float32)
    # the moment the most beats are on screen (or mid-scene)
    if scene.beats:
        t = max(scene.beats, key=lambda b: b.t_out - b.t_in)
        mid = (t.t_in + t.t_out) / 2.0
    else:
        mid = 0.0
    _compose_frame(plate, overlays, mid, (w, h), 1.0).save(path)
