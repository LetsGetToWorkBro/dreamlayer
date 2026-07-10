# DreamLayer

> **A memory layer for the real world.**
> Your glasses see what you see. DreamLayer remembers it, understands it, and
> hands it back the instant you need it — privately, on your own hardware.

**Try it right now, in your browser, no hardware, no install:**
**[the DreamLayer simulator →](https://dreamlayer.app/simulator.html)** —
the real renderer, the real orchestrator behavior, ten seconds to your first
card.

DreamLayer is the software stack for [Brilliant Labs](https://brilliant.xyz/)
**Halo** smart glasses. It turns a heads-up display into an ambient second
memory: it quietly keeps what matters — objects, people you were introduced to,
promises you made, where you left things — and surfaces it as a glance-able card
the moment it's useful. Everything runs on your own devices by default; the
cloud is a switch you own, not a default you accept.

**And the difference is checkable.** Every closed platform asks you to trust
it; DreamLayer's whole claim is auditable in this repository — capture is
veil-gated in code you can grep, the cloud is provably ciphertext-blind
([`docs/CLOUD.md`](docs/CLOUD.md)), and user-programmed behaviors ship as
statically-proven, signed *data* to a fixed on-glass interpreter, never as
code (the [Reality Compiler](docs/LENSES.md)). "Your glasses can't betray
you" is not a promise here; it's a property you can verify.

---

## What it feels like

- You glance at a snake plant. A soft card: *"water every 2 weeks · last done
  Tuesday."* You look at a wine label — its region, the price you paid last time.
- Someone says *"Hi, I'm Maya."* A card offers the name; one deliberate tap and
  Maya is yours to recall next time. Nothing is saved until you say so.
- You think *"where did I leave the bike?"* — **north rack, 4th & Alder.**
- You promised Marcus the lease by Friday. As Friday nears, the promise drifts
  to the rim and starts to glow. You don't forget.
- You read a menu in a language you don't speak. It reads back in yours.
- One gesture and the glasses go **fully deaf and blind** — nothing seen, heard,
  or kept — until you lift it.

None of this is mind-reading. It's the ordinary loop of *ask → see → anticipate*,
made instant.

---

## How it's built

Four parts, each doing the thing it's best at:

```
  Halo glasses  ──BLE──▶  Phone (the hub)  ──LAN/internet──▶  Mac mini (the Brain)  ──opt-in──▶  Cloud
   the display            orchestrator,                        bigger local model +              frontier reach
   & sensors              memory, privacy gate,                your files & mail                 for the hardest,
                          the brain by default                 (runs on your LAN)                 non-personal asks
```

**Intelligence lives at the lowest tier that can do the job.** The phone names
an object instantly and offline; a connected Mac mini explains it richly from
*your* knowledge; the cloud is only ever reached for the rare, hard, non-personal
question — and only if you turned it on. Nothing marked private ever leaves,
in any configuration.

### The three switches

The app and the Mac panel expose the brain as three independent switches — no
confusing "mode." See [`docs/AI_BRAIN.md`](docs/AI_BRAIN.md) for the full model.

| Switch | What it does | Default |
|---|---|---|
| **Mac mini** | upgrades the local brain to a bigger model **+ your indexed files** | off → *the phone is the brain* |
| **Cloud** | frontier reach for the hardest, non-personal asks | on |
| **Incognito** | forces cloud off and pauses capture for the session | off |

Pairing the whole trio — phone + Brain + glasses — is **one code**, scanned or
pasted once.

---

## The six lenses

Everything DreamLayer does groups into six lenses — the whole product at a
glance. The canonical grouping lives in code at
[`host-python/src/dreamlayer/lenses.py`](host-python/src/dreamlayer/lenses.py);
the full breakdown is in [`docs/LENSES.md`](docs/LENSES.md).

| Lens | For | Includes |
|---|---|---|
| 🧠 **Memory** | your life, remembered | Dream Mode · Ghost Layer · Lucid Recall · REM · Yesterlight · Premonition · Waypath |
| 👤 **People** | who's around you | Social Lens · Timbre · Name Capture |
| ⚖️ **Truth** | what's true, and where beliefs come from | Truth Lens · Candor · Provenance |
| 🌍 **World** | understand what you look at | **Juno** (look → know) · Label Lens · **AI Brain** · Rosetta · Puente |
| 🎯 **Life** | do, keep, and build | Commitment Drift · Saga · Reality Compiler (Rehearsal + Wayfinding) |
| 🤝 **Together** | two wearers, one sky | Confluence |

Two things run **underneath** all of them:

- **Privacy Veil** — the spine. One gesture and the glasses go fully deaf and
  blind. Nothing seen, heard, or kept.
- **Atmosphere** — the ambient light and feel: Inner Weather, the Prism Lens,
  and Palette Cycling.

---

## Privacy — the contract

Privacy isn't a setting here; it's the architecture.

- **On-device by default.** The phone is the brain; a Mac mini stays on your
  LAN; the cloud is an explicit, per-session opt-in. Nothing marked private ever
  leaves, in any mode.
- **No stranger identification.** The People lens only matches — and only
  remembers — people you were introduced to and chose to keep. No public
  database, no face lookup against the open world. *"I've met them, remind me,"*
  never *"identify this stranger."*
- **Spoken, bounded name capture.** A name is kept automatically — but only
  from a closed, offline grammar of self-introductions ("Hi, I'm Maya"), so
  only people who chose to give you their name are ever remembered. The Veil
  silences it like everything else, and "forget that" erases it.
- **Structured memory, never raw.** Audio and video are never stored or
  transmitted — DreamLayer keeps meaning, not recordings. (The local index
  keeps embeddings of *your own kept memories and contacts* on your device;
  they expire on the retention lifecycle and die with "forget that." See
  [`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md).)
- **One gate, honored everywhere.** `allow_capture()` / the Privacy Veil is
  respected across every lens.

Some capabilities are deliberately **not built** — stranger face lookup, voice
cloning, covert recording. See [`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md).

---

## The software you run

Two apps, both testable today without the glasses:

### 📱 Phone app — the hub
Expo / React Native. Pair your devices, ask your brain from your pocket, and
own your privacy from one screen. Opens on the **Brain** tab.
→ [`phone-app/README.md`](phone-app/README.md) · design system in
[`phone-app/DESIGN.md`](phone-app/DESIGN.md)

```bash
cd phone-app && npm install && npx expo start      # scan the QR with Expo Go
```

### 🖥️ Mac Brain — the knowledge node
A small local server that indexes your chosen folders and mail and serves a
polished control panel. Keyword search works with zero setup; add
[Ollama](docs/OLLAMA_SETUP.md) for written answers and vision.

```bash
pip install -e ./host-python
python -m dreamlayer.ai_brain.server --token rune-birch     # open the printed URL
```

**Full walkthrough — install, run, and pair the two — in
[`docs/TESTING.md`](docs/TESTING.md).**

---

## Repository map

```
dreamlayer/                one repo, four surfaces
├── halo-lua/              the Halo display client (Lua) — the eyes & the HUD
├── host-python/           the phone hub + the Mac Brain (Python)
│   └── src/dreamlayer/    the engine (see below)
├── phone-app/             the mobile app (Expo / React Native)
├── laptop-companion/      the Mac mini installer (Ollama + launch-at-login)
├── docs/                  design, architecture, testing, per-lens specs
│   └── gitbook/           the knowledge base — full reference with real renders
└── scripts/               end-to-end demos (run_demo_*.py)
```

The Python engine, `host-python/src/dreamlayer/`:

```
orchestrator/       central coordinator + the three brain switches
ai_brain/           tiered vision + knowledge router → device / Mac mini / cloud
  └── server/       the Mac Brain: index, control panel, pairing, macOS sources
lucid_recall/       query router → SocialLens / MemoryIndex → HUD card
object_lens/        Juno + Label — look at a thing → a contextual panel
social_lens/        recognise your own people; automatic self-introduction capture
truth_lens/         9-stage multimodal deception analysis
dream_mode/         the ambient loop, Ghost Layer, world-anchored cards
rem/                the sleep cycle: dream, consolidate, morning reel
reality_compiler/   v2 Rehearsal → signed Figment → fixed on-glass stage
confluence/         bonds, the entangled sky, TinCan, weather gifts
rosetta.py          visual translation (Rosetta = eye; Puente = ear/voice)
lenses.py           the six-lens registry (the mental model, in code)
pairing.py          one code → phone + Brain + glasses
memory/ pipelines/ hud/ bridge/     storage · ingestion · rendering · BLE
```

---

## For developers

```python
# Juno — look at a thing, get a panel (objects, never people)
panel = orchestrator.look_at_object(camera_frame)      # → HUD card

# Ask your brain — folds into Lucid Recall; device → Mac mini → cloud
answer = orchestrator.ask_brain("what does Marcus owe me?")

# The three switches
orchestrator.connect_mac_mini(True)     # use the Mac mini as the local brain
orchestrator.use_cloud(False)           # keep the hardest asks off the cloud
orchestrator.set_incognito(True)        # doors shut: cloud off, capture paused

# Social Lens — recall your own people; introductions are kept automatically
result = social_lens.identify(camera_frame)            # on double-tap
kept   = social_lens.offer_introduction("hi, I'm Maya", frame=camera_frame)
# kept is the KeptCard — Maya is already your contact, dossier started
```

```bash
cd host-python && python -m pytest -q        # the full host suite (1,909 tests)
```

**Knowledge base — the complete reference with real renders of every card,
screen, and panel: [letsgettoworkbro.github.io/dreamlayer-docs](https://letsgettoworkbro.github.io/dreamlayer-docs/)
(source: [`docs/gitbook/`](docs/gitbook/README.md)).**

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
AI Brain: [`docs/AI_BRAIN.md`](docs/AI_BRAIN.md) ·
API & device seams: [`docs/INTEGRATION.md`](docs/INTEGRATION.md) ·
Product spec: [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) ·
Lenses: [`docs/LENSES.md`](docs/LENSES.md)

## Roadmap

Future lenses under exploration: **Health** · **Focus** · **Skill**.

DreamLayer is a **pre-hardware build** and honest about it: every lens's logic
is built and tested against the lupa raster harness, but the physical seams —
camera/mic/ASR, the on-NPU vision models, the BLE render+input transport, and
the coded-PHY mesh — are wired points, not live silicon. Features that depend on
a second wearer or an on-glass display (Confluence, live Reality Compiler
deploys) render demo state until the transport is attached. The full seam matrix
is in [`docs/gitbook/hardware-seams.md`](docs/gitbook/hardware-seams.md).

## Build on DreamLayer

Three doors in, shallowest first:

1. **Run the whole layer with no hardware** — the [simulator](https://dreamlayer.app/simulator.html)
   in your browser (ten seconds, zero install), or
   `pip install -e "host-python[dev]"` and the test suite. The phone app's
   Explore mode is the same idea on your handset — a labeled sample-data
   *tour*, so every screen is alive before anything is paired.
2. **Write a lens in ten minutes** — [`examples/hello-lens/`](examples/hello-lens/)
   is a complete, store-valid plugin (~25 lines) with the full tutorial: the
   capability model, local testing through the real validation gate, packaging,
   and shipping to the store. CI runs the example itself, so it can't rot.
3. **Extend the engine** — optional capabilities follow one seam pattern
   ([`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)); platform surfaces are in
   [`docs/PLATFORM.md`](docs/PLATFORM.md); [`CONTRIBUTING.md`](CONTRIBUTING.md)
   has the ground rules (DCO, one green command, privacy contract).

## License

DreamLayer is open source under the [Apache License 2.0](LICENSE) — the whole
repository, engine and lenses alike, with an explicit patent grant. The
"DreamLayer" name and mark are reserved (see [NOTICE](NOTICE)); forks must use
their own. Contributions are welcome under the DCO — start with
[CONTRIBUTING.md](CONTRIBUTING.md), and see
[docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md) for governance and the project's
open-source posture.

---

*Built for Brilliant Labs Halo. Yours to run, yours to keep.*
