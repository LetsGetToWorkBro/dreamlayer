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
| B7 | Vinyl Oracle example plugin (1.2) | BUILD | `examples/` (+ needs a real classifier backend) | queued |
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
| O4 | GhostMode radio mesh (coda) | **REGISTERED** | publish protocol spec now; build on silicon | spec is the buildable half |
| O5 | ESP32 physical-events kit sketch (1.6) | **REGISTERED** | `examples/esp32/` sketch + one host route | sketch is owner hardware; host route is BUILD |
| V1 | Proof-carrying / signing / isolation tiers (3.2, 3.4) | DONE | `plugins/*`, this session's SDK arc | verify only |

| L1 | Thread Lens — steal color from the world (4.1) | **DONE** | `object_lens/palette_extract.py` + `ops_world_lenses.thread()` | ✅ extract k-swatch palette from a snapshot → `taught` memory (image not stored), veil-gated; 5 tests |
| L2 | Ember Lens — the anniversary layer (4.9) | **DONE** | `ops_world_lenses.ember()` | ✅ one pinned, year-ago memory surfaces; storm-suppressed, veil-gated, opt-in via pinning; 5 tests |

Remaining Category-4 lenses are **device/figment-shaped**, not host builds: Sous & Session (4.2) and Kiln (4.3) are figment templates (example content); Waypath (4.7) is GPS/on-glass. Docent (B14) and Rosetta Live (B13) already shipped.

---

## Log

- *(this file created)* — triaged the doc; started **B1 Memory Grep**.
- **B5 + B6 shipped** — Glass Desk devkit (`python -m dreamlayer.simulator --watch <plugin>` live-renders the card through the real device renderer with the safe-radius overlay) and Figment Golf (`dreamlayer golf verify` — budgets referee eligibility, score = expressiveness per byte).
- **D1 + D2 shipped** — LLM parser kept as a documented suggestion-layer; Nod to Remember wired host+grammar+boot-flag (default OFF) with a lupa nod-injection test.
- **B1 shipped** — `dreamlayer memories path` (where your data lives) and `dreamlayer memories browse` (Datasette over the SQLite memory file: immutable/`-i`, bound to 127.0.0.1, veil-gated via `$DREAMLAYER_VEIL`/`veil.lock`, four canned queries shipped in the metadata). Exposed the pre-existing-but-unwired `memory/datasette_app.py`. Next: **B4** (verify `os_sandbox`) and the **D1 (LLM parser)** decision.
