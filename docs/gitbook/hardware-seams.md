# Hardware and seams

DreamLayer is a **pre-hardware build**: the intelligence stack is complete
and tested (1,803 passing tests), and the handful of places where physical
hardware plugs in are explicit, narrow, and documented. This chapter is the
honest matrix.

## The target device: Brilliant Labs Halo

The Halo is a lightweight heads-up display with a circular additive
waveguide, camera, microphone, IMU, a button, and an on-glass Lua runtime
with a 16-slot runtime-writable palette (1,024 luma tiers per slot). All of
`halo-lua/` is written against its `frame` API through a compatibility
adapter (`halo-lua/compat/frame_adapter.lua`), and the repo runs that exact
Lua today inside a software rasterizer (`bridge/lua_raster.py`, via lupa) —
which is how every device-path image in this book was produced, and how the
draw-budget, richness, and reduce-motion contracts are enforced in CI.

Nothing in the stack is Halo-exclusive by design: the glasses' contract is
"render these card dicts, return these events," so any glasses with a
display runtime, BLE, and the basic sensors could host the same experience.

## Deployment tooling that exists today

- `scripts/upload.py` — deploys `halo-lua/` to a Halo over BLE
  (`brilliant-ble` tooling).
- `scripts/halo_bridge.py` — plays scripted Lab scenarios on a real Halo
  over BLE (bleak).
- `FIRST_DEVICE_TEST_PLAN.md` — the written on-glass calibration plan
  (fonts, pane luma, aurora amplitude, IMU units — each isolated to one
  constant table).

## The matrix

### Implemented and tested (no hardware required)

- All 33 bespoke device card renderers plus the never-black fallback, the
  Horizon, Dream rendering, materials,
  motion, palettes, budgets — exercised through the real device Lua in the
  raster harness.
- The entire orchestrator: Oracle grammar and persona, user model, Veritas,
  Truth Lens fusion and baselines, Discernment, answer-ahead, attention,
  anticipation, ledger, commitments, scrub, Social Lens matching and consent
  grammar, privacy gates.
- The Brain server: every endpoint, the index, config, pairing, saga,
  profile mirror, schedulers, backup/restore; live-HTTP tested.
- The phone app's store, screens, pairing codec (byte-compatible with
  Python), design system.
- The demo/film pipeline, golden images, motion exporters.

### Device seams (logic built and tested; physical signal to wire)

| Seam | Plugs in at | What a device build supplies |
|---|---|---|
| BLE render + input | `bridge/` <-> `halo-lua/ble/` | the radio link; cards down, gestures up (framing already matched on both sides) |
| Microphone + ASR | `hear(text)`, `ingest_caption(text)` | on-device speech-to-text and acoustic wake-word spotting |
| Camera frames | `on_scene_frame`, `look_at_object`, `look_at_person` | frames from the glasses camera |
| Face embedding | `load_contact_faces(face_embed_fn)`, Social Lens | a 512-d on-NPU face embedder (MobileFaceNet-class) |
| Truth Lens face / voice channels | `observe_face(frame)`, `observe_voice(mic_fft, amplitude)` | AU frames and prosody from device sensors |
| Wake signals | `activate(source)` | tap / gaze / raise detection; the wear/wake signal for the brief |
| Scrub gesture | `scrub(direction)` | the twist/tap that drives rewind |
| Earcons + haptics | card payload fields | the speaker and actuator (files ship in the phone app; visual analogs drawn today) |
| IMU parallax and gestures | `display/parallax.lua`, `app/imu_gesture.lua` | real `frame.imu_data()` — logic is EMA-normalized and nil-guarded; units recalibrate in one constant |
| Live context feed | `start_pulse(context_fn)` | place / people-in-view / clock context for anticipation and attention |
| macOS readers | `server/macos_sources.py` | Messages (chat.db), Mail (.emlx), Calendar / Contacts / Reminders (AppleScript) — real on macOS, empty lists elsewhere |
| macOS send | `send_message(approved=True)` | osascript dispatch, only ever on explicit approval |
| Cloud verify / answers | `verify.py`, cloud tier | an Ollama install and/or an OpenAI-compatible key — plumbing, gating, parsing all built |
| Phone notifications | `services/notify.ts` | permission on a real device |
| Reach-anywhere relay | pairing `relay_url` + `brainFetch` | any secure tunnel to the Brain; client already prefers LAN and falls back |
| OCR + translation models | Rosetta / Puente | the recognition and translation models behind the seams |
| Tier-0 NPU perception | `ai_brain/perception.py: NpuPerceptor` | a Vela-compiled model for the Halo's Ethos-U55; the heuristic tier answers until then |
| GhostMode radio | `confluence/mesh.py: MeshTransport` | the LE Coded PHY group transport; an in-memory bus stands in today |
| MIDI bridge | plugin `midi_out` seams (Face Synth, Air Drums) | python-rtmidi or an OSC bridge; plugins stay dormant without one |

### Pre-hardware (interaction model built; live cross-device streaming pending)

- **Confluence live bonds and the GhostMode mesh** — the engines, wire
  messages, crypto, and phone UI exist; live streaming between physically
  separate wearers is pending the radio.
- **Rehearsal deploys** — the phone Rehearsal screen is now live end to end
  against the Brain's `rc/*` endpoints (rehearse, keep, deploy, revoke);
  deploys record their BLE envelopes until the glasses transport attaches.
- **On-glass calibration** — pane luma, aurora amplitude, `DEVICE_FONT`
  metrics, and IMU gain are single-table constants explicitly flagged for
  tuning on real glass.

## Things people ask about that are not in the codebase

An EMG wristband input, health sensing, and additional lens packs (Health,
Focus, Skill) appear in roadmap discussions but have **no code** in this
repository today. This book documents what exists.
