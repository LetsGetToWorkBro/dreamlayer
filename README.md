# DreamLayer

> *A memory layer for the real world.*

DreamLayer is the software stack for [Brilliant Labs](https://brilliant.xyz/) Halo smart glasses. It gives you ambient memory, precision analysis lenses, and programmable AR behaviors — all running on-device, privately.

---

## Experience Layers

| Layer | Name | What it does |
|---|---|---|
| Ambient state | **Dream Mode** | Passive listening, background sensing, double-tap entry point |
| Memory resurfacing | **Ghost Layer** | WorldAnchorCards, memory echoes, contextual recalls |
| Clear retrieval | **Lucid Recall** | On-demand face/name/fact answer cards |
| Behavior builder | **Reality Compiler** | Rehearsal: perform a behavior once, a verified Figment runs it forever |
| Sleep cycle | **REM** | The glasses dream the day recombined — and the dreaming IS memory consolidation |
| Time scrub | **Yesterlight** | Roll your head back: the room replays its own recorded light |
| Voice shapes | **Timbre** | Known voices glow as waveforms at the rim; strangers are static |
| Future ghosts | **Premonition** | Your rhythms shimmer ahead of the now-notch, precision-gated |
| Your climate | **Inner Weather** | Your body churns the core; the room storms the rim |
| Two wearers | **Confluence** | Bonded skies entangle: converge and they merge, drift and they split |

## Precision Lenses

| Lens | What it does |
|---|---|
| **Truth Lens** | 9-stage multimodal deception analysis: face → AU → voice → linguistic → fusion → HUD |
| **Social Lens** | Contact face-binding, real-time labeling, per-contact baselines |

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
result = sl.identify(camera_frame)  # on double-tap
card = result.to_hud_card()

# Lucid Recall — on-demand queries
from dreamlayer.lucid_recall import LucidRecall

lr = LucidRecall(social_lens=sl)
result = lr.query("Who is this?", camera_frame=frame)
card = result.to_hud_card()
```

## Privacy

- All processing on-device (phone). Nothing leaves the device by default.
- No stranger identification. Social Lens only matches your personal contacts.
- Audio, video, and embeddings are never stored or transmitted.
- Privacy gate (`allow_capture()`) respected across all lenses.

## Internal Engine

`dreamlayer/` — memory storage, pipelines, orchestration (internal name, unchanged)  
`halo_bridge.py` — BLE hardware transport layer

## Roadmap

Future lenses: **Health Lens** · **Focus Lens** · **Skill Lens**

---

*DreamLayer is built for Brilliant Labs Halo. Internal engine: DreamLayer.*
