# Audit remediation — the owner-action register

> **Standing practice:** every security/privacy remediation gets an
> adversarial re-audit before it is trusted as closed — independent reviewers
> tasked to *refute* the fix, not confirm it, because a self-written
> remediation shares its author's blind spots and a green suite is not proof.
> This has repeatedly caught live leaks a passing audit declared fixed (the
> `no_cloud` phone-egress leak; the ember `purge_all` residue). The method is
> the `refute-remediation` skill; the policy is in `CONTRIBUTING.md`.

The 2026-07 system audit was remediated in code where code could fix it,
in three passes:

- **Pass 1 (audit fixes):** BLE framing interop, on-glass crash guard +
  banish kill switch, v1 codegen deletion, Ed25519 plugin signing,
  persistent ANN + retention lifecycle + cold-start maturity arc, the
  health ledger and latency contracts, the phone connection machine/
  outbox/caches/haptics/Look screen, luacheck/DCO/phone/web CI, registry
  rate limits, doc corrections.
- **Pass 2 (A/A+ push):** the orchestrator god-object decomposed into a
  coordinator + 10 ops mixins (behaviour-preserving); Plugin API v2
  (lifecycle + veil-gated events + settings) with a real subprocess
  isolation jail for untrusted plugins; the capture path wired end to end
  (mic→VAD→ASR→speaker→hub) plus a wake-word seam; real Moondream/CLIP
  vision backends behind a ladder; the Rig-3 social calibration harness
  and a retrieval-quality regression floor; dismissal learning; the phone
  BLE bridge as pure-TS-over-injected-transport (Expo Go intact) with an
  inert ble-plx shell, a jest-expo component-test project, and Look
  promoted to a tab; a cross-device e2e (live Brain ↔ hub ↔ real device
  Lua), BLE chaos storms, structured logging, `docs/CONCURRENCY.md`, the
  panel per-seam health view, and a `--cov-fail-under=85` coverage gate.
- **Pass 3 (offline intelligence made real):** the offline default embedder
  is now a real dependency-free lexical model (hashed char-ngrams, not the
  32-d mock) and the offline default vision backend a real pixel-reading
  classifier, each held to an enforced quality floor; the recall threshold
  was recalibrated to the better-behaved embedder, object-memory summaries
  are natural language rather than stringified dicts, and a non-blocking
  `real-models` CI workflow exercises MiniLM/CLIP for real.
- **Pass 4 (the 2026-07 re-audit's P0–P2 findings, all fifteen closed,
  PRs #292–#305):** the Mac brain binds localhost with an auto-generated
  token; capture is thread-safe and never confirms an unsaved commitment;
  phone purge clears the offline cache; the Timbre/TinCan clock and the
  figment clamp bypass are fixed on-glass; CI runs every test with a
  ruff+mypy gate in the required job; the incognito/pause recall contract
  is one gate applied everywhere; forget evicts the vector; the cloud
  embedder fails loud; plugin security defaults on (alias-following AST
  scan, no-exec validation, untrusted-by-default isolation); the menu bar
  respects the cloud opt-in; all four interpreters clamp text by one
  canonical unit (codepoint-safe UTF-8 bytes) with a non-ASCII parity
  sweep; the mutation gate covers the whole safety core under per-file
  survivor ceilings, the flash check measures the flashing component per
  WCAG, and the flaky float proof is reclassified honestly; the phone
  ships a11y roles/labels, demo fiction is contained to demo mode, the BLE
  transport is attached at startup, and the Memories body is localized in
  nine locales; ANN writes batch with purge-honest immediate deletes and a
  boot drift rebuild, dismissal windows are per card type, and the passive
  cadence knob is enforced.
- **Pass 5 (a second full-system re-audit's live-input findings, PRs
  #309–#313):** every finding was a "looks wired, breaks or lies on live
  input" defect. The default `{slot}` render used raw substitution in two
  interpreters — a `%` in host slot text *raised* on the device's Lua 5.3
  (figment fell to the fallback ring every tick) and `$&`/`$1`/`$$`
  *silently corrupted* the JS line; both default paths now use
  verbatim-insert function replacement, matching Python, with `%`/`$`/backref
  parity vectors so the class can't hide again. Two recall surfaces bypassed
  the pause veil (`ask()` and the passive `tick()` loop) — both are now
  recall-gated. The Mac brain server binds `127.0.0.1` by default (the old
  `0.0.0.0` made "localhost by default" a claim, not a fact); the login-agent
  appliance opts into the LAN explicitly and mints a token. The cloud-egress
  ledger counts what *leaves* the device, not only what returns non-empty
  (an errored/empty call still egressed). The plugin AST scan now follows
  value rebinds (`o = os`), callable rebinds (`run = os.system`), and
  `getattr(os, …)` — constant and dynamic — as defence-in-depth; the untrusted
  isolation tier is loud when no OS/WASM kernel sandbox is present and
  fails closed under `DL_REQUIRE_SANDBOX`, deciding before it launches the
  child. The phone's last English strings are localized: the People screen's
  live literals and the entire Settings screen (~60 strings) now carry all
  nine locales, and icon-only ✕ controls are labelled for VoiceOver/TalkBack.
- **Pass 6 (adversarial deep-dive on Intelligence + Memory, PRs #315–#318):**
  two adversarial auditors swept the perception/answer paths and the storage/
  index/recall lifecycle for code-reachable "lies on live input" defects on the
  default (no-ML-deps) configuration. Privacy/veil: `purge_all` now erases the
  `places`/`entities` tables (a place row is a location signature — a residue
  after a full wipe), the capture veil fails CLOSED when the privacy gate
  errors, and the index-skipping purge helpers in `memory/privacy.py` are gone.
  Recall truth: the "Nod to Remember" gesture now embeds AND indexes its row
  (it was invisible to ANN recall), a structured conversation writes each
  promise ONCE (was double-written by the legacy + tier-1 extractors), a
  kind-filtered ANN query falls through to the exact scan instead of starving
  `top_k`, and a genuine `0.0` confidence is no longer coerced to `0.5`.
  Perception default paths: the Veritas verdict parser handles negation ("not
  correct" is DISPUTED, not SUPPORTED), the energy-VAD normalises by dtype
  full-scale so near-silence isn't "speech", the offline vision rung maps
  confidence to `[0,1)` so a wall/noise is gated out rather than labelled, the
  text-density heuristic normalises by full scale (a flat wall scores ~0), the
  LucidRecall router matches on word boundaries and routes fact questions to
  memory, and tier-1 ingest stops minting "Person: Tomorrow/Thursday" from
  sentence-initial capitals. Concurrency/durability: lock-guarded DB backfills,
  a locked ring buffer, an ANN dirty counter that survives a failed save, a
  batched retention sweep, and a maturity gate that earns RESIDENT on observed
  cards (not vacuously) and counts an expired card as a dismissal. Plus the
  minor tail (glance `0.0`-ambiguity, empty dream anchors, sqlite-vec eviction,
  a stale classifier docstring). Documented, NOT faked: without a speaker
  diarizer, capture cannot tell the wearer's voice from a bystander's, so the
  `speaker=""`-means-wearer contract stays and the attribution question is
  gated on the diarizer rather than papered over.

What remains is, by nature, **owner action** — things a terminal cannot
do. This file is the tracked list; delete entries as they land. Note that
Pass 2 built the *code half* of several items below (the capture pipeline,
the vision backends, the BLE bridge, the calibration harness); what's left
under them is the physical/organizational half.

## 1. Close the first real loop on real glass (the audit's One Thing)
The loopback rig (Rig 0, `test_ble_loopback.py`) is in CI; the crash
guard, banish gesture, and heap-watermark telemetry are on the device
code. What's left needs a physical Halo:
- [ ] flash `halo-lua/` with `scripts/upload.py`; run
      `FIRST_DEVICE_TEST_PLAN.md` until one Horizon, one card, and one
      figment put→swap→ack survive over real BLE
- [ ] record the heap watermark (`TEL HEAP`) — the first real number for
      the Lua memory ceiling
- [ ] begin marking device-dependent tests `@pytest.mark.hardware` (the
      marker infrastructure exists; zero tests use it)

## 2. Ask Brilliant Labs the load-bearing firmware question
Roughly half the lens catalogue consumes transcribed speech
(hardware-seams: "The transport budget"). The blocking question:
- [ ] does Halo firmware expose the microphone with an on-glass codec
      (Opus-class, 16–24 kbps), or a raw stream the phone can encode?
- [ ] secondarily: snapshot camera API shape + JPEG size envelope, and
      whether LE Coded PHY group transport (GhostMode) is reachable

## 3. Privacy counsel review (now overdue — the repo is public)
`PRIVACY_MODEL.md` now states the bystander-biometrics legal theory
(introduction-as-consent, transient probe embeddings, CUBI/BIPA/GDPR).
- [ ] one hour with an actual privacy lawyer on that section
- [ ] decide the per-jurisdiction face-matching opt-in default

## 4. Go-public checklist (docs/OPEN_SOURCE.md)
The flip happened (July 2026, full history — strategy docs published with
it), so both sharpened items are resolved or downgraded:
- [x] fresh-history vs full-history — decided by doing: full history
- [ ] (optional) install the DCO GitHub App for its reviewer-facing UX;
      dco.yml already enforces trailers on external PRs
Remaining owner-console items live in OPEN_SOURCE.md's checklist: the
`security@`/`conduct@` aliases, Sponsors enrollment, branch protection,
Discussions, topics + website field.

## 5. Trademark
NOTICE asserts rights in the DreamLayer name and mark; unregistered,
they're thin.
- [ ] file the registration (name + ring mark)

## 6. DreamLayer Cloud sequencing
CLOUD.md P1 (accounts, Stripe, managed-AI proxy) puts user tokens behind
one solo-operated service — the one place the privacy marketing and an
attacker meet.
- [ ] sequence P1 AFTER the first real device loop closes
- [ ] external security review of the managed-AI proxy before launch
- [ ] account-bind marketplace votes before any "top rated" ranking ships
      (the Worker's per-IP limits are a floor, not a ceiling)

## 7. Perception bench (Rig 3)
The Social Lens threshold (0.65) and the new top-2 margin (0.08) are
placeholders calibrated against a stub embedder. The *offline* intelligence
path is now real, not mock: the default text embedder is a dependency-free
char-ngram lexical model (`HashingEmbeddingProvider`) held to an enforced
precision@3 floor, and the default vision backend is a real pixel-reading
`HeuristicVisionClassifier` held to an accuracy floor; the neural backends
(MiniLM, CLIP) run for real in the `real-models` CI workflow. What still
needs the physical embedder:
- [ ] with the real on-device face embedder: ROC over genuine/impostor
      pairs, set the Social-Lens threshold + margin from data, and add the
      fixed-photo-set recognition regression to CI

## 8. Innovation-program owner actions (INNOVATION_SESSION.md)

The 2026-07 innovation pass shipped every code-reachable idea (tracked in
`INNOVATION_BUILD.md`). These five are the residue — genuinely blocked on
hardware, a training run, an account, or a decision a terminal can't make.
Each notes the code half already in the tree.

### 8.1 NPU: a day-one model for the Ethos-U55 (Cat 8 #3, 1.4)
The 46-GOPS NPU is at 0% utilization; `ai_brain/perception.py: NpuPerceptor`
answers with heuristics, and there is no `.tflite`, no Vela pipeline, no
candidate zoo. The software perception bench (`test_perception_bench.py`) and
the "350ms Club" seam ship; the model does not.
- [ ] commit a `models/` directory with a quantization recipe and one
      candidate model, so day-one silicon has a day-one model
- [ ] wire the Vela compile step (needs the vendor toolchain + real silicon)

### 8.1b Plugin signing: sign the first-party catalogue (P1-10)
The gate now defaults to the secure posture — the validation gate never
executes a package on the install path (smoke is author-opt-in), its AST
screen follows import aliases (`import os as o; o.system(...)` is caught),
and `load_installed` defaults to `isolate="untrusted"` so unsigned
third-party code runs in the capability jail, not the host. The one part
a terminal cannot do is mint the trust root: the first-party catalogue
ships under the curated-registry model, unsigned, because signing it needs
a private key that must never touch the repo.
- [ ] generate the `DreamLayer Team` Ed25519 keypair off-repo; register
      ONLY the public key in `registry/keys.json` (`publishers` is empty by
      design until then); sign the first-party packages; keep the private
      key off every machine that pushes to the repo. Once signed, the
      first-party plugins take the in-process trusted path and the
      untrusted-by-default jail applies to everyone else.

### 8.2 WASM tier: an operator-provided runtime (3.4)
`plugins/wasm_host.py` is wired as the strongest jail — capability→WASI grant
mapping and tier selection are tested; the store falls back to the OS-sandboxed
subprocess tier until a runtime exists. End-to-end WASM execution is blocked on:
- [ ] an operator-provided `wasmtime` + a `python.wasm` guest with dreamlayer
      bundled (not shippable from this container)

### 8.3 Wake word: brand + a trained model (Cat 8 #8)
Docs/pitch and `orchestrator/wakeword.py` (openWakeWord) must agree on the
phrase. The engine + text-level fallback ship; the custom acoustic model does
not.
- [ ] decide the brand wake phrase
- [ ] train a custom openWakeWord model (synthetic-TTS positives + community
      recordings) — a weekend of compute, not a rewrite

### 8.4 GhostMode: publish the mesh protocol spec (the coda)
Pillar 2 (`docs/PLATFORM.md`: LE Coded PHY, S=8, ~125 kbps, the Beacon). The
`MeshManager`/`Beacon` seams sit in Confluence and the figment `bond:` events
now exist (B10), but a radio mesh cannot be demoed in a rasterizer.
- [x] write and publish the mesh transport spec *now* — **done**:
      `docs/GHOSTMODE_PROTOCOL.md` v1.0 (wire format, key derivation, a normative
      test vector pinned to the code, receive rules, the Beacon, privacy
      invariants, security model, conformance checklist)
- [ ] the mesh itself lights up only with silicon on the desk

### 8.5 ESP32 physical-events kit (1.6)
The figment event grammar accepts `ble:<n>` exits; both code halves of the
`$6 reed switch → your retina` demo now ship. What's left is the hardware on
the desk.
- [x] a MicroPython sketch (ESP32 + reed switch) — **done**:
      `examples/esp32/mailbox.py`
- [x] the `POST /dreamlayer/event/ble/<n>` Brain route that forwards to the
      active figment — **done**, covered by `test_physical_events.py`
- [ ] flash it to a physical ESP32 and close the loop for real
