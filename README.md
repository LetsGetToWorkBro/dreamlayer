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
| Living promises | **Commitment Drift** | Commitments are HUD physics objects — bloom, crack, and shatter by behavior and time |
| Living light | **Palette Cycling** | The demoscene trick: the quiet sky flows like an aurora by recolouring slots, not redrawing pixels — zero-cost motion on-device |
| Personal RPG | **Saga** | Commitments become quests: complete them for XP, build streaks, rescue one from the brink for a bonus |
| Hands-free how-to | **Wayfinding** | A step list compiled to a verified Figment you tap through; timed steps advance themselves |
| Your own truth | **Candor** | The inward twin of Truth Lens: new statements checked against your own memories — never the cloud — flagging when they can't both be true |
| Belief genealogy | **Provenance Lens** | Point it at a claim and it traces where that belief entered your head — who told you, when, corroborated or contested |
| Wonder | **Prism Lens** | Turns the world into a reactive psychedelic overlay — kaleidoscopic, sound- and motion-driven, built on palette cycling |
| Invisible UI | **Object Lens** | Look at a thing → a contextual panel: what you already know about it, plus pluggable integrations (laptop files, tire pressure). Objects only, never people |

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
