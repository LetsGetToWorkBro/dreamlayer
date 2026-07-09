# Optional integrations — what each adds, and over what

DreamLayer wired 58 open-source libraries in as **optional adapters**, each behind
a `try/except ImportError` with a working fallback. This is the reference for what
every one of them changes, stated as **before → after**.

## How to read "before → after"

Every adapter has two states:

- **Before** = what runs today with *nothing* installed. Either the feature did not
  exist and the system declined, or it ran on a cruder built-in fallback.
- **After** = what activates when someone runs one `pip install dreamlayer[<group>]`.

So most of these are **capability-latent**: the improvement is real but lands when
the dependency is installed, not the moment the adapter merged. A smaller set are
**live today** (marked **[live]**) — pure-Python modules or fallbacks that improved
behaviour immediately, with zero dependencies.

Nothing here changed an existing file, class, or signature, and no *core* dependency
was added. The system runs identically with none of this installed. That constraint
is what made it safe to add all 58 at once.

Optional groups are declared in `host-python/pyproject.toml`
(`memory`, `voice`, `asr-extra`, `structured`, `llm`, `intelligence`, `vision`,
`causal`, `infra`, `privacy`, `platform`). Install a group with, e.g.,
`pip install -e "host-python[memory]"`.

---

## PR1 — Memory, Voice, Structured output, LLM

### Vector search / memory store (`memory`)
| Library | Before | After | Why it matters |
|---|---|---|---|
| **sqlite-vec** | Linear cosine scan in Python, O(n) per query | Indexed on-disk vector store | Recall stays fast as memory grows; persists across restarts |
| **chromadb** | Linear store, no metadata filtering | Embedded vector DB with collections + metadata filters | "Memories about Jordan, from last month" becomes a real query |
| **lancedb** | Everything in RAM | Columnar on-disk ANN | Scales past RAM |
| **usearch** | Linear cosine router | HNSW approximate-nearest-neighbour index | Sub-ms routing at scale |
| **sentence-transformers** | Embeddings from a *mock* provider (no real meaning) or OpenAI (cloud, paid, networked) | Real semantic embeddings computed locally | Memories become semantically searchable **offline and free** — the single biggest win here |
| **mem0** **[live]** | Passthrough list; duplicates accumulated | Dedup + decay (even in fallback) | Memory stays clean, not noisy |
| **docarray** | Plain dataclass | Typed multimodal doc schema w/ validation | Structured, validated records |
| **networkx** | Hand-rolled adjacency dict, basic lookups | Real graph algorithms (paths, centrality, communities) | "How do I know this person / who connects us" becomes answerable |

### Voice (`voice`, `asr-extra`)
| Library | Before | After | Why it matters |
|---|---|---|---|
| **silero-vad** | Crude energy-threshold VAD (fires on any loud sound) | Neural speech-vs-noise detection | ASR wakes only on real speech: fewer false triggers, less battery, more privacy |
| **faster-whisper** | No in-host transcription (empty string) | Fast local speech-to-text | Transcription **without sending audio to the cloud** |
| **whisperX** | No word-level timing | Word-aligned timestamps | Needed for prosody (*how* something was said) |

### Structured output / LLM (`structured`, `llm`)
| Library | Before | After | Why it matters |
|---|---|---|---|
| **outlines / instructor** | Regex intent parser, brittle to phrasing | LLM structured output constrained to a schema | Understands free-form speech, still returns valid typed intent |
| **answer validation** **[live]** | Answers passed through unvalidated | A validation seam | Malformed answers caught before they reach the eye |
| **litellm** | Hand-rolled OpenAI + a few presets | One interface to ~100 providers, routing/fallback | Swap or fail over providers without code changes |

---

## PR2 — Intelligence (`intelligence`, `vision`, `causal`)

| Library | Before | After | Why it matters |
|---|---|---|---|
| **LibreFace / py-feat / facetorch / OpenFace-3** | AU frame passed through untouched — no micro-expression signal | Real facial action-unit / expression detection | The credibility/truth lens gets real input instead of nothing |
| **whisperX (prosody)** | No pitch/timing signal | Word-timed prosody into the analyzer | Tone becomes a readable channel |
| **dowhy** | Credibility channels combined by fixed weighted heuristics | Causal inference over them | Principled fusion instead of guessed weights |
| **speechbrain (ECAPA)** | "Voice vector" was a hash — couldn't tell speakers apart | Real 192-dim speaker embeddings | "Who said this" genuinely works |
| **spaCy** | Names / (subject, verb, deadline) pulled by regex, broke on real sentences | Real NER + dependency parsing | Reliable who/what/when extraction — the backbone of commitment tracking |
| **river** **[partly live]** | Static ranking / sampling | Online learning that adapts per-user in real time | TasteLens learns *your* taste; InnerWeather adapts |
| **human-learn** | Persona classification was identity (no-op) | Interactive human-in-the-loop classifier | Tune the persona model by example |
| **EyeMU** | Basic nod / double-tap heuristics | Richer IMU gesture recognition | More hands-free head/motion gestures |
| **LostFound** | No scene graph | Spatial scene understanding for object recall | "Where did I leave it" gets real spatial context |
| **supervision (ByteTrack)** | Nearest-centroid tracking, loses identity under occlusion | Proper multi-object tracking | Keeps track of the same thing across frames |
| **CLIP / ultralytics / moondream / coremltools** | `classify_fn=None` — "what is this?" declined | Four real classifiers (open-vocab CLIP, YOLO, Moondream VLM, on-device CoreML) | Object recognition actually happens, with an on-device option |
| **diart** | No live diarization | Real-time speaker turns | "Who's talking right now" in a live conversation |
| **LatentSpatialMemory** | Spatial anchoring was a no-op | Spatial recall | Memories tie to places |
| **EgoLife** | No long-horizon episodic index | Temporal/egocentric recall | "What happened last Tuesday" becomes searchable |

---

## PR3 — Polish / operability (`infra`)

| Library | Before | After | Why it matters |
|---|---|---|---|
| **rich** | Plain log lines | Live TUI dashboard | You can read what the Brain is doing |
| **watchdog** | No filesystem watching | Real file-change events | The Brain reacts instantly to new files/config |
| **zeroconf** | Manual IP config | mDNS auto-discovery on the LAN | The phone finds your Mac automatically |
| **datasette** | No way to inspect the memory DB | Browsable SQL explorer | Audit exactly what's stored |
| **rerun** | No spatial/temporal viz | Visualization of simulator/sensor data | Debug spatial data visually |

---

## PR4 — Privacy, security, reliability (`privacy`)

| Library | Before | After | Why it matters |
|---|---|---|---|
| **presidio** **[live fallback]** | Nothing redacted PII | Fallback adds regex redaction (emails/phones/digits) today; presidio adds ML detection of names, addresses, cards, in context | Sensitive data scrubbed before it's ever written |
| **pydantic** **[live]** | No typed memory record at all | `MemoryEvent` makes the Privacy Veil a **type invariant** — a veiled memory cannot be constructed | Privacy enforced by the type system, not a forgettable check |
| **cryptography** | Symmetric HMAC — anyone with the key can forge | Ed25519 asymmetric signatures (private sign, public verify) | Real provenance/authenticity; third parties verify without the secret |
| **anyio** | Veil-stop used raw asyncio gather+cancel | Structured-concurrency task groups | Cleaner guarantee that no task outlives the Veil drop |
| **pydantic-ai** **[live fallback]** | RC stages ran with no inspectable trace | Typed stage pipeline recording what ran and where it failed | The compile→validate→deploy path is debuggable |
| **pytest-benchmark, hypothesis** **[live]** | No latency budgets, no property tests | Latency-budget assertions + property tests | Perf regressions and edge-case bugs caught in CI |

---

## PR5 — Platform / extensibility (`platform`)

| Library | Before | After | Why it matters |
|---|---|---|---|
| **pluggy** | Plugins had to be in-process `register()` callables wired by hand | Entry-point discovery — a plugin ships as a pip package, found automatically | Third parties can distribute plugins via PyPI |
| **pyee** **[live fallback]** | Mesh events were direct calls, no subscribers | Pub/sub bus; many parts react to one packet, decoupled | Cleaner reactive architecture (Veil contract preserved — nothing published if nothing emitted) |
| **argostranslate** | RosettaLens with no translator returned text unchanged | Real offline neural translation | The translation lens actually translates, no network |
| **skia-python** | HUD rendered with PIL | Optional Skia GPU-accelerated anti-aliased rendering | Crisper strokes/gradients (PIL stays default) |
| **fastapi / uvicorn** | Brain server was stdlib `http.server` (blocking) | Optional ASGI mirror with async handlers + websockets | Modern async surface *alongside*, not replacing, the simple server |
| **Ollama / Gemma** **[live]** | Only a generic Ollama backend | Gemma-pinned preset | Convenience for running Gemma locally |
| **exo** | Single-node inference | Client for an exo cluster | Run a bigger model split across machines you own |
| **MLX** | Local model never adapted | Optional overnight LoRA fine-tune on Apple silicon | The model gradually learns your world (privacy-gated) |
| **frame-sdk / noa-assistant** **[live fallback]** | Halo the only display target | Brilliant **Frame** display adapter + formatting patterns | A second hardware target for prototyping |
| **pairing rate-limit** **[live]** | Nothing stopped brute-forcing pairing codes | In-house lockout limiter | Real anti-brute-force (django-axes is Django-only and didn't fit) |
| **presence ledger** **[live]** | No signal for sustained attention | Gaze→presence micro-ledger | "Who/what am I spending attention on" (standalone, so saga's achievement list stayed untouched) |
| **pylsl** | No research-tooling output | Lab Streaming Layer transport | Sync Halo sensors with EEG / eye-trackers for experiments |
| **LocalRecall** **[live fallback]** | Only the built-in memory DB | Optional client for an external LocalRecall RAG server, with in-process fallback | A pluggable external knowledge base, capture-guarded |

---

## Bottom line

- **Live improvements today (no install):** mem0 dedup, the PII redactor, the
  Veil-as-type-invariant, answer validation, the typed RC pipeline, the pairing
  rate-limiter, the presence ledger, the event bus, the Frame/LocalRecall
  fallbacks, and the whole test-infra layer.
- **Capability-latent (one `pip install` away):** the vector stores, real
  embeddings, ASR, the vision/AU/speaker/NLP models, translation, Skia, FastAPI,
  exo, MLX. Wired, tested against their fallbacks, declared in optional groups,
  ready to switch on per-deployment.
- **What did not change:** no existing file, class, or function renamed, deleted,
  or resignatured; no new core dependency; the system runs identically with none
  of this installed.
