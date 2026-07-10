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
| B2 | Data trinity — `memories export/import/burn` (3.3) | BUILD | `cli.py` + `ai_brain/server/cloud_sync.py` | queued (burn is destructive → confirm) |
| B3 | Capability catalog surfaced (C8#10) | BUILD | `capabilities.py` CLI (done) → phone screen (later) | partial |
| B4 | Verify `os_sandbox` wired; kill stale docstring (3.4, C8#9) | **DONE** | `plugins/os_sandbox.py` | ✅ verified wired via isolation.py; corrected stale "WASM not yet wired" line |
| B5 | Glass Desk devkit — `simulator --watch` (1.1) | **DONE** | `simulator/glass_desk.py` + `simulator/server.py` | ✅ live-renders a plugin card through the real 256px renderer + safe-radius overlay on save; watchdog + poll fallback; `--once`; 3 tests; SDK.md |
| B6 | Figment Golf CLI — `golf verify` (1.3) | **DONE** | `reality_compiler/v2/golf.py` + `cli.py` `golf` group | ✅ referees budgets + scores expressiveness/byte; bare + wrapped listings; 5 tests |
| B7 | Vinyl Oracle example plugin (1.2) | BUILD | `examples/` (+ needs a real classifier backend) | queued |
| B8 | Earcon/Haptic pack manifest + validator (1.5) | BUILD | `plugins/package.py` + `plugins/validate.py` | queued |
| B9 | Proof-carrying install safety card (3.2) | BUILD | `reality_compiler/v2/budgets.py` report → render | queued |
| B10 | Figment grammar: gesture/place/presence/cadence/ledger/slot events (5.1) | partial | `reality_compiler/v2/figment.py` grammar + `budgets.py` | ✅ 5.1 #1 gesture events (`imu:<g>`) shipped with D2; place/presence/cadence/ledger/slot still queued |
| B11 | Device Vitals surface — TEL has an audience (C8#5) | BUILD | phone settings screen + `HaloBridge` TEL callback | queued (phone) |
| B12 | Retrace — ambient-sighting recall (2.6) | **DONE** | `orchestrator/ops_commitments.py` | ✅ `retrace(subject)` — recency-blended, place+time ("kitchen counter, 8:40am"), veil-gated, draws ObjectRecallCard; `_locate` falls back to it when no anchor; 6 tests |
| B13 | Rosetta Live offline captions (4.6) | BUILD | wire `social_lens/rosetta_argos.py` | queued |
| B14 | Docent Lens — venue RAG plugin (4.5) | BUILD | wire `memory/localrecall_api.py` | queued |
| B15 | Heirloom figments — `meta.dedication` + Inherited vault view (5.5) | **DONE** | `reality_compiler/v2/figment.py` + `vault.py` | ✅ `fig.dedicate()`/`dedication()` (signed), `Vault.inherited()`; roundtrip test; 3 tests |
| B16 | "What the cloud can see" panel (C6) | BUILD | phone/panel + `cloud_sync.py` byte-shapes | queued |
| D1 | LLM intent parser: keep-as-suggestion-layer vs delete (C8#4) | **DONE** | `reality_compiler/intent_parser_llm.py` | ✅ owner chose KEEP; docstring reframed as suggestion-layer, grammar-escape test added, doc #4 reconciled |
| D2 | Nod to Remember: wire host + sim, boot flag OFF (2.1) | **DONE** | `halo-lua/main.lua` + `orchestrator/ops_ingest.py` + `reality_compiler/v2/figment.py` | ✅ D2a host pin path + `imu:<gesture>` grammar; ✅ D2b main.lua boot-flag classifier (default OFF) + accel feed, lupa device test injects a synthetic nod → `imu_gesture` envelope. 8 gesture tests; full suite 1982 green |
| D3 | **Answer-ahead default** — flip `copilot_on`? (2.5) | DECIDE | `orchestrator/answer_ahead.py` | stays off by default unless told |
| D4 | Overnight Self nightly LoRA (2.2) | DECIDE→BUILD | `rem/nightly_mlx.py` | build the eval gate FIRST (see 2.2 caution) |
| O1 | NPU: `.tflite` + Vela recipe + candidate zoo (C8#3, 1.4 tail) | OWNER | new `models/` + `AUDIT_ACTIONS.md` | register recipe, no silicon |
| O2 | Live WASM e2e (needs wasmtime + python.wasm) (3.4) | OWNER | `plugins/wasm_host.py` | seam done; runtime is operator's |
| O3 | Custom wake-word model for the chosen brand phrase (C8#8) | OWNER | `orchestrator/wakeword.py` | brand decision + training run |
| O4 | GhostMode radio mesh (coda) | OWNER | publish protocol spec now; build on silicon | spec is the buildable half |
| O5 | ESP32 physical-events kit sketch (1.6) | OWNER-ish | `examples/esp32/` sketch + one host route | sketch is owner hardware; host route is BUILD |
| V1 | Proof-carrying / signing / isolation tiers (3.2, 3.4) | DONE | `plugins/*`, this session's SDK arc | verify only |

Categories 4 (lenses), 7 (demos), and the Top-5 are **specs/narratives**, not build items — they compose the BUILD rows above. They stay in `INNOVATION_SESSION.md` as the design source.

---

## Log

- *(this file created)* — triaged the doc; started **B1 Memory Grep**.
- **B5 + B6 shipped** — Glass Desk devkit (`python -m dreamlayer.simulator --watch <plugin>` live-renders the card through the real device renderer with the safe-radius overlay) and Figment Golf (`dreamlayer golf verify` — budgets referee eligibility, score = expressiveness per byte).
- **D1 + D2 shipped** — LLM parser kept as a documented suggestion-layer; Nod to Remember wired host+grammar+boot-flag (default OFF) with a lupa nod-injection test.
- **B1 shipped** — `dreamlayer memories path` (where your data lives) and `dreamlayer memories browse` (Datasette over the SQLite memory file: immutable/`-i`, bound to 127.0.0.1, veil-gated via `$DREAMLAYER_VEIL`/`veil.lock`, four canned queries shipped in the metadata). Exposed the pre-existing-but-unwired `memory/datasette_app.py`. Next: **B4** (verify `os_sandbox`) and the **D1 (LLM parser)** decision.
