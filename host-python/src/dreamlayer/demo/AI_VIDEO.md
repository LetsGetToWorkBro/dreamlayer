# Making a viral DreamLayer video — no POV footage, AI does most of it

You don't need to film anything to make a high-quality, **honest** launch video.
The one rule that keeps it honest: **the interface on screen is always the real
DreamLayer HUD** (this tool's overlays). Everything *around* it — environments,
voice, music, motion — AI can generate. This is a *concept film*, the same thing
Apple/Meta ship at launch; it's not claiming to be raw device capture.

## Two honest formats (pick or mix)

**A · Motion-graphics teaser (zero footage, fastest).**
Just the real HUD cards + kinetic captions + our earcons over a dark plate,
choreographed to music. Render it *complete* right now:

```
python -m dreamlayer.demo the_tour out/the_tour   # eight features, ~32s
python -m dreamlayer.demo all                      # every storyboard
```

`out/the_tour/preview.gif` is already a finished clip. For posting quality,
import `out/the_tour/overlays/*.png` + `manifest.json` into any editor and export
MP4 (see Assembly).

**B · Cinematic product film (AI environments, higher ceiling).**
Same real HUD overlays, but composited over **AI-generated environment plates** —
a café, a walk, a desk — instead of the synthetic plate. The AI makes the *world*;
we supply the *true UI*.

## Who does what (AI does ~80%)

| Stage | Tool | Note |
|------|------|------|
| Script / VO copy | **Claude** | one line per feature; the `note:` field in each scene is a starting point |
| Voiceover | **ElevenLabs** | one calm narrator; ~110 wpm |
| Environment plates (format B) | **Veo 3 / Sora 2 / Kling** | 5–8s each: "POV, café table, morning light, shallow depth, no text/UI" — never ask it to draw the HUD |
| Music | **Suno / Udio** | one build to a drop; cut the reveals on the drop |
| The HUD | **this tool** | real cards → emissive overlays + manifest |
| Earcons | `phone-app/assets/sounds` | `listen1` on a hark, `watchout1` on Veritas; the tour beats can stay musical |
| Assembly | **DaVinci Resolve** (free) | Screen/Add the overlays; match `manifest.json` timing |
| Upscale/clean (optional) | **Topaz** | if plates need it |

## Assembly (Resolve)

1. **Base track:** the synthetic plate (format A) or your AI plates (format B),
   one per beat per the manifest `t_in`/`t_out`.
2. **HUD track:** import `overlays/*.png`, blend mode **Screen** (or **Add**),
   place each at its `anchor` (fractions of frame w/h), scale to `width`.
3. Add the `fade`, a touch of bloom, and the earcons on their beats.
4. Lay the VO + music; cut each reveal on the beat the card lands.
5. Export 1080×1920 (9:16) H.264.

## Keeping it honest (and un-cancellable)

- HUD = real, always. Never let an AI *draw* the interface or a fake behavior.
- Environments are clearly "a scene," not a claim of raw capture. A 1-frame
  end-card — *"Interface is real DreamLayer. Environments illustrative."* — costs
  nothing and pre-empts the "staged demo" backlash that sank Google Glass.
- Every claim maps to a shipped feature (the `note:` in each scene cites it).

## What to lead with

The **tour** for breadth (there's far more than the fact-checker), then the
single-feature clips (`veritas`, `answer_ahead`, `owe_someone`) as follow-ups —
each is one jaw-drop, 9:16, built to travel.
