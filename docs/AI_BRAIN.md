# DreamLayer AI Brain — design spec (draft for review)

**Status:** proposal, not built. This is the spec to steer before coding.

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

1. **Router + interfaces + MockBrain** — deterministic, works today. AI Object
   Lens end to end with a mock ("that's a snake plant · water every 2–3 wks").
   Tests + demo. *No model required to prove the whole pipeline.*
2. **Laptop brain (vision)** — `/dreamlayer/brain/explain` hosting a real
   local VLM; phone client + `PolledSource`; escalation from Tier 0.
3. **Personal Knowledge Brain** — index your own files on the laptop (local
   RAG); `/dreamlayer/brain/ask`; the "where's that contract?" path.
4. **Cloud tier (opt-in)** — the existing LLM client behind the consent gate,
   for the hardest asks only.

## 8. Open decisions for you to steer

1. **Cloud posture** — recommend **off by default**, opt-in per session for
   hard cases. (Alternatives: on-by-default, or never/cloud-free.)
2. **Knowledge base scope** — start with **files/notes** on the laptop?
   Add emails/photos later? (Bigger scope = bigger build + more to index.)
3. **"Look at anything" extras** — include **read/translate text** you look
   at (menus, signs)? Cheap, high-value; recommend yes.
4. **Local model target** — left abstract until Phase 2; the seam doesn't
   care which VLM. (We pick when we get there.)
5. **Naming** — "AI Object Lens" for the vision half; the knowledge half
   could be its own lens (e.g. **Oracle**, or fold into Lucid Recall).

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
