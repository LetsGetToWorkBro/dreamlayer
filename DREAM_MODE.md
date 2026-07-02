# Dream Mode — Developer Guide

Dream Mode is a continuous ambient perception layer that runs in parallel with
DreamLayer's normal memory engine.  Instead of responding to user queries, it
listens to the environment (mic, camera, IMU, place) and renders the emotional
texture of the world directly onto the glasses display.

## Architecture

```
OrchestratorDreamMode
  double_tap event
    └─ enter_dream() / exit_dream()
         └─ DreamEngine.start() / .stop()
              └─ _loop() at 2 Hz
                   ├─ MicReactor    → palette BLE frame
                   ├─ ImuReactor    → geometry BLE frame
                   ├─ GhostLayer    → WorldAnchorCard
                   └─ SceneDescriber → SynesthesiaCard (every 4s)

Sensor feed-in (from Orchestrator):
  on_audio_frame(transcript, context={mic_fft, mic_amplitude})
  on_scene_frame(scene={camera_jpeg, imu_pose, imu_delta})
  on_place(signature)  →  feed_place(sig, anchors)

BLE frames sent to Halo:
  {t: "dream_enter"}          clears display, starts dream render loop
  {t: "palette", colors: [...]}  reassigns 16-color palette slots in real time
  {t: "geometry", mode, intensity, yaw_rate, pitch_rate}
  {t: "sprite", data: <packed TxSprite>}   4bpp indexed bitmap
  {t: "dream_exit"}           restores normal card UI

Halo Lua (dream_renderer.lua):
  apply_palette_shift(colors)  — frame.display.assign_color_ycbcr()
  draw_frame()                 — 24-particle system + 8-vector line field
  render_world_anchor(card)    — ghost text at bottom of display
  render_synesthesia(card)     — 6-word VLM hero text
  on_sprite(msg)               — frame.display.bitmap() via TxSprite
```

## Quick Start

```python
# Install dream dependencies
pip install dreamlayer[dream]

# Dream Mode activates automatically on double_tap event from glasses.
# To trigger manually in tests / CLI:
from dreamlayer.orchestrator.orchestrator import Orchestrator
orc = Orchestrator(bridge)
orc.enter_dream()

# Feed sensors:
orc.on_audio_frame("", context={"mic_fft": fft_data, "mic_amplitude": 0.6})
orc.on_scene_frame({"camera_jpeg": jpeg_bytes, "imu_pose": pose})
orc.on_place("kitchen_001")

# Exit:
orc.exit_dream()
```

## Card Types

| Card | Priority | Description |
|------|----------|-------------|
| `SynesthesiaCard` | URGENT | 6-word VLM poetic scene description, updates every ~4s |
| `WorldAnchorCard` | CONTEXT | Ghost memory echo at current location, 20% opacity, 8s dismiss |
| `PaletteShiftCard` | AMBIENT | Mic-reactive palette animation command |

## Display Rendering

Dream Mode uses a two-tier render model:

- **Fast layer (~50ms)**: Palette animation + geometry (particles + line field).  
  Driven by `MicReactor` and `ImuReactor` at 2 Hz.  Costs ~300 bytes BLE per update.
- **Slow layer (~2-3s)**: Generated bitmap via `TxSprite` + `frame.display.bitmap()`.  
  Driven by `SceneDescriber` and `SpriteBridge`.  Costs ~4-8 KB BLE per frame.

The fast layer always runs.  The slow layer fires only when a camera frame is
available and the 4-second scene interval has elapsed.

## Adding a New Dream Reactor

1. Create `host-python/src/dreamlayer/app/dream/my_reactor.py`
2. Implement `tick(ctx: RecallContext) -> Optional[dict]` returning a BLE command dict or card dict
3. Import and instantiate in `DreamEngine.__init__`
4. Call `my_reactor.tick(ctx)` in `DreamEngine._tick()`
5. Add a Lua handler in `host_comm_dream.lua` if you need a new `t=` type

## Fallback Behaviour

- `brilliant-msg` not installed: `SpriteBridge` no-ops silently, palette + geometry still work
- No API key: `SceneDescriber` falls back to cycling mood phrases
- No camera frame: `SceneDescriber` skips entirely
- Privacy Veil: `GhostLayer` suppresses all ghost overlays

## Hardware Notes

- `frame.display.bitmap()` confirmed via Halo SDK sprite pipeline (`TxSprite.from_indexed_png_bytes`)
- Max sprite size: 256×256 px, 4bpp (16 colors)
- BLE MTU: 240 bytes; `brilliant-msg` handles chunking + ACK flow control automatically
- Target round-trip: camera → LFM2-VL → sprite → display ≤ 3s on modern phone
- Swap `gpt-4o-mini` for `liquid/lfm2-vl-450m` in `vision.py` once Liquid API is stable
