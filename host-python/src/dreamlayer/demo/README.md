# DreamLayer demo overlays

Turn the **real** HUD into compositing-ready overlays for a first-person demo
video. The HUD is always the actual renderer output — this tool never fakes the
UI, which matters double for a product whose headline feature is a fact-checker.

## Why not just generate the video with AI?

Text-to-video (Sora, Veo, Runway…) makes gorgeous POV footage but *cannot*
render your exact cards or your product's real behavior — it hallucinates generic
overlays. So the pipeline is a **hybrid composite**: an AI- or camera-shot POV
*plate* underneath, and your **real rendered HUD** on top, keyed to look like
waveguide light.

## What it exports

```
python -m dreamlayer.demo <storyboard> <out_dir>
python -m dreamlayer.demo --list
```

For each scene:

- `overlays/beat_NN.png` — each real card as an **emissive** overlay: black keyed
  to transparent, alpha = brightness, soft bloom. Drops over footage with a
  **Screen / Add** blend and reads as light on the world.
- `manifest.json` — the EDL: when/where each overlay appears (`t_in`, `t_out`,
  fractional `anchor`, `width`, `fade`), plus `blend` and `fps`.
- `preview.gif` — a ready-to-watch preview over a synthetic night plate.
- `poster.png` — a single key frame.

## Compositing (DaVinci Resolve — free — or After Effects / Premiere)

1. Drop your POV footage on the base track.
2. Import `overlays/*.png` above it; set blend mode **Screen** (or **Add**).
3. Place each by the manifest's `t_in`/`t_out` and `anchor` (fractions of frame
   w/h), scale to `width` (fraction of frame width), add the `fade`.
4. Layer the earcons (`phone-app/assets/sounds`) on the beats and a voiceover.

Authoring a new scene is a few lines — see `storyboards.py`.
