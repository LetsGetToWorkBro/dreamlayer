# DreamLayer as a platform — the five pillars

DreamLayer started as an app. This document is the plan for turning it into a
*platform*: a layer other people build on. Five workstreams, in dependency
order, each ending in shipped, tested code.

1. **Tier-0 NPU** — a real on-device model tier (Halo's Ethos-U55), so the
   cheapest tier stops being heuristics and starts being a quantized net.
2. **GhostMode mesh** — the pairwise Confluence bond, lifted to an N-wearer
   group over the long-range coded PHY. **The Beacon** ships first on it.
3. **The Plugin API** — formalise the registries and seams the codebase
   *already* has into a supported extension surface.
4. **TasteLens** — a first-party lens (shelf/menu ranked comparison) built on
   the plugin seams, with its price/review connectors as the first plugins.
5. **WebBLE playground** — drive the Lua HUD straight from a browser, no app
   store (Android/desktop; iOS Safari can't — see the caveat).

The through-line: **the codebase is already a plugin system in disguise.**
`object_lens.ProviderRegistry` (providers declare `matches`/`build`),
`orchestrator.glance.GlanceArbiter` (candidates declare `bid`), and the
`BrainRouter` tiers are all declarative registries. Everything below either
*uses* one of those seams or *formalises* it — nothing is a rewrite.

---

## Hardware ground truth

Two facts shape the whole plan; both were checked, and both correct a spec we
were carrying loosely:

- **Silicon: Alif *Balletto* B1** (not "Ensemble B1" — Balletto is the
  Ensemble-class compute *plus* an integrated BLE radio, built for wearables).
  **Cortex-M55 + Ethos-U55 NPU (~46 GOPS int8) + Helium DSP.** The NPU runs
  **quantized (int8) models** via the Vela compiler / TFLite-Micro. It is
  MobileNet-class, **not** LLM-class: perception primitives on-glass, language
  and reasoning still tier up. This is what makes "the only wearable where you
  deploy models to hardware you control" literally true.
- **Radio: BLE 5, incl. LE Coded PHY (S=8) ≈ 125 kbps, long-range, robust in
  RF-noise.** GhostMode packets are tiny (a WeatherPacket is a scalar + four
  palette slots; a gesture is one of a handful of symbols — "5 bits per
  command"). We do not want bandwidth, we want **range + robustness in a
  crowd** — exactly what coded PHY trades throughput for. It is the right
  transport for the mesh.
- **WebBLE caveat: iOS Safari does not implement Web Bluetooth.** Browser-
  direct BLE works on Chrome/Edge/Android/desktop; on iPhone the phone app
  stays the hub. WebBLE is a dev surface and a demo, never the only path.

---

## Pillar 1 — Tier-0 NPU seam

**Problem.** Today the cheapest tier (the Glance Arbiter's coarse read,
wake-word) is hand-written heuristics — `classify_coarse` over cues someone
else has to produce. The Balletto's NPU can run a real net there.

**Design.** A new *perception* seam, distinct from `VisionBrain.explain`
(which returns rich `Answer`s). Perception is fast, structured, and local:

```
Perceptor.perceive(frame) -> PerceptSignals   # face?, text_density, form grid, object?, lang
Perceptor.listen(audio)   -> AudioPercept      # wake-word conf, VAD, keyword id
```

- A `Perceptor` **Protocol** with two methods and an `is_npu: bool` /
  `tier: str` marker, mirroring `VisionBrain`/`KnowledgeBrain`.
- `HeuristicPerceptor` — ships today, wraps the existing cheap-cue logic, zero
  model. Keeps every test green with no hardware.
- `NpuPerceptor(infer_fn)` — the real seam: `infer_fn(tensor) -> dict` is where
  a Vela-compiled Ethos-U55 model (or, off-glass, an Ollama/ONNX model on the
  Mac) plugs in. The class handles quantise/dequantise and maps model output to
  `PerceptSignals`.
- A `PerceptionRouter` (same shape as `BrainRouter`) picks the best available
  perceptor: NPU on-glass → heuristic fallback. Never throws; a dead tier is
  skipped.

**Wiring.** `Orchestrator._glance_signals_fn` becomes
`self.perception.perceive(frame).as_signals()` — so the Glance Arbiter's coarse
read is model-backed when the NPU is present and heuristic when it isn't, with
**no change to the arbiter**. Wake-word routes through `listen()`.

**Why it's foundational.** Better coarse Glance (fewer needless escalations to
the phone/Mac vision tier), faster wake-word, and it's the multi-object
detector TasteLens needs to read a whole shelf.

**Tests.** Heuristic parity with today's `classify_coarse`; NPU seam is called
with the right tensor and its output maps to signals; router falls back when
the NPU is absent; veil still gates.

---

## Pillar 2 — GhostMode mesh + The Beacon

**Problem.** `confluence/bond.py` is strictly 1:1 (a pairwise HMAC from
`(bond_id, code)`). Presence at scale — a room, a group, a crowd — needs a
group.

**Design — the mesh.** A `confluence/mesh.py` layer over the existing bond:

- **Group key.** A circle of wearers derive one shared key. Reuse the bond
  handshake to admit members (propose → human code → accept → confirm), then
  fold each new member into a group secret. Same crypto family, one level up.
- **Membership.** Join/leave/expire; a quiet member fades after the same 12 s
  as a pairwise peer; the whole group expires (default 8 h) unless renewed.
- **Gossip.** Tiny packets (`WeatherPacket`, `BearingPacket`, gesture symbols)
  flood the mesh with a sequence number + short TTL, deduped by `(sender,
  seq)`. Forged / replayed / stranger traffic drops silently — the pairwise
  invariant, generalised.
- **Transport seam.** `MeshTransport.send(packet)` / `recv() -> [packet]` is
  injectable. The default is an in-memory bus (tests, demo); the real one is
  **LE Coded PHY**, phone-relayed for range. Nothing above the seam knows the
  radio.
- **The invariant holds:** only *feeling* crosses — a state scalar, palette
  slots, a bearing, a gesture symbol. **Never speech, places, or names.** The
  Veil silences your side completely.

**Design — The Beacon (ships first).** `confluence/beacon.py`:

- Each member periodically emits a `BearingPacket`: a coarse bearing + distance
  band relative to *themselves* (never absolute coordinates), signed with the
  group key.
- On receipt, the wearer renders a **pulse train at that bearing** on the rim —
  reusing TinCan's bearing-pulse renderer. Nearer = faster/brighter pulses.
- A **BeaconCard** lists who's found and roughly where ("Maya · ahead-left ·
  close"). No map, no "where are you" text. Veil-gated; only bearing/presence
  crosses.
- The Glance Arbiter gains nothing here (it's an ambient rim feature, not a
  look); the phone app gets a "Find my group" toggle that arms the Beacon.

**Tests.** Group-key derivation + round-trip; join/leave/expire; gossip dedup
and forged-packet drop; Beacon bearing → pulse-train mapping; the "only bearing
crosses" invariant; veil gate.

---

## Pillar 3 — The Plugin API

**Problem.** We have four real extension points and no supported way to plug
into them from outside core:

| Extension point | Declares | Lives in |
|---|---|---|
| Object-lens provider | `matches(sighting)` → rows | `object_lens.ProviderRegistry` |
| Glance candidate | `bid(reading, ctx)` → a lens bid | `orchestrator.glance.GlanceArbiter` |
| Brain tier | `explain` / `ask` / `perceive` | `ai_brain.BrainRouter` / PerceptionRouter |
| Card renderer | payload → HUD frame | `hud.renderer` dispatch map |

**Design.** A `plugins/` package that *formalises*, not replaces, these:

- **`Plugin` manifest** — `name`, `version`, `provides` (which extension points
  it touches), an optional `requires` (capabilities: `vision`, `mesh`, `midi`),
  and a `register(ctx)` entrypoint.
- **`PluginContext`** — the narrow, safe surface a plugin is handed:
  `add_object_provider(p)`, `add_glance_candidate(c)`, `add_brain(b)`,
  `add_card_renderer(type, fn)`, plus read-only access to the ring/veil state.
  A plugin can *extend*; it cannot reach into private orchestrator state.
- **`PluginRegistry`** — discovers plugins (entry-points / a manifest dir),
  checks `requires` against available capabilities, and calls `register(ctx)`
  during orchestrator boot. Load failures are isolated: one bad plugin never
  brings down the layer.
- **Sandbox posture (v1):** plugins are trusted in-process Python (the
  open-source ethos: read the code you run). A capability gate keeps a plugin
  that only asked for `midi` from quietly using `vision`. A real sandbox
  (subprocess / wasm) is a later hardening, noted not built.

**Core vs plugin — the rule this encodes.** A *feature* is first-party,
on-thesis, on by default, and may touch privileged state (Veil, Brain, core
stores). A *plugin* is optional, integration-specific, and only *extends*
through `PluginContext`. Crucially, **first-party features are implemented
through the same registries** — so building TasteLens on these seams
*dogfoods* the API and proves it's real.

**Tests.** Register a plugin → its provider/candidate/renderer shows up in the
right registry and fires end-to-end; a plugin that `requires` an absent
capability is skipped, not crashed; a throwing plugin is isolated.

---

## Pillar 4 — TasteLens (feature) + connectors (plugins)

**The decomposition** (the worked example of Pillar 3's rule):

- **TasteLens the lens = a first-party feature.** It is Label Lens grown up:
  look at a *whole shelf or menu* → a **ranked comparison against your rules**
  (dietary profile, budget, past purchases). It owns the multi-object read, the
  ranking, the card, and a Glance Arbiter scene/bid. It touches the Veil and
  the Brain tiers, so it is core.
- **The data it ranks against = plugins.** A reviews API, a price feed, a
  store's catalog or loyalty integration — each a `PanelProvider` (facet
  `shop`) registered through the Plugin API. These are the cloud/opt-in, the
  niche, and the risky parts — exactly what should be pluggable and off by
  default. "Your rules" stays local and first-party; "the world's data" rides
  the opt-in cloud tier, the same split Label Lens already documents.

**Design.**

- **Read.** Tier-0 NPU (Pillar 1) does the coarse multi-object pass over the
  shelf; the Brain's vision tier does the fine read (labels + attributes) only
  when the coarse read is ambiguous — the same two-tier escalation the Glance
  Arbiter already uses.
- **Rank.** A pure `rank(items, profile, providers)` — items scored by
  hard-rule matches (allergen/dietary = veto), soft preferences (budget,
  past-purchase affinity), and any `shop` provider signal (rating, price).
  Deterministic, fully unit-tested offline.
- **Surface.** A `TasteCard` — the winner highlighted, a short ranked list, and
  the *why* ("dairy-free · you bought this before · 4.6★"). A new
  `ScholarExplain`-style renderer.
- **Route.** A `TasteLensCandidate` bids when the scene is `shelf`/`menu`
  (many labels, price cues); the arbiter fires it or offers it against Juno.

**Tests.** Ranking (hard veto beats soft preference; ties broken stably); the
`shop` provider seam plugs in and shifts the order; veil gate; the arbiter
routes a shelf scene to TasteLens; no cloud call unless opted in.

---

## Pillar 5 — WebBLE playground

**Problem / opportunity.** Halo/Frame are controllable entirely over BLE GATT.
A browser with Web Bluetooth can talk to them with **no app store** — a perfect
dev surface and a "try it right here" demo.

**Design.** A static page (same discipline as `landing/`): a single
self-contained HTML app that

- requests the device over `navigator.bluetooth`, connects to the documented
  GATT service, and exposes the Lua REPL + a few canned HUD demos (push a card,
  run a gesture, read the IMU);
- degrades honestly: on a browser without Web Bluetooth (**every iPhone**,
  Firefox) it shows a clear "use Chrome/Edge on Android or desktop, or the
  app" message instead of a dead button;
- ships as a hacking playground first, a marketing demo second. It never
  becomes the phone hub — it's a companion.

**Docs.** A short `laptop-companion` / web note on the GATT contract, and the
iOS caveat stated plainly so no one ships an iPhone demo that can't work.

---

## Sequencing & why

```
Tier-0 NPU ─┬─> better coarse Glance + wake-word
            └─> multi-object read ─────────────┐
GhostMode mesh ─> The Beacon (ships first)     │
Plugin API ─┬─> Face Synth (plugin)            │
            └─> TasteLens connectors (plugins) ─┴─> TasteLens (feature)
WebBLE playground (independent; dev surface + demo)
```

NPU first because it makes everything after it cheaper and unlocks TasteLens's
read. The mesh next because the Beacon is the highest gasp-to-effort win and
proves the group layer. The Plugin API before TasteLens so TasteLens is built
*on* it (dogfood). WebBLE any time — it depends on nothing.

Each pillar lands as its own tested PR. Hardware and models stay behind seams:
the software is complete and green offline today; the Ethos-U55 model, the
coded-PHY radio, and the browser GATT calls drop into the seams on-device.
