# DreamLayer

> *A memory layer for the real world.*

DreamLayer is the software stack for [Brilliant Labs](https://brilliant.xyz/) Halo smart glasses. It gives you ambient memory, precision analysis lenses, and programmable AR behaviors — all running on-device, privately.

---

## The six lenses

Everything DreamLayer does groups into six lenses — the whole product in one
glance. (The canonical grouping lives in code at `dreamlayer/lenses.py`; the
full breakdown is in [docs/LENSES.md](docs/LENSES.md).)

| Lens | For | Includes |
|---|---|---|
| 🧠 **Memory** | your life, remembered | Dream Mode · Ghost Layer · Lucid Recall · REM · Yesterlight · Premonition · Waypath Lens |
| 👤 **People** | who's around you | Social Lens · Timbre · Name Capture |
| ⚖️ **Truth** | what's true, and where beliefs come from | Truth Lens · Candor · Provenance Lens |
| 🌍 **World** | understand what you look at | Oracle · Label Lens · AI Brain · Rosetta Lens · Puente |
| 🎯 **Life** | do, keep, and build | Commitment Drift · Saga · Reality Compiler (Rehearsal + Wayfinding) |
| 🤝 **Together** | two wearers, one sky | Confluence |

Two things run underneath all of them:

- **Privacy Veil** — the spine. One gesture and the glasses go fully deaf and
  blind. Nothing seen, heard, or kept.
- **Atmosphere** — the ambient light and feel: Inner Weather, the Prism Lens,
  and Palette Cycling.

## Precision Lenses

| Lens | What it does |
|---|---|
| **Truth Lens** | 9-stage multimodal deception analysis: face → AU → voice → linguistic → fusion → HUD |
| **Social Lens** | Contact face-binding, real-time labeling, per-contact baselines, and consent-first *name-you-were-told* capture |

## Module Map

```
dreamlayer/
├── dream_mode/          # Ambient loop, Ghost Layer, WorldAnchorCards
├── lucid_recall/        # Query router → SocialLens / MemoryIndex → HUD card
├── reality_compiler/    # v1 text pipeline + v2 Rehearsal → Figment → fixed stage
├── rem/                 # The sleep cycle: dream, consolidate, morning reel
├── confluence/          # Bonds, the entangled sky, TinCan, Crossing, Duet, gifts
├── truth_lens/          # 9-stage deception analysis pipeline
├── social_lens/         # Contact recognition, labeling, baseline storage
├── object_lens/         # Look at a thing → contextual panel (objects, not people)
├── hud/                 # Card definitions, renderer, framebuffer pipeline
├── memory/              # Anchors, storage, retrieval, ranking
├── pipelines/           # Audio, vision, IMU, place context ingestion
├── orchestrator/        # Central coordinator, mode management
└── bridge/              # BLE protocol, hardware translation
```

## Quick Start

```python
# Truth Lens — deception analysis
from dreamlayer.truth_lens import TruthLens

tl = TruthLens(contact_registry=my_contacts)
tl.feed_frame(camera_frame)
tl.feed_audio(mic_fft, mic_amplitude)
tl.feed_transcript(asr_text)
result = tl.tick()
if result:
    card = result.to_hud_card()  # → HUD renderer

# Social Lens — contact recognition
from dreamlayer.social_lens import SocialLens

sl = SocialLens(contacts=my_contacts)
result = sl.identify(camera_frame)  # on double-tap — recall your own people
card = result.to_hud_card()

# Name-you-were-told capture — someone says "Hi, I'm Maya"
offer = sl.offer_introduction("hi, I'm Maya", frame=camera_frame)
if offer:                     # a name was heard; nothing saved yet
    send_to_hud(offer)
    sl.confirm_introduction()  # on a deliberate tap: Maya is now your contact

# Lucid Recall — on-demand queries
from dreamlayer.lucid_recall import LucidRecall

lr = LucidRecall(social_lens=sl)
result = lr.query("Who is this?", camera_frame=frame)
card = result.to_hud_card()
```

## Privacy

- All processing on-device (phone). Nothing leaves the device by default.
- No stranger identification. Social Lens only matches — and only remembers —
  people you were introduced to and chose to keep. No public database, no
  face lookup against the open world. "I've met them before, remind me,"
  never "identify this stranger." Name capture is voluntary (nothing saved
  without an explicit confirm), spoken (a closed offline grammar of
  self-introductions only), and silenced by the Privacy Veil.
- Audio, video, and embeddings are never stored or transmitted.
- Privacy gate (`allow_capture()`) respected across all lenses.

## Internal Engine

`dreamlayer/` — memory storage, pipelines, orchestration (internal name, unchanged)  
`halo_bridge.py` — BLE hardware transport layer

## Roadmap

Future lenses: **Health Lens** · **Focus Lens** · **Skill Lens**

---

*DreamLayer is built for Brilliant Labs Halo. Internal engine: DreamLayer.*
