# Audit remediation — the owner-action register

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

## 3. Privacy counsel review (before going public)
`PRIVACY_MODEL.md` now states the bystander-biometrics legal theory
(introduction-as-consent, transient probe embeddings, CUBI/BIPA/GDPR).
- [ ] one hour with an actual privacy lawyer on that section
- [ ] decide the per-jurisdiction face-matching opt-in default

## 4. Go-public checklist (docs/OPEN_SOURCE.md)
Everything there stands; two items the audit sharpened:
- [ ] decide fresh-history vs full-history BEFORE flipping visibility
      (the strategy docs live in the history either way)
- [ ] install the DCO GitHub App (the new dco.yml workflow enforces
      trailers on PRs; the app adds the reviewer-facing UX)

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
