# DreamLayer

> **A memory layer for the real world.**
> Your glasses see what you see. DreamLayer remembers it, understands it, and
> hands it back the instant you need it — privately, on your own hardware.

**Try it right now, in your browser — no hardware, no install:**

- **[The simulator](https://dreamlayer.app/simulator.html)** — the real
  renderer and the real behavior; ten seconds to your first card.
- **[The Lens Builder](https://dreamlayer.app/lens-builder.html)** — build
  something *for* the glasses in plain words, watch it run, share it as a
  link.
- **[The gallery](https://dreamlayer.app/gallery.html)** — what people have
  built, every entry running live, one tap to remix.

DreamLayer is the software stack for [Brilliant Labs](https://brilliant.xyz/)
**Halo** smart glasses. It turns a heads-up display into an ambient second
memory: it quietly keeps what matters — objects, people you were introduced
to, promises you made, where you left things — and surfaces it as a
glance-able card the moment it's useful. Everything runs on your own devices
by default; the cloud is a switch you own, not a default you accept.

**And the difference is checkable.** Every closed platform asks you to trust
it; DreamLayer's whole claim is auditable in this repository — capture is
veil-gated in code you can grep, the Brain binds to localhost until you
deliberately open it, the cloud is provably ciphertext-blind
([`docs/CLOUD.md`](docs/CLOUD.md)), and user-programmed behaviors ship as
statically-proven, signed *data* to a fixed on-glass interpreter, never as
code (the [Reality Compiler](docs/LENSES.md)). "Your glasses can't betray
you" is not a promise here; it's a property you can verify.

---

## What it feels like

- You glance at a snake plant. A soft card: *"water every 2 weeks · last done
  Tuesday."* You look at a wine label — its region, the price you paid last
  time.
- Someone says *"Hi, I'm Maya."* One deliberate moment later, Maya is yours
  to recall next time. Only people who introduce themselves; never a
  stranger lookup.
- You ask *"where did I leave the bike?"* — **north rack, 4th & Alder.**
- You promised Marcus the lease by Friday. As Friday nears, the promise
  drifts to the rim and starts to glow. You don't forget.
- Mid-thought at the workbench, the doorbell rings. *"Hold that thought."*
  Back at the bench, the glasses hand you your own last sentence, verbatim,
  unfinished: *"…the torque spike should show up when—"* Your brain finishes
  it.
- You read a menu in a language you don't speak. It reads back in yours.
- Three weeks ago your father told the lake house story you never wanted to
  lose. At the kitchen doorway a soft gold glow asks: *"What did Dad say
  about the ice?"* — and you tell it, from memory. Months later the glasses
  offer to **delete the recording**. You know it now. You burn the tape.
- One gesture and the glasses go **fully deaf and blind** — nothing seen,
  heard, or kept — until you lift it.

None of this is mind-reading. It's the ordinary loop of
*ask → see → anticipate*, made instant.

## Meet Juno

The voice of all of it is **Juno** — calm, brief, honest, and yours. Say
*"Hey Juno"* and ask, teach ("call me Sam"), command ("go incognito"),
stash ("I left my bike at the north rack"), or build ("set a timer, 30 on,
15 off, 8 rounds" — compiled into a signed on-glass behavior on the spot,
no cloud, no Brain required). When Juno doesn't know, she says so; she
never invents. What she learns about you fits on one phone screen, stays on
your devices, and is yours to erase.

She has a face, too — the small winged figure on
[dreamlayer.app](https://dreamlayer.app), in the app's welcome, and in the
corner of the Mac panel. In keeping with this project's honesty rules: the
character is brand art (an AI-produced clip), always decorative, never
presented as something the glasses render.

---

## How it's built

Four parts, each doing the thing it's best at:

```
  Halo glasses  ──BLE──▶  Phone (the hub)  ──LAN/internet──▶  Mac mini (the Brain)  ──opt-in──▶  Cloud
   the display            orchestrator,                        bigger local model +              frontier reach
   & sensors              memory, privacy gate,                your files & mail                 for the hardest,
                          the brain by default                 (runs on your LAN)                 non-personal asks
```

**Intelligence lives at the lowest tier that can do the job.** The phone
names an object instantly and offline; a connected Mac mini explains it
richly from *your* knowledge; the cloud is only ever reached for the rare,
hard, non-personal question — and only if you turned it on. Nothing marked
private ever leaves, in any configuration. Every tier runs under a measured
latency budget (naming a glance gets 350 ms), and every answer is stamped
with the tier it came from.

### The three switches

The app and the Mac panel expose the brain as three independent switches —
no confusing "mode." See [`docs/AI_BRAIN.md`](docs/AI_BRAIN.md).

| Switch | What it does | Default |
|---|---|---|
| **Mac mini** | upgrades the local brain to a bigger model **+ your indexed files** | off — *the phone is the brain* |
| **Cloud** | frontier reach for the hardest, non-personal asks | off — opt-in |
| **Incognito** | forces cloud off and pauses capture for the session | off |

Pairing the whole trio — phone + Brain + glasses — is **one code**, scanned
or pasted once.

---

## The six lenses

Everything DreamLayer does groups into six lenses — the whole product at a
glance. The canonical grouping lives in code at
[`host-python/src/dreamlayer/lenses.py`](host-python/src/dreamlayer/lenses.py);
the full breakdown is in [`docs/LENSES.md`](docs/LENSES.md).

| Lens | For | Includes |
|---|---|---|
| **Memory** | your life, remembered | Dream Mode · Ghost Layer · Lucid Recall · REM · Yesterlight · Premonition · Waypath · Ember · Stasis |
| **People** | who's around you | Social Lens · Timbre · Name Capture |
| **Truth** | what's true, and where beliefs come from | Truth Lens · Candor · Provenance |
| **World** | understand what you look at | Juno (look → know) · Label Lens · Scholar · TasteLens · AI Brain · Rosetta · Puente |
| **Life** | do, keep, and build | Commitment Drift · Saga · Reality Compiler (Rehearsal + figments) |
| **Together** | two wearers, one sky | Confluence |

(And a wider set rides alongside the registry — Retrace, Thread, Docent,
Rosetta Live, Candor Mirror, the GhostMode mesh — all in
[the knowledge base](https://letsgettoworkbro.github.io/dreamlayer-docs/lenses.html).)

Two things run **underneath** all of them:

- **Privacy Veil** — the spine. One gesture and the glasses go fully deaf
  and blind. Nothing seen, heard, or kept.
- **Atmosphere** — the ambient light and feel: Inner Weather, the Prism
  Lens, and Palette Cycling.

---

## Privacy — the contract

Privacy isn't a setting here; it's the architecture.

- **On-device by default.** The phone is the brain; a Mac mini stays on your
  LAN (and binds to localhost until you deliberately expose it); the cloud
  is off until you explicitly opt in. Nothing marked private ever leaves,
  in any mode.
- **No stranger identification.** The People lens only matches — and only
  remembers — people you were introduced to and chose to keep. No public
  database, no face lookup against the open world. *"I've met them, remind
  me,"* never *"identify this stranger."*
- **Spoken, bounded name capture.** A name is kept automatically — but only
  from a closed, offline grammar of self-introductions ("Hi, I'm Maya"), so
  only people who chose to give you their name are ever remembered. The
  Veil silences it like everything else, and "forget that" erases it.
- **Structured memory, never raw.** Audio and video are never stored or
  transmitted — DreamLayer keeps meaning, not recordings. (The local index
  keeps embeddings of *your own kept memories and contacts* on your device;
  they expire on the retention lifecycle and die with "forget that.")
- **Erased means erased.** "Forget that" evicts the vector, not just the
  row; a purge sweeps every recall-bearing store, including the phone's
  on-disk cache; Ember's burn ceremony deletes the recording and leaves
  only the cue. See [`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md).
- **One gate, honored everywhere.** `allow_capture()` / the Privacy Veil is
  respected across every lens, and third-party plugins receive only the
  `veil` event while it's down.

Some capabilities are deliberately **not built** — stranger face lookup,
voice cloning, covert recording.

---

## The software you run today

All of it works before the glasses exist:

### The phone app — the hub

Expo / React Native, seven tabs, localized in nine languages, with its own
test suite. Pair your devices, ask your brain from your pocket, point the
camera at anything (the Look tab), walk a route as a single dot of light
(Waypath), and own your privacy from one screen. No hardware yet? **Demo
Mode** fills every screen with labeled sample data, one tap to exit.

```bash
cd phone-app && npm install && npx expo start      # scan the QR with Expo Go
```

### The Mac Brain — the knowledge node

A menu-bar Mac app (a notarized .dmg on the releases page) or one command
from source, on any OS. It indexes the folders you choose, reads your
Messages and Mail if you allow it, serves a nine-view control panel, and
answers questions from *your own stuff*. Keyword search works with zero
setup; add [Ollama](docs/OLLAMA_SETUP.md) — or any of seven cloud presets,
strictly opt-in — for written answers and vision.

```bash
pip install -e ./host-python
python -m dreamlayer.ai_brain.server --token rune-birch     # open the printed URL
```

### The simulators

The [browser simulator](https://dreamlayer.app/simulator.html) is the front
door; `python -m dreamlayer.simulator` is the workbench (the real
orchestrator, ledger, and stage over a software glass); and
`python -m dreamlayer.simulator --watch my-lens/` is **Glass Desk** — a
live glass on your desk that re-renders your plugin's card on every save.

**Full walkthrough — install, run, and pair — in
[`docs/TESTING.md`](docs/TESTING.md).**

---

## Build on DreamLayer

Four doors in, shallowest first:

1. **Make a lens with no code** — the
   [Lens Builder](https://dreamlayer.app/lens-builder.html): describe what
   you want, or start from a showcase, watch it run on a live ring, then
   deploy to your Brain in one click. A lens is *data, not code* — it ships
   with a machine-verified safety card ("This behavior CANNOT: ...") and a
   plain-words list of the host powers it asked for, and every device
   re-proves it before running it. Share one as a link or QR; remixing is
   one tap in the [gallery](https://dreamlayer.app/gallery.html); the
   competitive version is [Figment Golf](https://dreamlayer.app/golf.html),
   where the server re-runs your entry and recomputes the score.
2. **Run the whole layer with no hardware** — the simulators above, or
   `pip install -e "host-python[dev]"` and the test suite. The phone app's
   Demo Mode is the same idea on your handset.
3. **Write a plugin in ten minutes** — the typed Python SDK + CLI:
   `dreamlayer plugins new my-lens` scaffolds one; `validate / preview /
   dev --watch / pack` carry it to the store, through the same five-defence
   gate the Brain runs, onto an isolation ladder (subprocess jail by
   default, OS sandbox and WASM above it).
   [`docs/SDK.md`](docs/SDK.md) is the quickstart;
   [`examples/hello-lens/`](examples/hello-lens/) is a complete, store-valid
   example that CI runs so it can't rot.
4. **Extend the engine** — optional capabilities follow one seam pattern
   ([`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)); platform surfaces are
   in [`docs/PLATFORM.md`](docs/PLATFORM.md);
   [`CONTRIBUTING.md`](CONTRIBUTING.md) has the ground rules (DCO, one
   green command, the privacy contract).

The plugin store lives at
[dreamlayer.app/plugins](https://dreamlayer.app/plugins.html) — six
official plugins today, one ranked search shared by the web, the phone,
and the API, and ratings served by a separate Worker
([api.dreamlayer.app](https://api.dreamlayer.app)) that can never ship
code.

---

## Honest numbers

| | |
|---|---|
| Host test suite | 3,022 passing (plus the phone's Jest suite and the Worker's Node suites) |
| Bespoke on-glass card renderers | 33, with a never-black fallback under every card |
| Figment interpreters in lockstep parity | 4 — Python, device Lua, browser JS, Rust `reality-core` |
| Optional capabilities, honestly reported | 42 (over 58 wired libraries), five one-click packs |
| Locales | 9, with a build-failing catalog-parity gate |
| CI gates | pytest + coverage floor, ruff + mypy, luacheck, DCO, pip-audit, cross-interpreter parity |

## Pre-hardware, and honest about it

DreamLayer is a **pre-hardware build**: every lens's logic is built and
tested (the device rendering runs through the real Lua in a raster
harness), but the physical seams — camera/mic/ASR, the on-NPU vision
models, the BLE render+input transport, the coded-PHY mesh — are wired
points, not live silicon. Features that need a second wearer or live glass
render demo state until the transport attaches. The full seam matrix is in
[the knowledge base](https://letsgettoworkbro.github.io/dreamlayer-docs/hardware-seams.html).

## Repository map

```
dreamlayer/                one product, four runtimes and their world
├── halo-lua/              the Halo display client (Lua) — the eyes & the HUD
├── host-python/           the phone hub + the Mac Brain (Python)
│   ├── src/dreamlayer/    the engine: orchestrator, ai_brain, lenses, memory,
│   │                      reality_compiler, plugins, sdk, simulator, hud, bridge
│   └── packaging/         the macOS .dmg app (py2app)
├── reality-core/          the Rust figment interpreter core (native + WASM)
├── phone-app/             the mobile app (Expo / React Native, 7 tabs, Jest suite)
├── laptop-companion/      the minimal laptop context agent
├── examples/              hello-lens (the ten-minute plugin) + example figments
├── registry/              the plugin store catalog (git-backed, validated)
├── registry-api/          the social/community Worker (api.dreamlayer.app)
├── landing/               dreamlayer.app: simulator, lens builder, gallery,
│                          golf, plugin store, playground
├── web/                   the Vite/TS site rebuild + WebBLE playground
├── docs/                  design specs, ADRs, audits, testing
│   └── gitbook/           the knowledge base source (published below)
└── scripts/               demos, exporters, the Halo lab
```

**The knowledge base** — the complete reference with real renders of every
card, screen, and panel:
**[letsgettoworkbro.github.io/dreamlayer-docs](https://letsgettoworkbro.github.io/dreamlayer-docs/)**
(source: [`docs/gitbook/`](docs/gitbook/README.md)).

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
AI Brain: [`docs/AI_BRAIN.md`](docs/AI_BRAIN.md) ·
API & device seams: [`docs/INTEGRATION.md`](docs/INTEGRATION.md) ·
Product spec: [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) ·
Lenses: [`docs/LENSES.md`](docs/LENSES.md)

## License

DreamLayer is open source under the [Apache License 2.0](LICENSE) — the
whole repository, engine and lenses alike, with an explicit patent grant.
The "DreamLayer" name and mark are reserved (see [NOTICE](NOTICE)); forks
must use their own. Contributions are welcome under the DCO — start with
[CONTRIBUTING.md](CONTRIBUTING.md), and see
[docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md) for governance and the project's
open-source posture.

---

*Built for Brilliant Labs Halo. Yours to run, yours to keep.*
