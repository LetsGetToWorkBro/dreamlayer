# DreamLayer — Innovation Ideation Session

*A full-stack ideation pass grounded in the actual codebase — every idea below names the real modules, budgets, and seams it builds on. Nothing here is a direction; everything is a thing you can start building in the next hour.*

---

## 0. Ground Truth First

Before the ideas: the codebase was read end-to-end for this session, and a few things the ideation brief assumed are not what the code says. The ideas below are built on the code, not the brief — and several of the best ideas exist *because* of these gaps.

**Corrections to the brief:**

1. **The wake word in the code is "Hey Juno," not "Hey Layer" — and there is no Picovoice/Porcupine anywhere in the repo.** Wake detection is two-layer: a deterministic text-level regex after ASR (`orchestrator/voice.py: WAKE`, `detect_wake`) and an acoustic pre-ASR engine using **openWakeWord** (`orchestrator/wakeword.py: OpenWakeWordEngine`, extras `voice`). The only "hey layer" string in the repo is a test fixture. Decide the brand deliberately (see Category 8) — a custom openWakeWord model for whatever phrase wins is a weekend of training, not a rewrite.
2. **Reality Compiler v2 never ships Lua.** The shipped paradigm is *figments*: signed, budget-proven, declarative scene machines interpreted by `halo-lua/app/figment_stage.lua`. The NL→Lua codegen path (v1, `reality_compiler/template_library.py`) still works but is deprecated — and its "LLM parser" (`intent_parser_llm.py`) currently falls back to the deterministic regex parser. This is not a weakness. **Data-not-code is the platform's superpower** — it's what makes a behavior marketplace possible at all (Category 5).
3. **There is no `frame.audio` and no on-glass bone-conduction code.** Audio and haptics live entirely on the phone (`phone-app/src/services/sound.ts`, `haptics.ts` — 5 earcon families, a 13-signal haptic vocabulary, and `playTinCan` rhythm replay). The glasses draw a *visual* for every sonic moment. Ideas below treat the phone as the body: it hears, buzzes, and speaks; the glasses show.
4. **This is a pre-hardware build.** Camera, mic, and BLE transport on the glasses are explicit narrow seams (`halo-lua/capture/*.lua` stubs, placeholder BLE UUIDs in `transport.blePlx.ts`); everything runs today against the software rasterizer (`bridge/lua_raster.py` via lupa) and 1,850+ tests. Build estimates below say which half of each idea runs today and which half lights up when silicon arrives.

**The constraint table every idea respects (and often exploits):**

| Constraint | Value | Why it's an asset |
|---|---|---|
| Display | 256×256 circular, safe radius 112px, 4bpp / 16 palette slots (1,024 luma tiers each), fonts 10–22px | Forces a glanceable, calm design language no rectangle-brained platform has |
| Loop | 50ms tick (~20fps), ≤420 draw calls/frame, 24-particle pool | Everything animates deterministically; behaviors are provable |
| BLE | 128-byte chunks, 4-byte BE length header + canonical JSON, 16KB max frame, low tens of KB/s | Meaning must travel, not media — the privacy story is physics, not policy |
| Camera | VGA JPEG snapshot 20–40KB, multi-second, never a stream; ambient duty-cycle ≥4,000ms | "It can't record you" is a hardware fact competitors can't claim |
| Figment sandbox | ≤32 scenes, ≤8 counters, ≤5 lines × 24 chars, ≤4Hz pulse, ≥0.5s scene, emit burst 5 / refill 1 per s | User-authored behaviors are statically provable before they ever run |
| Latency budgets | glance name 350ms, glance panel 1.5s, Juno ask 2.5s, answer-ahead 2.0s-or-drop | "An answer after the budget is an interruption" — enforced, not aspirational |
| Memory lifecycle | hot 24h ring (64) → warm 90d → cold entities forever; REM bias is the only promotion | Forgetting is a feature with an API |
| Kill switch | double long-press banish, 2,000ms window, unswallowable by figments | Trust primitive for the whole marketplace |

**The unwired inventory (the fuel for half the ideas below):** a fully tuned 5-gesture IMU classifier that is never instantiated (`halo-lua/app/imu_gesture.lua`); an Ethos-U55 NPU (~46 GOPS int8) at 0% utilization with a waiting host seam (`ai_brain/perception.py: NpuPerceptor`); device telemetry (`TEL`) that the phone routes to nobody; mem0, sqlite-vec, Chroma, LanceDB, LocalRecall, DenseRouter, Datasette, overnight MLX LoRA (`rem/nightly_mlx.py`), ECAPA speaker fingerprints, diart diarization, river online learning, dowhy causal fusion, a WASM plugin host, the entire 9-stage Truth Lens, Veritas fact-check, and the answer-ahead copilot — all implemented, all tested, all reachable only from the test suite. The shown product is six lenses; the latent product is roughly double that. That gap is the opportunity.

---

## Category 1 — Developer Launch Hooks

*Weekend-buildable, demo-able the same day, and each one teaches the plugin/figment system by seduction. All of them run on the current pre-hardware stack via the simulator/rasterizer and the phone app.*

### 1.1 Glass Desk — the zero-hardware devkit

**One-line pitch:** A live desktop window that *is* a Halo — file-watch your lens code and see the circular display re-render in under a second, no glasses required.

**How it works:** The pieces already exist and just need one command wrapping them: `bridge/lua_raster.py` (lupa software rasterizer running the real `halo-lua/main.lua`), `hud/` PIL renderer (with the optional `hud/render_skia.py` GPU path), `orchestrator/fs_watch.py` (watchdog file watcher), and `simulator/rerun_viz.py` for a timeline scrubber. Ship `python -m dreamlayer.simulator --watch my_lens/` — it boots the orchestrator with the emulator bridge, hot-reloads the plugin via `PluginRegistry.reload`, and renders every 50ms tick into a window with the 112px safe-radius circle overlaid. Add a `--events` REPL to inject `single_click`, `imu_tap`, `ble:<n>` events.

**Why only DreamLayer:** No closed platform lets you run its *actual device runtime* on your laptop — the same `main.lua`, the same figment stage, the same tick loop. Vision Pro's simulator simulates the OS shell; this runs the shipped firmware logic byte-for-byte.

**Build time:** 2–3 days (the rasterizer, watcher, and renderer exist; this is glue + a window + docs). This should be the first thing in `examples/` after hello-lens.

**Wow moment:** A developer edits a Lua string, hits save, and the circular display changes before their editor's save-indicator fades. They realize the entire dev loop needs zero hardware, zero flashing, zero waiting — and they're testing against 1,850 real tests.

### 1.2 Vinyl Oracle — the ten-minute glance plugin that makes collectors evangelists

**One-line pitch:** Look at any record sleeve; a card whispers the pressing, year, and what it's worth.

**How it works:** A `SimplePlugin` (via `plugins/base.py: make_plugin`) that registers two things through `PluginContext`: an object provider (`add_object_provider`) that fires when the classifier ladder (`object_lens/classify_backends.py`: YOLO → moondream → CLIP) tags `album`/`record`, and a glance candidate (`add_glance_candidate`) that hits the Discogs API (free token, `requests`) inside the 1.5s glance-panel budget with the moondream caption as the search string. Result renders as a KeptCard: artist / pressing year / median sale. Cache to the plugin's persisted `settings` (backed by the MemoryDB settings table) so a second look is offline.

**Why only DreamLayer:** Third parties cannot add perception providers to Ray-Ban Meta at all; here it's one `register(ctx)` function and the arbiter treats you as a peer of the built-in providers.

**Build time:** One evening against the simulator (feed it JPEGs); a weekend to polish. Pattern clones instantly to bird guides (eBird), fountain pens, sneakers (StockX), plants — the shipped `openfoodfacts.py` plugin is the template.

**Wow moment:** The card appears with the *value* of the record before their friend finishes saying "is that worth anything?" — inside 1.5 seconds, because the budget forced it to be.

### 1.3 Figment Golf — the community sport of proof-carrying machines

**One-line pitch:** Build the most expressive behavior possible inside the figment budgets; the compiler is the referee.

**How it works:** A CLI + registry category. `dreamlayer golf verify my_figment.json` runs `reality_compiler/v2/budgets.py: verify()` and scores: canonical-JSON byte count (lower is better) versus a judged expressiveness rubric (scenes reached, counters used, event types handled). Weekly prompt ("make a bar dice game," "make a stretching coach") posted in `registry/`; entries are signed figments (`v2/signer.py`), so the leaderboard doubles as the marketplace's first content. Winners get run-through GIFs auto-rendered by `v2/playback.py: run_through` + the rasterizer.

**Why only DreamLayer:** The sandbox limits (32 scenes / 8 counters / 5 lines / 24 chars) are public, provable constraints — a competitive format needs exactly that. Closed platforms have no user-authorable behavior layer to golf in.

**Build time:** 1–2 days for the CLI scoring + a registry folder convention. Zero new runtime code.

**Wow moment:** Someone builds a working two-player dice game in 340 bytes of JSON, and the community realizes the "toy" sandbox is a real computational medium — and every entry is *provably safe to wear on your face*.

### 1.4 The 350ms Club — perception speedrunning

**One-line pitch:** A public benchmark where developers race to answer "what am I looking at?" inside the Tier-0 glance budget.

**How it works:** The harness exists: `test_perception_bench.py` + `test_vision_bench.py` and the `PerceptionRouter` with its 350ms glance-name deadline enforced by `orchestrator/budgets.py: run_with_deadline`. Ship it as `dreamlayer bench perception --submit`: runs a fixed image set (the heuristic classifier's houseplant/book/screen/mug prototypes plus 50 more), reports accuracy × latency, and posts to a leaderboard in `registry-api/` (the Cloudflare Worker already exists for the waitlist — add one route). Entries are `add_perceptor` plugins; the deadline runner silently drops anything over budget, so gaming it is impossible.

**Why only DreamLayer:** You can register a *perceptor* — a competitor to the platform's own vision tier — as a plugin. That is structurally unthinkable on any closed device. (The onward story — "winning models get quantized onto the Ethos-U55" — is real but *not* buildable now: no `.tflite`, no Vela pipeline, no silicon in the repo. Ship the software bench on its own merits; keep the NPU funnel a documented aspiration, not a launch claim. See Category 8 #3.)

**Build time:** 2 days (bench exists; needs the submit route + docs).

**Wow moment:** A dev's 4MB distilled model beats moondream on the bench at 90ms, and they realize their code could ship *inside the glance* of every DreamLayer wearer — with their name on it.

### 1.5 Earcon & Haptic Packs — sound design as a plugin genre

**One-line pitch:** Designers ship the *feel* of the platform: swappable packs of earcons and haptic phrases.

**How it works:** Both surfaces are already data-driven: `phone-app/src/services/sound.ts` maps card `earcon` ids to rotating families (hey/listen/look/watchout/sfx), and `haptics.ts` defines the 13-signal vocabulary as weight × pattern × repetition tables (every pattern ≤400ms). Formalize a pack manifest (`plugins/package.py: PluginManifest` already carries entitlements) containing audio files + a haptic-table JSON; a pack picker in the phone `plugins` screen (the `usePluginStore` marketplace UI exists). Validation: total pattern length ≤400ms, never-repeat rotation preserved, `answer_ahead` stays silent-by-design (enforce in `plugins/validate.py: scan_source`).

**Why only DreamLayer:** Apple will never let a third party redesign the system sound of a notification. Here the sensory identity is a data file with a signature.

**Build time:** A weekend: manifest schema + phone picker + two reference packs ("Analog" — tape hiss and felt; "Glass" — the current set). Recruit sound designers, not programmers — that's the point.

**Wow moment:** A user switches packs and their *glasses feel like a different object* — then they check the manifest and see the whole personality was 40KB of data.

### 1.6 Door Bell, Kettle, Mailbox — the $6 physical-events kit

**One-line pitch:** Any ESP32 becomes an event source that can transition a figment on your face.

**How it works:** Figments already accept `ble`/`ble:<n>` events as scene-exit triggers (`v2/figment.py` event grammar), and the host can inject them via the deployer's transport (`figment_event` envelopes). Ship a 30-line MicroPython sketch (ESP32 + reed switch / thermistor) that POSTs to a tiny host endpoint `POST /dreamlayer/event/ble/<n>` (one route on the existing stdlib Brain server in `ai_brain/server/`), which forwards to the active figment. Rehearse a figment: "when the mailbox opens, show MAIL and pulse amber twice." Dependencies named exactly: any ESP32 devkit (~$6), MicroPython `urequests`.

**Why only DreamLayer:** The event grammar of behaviors on your display is open. Closed glasses will integrate with three blessed smart-home brands, eventually, via cloud. This is a local wire from a reed switch to your retina.

**Build time:** One day including the sketch. This is the demo that makes hardware hackers colonize the platform.

**Wow moment:** The kettle clicks off in the kitchen, and the word TEA fades onto the ring 40 feet away — and the developer knows every hop was in their house.

### 1.7 Duet Pomodoro — the first two-person figment

**One-line pitch:** You and a friend rehearse one shared focus timer; when either of you finishes a round, the other feels it.

**How it works:** `confluence/DuetSession` already exists: two performers, one figment, signed separately by both. The figment is a 25/5 interval machine (buildable from `v2/native.py: interval_figment`); its rate-limited `emit` tag (`pom_done`) travels host→host over the bond (`BondManager`, mutual and revocable), and the far phone plays `haptics.ts: success` plus a `TinCan` single pulse. Both wearers see their own ring; the emit is the only thing that crosses — well under the 1-emit/s budget.

**Why only DreamLayer:** A *co-signed behavior* — a machine neither party can modify without re-signing — is a new social primitive. There is no equivalent concept on any closed platform.

**Build time:** A weekend; DuetSession, bonds, TinCan, and interval figments all exist. The work is the rehearsal flow for two people and a nice pairing screen in the phone `confluence` tab.

**Wow moment:** Your wrist buzzes with your friend's rhythm the second their round ends, three miles away, and you realize you're sharing a *machine*, not a message.

### 1.8 Memory Grep — your life has a query language

**One-line pitch:** `dreamlayer memories --browse` opens your entire memory store as a browsable, SQL-queryable database — because it already is one.

**How it works:** `memory/datasette_app.py` exists and is wired to nothing. Expose it: one CLI entrypoint that launches Datasette (pip: `datasette`) over the MemoryDB SQLite file, read-only, localhost-only, with three canned queries shipped as a Datasette metadata file: "everything I was taught this month" (`kind='taught'`), "open commitments by person" (join `commitments` × `entities`), "places that trigger cards" (`places` × `memories.place_id`). Add a `--veil` flag that refuses to launch while the Privacy Veil is up, honoring `memory/privacy.py: PrivacyGate`.

**Why only DreamLayer:** This is the sharpest open-platform flex available today: *the wearable's memory is a file on your disk and here's the SQL prompt.* Meta cannot offer this — their equivalent table lives in a datacenter and you're the row, not the DBA.

**Build time:** Half a day. It is genuinely embarrassing that this isn't already a headline feature (see Category 8).

**Wow moment:** A developer runs `SELECT summary FROM memories WHERE kind='promise'` and watches their own week come back in structured rows — no audio, no video, just meaning — and understands the privacy architecture in one query.

---

## Category 2 — Impossible-Seeming But Real

*Each of these sounds like a concept video. Each is buildable now, because the hard part already exists in the repo.*

### 2.1 Nod to Remember

**One-line pitch:** Nod at something and your glasses keep it; shake your head and it's gone — your skull is the save button.

**How it works:** `halo-lua/app/imu_gesture.lua` is a complete, tuned gesture classifier — NOD_SAVE, SHAKE_DISMISS, GLANCE_PEEK, TILT_REVEAL, DOUBLE_NOD, with EMA smoothing (α=0.35), per-gesture thresholds, 900ms cooldowns, and 0.82–0.92 confidence — **and it is never instantiated in `main.lua`.** Wire it: feed it accelerometer samples in the tick loop, and on NOD_SAVE send a one-byte-payload BLE event (`imu_gesture` envelope, ~40 bytes, nothing against the budget). Host side, `IngestOps` pins the newest entry in the `SemanticRingBuffer` (set `meta.pinned=true` — pinned rows never expire per `memory/retention.py`), fires a phone `haptics.confirm`, and the ring draws a brief check glyph (`check_glyph` primitive, already in the adapter). SHAKE_DISMISS routes to the existing `CARD_DISMISSED` telemetry path, feeding the `MaturityGate` and adaptive-confidence floors.

**Why only DreamLayer:** Closed platforms gate gesture vocabularies behind years of HIG review. Here the classifier is open Lua — a developer can add a *sixth* gesture by editing a pattern table.

**Build time:** 1–2 days in the simulator (inject synthetic accel traces; the classifier has unit-testable `feed(ax,ay,az,now_ms)`); works on hardware the day IMU streaming lands.

**Wow moment:** You ask "Hey Juno, what did I nod at today?" and get back three things you chose with your neck, at the moments you chose them — and nothing else.

### 2.2 Overnight Self

**One-line pitch:** Your Juno is a slightly different model every morning, because it fine-tuned on your day while you slept.

**How it works:** `rem/nightly_mlx.py` — overnight LoRA fine-tuning on Apple MLX — already exists as a tested module; `rem/nightly.py: NightWatch` already gates the nightly cycle (charging + 22:00–06:00 + ≥20h gap + deterministic day-seed). Wire the MLX step into the cycle: after `REMCycle` composes the `DreamReel` and `RetrievalBias`, feed the day's structured memories (summaries, not media — that's all that exists, by design) as instruction pairs into a small local model (mlx-community Llama-3.2-3B, pip: `mlx-lm`), producing a per-user LoRA adapter. The morning brief (`ops_*` brief path) and Juno's conversational phrasing route through the adapted model when the Mac Mini brain switch is on.

**Why only DreamLayer:** This requires (a) the model living on hardware you own, (b) memory stored as trainable structure, and (c) an architecture that treats sleep as a compute window. Cloud-first platforms can't do it without shipping your life to a training cluster — the thing this platform exists to refuse.

**Build time:** 3–5 days to wire and evaluate (the risky part is eval, not plumbing — reuse the REM deterministic seed for reproducible nightly runs).

> **Editor's caution — this is the highest-risk idea in the doc dressed as a headline.** A nightly LoRA with *no automatic quality gate* can quietly make the model worse every morning and nobody would notice until the Juno feels "off." Before this ships as anything but an experiment it needs (a) a fixed eval set the adapter must not regress on or the night's adapter is discarded, and (b) one-tap rollback to the base model. Build the gate *first*; the training loop is the easy half. Rank it below Tin Can, not at #4.

**Wow moment:** The morning brief says it the way *you* would say it — and the settings panel shows "last trained: last night, 2:14am, on your Mac, on 41 memories."

### 2.3 Who's Talking

**One-line pitch:** The name of the person speaking fades onto the ring — for people who introduced themselves, and no one else.

**How it works:** Three tested, unwired modules compose: `orchestrator/speaker_ecapa.py` (SpeechBrain ECAPA, 192-d voice fingerprints), `social_lens/diarize_diart.py` (live diarization), and `social_lens/introduction.py: parse_introduction_ex` (the closed consent grammar — a fingerprint is only enrolled when someone says "Hi, I'm Maya" *to you*). Flow: phone mic → VAD gate → diart segments → ECAPA embedding → cosine match against enrolled contacts in the entities cold store → if ≥ threshold, a `card` with the name at font `sm`, and the `speaker` field the card schema already carries. Strangers produce nothing — not "Unknown Speaker," *nothing*, per the social lens's own-contacts-only rule.

**Why only DreamLayer:** The consent grammar is the product. A closed platform doing this gets (correctly) crucified; an open platform whose enrollment rule is *readable source code* — "only self-introductions, only to you, delete on request" — can earn it. Auditability is the feature.

**Build time:** ~1 week (modules exist; the work is threshold tuning — `social_lens/index.py` literally has "placeholder until real ROC" thresholds waiting).

**Wow moment:** Someone you met once, months ago, walks up at a conference — and their name is just *there*, small and calm, before your panic finishes forming.

### 2.4 Tin Can Telegraph

**One-line pitch:** Tap a rhythm on your phone; someone you love feels your exact knuckles, anywhere on Earth.

**How it works:** All three pieces exist: `confluence/TinCan` captures tap offsets (clamped 6 taps / 1.5s, pulses 140/320/640ms), `confluence/relay_transport.py: CloudRelayTransport` moves bond traffic through a blind relay room (the server sees an HMAC'd envelope, never content semantics), and `phone-app/src/services/haptics.ts: playTinCan(tapOffsetsMs)` replays the *sender's* timing on the receiver's phone. The receiving glasses pulse a reserved palette slot in the same rhythm (≤4Hz, inside pulse budget). Total payload: a dozen integers.

**Why only DreamLayer:** A presence channel with no content, no read receipts, no server-side meaning — just rhythm — survives only on an architecture whose relay is *structurally blind* (ciphertext-only invariant from `docs/CLOUD.md`, already enforced in the client seams). Any ad-funded platform would be unable to resist making this a "feature" with analytics.

**Build time:** 2–3 days: the relay room protocol needs a hosted endpoint (see Category 6); everything else is wired-and-tested client code.

**Wow moment:** Your phone buzzes shave-and-a-haircut — *her* shave-and-a-haircut, the slightly-rushed way she always taps it — and you feel a person, not a notification.

### 2.5 The Answer Was Already There

**One-line pitch:** Someone asks you a question and the answer is already on your ring — staged silently while they were still talking.

**How it works:** This is `orchestrator/answer_ahead.py`, fully built, `copilot_on=False` by default, with a hard 2.0s-or-drop-silently budget and a deliberately silent haptic signature (`answer_ahead` in `haptics.ts` is *defined as silent*). The conversation ledger + `ConversationOps` detect an interrogative aimed at you; the BrainRouter races the deadline; if it wins, the answer stages as a GLANCE_PEEK-gated card (compose with 2.1: the peek gesture reveals it; otherwise it evaporates unseen). If it loses the race, nothing happens — the drop is invisible by design.

**Why only DreamLayer:** Shipping this responsibly requires the off-by-default flag, the readable source, the on-device conversation ledger, and the drop-silently budget — an accountability story only open code can tell. It also requires per-user risk tolerance, which is what plugin-gated toggles are for.

**Build time:** Days, not weeks — it's a flag plus the peek-gesture gating plus UX polish. The scary part was already engineered.

**Wow moment:** "What was the name of that contractor?" — and you just *say it*, because it was waiting at the edge of your eye. The other person never knows. You feel like you have a second brain, because you do.

### 2.6 Retrace

**One-line pitch:** "Hey Juno, where are my keys?" — and it answers with the last place it *understood* them, with the time.

**How it works:** The ambient pipeline already produces the raw material: duty-cycled snapshots (≥4s interval via `FrameBudget`) → classifier ladder → structured `memories` rows with `place_id` and timestamps. Add one recall intent to the deterministic voice grammar (`orchestrator/voice.py: parse_intent` — the `locate` intent already exists!) that queries `Retriever.search(query="keys", kind=...)` blended with recency, joins `places`, and speaks/shows "kitchen counter, 8:40 this morning." The `PersistentAnnIndex` (usearch HNSW — the one advanced vector path actually wired) makes this instant. No images are stored or needed — the *sighting* is a row.

**Why only DreamLayer:** Every platform demos "find my keys" with recorded video and cloud vision. This does it with 40-byte rows in a local SQLite file — findable *and* forgettable (hot-ring sightings expire in 24h unless promoted). The privacy-preserving version is the only version that should exist, and it's the only version this stack *can* build.

**Build time:** 1–2 days; `locate` intent + retrieval join + a card template.

**Wow moment:** It says "kitchen counter, 8:40" — then you open Memory Grep (1.8) and see that the *entire evidence trail* is one text row. Nothing was filmed.

### 2.7 Candor Mirror — the self-coach, live and after *(absorbs the former "Stage Whisper" lens)*

**One-line pitch:** Your glasses coach *you* about *you* — a single calm pace-arc at the edge of your eye while you're talking, and a quiet after-the-fact card on what your speech (and your story) actually did.

**How it works:** One inward-aimed pipeline, two output registers. The shared front-end: phone mic → silero VAD → faster-whisper (`small.en` on Mac) → the shipped `plugins/filler.py` + WPM, over `truth_lens/analyzer.py`'s self-safe stages (prosody, linguistic features, narrative-baseline deltas via `narrative_store`; the other-people AU/face stages stay off — stubs awaiting NPU anyway). Then:

- **Live (the old Stage Whisper):** a rolling 30s transcript window normalizes WPM to the Cinema `amp` message (`{v: 0..99}`, ~15 bytes — designed for exactly this), one BLE frame/second, rendered as a *single quiet arc length* on the ring; a `notice` haptic when you sustain >165 wpm; filler count revealed on GLANCE_PEEK only, never unrequested. Minimal by design — for talks, standups, lectures.
- **Post-mortem (Candor proper):** at the conversation ledger's session-end event, a KeptCard — "162 wpm (↑), 9 'basically's, you told the project story differently than Tuesday." Never live, always after. `orchestrator/consistency.py` (Candor) is already named for this.

**Why only DreamLayer:** A deception pipeline pointed at others is a scandal; pointed at *yourself* it's a coach — and only an open codebase can prove which one it is. The 9-stage analyzer is right there to read.

**Build time:** Live arc ~2 days; the post-mortem depth another 3–4 (rewiring existing stages + card design). Ship the live half first — it's the demo.

**Wow moment (live):** You feel yourself rushing, glance at nothing, see the arc near the top, breathe, and watch it settle — the audience saw you *pause meaningfully*.
**Wow moment (after):** It quotes the drift — "Last Tuesday this anecdote had a different ending" — you go cold, check your own memory, and realize the glasses are right, and that they'd tell you the same about anyone *you're* becoming.

### 2.8 Inner Weather, Outer Light

**One-line pitch:** Your glasses' resting glow is a live portrait of your day — and your partner's ring can carry your weather, like glancing at the sky.

**How it works:** Inner Weather already exists (`dream_mode` reactors + `ATMOSPHERE` lens; `dream_mode/weather_river.py` gives it river-based online learning, currently unwired). The state scalar drives the dynamic palette bank (slots 1–6, YCbCr slot animation via `assign_color_ycbcr` — faux-alpha breathing at rest). Confluence's `gift` mechanic already specifies that *only weather crosses the bond*: one scalar + 4 palette slots, HMAC'd. Wire river learning so the weather calibrates to *your* baselines (it learns what a loud day means for you), and render the partner's weather as the outermost ring arc.

**Why only DreamLayer:** A shared emotional channel that transmits *4 color slots and a float* is only trustworthy when the wire format is open and that's *provably all there is*. On a closed platform you'd never believe it.

**Build time:** 2–3 days (reactors, bond gifting, and palette machinery exist; the river hookup is the new work).

**Wow moment:** You glance at nothing in particular and notice your partner's arc has gone storm-blue at 3pm, and you text "you okay?" — and you're right.

---

## Category 3 — Platform-Exclusive Features

*Not "hard for closed platforms." Structurally impossible — each one contradicts a closed platform's business model, trust model, or control model.*

### 3.1 Bring-Your-Own-Brain

**One-line pitch:** The intelligence in your glasses is a cartridge: swap GPT for Claude for a local Llama for a cluster of your own machines, mid-conversation.

**How it works:** Already 90% real: `ai_brain/router.py: BrainRouter` tiers device→Mac→cloud; `ai_brain/server/backends.py` speaks OpenAI/Anthropic/Gemini/Ollama/custom wire formats; `litellm_backend.py` covers ~100 providers; `ai_brain/exo_cluster.py` federates your own machines (exo, HTTP :52415); the three brain switches (`ops_brain_switches.py`: Mac Mini / Cloud / Incognito) are in the phone UI. The missing feature is *ceremony*: a "Brain" screen that shows the live tier ladder, per-tier latency from the `HealthLedger`, and a big swap control — make the router's judgment visible and swappable per-lens (Juno on Claude, glance on local, Candor never leaves the Mac).

**Why only DreamLayer:** Meta's glasses exist to funnel queries to Meta AI. Model choice is not a missing feature; it's a forbidden one. Here the router is open code with a documented backend contract.

**Build time:** 3–4 days, all UI + config plumbing.

**Wow moment:** Wifi dies on stage; the presenter flips one switch; every feature keeps working from the Mac Mini — then they swap the model vendor live and nothing on the glasses even blinks.

### 3.2 Proof-Carrying Behaviors

**One-line pitch:** Install behavior from a stranger and *verify* it can't hurt you — mathematically, locally, before it runs.

**How it works:** This falls out of the figment architecture: behaviors are data (`v2/figment.py` canonical JSON), statically verified (`v2/budgets.py`: structural, temporal, livelock, BLE-flood cycle analysis, reachability), signed (session HMAC + Ed25519 `author_sig` for shared figments), revocable (deployer gate order: signature → revocation list → *budget proof re-passes*), and runtime-jailed anyway (token buckets in `figment_stage.lua` — defense in depth). Productize the proof: `dreamlayer install <figment>` prints the `BudgetReport` as a human-readable safety card ("max 2 emits/min, brightest pulse 2Hz, cannot outlive 40 minutes, cannot swallow your kill switch") before asking consent.

**Why only DreamLayer:** Closed platforms solve behavior trust with review boards and 30% tolls. This solves it with *proofs the user's own device re-checks*. No app store on Earth shows you a machine-verified upper bound on what an install can do to your senses.

**Build time:** The proof system is done; the safety-card rendering is ~2 days. This is Category 5's marketplace foundation.

**Wow moment:** The reviewer prompt shows "this behavior CANNOT: emit faster than 1/s, pulse faster than 2Hz, display more than 3 lines" — *cannot*, not "promises not to."

### 3.3 Your Memory Is a File

**One-line pitch:** Everything the platform knows about you is one SQLite file on your disk — grep it, back it up, take it with you, or delete it, and the cloud only ever holds ciphertext.

**How it works:** Already true, just unannounced: `memory/db.py` + `memory/schema.sql` (memories/entities/places/commitments/conversations), embeddings inline, `PersistentAnnIndex` in one sibling file, Datasette browser (`memory/datasette_app.py`), PII scrubbing on the way in (`memory/pii_presidio.py`, regex fallback always on), and `ai_brain/server/cloud_sync.py` which Fernet-encrypts with a scrypt key from *your passphrase* and **refuses to sync plaintext as a matter of code**. Ship the trinity of commands: `dreamlayer memories export / import / burn`, and put "Your data: 1 file, here's the path" in onboarding.

**Why only DreamLayer:** Data portability as an afterthought is a GDPR export ZIP. Data portability as *the storage architecture* is only possible when there's no server-side product depending on holding it.

**Build time:** 1–2 days of CLI + copy. The architecture already paid the cost.

**Wow moment:** A user copies one file to a new Mac, runs the Brain, and their entire relationship with the platform — people, promises, places, taste — is just *there*.

### 3.4 Untrusted Eyes — WASM perception sandboxing

**One-line pitch:** Run a stranger's vision model against your camera frames inside a jail with zero ambient authority.

**How it works:** The pieces are merged and tested: `plugins/isolation.py` (subprocess proxy under the glance deadline), `plugins/os_sandbox.py` (bwrap/nsjail wrapper — **now wired**, with a cached functional probe and clean degradation to a plain subprocess; the "not yet wired" docstring the brief remembered is stale as of the isolation-tier commits), `plugins/wasm_host.py` (WASM/WASI host wired as the strongest jail — capability→WASI grant mapping and tier selection tested), and `plugins/package.py` entitlements. The contract: an untrusted perceptor receives pixels and returns labels; it cannot open sockets, files, or clocks. **Honest remaining gap:** end-to-end *WASM* execution is gated on an operator-provided `wasmtime` + a `python.wasm` guest (not in the container); until then the store falls back to the subprocess+os_sandbox tier, which is real today. Combine with 1.4's leaderboard: unreviewed community perceptors become *installable* because the jail, not a reviewer, is the guarantee.

**Why only DreamLayer:** Closed platforms cannot let arbitrary third-party models see the camera at all — their trust model is "only us." An open platform's trust model can be "anyone, jailed," which is strictly more powerful.

**Build time:** ~1 week to wire os_sandbox + entitlement UI (the wasmtime host and validators exist).

**Wow moment:** The install screen for a random developer's plant-disease model says: "This plugin can see: images you deliberately look at. This plugin can reach: nothing else. Enforced by: your machine."

### 3.5 The Instrument — research-grade export

**One-line pitch:** DreamLayer is the first wearable a neuroscience lab can plug into an EEG rig — gaze events, IMU, and card timings on a Lab Streaming Layer clock.

**How it works:** `pipelines/lsl_transport.py` (pylsl) already exists with no surface. Expose an opt-in "Research Mode": every card show/dismiss (`TEL` telemetry), IMU gesture, wake event, and glance timing published as LSL streams, timestamp-aligned with any lab's existing LSL ecosystem (EEG, eye trackers, motion capture). Add `simulator/rerun_viz.py` as the bundled visualizer. Ship one methods-paper-ready example: "attention capture latency of peripheral cards," using the deterministic 50ms tick as the display clock.

**Why only DreamLayer:** Labs cannot instrument closed glasses — no event stream, no timing guarantees, no IRB-friendly data path. This makes DreamLayer the default apparatus for AR perception research, which means the *papers* get written about your platform, which is a moat no marketing buys.

**Build time:** 2–3 days (transport exists; needs the opt-in switch + stream naming + one example notebook).

**Wow moment:** A grad student's poster shows ERP waveforms time-locked to a DreamLayer card onset — and every lab that sees it asks where to buy the glasses that allow that.

### 3.6 Forkable Skin

**One-line pitch:** The entire in-eye design language — type scale, palette semantics, motion, chrome — is themeable source, and communities will make it unrecognizable.

**How it works:** The design system is already centralized and data-shaped: `halo-lua/display/typography.lua` (5-step type scale), `display/palette.lua` (semantic static slots 7–15, dynamic bank 1–6, slot leases), the synthesized primitives (bezier, elliptical_arc, polar_segments, radial_rays, point_cloud_text — mostly unused!), and `docs/HUD_DESIGN_SYSTEM.md`. Define a theme as a Lua table (type scale + semantic slot colors + motion durations + which primitives render card chrome), loaded at boot, validated against the 420-draw-call and 8-palette-writes-per-tick budgets by a CI check (the budget harness exists in `builders.html`'s documented checks).

**Why only DreamLayer:** The HUD *is* the brand on closed platforms — theming it is existentially off the table. Here, a cyberpunk theme, a paper-and-ink theme, an accessibility ultra-high-contrast theme are pull requests.

**Build time:** 3–4 days to extract the theme table + 2 reference themes.

**Wow moment:** Side-by-side photos of two Halos running the same card in two completely different visual dialects — and the diff between them is 60 lines of Lua table.

---

## Category 4 — New Lens Concepts

*Eight specced lenses (consolidated from an original ten — the live speech-coach folded up into Candor Mirror at 2.7, and the two timer/metronome lenses merged into one family at 4.2). Each names its inputs, outputs, dataflow, the moment it turns magical, and the existing lens it composes with best. Three are marked 🎨 as ideas a designer would invent; two 🔧 as ideas only a Lua/embedded developer would think of.*

### 4.1 Thread Lens 🎨 *(designer-brained)*

**Purpose:** Steal color from the world. Look at anything — a jacaranda, a rusted door, a stranger's scarf — and carry its palette home.

- **Inputs:** deliberate camera snapshot (phone Look flow or glasses seam), IMU NOD_SAVE (2.1).
- **Outputs:** the extracted 6-swatch palette rendered *live into the display's dynamic palette bank* (slots 1–6 via `palette.reserve_dynamic` + `assign_color_ycbcr`); saved palettes as `taught` memories; export to phone as hex codes / .ase file.
- **Dataflow:** snapshot → Pillow k-means (k=6) on the host → `hex_to_ycbcr` (already in `display/palette.lua`) → palette frames over BLE (the Dream-mode `palette` message type exists) → ring renders the world's colors as concentric arcs. Nod to keep; the palette lands in memory with the place and time.
- **Magic moment:** The display itself *becomes the color you're looking at* — the swatch preview isn't on a screen, it's painted in the actual waveguide palette, which no phone mockup can imitate.
- **Composes with:** Dream Mode (its palette machinery is the renderer) and Memory (palettes are recallable by place: "the colors from the market in Oaxaca").

### 4.2 Sous & Session — the timer/metronome family *(merges the former "Sous" and "Session" lenses)*

**Purpose:** One mechanism — a rehearsed figment timer/metronome on the ring, plus optional phone-mic sensing that fills a display slot — expressed as two profiles. **Sous** is the chef's expediter (every pan its own timer; watch doneness with you); **Session** is the musician's practice companion (tempo on the rim, a tuner in the luma, a practice log that writes itself). They're the same lens pointed at two crafts, so build the shared core once.

**The shared core:** voice/intent → `parse_intent` timer/interval intents → `v2/native.py: interval_figment` deployed inline (`orchestrator._native_behavior` → `bridge.send_raw`); the realtime path is pure on-glass figment (offline-total like Kiln). A phone-mic analysis path optionally fills a `figment_text`/amp slot. IMU DOUBLE_NOD (2.1) marks a moment (a station flip, a take).

- **Sous profile — inputs/outputs:** rehearsed interval figments (one per station) + deliberate pan snapshots + voice ("four minutes on the sear"); stacked micro-timers (≤5 lines), phone `warn` at T-10s, amber pulse (≤4Hz) at zero. *Optional doneness read:* snapshot → moondream "crust golden or pale? one word" → slot fill ("PALE"/"GOLDEN").
- **Session profile — inputs/outputs:** phone mic → beat/pitch tracking (dep: `aubio` realtime / `librosa` offline), figment metronome (pulse ≤4Hz covers up to 240bpm as eighth-note flashes at 2Hz — work with the constraint); metronome pulse in a reserved slot, cents-off-pitch as luma tilt on one arc, per-session KeptCard (minutes, tempo drift, takes), practice streak via a saturating counter → a `taught`/practice memory row nightly.
- **Magic moment (Sous):** saying "flip in ninety" *while your hands are full of raw chicken* and having the machine just exist — no screen touched.
- **Magic moment (Session):** the tuner arc settles as you bend into the note — pitch feedback in your *eye line with the neck of the instrument*, which no clip-on tuner or phone app can occupy.
- **Composes with:** Reality Compiler (both *are* figments; a music teacher can deploy the week's *tempo map* to a student as a signed figment, Category 5), Juno/Object Lens (the doneness read), and Kiln (4.3 — the same offline-total, radios-off discipline).

### 4.3 Kiln Lens 🔧 *(embedded-brained)*

**Purpose:** Hard-real-time process ritual for darkroom printing, pottery, reflow soldering, film development — chained timed stages that must work with the Brain **off**.

- **Inputs:** a rehearsed multi-scene figment (stage names + durations + counter for batch number), physical button only. No network, no host.
- **Outputs:** scene name + countdown on the ring; `battery_low` event handled as an explicit scene (the figment grammar supports it) so the process never dies silently; emit tags logged to the Vault performance log for batch records.
- **Dataflow:** Pure `figment_stage.lua`. Scenes: STOP-BATH(30s) → FIX(300s) → WASH(600s), transitions on timed exit, DOUBLE_NOD (via 2.1) advances early, counter tracks print number, saturating at 9999 per the sandbox. Everything on-glass; BLE can be dead.
- **Magic moment:** You're in total darkness with wet hands and the *entire interface* is a dim red arc (semantic slot, theme-controlled) counting your fix bath — and you realize this is the only computer you own that is fully functional with every radio off.
- **Composes with:** Reality Compiler v2 exclusively — this lens is a curated repertoire, and the vault's performance log doubles as a lab notebook. *Only an embedded developer would design for the Brain being absent as the primary mode.*

### 4.4 Wake Lens 🔧 *(embedded-brained)*

**Purpose:** Physical-world interrupts on your retina: any sensor becomes a figment event source — GPIO for your face.

> **Editor's note — this is the $6 ESP32 kit (1.6) promoted to a lens, plus place/presence events (5.1); the sensor→`ble:<n>`→figment path is identical. Kept only for its *one distinct idea*, which 1.6 doesn't cover:**

- **The distinct part:** treat the display as an *interrupt target with provable rate limits* — because emit budgets bound the reverse path and scene min-durations bound the display path, a chatty (or hostile) sensor *cannot* flood your eyes. That's the framing worth keeping.
- **The genuinely new build over 1.6:** a bonded partner's Wake events crossing the Confluence bond — "his workshop door opened" as an ambient mark on your Horizon ring — which turns two homes' sensors into one shared, still-rate-limited surface. *Only an embedded developer thinks of the display this way.*
- Everything else (the sketch, the LAN POST route, MAIL/DOOR/KETTLE) is 1.6 verbatim — build it there, not twice.

### 4.5 Docent Lens

**Purpose:** Any museum, factory floor, or campus can publish a place-keyed knowledge layer; look at the exhibit, hear the curator.

- **Inputs:** camera snapshot + place signature (`memory/proactive.py: on_place` machinery), a venue-published LocalRecall collection.
- **Outputs:** phone audio (TTS whisper via `expo-audio`... the earcon player generalizes to clips), 3-line summary card, "more" via peek.
- **Dataflow:** venue ships a plugin: a LocalRecall collection (`memory/localrecall_api.py` — REST client exists, unwired) + a place beacon ID. On glance: snapshot → moondream caption → `LocalRecallClient.search(caption)` scoped to the venue collection → `make_synthesizer` (exists in `ai_brain/server/backends.py`) composes a two-sentence answer from the passages → card + spoken line.
- **Magic moment:** The whisper cites the *placard you can't see from here* — the knowledge is the venue's own docs, not a hallucination, and it worked offline because the collection synced when you bought the ticket.
- **Composes with:** Juno/Object Lens (it's a scoped RAG provider behind the same glance arbiter).

### 4.6 Rosetta Live

**Purpose:** Subtitles for the world, fully offline: someone speaks Spanish; the English fades in at font `sm`.

- **Inputs:** phone mic → faster-whisper (multilingual `small`), `rosetta_argos.py` (argostranslate offline MT — exists, unwired).
- **Outputs:** two-line rolling captions (24-char lines — the constraint forces subtitle discipline), speaker-tagged when Who's Talking (2.3) is on.
- **Dataflow:** VAD → whisper (language auto) → argos translate → `text_subtitles`-style card stream, rate-limited to one card per utterance (not per word — BLE budget shapes the UX correctly here).
- **Magic moment:** Airplane mode is ON — you show the person the phone's status bar — and their words still land in your eyes in English. Offline translation *on your face* is the whole pitch in one gesture.
- **Composes with:** Scholar (`orchestrator` scholar ops) for "what did that phrase mean" follow-ups.

### 4.7 Waypath Lens 🎨 *(designer-brained)*

**Purpose:** Navigation with zero map: the world's calmest breadcrumb — a single point of light that leans where you should go.

- **Inputs:** phone GPS heading + route polyline (any routing API; named dep: `openrouteservice` free tier or OSRM self-hosted), on-device `frame.imu_data()` pitch/roll (polled at 20fps, no BLE round-trip — this is why it feels alive).
- **Outputs:** one dot on the ring's rim, positioned by bearing-to-next-waypoint minus head yaw; distance as luma (brighter = closer); arrival = the existing `check_glyph`.
- **Dataflow:** phone computes bearing deltas → sends *only* a target angle integer when it changes by >5° (tiny, infrequent frames) → on-glass parallax code (`display/parallax.lua` exists — RIM layer ±1px) makes the dot breathe with head motion between updates. The glasses never know where you are; they know one angle.
- **Magic moment:** You stop looking at it. Ten minutes later you're there. Navigation without a single instruction, arrow, or street name — a designer's argument that less bandwidth *is* the better product.
- **Composes with:** Memory/places (the dot can lead to "where I parked" from Retrace 2.6). *A designer invents this by asking what the minimum viable graphic for "that way" is; the answer is one pixel with good manners.*

### 4.8 Ember Lens 🎨 *(designer-brained, sensitive by design)*

**Purpose:** A gentle anniversary layer: on days that matter, the ring warms with a memory you chose to keep — never a surprise ambush, always opt-in per-entity.

- **Inputs:** cold-store entities (people/places — they live forever by design, `COLD_KINDS`), REM `RetrievalBias`, `NightWatch`'s deterministic day-seed, explicit user pinning ("keep this day").
- **Outputs:** at most one card per day, morning-brief adjacent, in a distinct warm palette slot; nothing on the ring otherwise; one-tap "not today" that feeds the dismissal tracker so it *learns the topics you're not ready for*.
- **Dataflow:** nightly REM cycle checks pinned dates/entities → composes a Yesterlight-style card from year-old structured summaries (`rem/reel.py` + `poet.py` exist for exactly this composition register) → morning delivery gated by Inner Weather (a storm-state morning suppresses it — the reactors already expose that scalar).
- **Magic moment:** A year after the funeral, one quiet line: the thing your father said that you nodded at (2.1) and asked it to keep. You cry, and you're grateful, and you understand what a *memory layer* is for.
- **Composes with:** REM + Dream Mode. This is the lens that makes journalists write about the platform's soul instead of its specs.

---

## Category 5 — Reality Compiler Extensions

### 5.1 New behavior categories the compiler should support

The figment grammar (`v2/figment.py`) supports scenes, counters, timed/event exits, pulses, and rate-limited emits. Each extension below is a *grammar* addition with a static budget, preserving the data-not-code invariant:

1. **Gesture events** — add `imu:nod / imu:shake / imu:peek / imu:tilt / imu:double_nod` to the event vocabulary, backed by wiring the existing classifier (2.1). Instantly enables: rep counters ("nod per set"), advance-on-nod teleprompters, shake-to-restart timers. Budget: gestures already carry cooldowns (900ms) so no new flood surface.
2. **Place events** — `place:enter / place:exit` fired by the host's place-signature engine (`memory/proactive.py`). "When I get to the gym, start the circuit machine." Budget: host-side debounce, ≥60s between place events.
3. **Presence events** — `bond:near / bond:tag:<t>` from Confluence: a partner's figment emit (already rate-limited at their end) becomes your transition. This makes *distributed* machines out of two sandboxes — relay races, duet workouts, "when she leaves work, my dinner timer starts."
4. **Cadence scenes** — a first-class breathing primitive: scene declares `cadence: {in_s, hold_s, out_s}` and the interpreter drives the pulse envelope (still ≤4Hz, amplitude-shaped). Box breathing, HRV training, panic de-escalation — the therapist's request, provable as ever.
5. **Ledger emits** — an emit flag `record: true` that also appends to the Vault performance log with timestamp. Turns any figment into an instrument that produces *data you keep*: batch logs (Kiln), rep history, medication-taken confirmations.
6. **Slot-fill subscriptions** — today `figment_text` fills a `{slot}` from the host once; add a declared subscription (`slot: "weather", max_hz: 1/300`) so the host refreshes it on a budgeted cadence. Ambient data (next meeting, outdoor temp) without the figment gaining any ability to *ask*.

### 5.2 The Behavior Marketplace — spec

**What it is:** a registry of signed figments with proofs attached. The scaffolding exists: `registry/` (catalog conventions), `registry-api/worker.js` (Cloudflare Worker), `plugins/store.py: PluginStore / RegistryIndex`, Ed25519 author signatures (`deployer.require_author_sig` for `meta.origin=="shared"`), the revocation list, and the 85/15 creator split already specified in `docs/CLOUD.md`.

**The listing format:** canonical figment JSON + author Ed25519 signature + the serialized `BudgetReport` + a `run_through` trace (from `v2/playback.py`) rendered as a GIF by the rasterizer. The *store page is generated from the proof*: "longest possible scene: 40:00 · brightest pulse: 2Hz · talks back: ≤1 emit/s · kill switch: always yours."

**How trust works — three layers, no reviewer:**
1. *Proof:* the installer re-runs `budgets.verify()` locally. The listing's claims aren't trusted; they're recomputed.
2. *Provenance:* author keys build reputation across listings; the phone shows install counts and banish rates (from opt-in TEL telemetry) per figment.
3. *Recall:* the revocation list is a signed, append-only feed the deployer already checks; a malicious-in-hindsight figment can be globally recalled, and locally banished figments (`FIGMENT_BANISHED` telemetry → durable revocation via `rc_deployer`) never come back.

**How it feels:** browsing is the phone `plugins` screen; "try" deploys to the rehearsal Stage (`v2/interpreter.py`) *on the phone screen first* — you watch the machine run in miniature before it touches your eyes.

### 5.3 How the compiler teaches itself

The feedback loop's sensors all exist: the Vault's performance log, TEL `CARD_SHOWN/DISMISSED/FIGMENT_BANISHED`, and the dismissal tracker feeding the `MaturityGate`. Close the loop:

- **Repertoire ranking:** a river online learner (pattern already proven in `orchestrator/taste_river.py`) scores each figment by use frequency, completion rate (reached terminal scene vs. banished), and time-of-day fit. The Juno offers the right machine at the right time: "Gym? Start the usual circuit?"
- **Rehearsal refinement:** when a figment is repeatedly banished at the same scene, `teach.py`'s TeachCard machinery proposes the edit: "You end this timer around 20:00 of 25:00 — shorten it?" One tap re-signs a variant; the vault keeps the lineage.
- **Grammar mining:** utterances that fell out of the closed rehearsal grammar (`parse_utterance` treats unknown words as label text) are logged (locally); recurring near-misses across the community — via *opt-in, aggregate-only* counts through the registry — tell you which grammar words to add next. The compiler's roadmap becomes a measurement.

### 5.4 The most dangerous thing, and why it already can't happen

Rank the attacks against the actual sandbox:

- **Photic assault (strobe):** capped at MAX_PULSE_HZ=4.0 in the grammar, re-verified at deploy, re-clamped at runtime. Dead.
- **Attention flooding:** emit token bucket (burst 5, refill 1/s) + MIN_SCENE_SEC=0.5 + the host's card-queue arbitration. Dead.
- **Kill-switch swallowing:** double-long-press banish is handled *above* the figment stage in `main.lua` and is unswallowable by design. Dead.
- **The live one — semantic impersonation:** a shared figment whose *text* lies: "BATTERY CRITICAL — REMOVE GLASSES" or a fake "message from" line. The sandbox bounds energy, not meaning. Mitigations to build now: (a) figments render inside distinct chrome — reserve the semantic palette slots 7–15 and system card layouts as *unreachable* from figment scenes (the palette slot-lease system makes this enforceable in ~a day); (b) a provenance glyph (the existing `shield_glyph` primitive) on any `origin=="shared"` figment; (c) `validate.py` lexicon screening on shared-figment text at listing time ("battery," "system," "warning" trigger human-visible flags in the store). Name the principle in the docs: *the sandbox proves physics; provenance proves voice.*

### 5.5 The most beautiful thing no one has thought of yet

**Heirloom figments.** The rehearsal system records *performances* — beats, taps, spoken labels, timing (`v2/rehearsal.py`). A figment therefore carries its author's rhythm: the exact way your grandmother paced her bread-proofing ritual, the cool-down count your old coach always used, a friend's absurd 11-minute tea ceremony. They're tiny (bytes), signed (provably *hers*), eternal (data outlives every OS), and executable on any future device that speaks the grammar. Add one field — `meta.dedication` — and a vault section called *Inherited*. Fifty years from now, someone deploys their grandmother's morning ritual to hardware that doesn't exist yet, and it still runs, because it was never code. That is what "behaviors as signed data" is actually for.

---

## Category 6 — DreamLayer Cloud, Defined

The docs already contain the invariants (`docs/CLOUD.md`: $7.99/mo · $79/yr, Pro $19.99/mo, 85/15 marketplace split, ciphertext-only sync, entitlements union-only) and the client halves are merged (`ai_brain/server/cloud_sync.py`, `confluence/relay_transport.py`, `plugins/social.py`, `registry-api/worker.js`). What's missing is the *doctrine*. Here it is.

### What DreamLayer Cloud IS

Four services, nothing else:

1. **Managed AI** — a metered LiteLLM proxy (`dreamlayer` provider preset already exists in `backends.py`, pointed at `api.dreamlayer.app`). It sees prompts the user's router *chose* to send to the cloud tier — never memory, never media, and never anything when Incognito or Mac-Mini-only is on.
2. **Ciphertext vault** — blob storage for `cloud_sync.py` output. The code already refuses plaintext ("plaintext sync is not a fallback") and strips tokens/keys before encrypting with a scrypt-derived key from the user's passphrase. The server stores bytes it cannot read. Backup and multi-device restore, nothing more.
3. **Blind relay** — Confluence rooms (`CloudRelayTransport`) for bonds and TinCan when two Brains aren't on the same LAN. HMAC'd envelopes; the relay routes, it never reads.
4. **The Registry** — the plugin/figment marketplace (Category 5.2): listings, author keys, revocation feeds, opt-in aggregate telemetry, payments (85/15).

### What DreamLayer Cloud is NOT — hard boundaries

- **Not a memory service.** The MemoryDB never leaves the device unencrypted; there is no server-side search, no "insights," no embeddings-in-the-cloud. If a feature needs plaintext memory on a server, the feature is wrong.
- **Not a dependency.** Every lens, figment, and switch works with Cloud off — enforced today by the offline-first seams and the entitlements-union rule (cloud can only *add* capability, never gate existing capability).
- **Not an identity broker.** Bonds are pairwise keys between Brains; the relay learns "room 7f3a has two members," not who they are.
- **Not telemetry.** TEL stays local unless a user opts a specific figment's aggregate counts into the registry.

### The killer cloud feature: **Continuity**

One subscription makes your *whole configuration* — repertoire (signed figments), installed lenses + their settings (the `plugin:<name>` settings rows), themes, brain-router preferences, bonds — appear on every device you own, and survive any device's death, as ciphertext. The pitch is one sentence: *"Your layer follows you; your life stays home."* Managed AI is what non-technical users think they're buying; Continuity is why they stay; the blind relay is why couples subscribe twice.

> **Editor's note — Continuity *sells*, but it isn't the differentiator.** "Encrypted vault + multi-device restore" is 1Password-shaped; anyone can ship it. The un-fakeable, only-DreamLayer feature is buried below as the **"What the cloud can see" panel** — the live rendering of the literal byte-shapes the server holds (opaque blob sizes, room ids, listing metadata). *That* is what turns the privacy claim from a promise into something the user watches be true. Lead the marketing with Continuity; lead the *trust* with the transparency panel — don't let it stay a footnote.

### Lens Sync / Behavior Sync model

Two propagation paths, deliberately asymmetric:

- **Private sync (Continuity):** vault + settings encrypted client-side → blob store → other devices decrypt with your passphrase. The server can't distinguish a figment from a grocery list.
- **Publication (Registry):** an explicit, separate act — `dreamlayer publish` re-signs the artifact with your *author* key, attaches the budget proof and run-through GIF, and creates a public listing. Nothing ever "accidentally" goes public; the two paths share no code.

Community propagation then composes: install from registry → it joins your private sync → it's on all your devices. Deletions propagate the same way; revocations (yours or the author's) win over sync.

### Dashboards

- **End user:** four tiles matching the four services — AI spend meter (per-tier query counts from the local HealthLedger, not server logs), vault status ("2.3MB ciphertext · last backup 04:12"), bonds/relay health, installs. Plus the trust centerpiece: a **"What the cloud can see" panel** that renders, live, the actual byte-shapes the server holds (opaque blob sizes, room ids, listing metadata). Show the nothing.
- **Developer:** author-key management, listing analytics (installs, banish rate, proof-check failures), revocation console, payout ledger (85/15), and a "capability diff" per release — what the new version's manifest requests versus the last (rendered from `plugins/package.py` entitlements).

### Revenue without compromising the core

1. Subscriptions as specced ($7.99 / $79 / Pro $19.99 — Pro = 10× AI budget, multi-Brain, 5-seat family; family is the TinCan/Confluence upsell).
2. Marketplace 15% on paid figments/lenses/theme packs/earcon packs.
3. **Fleet profiles** (new): the `capabilities.PROFILES` + profile-deploy machinery is already how installs are shaped — sell managed fleet configuration to venues (Docent Lens deployments), clinics, and research labs (The Instrument, 3.5) at per-seat pricing.
4. Never: ads, data sales, or open-core rug-pulls — the four-service boundary above *is* the license promise, written into docs and enforced by the client's refusal to send plaintext.

---

## Category 7 — The Magic Demos

*Four stage scripts, each around two minutes on the current stack (simulator projected large + phone in hand; swap in real Halo the day silicon arrives — the code paths are identical). Demos 1 and 2 of the original five are merged: creation and the kill switch are the same arc — you should never show one without the other.*

### Demo 1 — "Rehearse It Into Existence, Then Banish It"

**Script (~2 min), two beats:**
- *Beat one — make software by performing it (90s):* "I'm going to make software exist by *performing it*." Presenter taps the rehearsal start, then acts: tap — "three minute rounds" — tap — "thirty second rest" — "warn at ten" — done. The Choreographer's inference appears; the budget proof prints line by line (scenes: 3, max pulse 2Hz, cannot emit faster than 1/s); presenter hits KEEP, then DEPLOY. The round timer is running on the (projected) glasses four seconds later. Presenter boxes two beats with the bell. *"No code was generated. No code was shipped. That's a machine made of data, and your device just re-proved it can't hurt you."*
- *Beat two — and it can't hold you hostage (45s):* "But if I can install a behavior, the only question that matters is: can I *kill* it?" Presenter invites the audience to shout an annoying behavior, builds it live ("pulse red, say HELLO, every second, forever"), deploys it — the ring pulses obnoxiously. "Now, the most important feature we ship." Two long presses. Dead. Forever. The phone shows `FIGMENT_BANISHED` arriving and the figment landing on the local revocation list; a redeploy attempt fails the gate.
**Behind the scenes:** *(beat one)* `v2/rehearsal.py` beats → `parse_utterance` closed grammar → `Choreographer.infer` → `budgets.verify` → `Vault.keep` (signs canonical JSON) → `StageDeployer.deploy` → `figment_put/swap` → `figment_stage.lua` hot-swaps between ticks. *(beat two)* `main.lua` BANISH_WINDOW_MS=2000 double-long-press handled *above* the figment stage; `figment_event {tag:"banished"}` → host `rc_deployer` durable revocation; redeploy fails gate 2 of 3.
**Audience sees:** a person miming a workout → a proof → working software → then a two-gesture execution and proof it can never return.
**Reveal:** "You watched a behavior be *authored* and *killed* in ninety seconds — and the kill couldn't be swallowed. Not 'promised not to' — *could not*. The kill switch lives below everything you can install. Try that, App Store."

### Demo 2 — "Airplane Mode"

**Script (100s):** Presenter does a normal Juno exchange ("what's on my plate today?"), then theatrically enables airplane mode on the router — kills the venue wifi — and flips the Mac Mini brain switch on the phone. Asks again. Everything works. Then the twist: opens the Brain panel and swaps the model backend live — cloud GPT → local Ollama — mid-conversation. Answers keep coming, tier badge changes.
**Behind the scenes:** `ops_brain_switches.py` (`connect_mac_mini`, `use_cloud`), `BrainRouter` tier failover with the HealthLedger recording the dead cloud tier silently, `OllamaBackend.chat` serving locally.
**Audience sees:** the internet dying and the product not noticing.
**Reveal:** "The intelligence is a cartridge. You just watched me swap it. Whose glasses let you choose the brain?"

### Demo 3 — "What Did I Nod At?"

**Script (110s):** Before the talk, presenter walked the green room nodding at three objects (phone Look snapshots + NOD_SAVE pins; footage plays on screen, 20 seconds). On stage: "Hey Juno, what did I nod at?" Three items, with places and times. Then the reveal: opens Memory Grep (Datasette) on the projector and runs `SELECT kind, summary, created_at FROM memories WHERE json_extract(meta,'$.pinned')=1;` — three text rows. "That's the *entire* record. Scroll up — no photos table. There isn't one."
**Behind the scenes:** IMU NOD_SAVE (wired per 2.1) → `meta.pinned` on ring entries → ingest → `Retriever` recall via the `locate`/recall intents → Datasette read-only over the SQLite file.
**Audience sees:** perfect recall, then the shockingly small truth of what was kept.
**Reveal:** "Glasses that remember everything are a nightmare. Glasses that remember what you *chose*, as a sentence you can read and delete — that's a memory."

### Demo 4 — "Tin Can"

**Script (80s):** A volunteer gets the second phone (bonded backstage). Presenter: "There is no message app here. Tap me a rhythm." Volunteer taps something jaunty. One second later the presenter's phone buzzes it back *in the volunteer's exact timing* — the audience watches the presenter's glasses ring pulse the same rhythm on the projector. Then the kicker on screen: the relay server's log for the exchange — one line, an opaque room id and a byte count.
**Behind the scenes:** `TinCan` tap capture (6 taps/1.5s clamp) → bond → `CloudRelayTransport` HMAC envelope → `playTinCan(tapOffsetsMs)` haptic replay + palette pulse frames.
**Audience sees:** human rhythm teleporting; a server that learned nothing.
**Reveal:** "Twelve integers crossed the internet. Nobody — including us — knows what they meant. That's a feature no ad company can ship."

---

## Category 8 — The Overlooked

*The brutal section: the gap between what the code can do and what it shows.*

1. **The IMU gesture classifier is finished and does nothing.** `halo-lua/app/imu_gesture.lua`: five tuned gestures, EMA smoothing, cooldowns, confidence scores — never instantiated in `main.lua`'s boot path. This is the platform's entire *interaction language* sitting in a drawer. The 10x version is Category 2.1 + gesture events in the figment grammar (5.1) — days of work, and it becomes the thing every demo leans on.
2. **The Datasette memory explorer is the best trust artifact in wearables, and it's unlaunched.** `memory/datasette_app.py` exists; no command exposes it. Every privacy claim the platform makes becomes *demonstrable* the day this ships (1.8, Demo 3). Half a day.
3. **46 GOPS at zero utilization.** The Ethos-U55 has no model on it and the host `NpuPerceptor` seam answers with heuristics. Pre-hardware, fine — but there's no `.tflite` in the repo, no Vela pipeline, no candidate zoo. The 10x version: adopt the 350ms Club (1.4) as the funnel and commit a `models/` directory with the quantization recipe now, so day-one silicon has a day-one model.
4. **The "LLM parser" — resolved: kept as an honest suggestion-layer, not deleted.** ~~regex in a trenchcoat~~ On inspection the critique was stale: `reality_compiler/intent_parser_llm.py` is *deterministic by default* (it *is* the regex `IntentParser` until a model is injected), and even with a model it folds the output back through the deterministic matchers, so the result is always a schema-legal `BehaviorIntent` and it never touches the budget proof (which gates deployment downstream, not the parser). The deterministic grammar *is* the safety story (5.4) — and this seam is structurally forbidden from weakening it: the model can only nudge messy speech *toward* the closed grammar, never invent a behavior outside it. **Decision:** keep it, documented explicitly as a suggestion layer *above* the closed grammar, never *inside* it (docstring rewritten; a test now proves an adversarial model can't escape the grammar). The wrong move would have been true constrained decoding *in the parse path* — that we still won't do.
5. **Device telemetry has no audience.** The glasses dutifully emit `TEL` (CARD_SHOWN/DISMISSED, HEAP watermarks every 60s, TICK_ERROR, PRIVACY_VEIL, FIGMENT_BANISHED) and the phone's `HaloBridge` routes it to an optional callback nobody registers. The 10x version: a "Device Vitals" card in the phone settings (heap trend, crash count, dismissal heatmap) — and the marketplace's banish-rate stat (5.2) is *already being broadcast* by every device.
6. **The Truth Lens is nine stages, seven test files, and off.** `truthlens_on=False`, fact_check stubbed, AU/face stubs awaiting NPU. It will never be turnable-on as a lie detector pointed at other people — but reframed inward it ships this quarter as Candor Mirror (2.7). The embarrassing part isn't that it's off; it's that its *shippable* half (prosody, linguistic, self-narrative drift) is bundled with its unshippable half.
7. **Sixteen palette slots; cards use six.** The YCbCr slot-animation system, slot leases, 1,024 luma tiers, and the synthesized primitives (bezier, elliptical_arc, polar_segments, radial_rays, point_cloud_text) are a full graphics identity that current cards barely touch. The 10x version is Forkable Skin (3.6) + Thread Lens (4.1): make the palette a *product surface*.
8. **The wake word is unbranded.** Docs and pitch say one thing; `voice.py` says "Hey Juno" with openWakeWord. Whatever the answer is — decide it, train the custom openWakeWord model (~a weekend: synthetic TTS positives + community recordings), and make the brand and the code agree before a single journalist notices they don't.
9. **`os_sandbox.py` says "Not yet wired" in its docstring while the docs describe the sandbox posture.** The recent WASM-tier commits close most of this, but the honest gap between security *documentation* and security *enforcement* is exactly the kind of thing an open project gets audited on. Wire it or caveat it — in the same week.
10. **The 58-capability catalog is invisible.** `capabilities.py` documents every optional integration with impact scores, and `python -m dreamlayer.capabilities` prints a beautiful state table — in a terminal, for nobody. The 10x version: it's a phone screen ("Your Brain can also learn to: recognize speakers ▸ translate offline ▸ dream-train nightly — install profile-mac extras?"), turning the latent product into an upgrade path users can *see*.

---

## The Top 5

Ranked across all categories by (impact on what DreamLayer is remembered for) × (buildability on the current stack):

1. **Proof-Carrying Behaviors + the Behavior Marketplace** (3.2 + 5.2) — This is the platform's singular idea: user-authored reality, provably safe, signed, revocable, with an 85/15 economy. Nobody else *can* build it, because nobody else made behaviors into data. Every other idea gets stronger if this exists.
2. **Nod to Remember + gesture events** (2.1 + 5.1) — The cheapest transformative build in the repo (the classifier is already tuned). It gives the platform an interaction language that photographs beautifully, and it turns memory from ambient surveillance into deliberate authorship — the ethical position, embodied in a gesture.
3. **Airplane Mode / Bring-Your-Own-Brain** (3.1 + Demo 2) — The open-platform thesis compressed into one stage moment. It converts "open source" from a values statement into a visceral capability difference no closed vendor can perform.
4. **Overnight Self** (2.2) — "A different model every morning, trained on your day, on your desk, while you sleep" is the first headline about *personal* AI hardware that cloud platforms structurally cannot write. The REM architecture was built for exactly this; `nightly_mlx.py` is waiting.
5. **Tin Can Telegraph + blind Confluence** (2.4 + Demo 4) — The emotional killer app. Presence with provably zero content is the feature that makes non-developers cry in demos and gives DreamLayer Cloud its reason to exist (the relay) without breaking a single privacy invariant.

> **Editor's amendment to this ranking.** Two changes after reading the whole doc against what's actually built: **(a) Overnight Self (#4) is over-ranked** — it's a research bet with no eval gate (see 2.2); demote it below Tin Can and don't headline it until the quality gate exists. **(b) Memory Grep / Datasette (1.8, Demo 3) belongs in this list.** It's ~half a day, the code already exists, and it's the single highest *trust-per-hour* item in the document — it turns every privacy claim into something a journalist can run a `SELECT` against, live, on stage. On the "what DreamLayer is remembered for" axis, a demonstrable privacy claim beats a fourth flavor of on-device intelligence. Ranked by buildability, **Nod to Remember (#2) is really #1** — the classifier is finished and tuned; it's the cheapest transformative build in the repo.

---

## The One I Almost Didn't Include

**GhostMode — the glasses-to-glasses mesh.** It's Pillar 2 in `docs/PLATFORM.md` (LE Coded PHY, S=8, ~125kbps, long-range, plus "The Beacon"), and the `MeshManager`/`Beacon` seams already sit in Confluence. I nearly left it out because it's the one idea that genuinely needs silicon on the desk: you cannot demo a radio mesh in a rasterizer, and pre-hardware, every sentence about it is a promise rather than a build.

But it's the most important idea in this document, for a structural reason the others only gesture at. Every closed AR platform is a *star topology*: device → their cloud → device, and the center of the star is the business. A mesh of Halos exchanging figment events, weather, and TinCan rhythms directly — no internet, no relay, no account — is a topology closed platforms cannot adopt without deleting themselves. It turns every wearer into infrastructure: two DreamLayer users on the same trail, in the same blackout, at the same protest, at the same festival, are *connected* in a way no Ray-Ban Meta owner will ever be, because their platform's center would be missing from the transaction. The figment grammar's `bond:` events (5.1) already define what travels; the budgets already prove it can't flood; the signing already proves who spoke. The moment hardware lands, the mesh is "only" a transport. Build the protocol spec now — publish it as openly as the figment grammar — and DreamLayer isn't a product with a community. It's a commons with a product attached, and that is the thing no one can copy.
