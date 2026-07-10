# Innovation Build — the working ledger

This is the execution ledger for turning [`INNOVATION_SESSION.md`](INNOVATION_SESSION.md)
into shipped code. Every idea is triaged into one lane and given a **home** (the
module/dir where it belongs) so nothing lands in the wrong place.

**Lanes**
- **BUILD** — code-reachable now (the seam exists unwired, or it's a pure fix). We implement it, tested, in its home.
- **OWNER** — needs hardware, silicon, an account, or a human decision the code can't make. Registered in [`AUDIT_ACTIONS.md`](AUDIT_ACTIONS.md); *not* faked here.
- **DONE** — already shipped (often this session). Verify + reference; no new work.
- **DECIDE** — a real fork the owner should call before we touch it (destructive delete, on-glass boot change, etc.).

Rule we learned on contact: **verify each idea against the current tree before acting** — several of the doc's critiques are already stale (e.g. `os_sandbox` is wired; the "LLM parser" is an honest optional seam, not "regex in a trenchcoat"; `datasette_app.py` already exists). Verify, then build.

---

## Status board

| # | Idea (doc ref) | Lane | Home | Status |
|---|---|---|---|---|
| B1 | Memory Grep — browse your memory as a file (1.8, 3.3, C8#2) | **DONE** | `cli.py` `memories` group + `memory/datasette_app.py` | ✅ `memories path` / `browse` (read-only, veil-gated, canned queries); 8 tests |
| B2 | Data trinity — `memories export/import/burn` (3.3) | **DONE** | `cli.py` `memories` group | ✅ export (copy out), import (restore, `--force` to clobber), burn (delete, guarded behind `--yes`); 5 tests |
| B3 | Capability catalog surfaced (C8#10) | **DONE** | `capabilities.py` CLI + phone `app/capabilities.tsx` + `useCapabilityStore` | ✅ phone screen fetches `/dreamlayer/capabilities`, renders the "your Brain can also learn to…" upgrade path (impact-sorted), linked from settings; 5 tests (store + screen) |
| B4 | Verify `os_sandbox` wired; kill stale docstring (3.4, C8#9) | **DONE** | `plugins/os_sandbox.py` | ✅ verified wired via isolation.py; corrected stale "WASM not yet wired" line |
| B5 | Glass Desk devkit — `simulator --watch` (1.1) | **DONE** | `simulator/glass_desk.py` + `simulator/server.py` | ✅ live-renders a plugin card through the real 256px renderer + safe-radius overlay on save; watchdog + poll fallback; `--once`; 3 tests; SDK.md |
| B6 | Figment Golf CLI — `golf verify` (1.3) | **DONE** | `reality_compiler/v2/golf.py` + `cli.py` `golf` group | ✅ referees budgets + scores expressiveness/byte; bare + wrapped listings; 5 tests |
| B7 | Vinyl Oracle example plugin (1.2) | **DONE** | `plugins/vinyl_oracle.py` | ✅ object-lens `PanelProvider` + `network`: reads a sleeve's artist/title, resolves the pressing against Discogs (year/label/country/format + want-over-have collectibility), per-release TTL cache, token persisted in `ctx.settings` (API v2); 14 tests, all offline. Honest reach: a live demo needs a real vision backend (YOLO→moondream→CLIP) to read the sleeve + a Discogs token past the anon rate limit |
| B8 | Earcon/Haptic pack manifest + validator (1.5) | **DONE** (host) | `plugins/packs.py` + `cli.py` `packs validate` | ✅ store-gate validator enforces ≤400ms patterns, silent answer_ahead, ≥2-variant rotation; 7 tests. Follow-on: phone pack picker |
| B9 | Proof-carrying install safety card (3.2) | **DONE** | `reality_compiler/v2/safety.py` + `cli.py` `figment safety` | ✅ renders the budget proof as a "this behavior CANNOT…" consent card; violators flagged; 5 tests |
| B10 | Figment grammar: gesture/place/presence/cadence/ledger/slot events (5.1) | partial | `reality_compiler/v2/figment.py` grammar + `budgets.py` | ✅ 5.1 #1 gestures, #2 place, #3 presence (enforced at verify), #4 cadence (breathing envelope in the interpreter + budget), #5 ledger emits (`record` → `log_recorded()` to the Vault log). Remaining: host-firing of place/bond events + #6 slot subscriptions |
| B11 | Device Vitals surface — TEL has an audience (C8#5) | **DONE** | phone `app/vitals.tsx` + `useVitalsStore` + `useGlassesStore` wiring | ✅ HaloBridge `onTelemetry` now feeds a vitals store (heap trend/sparkline, crashes, dismiss rate, banishes, veil); screen linked from settings; 6 tests |
| B12 | Retrace — ambient-sighting recall (2.6) | **DONE** | `orchestrator/ops_commitments.py` | ✅ `retrace(subject)` — recency-blended, place+time ("kitchen counter, 8:40am"), veil-gated, draws ObjectRecallCard; `_locate` falls back to it when no anchor; 6 tests |
| B13 | Rosetta Live offline captions (4.6) | **DONE** | `orchestrator/orchestrator.py` + `ops_world_lenses.py` | ✅ wired the offline Argos backend into `self.rosetta` (identity when absent); `translate_heard()` — the ear, one subtitle card/utterance, veil-gated; 4 tests |
| B14 | Docent Lens — venue RAG plugin (4.5) | **DONE** | `orchestrator/ops_world_lenses.py` (wires `localrecall_api`) | ✅ `docent(query, client, synth)` — grounded answer from a venue's LocalRecall collection, optional synthesizer, veil-gated, ScholarCard; 5 tests |
| B15 | Heirloom figments — `meta.dedication` + Inherited vault view (5.5) | **DONE** | `reality_compiler/v2/figment.py` + `vault.py` | ✅ `fig.dedicate()`/`dedication()` (signed), `Vault.inherited()`; roundtrip test; 3 tests |
| B16 | "What the cloud can see" panel (C6) | **DONE** | `server.py` `/dreamlayer/cloud` + phone `app/cloud.tsx` + `useCloudViewStore` | ✅ Brain reports opaque shapes only (vault bytes, room ids, counts) + "cannot see" list; phone panel renders the nothing + guarantees; 2 host + 4 phone tests |
| D1 | LLM intent parser: keep-as-suggestion-layer vs delete (C8#4) | **DONE** | `reality_compiler/intent_parser_llm.py` | ✅ owner chose KEEP; docstring reframed as suggestion-layer, grammar-escape test added, doc #4 reconciled |
| D2 | Nod to Remember: wire host + sim, boot flag OFF (2.1) | **DONE** | `halo-lua/main.lua` + `orchestrator/ops_ingest.py` + `reality_compiler/v2/figment.py` | ✅ D2a host pin path + `imu:<gesture>` grammar; ✅ D2b main.lua boot-flag classifier (default OFF) + accel feed, lupa device test injects a synthetic nod → `imu_gesture` envelope. 8 gesture tests; full suite 1982 green |
| D3 | **Answer-ahead default** — flip `copilot_on`? (2.5) | DECIDE | `orchestrator/answer_ahead.py` | stays off by default unless told |
| D4 | Overnight Self — the eval gate (2.2) | **DONE (gate)** | `rem/adapter_gate.py` | ✅ no-regression acceptance over a versioned eval set + one-tap rollback (`AdapterGate`/`AdapterRegistry`/`gate_nightly`), model-agnostic; 7 tests. Follow-on: wire into `MlxNightlyTrainer` when MLX is real |
| O1 | NPU: `.tflite` + Vela recipe + candidate zoo (C8#3, 1.4 tail) | **REGISTERED** | new `models/` + `AUDIT_ACTIONS.md` | register recipe, no silicon |
| O2 | Live WASM e2e (needs wasmtime + python.wasm) (3.4) | **REGISTERED** | `plugins/wasm_host.py` | seam done; runtime is operator's |
| O3 | Custom wake-word model for the chosen brand phrase (C8#8) | **REGISTERED** | `orchestrator/wakeword.py` | brand decision + training run |
| O4 | GhostMode radio mesh (coda) | **SPEC DONE** | `docs/GHOSTMODE_PROTOCOL.md` | ✅ v1.0 wire spec published (layering, keys, frame + normative test vector, receive rules, Beacon, privacy invariants, security model, conformance) — pinned to the code by 4 tests. Mesh itself still needs silicon. |
| O5 | ESP32 physical-events kit sketch (1.6) | **REGISTERED** | `examples/esp32/` sketch + one host route | sketch is owner hardware; host route is BUILD |
| V1 | Proof-carrying / signing / isolation tiers (3.2, 3.4) | DONE | `plugins/*`, this session's SDK arc | verify only |

| L1 | Thread Lens — steal color from the world (4.1) | **DONE** | `object_lens/palette_extract.py` + `ops_world_lenses.thread()` | ✅ extract k-swatch palette from a snapshot → `taught` memory (image not stored), veil-gated; 5 tests |
| L2 | Ember Lens — the anniversary layer (4.9) | **DONE** | `ops_world_lenses.ember()` | ✅ one pinned, year-ago memory surfaces; storm-suppressed, veil-gated, opt-in via pinning; 5 tests |

| L3 | Waypath Lens — the dot, no maps app (4.7) | **DONE** | phone `src/nav/{waypath,osrm}.ts` + `useWaypathStore` + `app/waypath.tsx` | ✅ geometry (9 tests) + OSRM routing adapter (self-hostable, fetch-injected) + store + screen (one-dot ring, distance, arrival, expo-location guarded); GPS + routing are seams, not Apple/Google Maps; 20 tests total |
| L4 | Sous & Kiln — example figments (4.2, 4.3) | **DONE** | `reality_compiler/v2/recipes.py` + `examples/figments/*.json` | ✅ budget-verified builders + committed JSON; double-nod advance, battery-low escape, print counter; 6 tests |

Docent (B14) and Rosetta Live (B13) already shipped as host lenses; Thread (L1) and Ember (L2) too.

### Second sweep — line-by-line re-audit (things the first pass missed)

A full re-read of `INNOVATION_SESSION.md` against the tree turned up three **BUILD**-lane ideas that were never triaged and are code-reachable now. All three shipped:

| # | Idea (doc ref) | Lane | Home | Status |
|---|---|---|---|---|
| P1 | The 350ms Club — perception bench under the glance budget (1.4) | **DONE** | `object_lens/bench.py` + `cli.py` `bench perception` | ✅ deterministic labeled set, real deadline runner drops late answers, accuracy × latency score; any `add_perceptor` callable can be benched; degrades w/o numpy. 6 tests. (Leaderboard submit stays OWNER — hosted worker.) |
| P2 | $6 physical-events kit — sensor → figment host route (1.6 / O5 tail) | **DONE** | `reality_compiler/v2/transport.py` + `deployer.py` + `server.py` route + `main.lua` + `examples/esp32/` | ✅ `event_envelope`/`push_event`/`Brain.rc_event` + `POST /dreamlayer/event/ble/<n>`; `main.lua` routes `event` into the running figment; MicroPython reed-switch sketch + README. 9 tests, luacheck clean. Closes the "host route is BUILD" note under O5. |
| P3 | Semantic-impersonation screen — shared-figment text mimicry (5.4) | **DONE** | `reality_compiler/v2/impersonation.py` (folded into `safety.py`) | ✅ screens figment text for power/system/security/alarm/message chrome, marks shared origin + provenance glyph, flags only shared-AND-mimicking; surfaced on the safety card. "The sandbox proves physics; provenance proves voice." 10 tests. |

**Still open after the re-audit — honest dispositions (not silently dropped):**

- **2.3 Who's Talking** — modules (`speaker_ecapa`, `diarize_diart`, `introduction`) + the calibration harness (`scripts/calibrate_social.py`, W3) exist and `on_speaker` is wired; the live self-introduction→name path needs real audio + a labeled ROC set to tune the threshold. **OWNER** (real-data numbers), harness is BUILD-done.
- **2.7 Candor Mirror** — the *belief-drift* half is wired (`consistency.py` "Candor", live in the orchestrator). The *speech-pace live arc + filler post-mortem* self-coach half (`filler.py` exists) is unbuilt. **BUILD (deferred)** — a genuine new lens, larger than a sweep item.
- **2.8 Inner Weather, Outer Light** — ✅ **DONE.** `weather_river.WeatherBaseline` (river EWMean w/ running-mean fallback) learns your state's mean+spread; `InnerWeather` grows an opt-in `calibrate` mode that fires the storm warning on what's unusual *for you* (`is_elevated`), the dream engine opts in, the class default stays off so every pinned test holds. The churn stays absolute (calm = calm); only the warning is personal. 7 tests, incl. a divergence case.
- **3.1 Bring-Your-Own-Brain ceremony** — ✅ **DONE.** The HealthLedger now records per-seam **latency** (`record_ok(seam, ms=…)`, EWMA-smoothed; the router times each tier call); the Brain exposes the tier ladder (`_brain_view_payload` + GET `/dreamlayer/brain/tiers`) — on-device → Mac mini → cloud, each with measured latency + reliability + enabled/active state + the loaded model cartridge. Phone: `useBrainTiersStore` + `app/brain-tiers.tsx` — a "Brain" ceremony screen rendering the live ladder with latency and the cloud/incognito swap controls, degrading to phone-only when no Mac is paired, linked from Settings. 5 host + 5 phone tests.
- **3.5 The Instrument / Research Mode** — `pipelines/lsl_transport.py` exists + capability registered; the opt-in "Research Mode" LSL stream surface is unbuilt and needs `pylsl` (an extra). **OWNER-dep**, surface is BUILD.
- **3.6 Forkable Skin** — ✅ **DONE.** `display/theme.lua`: a theme is a Lua table restyling the static identity (semantic colors + 5-step type scale + motion), validated against the skin budget — only the static tokens are restylable (the dynamic slot bank 1-6 is unnameable, so the ≤8-writes/tick invariant holds), type stays in the [10,22] font band, motion bounded; refused whole on any violation. `main.lua` applies `_G.DREAMLAYER_THEME` at boot (falls back to defaults, telemetry on failure). Two reference skins: `themes/cyberpunk.lua`, `themes/high_contrast.lua` (accessibility). 10 lupa tests; luacheck clean.
- **4.2 Session profile** — the Sous & Kiln timer/metronome family shipped (L4); the *Session* music profile (beat/pitch tracking) needs `aubio`/`librosa`. **OWNER-dep**; the metronome-figment core is BUILD.
- **5.3 Compiler self-teaching** — ✅ **repertoire ranking DONE.** `reality_compiler/v2/repertoire_ranker.py` (`RepertoireRanker`, river-optional like `taste_river`) scores each kept figment by use frequency + completion rate (finished vs. banished) + time-of-day fit; `RealityCompilerV2` logs deploy+hour and outcomes to the vault and rehydrates the ranker on boot (survives restart); the Brain surfaces a ranked repertoire + a "start the usual?" suggestion, learns a rejection from every revoke. 12 tests. ✅ **rehearsal refinement DONE** too — `reality_compiler/v2/refine.py`: a banish now records *which scene* (`record_outcome(..., scene, elapsed)`); `propose_refinement` detects a repeated same-scene banish hotspot and proposes the trim in rehearsal words ("you end this around 20:00 of 25:00 — shorten it?"); `build_variant` re-signs a fresh, budget-verified figment with the scene trimmed and `meta.refined_from` lineage (original kept). Brain `rc_refine_suggestion`/`rc_refine_apply`. 9 tests. ✅ **grammar mining DONE** (local half) — `reality_compiler/v2/grammar_mine.py`: a rehearsal beat that falls out of the closed grammar (`parse_utterance → ("label", …)`) contributes its words to a local, counts-only near-miss tally (known vocab + stopwords filtered); recurrence surfaces the words people keep trying to say. Wired into the Brain's rehearse path + `rc_grammar_candidates`; persists under the vault. 9 tests. **All three 5.3 sub-parts shipped**; only the community-aggregate roll-up (opt-in, through the registry) stays OWNER.
- **5.4(b) on-device provenance glyph** — the host discloses `provenance_glyph` (P3); rendering the `shield_glyph` on shared figments in `figment_stage.lua` is a small **BUILD (deferred, Lua)** follow-on.
- **1.7 Duet Pomodoro** — `DuetSession` + `interval_figment` exist; a two-person pomodoro example over the bond needs the hosted relay (Category 6). **OWNER-relay**, example is BUILD.

The rest of the document (Category 6 Cloud doctrine, Category 7 demo scripts) is prose/stage-direction, already reflected in `docs/CLOUD.md` and the shipped demos — no code owed.

### Less-CLI surfacing (Mac panel / website)
| S1 | Memory Grep in the Mac panel | **DONE** | `server.py` + `panel.py` | ✅ "your memory is a file" — browse (Datasette) / export, 3 endpoints; 6 tests |
| S2 | "What the cloud can see" in the panel | **DONE** | `panel.py` (reads `/dreamlayer/cloud`) | ✅ opaque-shapes + can't-see readout in the cloud section |
| S3 | Proof-carrying safety card on the website | **DONE** | `landing/plugins.html` | ✅ trust section showing the real "this behavior CANNOT…" card; 1 test |

---

## Log

- *(this file created)* — triaged the doc; started **B1 Memory Grep**.
- **B5 + B6 shipped** — Glass Desk devkit (`python -m dreamlayer.simulator --watch <plugin>` live-renders the card through the real device renderer with the safe-radius overlay) and Figment Golf (`dreamlayer golf verify` — budgets referee eligibility, score = expressiveness per byte).
- **D1 + D2 shipped** — LLM parser kept as a documented suggestion-layer; Nod to Remember wired host+grammar+boot-flag (default OFF) with a lupa nod-injection test.
- **B1 shipped** — `dreamlayer memories path` (where your data lives) and `dreamlayer memories browse` (Datasette over the SQLite memory file: immutable/`-i`, bound to 127.0.0.1, veil-gated via `$DREAMLAYER_VEIL`/`veil.lock`, four canned queries shipped in the metadata). Exposed the pre-existing-but-unwired `memory/datasette_app.py`. Next: **B4** (verify `os_sandbox`) and the **D1 (LLM parser)** decision.
