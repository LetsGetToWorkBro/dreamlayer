# DreamLayer AI Brain — design spec

**Status:** decisions resolved (§8). **Phases 1–4 built.**
- **P1** — router, interfaces, mocks, AI Object Lens, knowledge → Lucid Recall.
- **P2** — the **Brain app** (`ai_brain/server/`, runs on the Mac mini): a
  local index over your chosen folders, a control panel, and the API; the
  phone connects via `RemoteVisionBrain`/`RemoteKnowledgeBrain` (`connect_brain`).
  Vision uses the Ollama backend seam (keyword retrieval works with no model).
- **P3** — the config layer: folders, drag-drop upload, model choice, and
  **query history**, all editable from the control panel; **auto-reindex**
  when watched folders change. **Mac mini sources** (`macos_sources.py`):
  iMessage (chat.db) and Mail (.emlx) read and folded into the index when
  email is enabled, plus a **draft → approve → send** path that never sends
  silently. Setup: `laptop-companion/install-macos.sh` +
  [`docs/OLLAMA_SETUP.md`](OLLAMA_SETUP.md).
- **P4** — the **opt-in cloud tier** (`CloudVisionBrain`/`CloudKnowledgeBrain`),
  gated by `opt_in_cloud()`.

Run the Brain: `python -m dreamlayer.ai_brain.server --token <t>` →
control panel at `http://<mac-mini>:7777/`. Demos:
`scripts/run_demo_ai_brain.py` (tiers), `scripts/run_demo_brain_app.py`
(the app). Tests: `test_ai_brain.py`, `test_ai_brain_server.py`.

## 1. The idea in one line

Look at *anything* and the glasses name it and explain it; ask *anything*
about your own digital life and it answers from your own machine — powered
by a tiered "brain" that runs as much as possible on hardware **you** own,
and only reaches the cloud if you say so.

Two capabilities, one architecture:

- **AI Object Lens** — recognise + explain any object you look at.
- **Personal Knowledge Brain** — ask about your own files/notes/photos.

## 2. The tiered brain (the core architecture)

Intelligence lives at whatever tier is available and appropriate. Each tier
is smarter and less private than the one below it; we always prefer the
lowest tier that can do the job.

| Tier | Runs on | Good for | Cost |
|---|---|---|---|
| **0 · on-device** | Halo NPU | *naming* objects, fast, fully offline | small model → coarse |
| **1 · phone** | phone (the hub) | routing, caching, the privacy gate, DreamLayer's own memory | — |
| **2 · your brain** | your laptop / home box | *explaining* objects + searching your own knowledge — smart **and** private | only when reachable on your LAN |
| **3 · cloud** | GPT / Claude / Gemini vision | the hardest asks | leaves the device → **opt-in only** |

The flow: **Tier 0 names it instantly → the best available higher tier
explains it → cloud only if you enabled it and nothing local sufficed.**
The laptop "brain" (Tier 2) is the reframed laptop — not an object you look
at, but a private compute + knowledge node the whole system taps.

### 2a. The three brain switches (not one dial)

There is no "mode picker." There are three independent switches the phone app
and the Mac mini panel both expose:

| Switch | What it does | Default |
|---|---|---|
| **Mac mini** (`connect_mac_mini`) | upgrades the local brain from the phone's small on-device model to the Mac mini's bigger model **+ your indexed files**, when it's reachable | off → **the phone is the brain** |
| **Cloud** (`use_cloud`) | reach the frontier cloud for the hardest, *non-personal* asks — works in any brain | **on** |
| **Incognito** (`set_incognito`) | privacy shield: forces cloud **off** for the session and pauses capture; restores your cloud preference when you leave | off |

The phone is the brain until you connect a Mac mini — that's the honest
default (works anywhere, no computer required). Connecting a Mac mini is the
obvious upgrade; the cloud switch is orthogonal to both, so *"no computer, but
reach the cloud for hard cases"* (`connect_mac_mini(False)` + `use_cloud(True)`)
is a first-class setup. `local_only` skips only the Mac-mini remote tier; the
cloud gate is independent. Incognito is the old "home/private" mode, renamed.

**What cloud ON buys you (vs. off):**

| Capability | Cloud OFF (on-device / LAN) | Cloud ON |
|---|---|---|
| Name an object (Juno) | ✓ fast, offline | ✓ (same Tier 0) |
| DreamLayer's own memory, people, waypaths | ✓ always local | ✓ |
| Search *your* files & mail (Lucid Recall) | ✓ on the Mac mini | ✓ |
| Deep "explain / tell me more" on an object | ✓ Mac mini; **phone mode: coarse** | ✓ frontier VLM, richest |
| Rare/obscure knowledge not in your files | ✗ ("nothing local matches") | ✓ |
| Translation (Rosetta / Puente) breadth | ✓ common langs on-device | ✓ widest coverage |
| Works in airplane mode | ✓ | ✗ (cloud tier needs a connection) |

Rule of thumb: **everything that is *yours* — memory, people, your files,
naming objects — works with cloud off.** Turning cloud on only adds reach for
the *hardest, non-personal* asks (obscure facts, richest object explanations,
long-tail translation), and always as an explicit, per-session opt-in.
Nothing marked private ever leaves regardless of mode.

## 3. Interfaces (the seams)

Small, stable contracts so any model/provider drops in. All are already the
shape of things the codebase does today.

```python
# vision: name and explain what's in view
class VisionBrain(Protocol):
    def identify(self, frame) -> Sighting: ...              # label + confidence
    def explain(self, frame, label, question=None) -> Answer: ...  # rich text

# knowledge: ask about your own stuff
class KnowledgeBrain(Protocol):
    def ask(self, query: str) -> Answer: ...   # Answer(text, sources=[…])

@dataclass
class Answer:
    text: str
    sources: list[str] = []      # provenance: which file/tier produced it
    tier: str = ""               # "device" | "laptop" | "cloud"
    confidence: float = 0.0
```

- **Transport to the laptop brain** reuses the companion contract already
  built: token-paired, LAN-only HTTP, wrapped in a `PolledSource`/async call.
  New endpoints alongside `/dreamlayer/context`:
  `POST /dreamlayer/brain/explain` (frame + label → Answer) and
  `POST /dreamlayer/brain/ask` (query → Answer).
- **Cloud** reuses the existing config-gated LLM client in the repo.
- **On-device** is the existing `ObjectRecognizer(classify_fn=…)` seam.

## 4. The router

```python
class BrainRouter:
    # tiers registered in preference order; cloud only if opted in
    def identify(self, frame) -> Sighting          # tier 0, always
    def explain(self, frame, label, want="quick")  # escalates as needed
    def ask(self, query)                            # knowledge → laptop/cloud
```

Rules: prefer the lowest tier that can answer; escalate on low confidence or
an explicit "tell me more"; **never cross to cloud without the opt-in gate**;
every Answer carries the tier it came from so the HUD can show it and
Provenance can trace it.

## 5. Privacy model (non-negotiable)

- **On-device by default; laptop stays on your LAN; cloud is explicit opt-in**
  — per session or per request, with a visible "left the device" indicator.
- The **Privacy Veil** still silences everything.
- **Objects only.** The AI Object Lens never identifies people — that stays
  Social Lens's consented domain (`PERSON_LABELS` already enforces it).
- Answers are **attributed** (which tier / which file), so you always know
  where a claim came from — this plugs straight into the Provenance Lens.

## 6. How it maps onto what's already built (why it's cheap)

- `ObjectRecognizer.classify_fn` → the Tier-0 brain (seam exists).
- A new `AIProvider` (sibling of `LaptopProvider`) whose `data_source` calls
  `router.explain()` → drops into the existing Object Lens panel machinery.
- The laptop brain **extends the companion agent** (`laptop-companion/`) with
  the two `/brain/*` endpoints — same server, same token, same `PolledSource`.
- Cloud tier reuses the existing LLM client (already config-gated).
- Answers flow through the same HUD card + Provenance paths already shipped.

## 7. Phased build

1. **Router + interfaces + MockBrain** — ✅ **done.** Deterministic, works
   today. AI Object Lens end to end with a mock ("snake plant · water every
   2–3 wks"), tier escalation, the cloud opt-in gate, and knowledge queries
   over your own docs. Tests + demo. *No model required to prove the pipeline.*
2. **Laptop brain (vision)** — `/dreamlayer/brain/explain` hosting a real
   local VLM; phone client + `PolledSource`; escalation from Tier 0.
3. **Personal Knowledge Brain** — index your own files on the laptop (local
   RAG); `/dreamlayer/brain/ask`; the "where's that contract?" path.
4. **Cloud tier (opt-in)** — the existing LLM client behind the consent gate,
   for the hardest asks only.

## 8. Decisions (resolved)

1. **Cloud posture** *(re-revised 2026-07)* — **connected by default, cloud
   opt-in**: your *own* brains are reachable wherever you are (the Mac mini
   brain runs over the internet by default), but the third-party **cloud tier
   starts off** and stays off until you flip it on (`use_cloud()` / the Cloud
   switch) — a privacy-first product shouldn't send your hardest questions to
   someone else's model by default. On-device remains the airplane-mode
   fallback (DreamLayer works phone-only, just more limited). **Advanced
   users** flip `set_private_mode()` / `network_mode="lan_only"` to keep
   everything on-device and home-LAN. (Privacy Veil and "private events never
   leave" still hold in every mode.)
2. **Knowledge base** — the brain lives on an **always-on Mac mini (Apple
   Silicon)** and indexes **chosen directories** (a configurable watch-list),
   plus **email and iMessage read**. It can also **send** email/iMessage —
   but only through a **draft → you approve → send** consent flow (an
   outbound action is never taken silently; see Phase 3). iMessage reads from
   `~/Library/Messages/chat.db`; sending via AppleScript to Messages/Mail.
3. **Read/translate visual text** — **yes.** Scope boundary with **Puente**
   (`orchestrator/puente_bridge.py`): Puente is the **ear** (real-time
   voice/conversation translation → LiveCaptionCard); the AI Object Lens is
   the **eye** (text you *look at* — a menu, a sign — OCR'd + translated).
   Complementary, no duplication; the Object Lens may reuse Puente's caption
   card styling but not its pipeline.
4. **Local model** — target the Mac mini with **Ollama** (least friction:
   local HTTP, OpenAI-compatible API, vision models + an embedding model for
   RAG in one install). **MLX** is the higher-performance alternative later.
   The seam (`VisionBrain` / `KnowledgeBrain`) doesn't care which.
5. **Naming** — the **knowledge half folds into Lucid Recall** (it *is*
   "ask and receive," now extended from your memory to your files/mail), so
   no new lens there. The **vision half is the AI Object Lens**. ("Juno"
   was a nice name we consciously don't need — Lucid Recall already is it.)

## 9. What "mind-blowing" looks like when this lands

- Look at a plant → *"snake plant, water every 2–3 weeks, yours looks
  overwatered."*
- Look at a foreign menu → translated, with the two dishes you'd like flagged
  from your own tastes.
- Look at a gadget you've never seen → what it is, what it's worth, how to use
  it.
- Say *"where's the lease?"* → your laptop finds it and reads you the rent
  line — your files, never the cloud.

All of it degrading gracefully: brilliant at home with the brain reachable,
still useful on the train with just the glasses.
