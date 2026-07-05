# The AI Brain deep dive

This chapter is the technical companion to
[the desktop Brain app](brain-app.md): the tiered router, the index, the
model seams, and the exact rules that keep private things private. Code:
`host-python/src/dreamlayer/ai_brain/`.

## Three routers, one shape

The tiered-router idea now appears three times, deliberately identical in
shape: the **BrainRouter** (vision + knowledge, this chapter), the
**PerceptionRouter** (`ai_brain/perception.py` — coarse per-frame percepts;
a zero-model heuristic tier ships today and an NPU tier plugs into the
`NpuPerceptor` seam when hardware arrives), and the **WorldChecker**
(`ai_brain/world_check.py` — Veritas' cached, deadline-bounded verification
worker; see [Truth](truth.md#fast-by-construction)). Prefer the lowest tier
that can answer; degrade gracefully; never block the moment.

## Two capabilities, one architecture

- **Vision** — name and explain what is in view: `identify(frame)` returns a
  `Sighting` (label + confidence); `explain(frame, label, question)` returns
  rich text.
- **Knowledge** — ask about your own stuff: `ask(query)`.

Both are small protocols (`VisionBrain`, `KnowledgeBrain`) so any model or
provider drops in, and both return one shape:

```python
Answer(text: str, sources: list[str], tier: str, confidence: float)
# tier: "device" | "laptop" | "cloud" — every answer says where it came from
```

## The router

`BrainRouter` holds vision and knowledge tiers in preference order and always
prefers the lowest tier that can answer:

1. **device** — the on-device recognizer seam. Instant, offline, coarse.
2. **laptop** — the Mac mini over token-paired HTTP
   (`RemoteVisionBrain` / `RemoteKnowledgeBrain`, registered by
   `connect_brain` / pairing).
3. **cloud** — an OpenAI-compatible provider, **only if opted in**.

The rules, all enforced in `router.py` and covered by tests:

- `local_only` (the "no Mac mini" state) skips only the remote tier — the
  cloud gate is independent, so *phone-only but cloud-on* is a first-class
  configuration.
- The cloud tier is consulted **only** when `cloud_opt_in` is true. There is
  no code path around the gate.
- A tier that throws is skipped (dead Mac mini degrades gracefully); the
  first non-empty answer wins and is stamped with its tier.
- Escalation on vision is driven by `want` ("quick" versus "tell me more").

Confidence conventions: the local index scores `0.4 + 0.15 x hits` (capped
at 1.0); cloud knowledge answers carry 0.6, cloud vision 0.65, Ollama vision
0.7 — so a caller can always prefer richer-but-lower-tier evidence.

## The index — your files, on your machine

`server/index.py` walks the watched folders and splits text-like files
(default extensions: txt, md, markdown, rst, text, log, csv, json, py, org,
tex; configurable) into passages of at most 600 characters, skipping files
over the size cap and any exclude-glob match.

- **Keyword retrieval** (always available): stopword-filtered token overlap,
  top four passages; the hit count is the score.
- **Semantic search** (opt-in, needs Ollama's embedding model): cosine
  similarity over passage embeddings with a 0.15 floor, mapped onto the same
  hit scale, falling back to keyword when nothing clears the floor.
- **Synthesis:** with a chat model wired, retrieved passages are rewritten
  into a direct answer; with none, the best passage is returned verbatim —
  honest, sourced, and still useful.
- Messages and Mail documents fold into the same index when email is enabled.
- Reindex triggers: config changes, folder add/remove, uploads, the API, and
  a 3-second modification watcher.

## Ollama and the model features

One backend (`server/backends.py`) speaks to a local Ollama over HTTP
(`/api/generate`, `/api/embeddings`, `/api/tags`, `/api/pull`), bypassing any
system proxy. What uses the LLM, and what each falls back to without one:

| Feature | With Ollama | Keyword fallback |
|---|---|---|
| Written answers | synthesized from your passages | best passage verbatim |
| Object explain (vision) | the vision model reads the frame | tier declines (empty answer) |
| Email summaries | one-sentence summary | first sentence, clipped |
| Morning brief | two warm sentences from the bullets | the bullets joined |
| Smart replies | three short in-context replies | "On my way" / "Give me a few" / "Thanks!" |

`probe_ollama` reports reachability and which configured models are pulled
(matching by base name); `pull_model` blocks on Ollama's own pull API and
re-wires the index on success.

## The cloud tier

An OpenAI-compatible `/v1/chat/completions` client, configured entirely in
the panel (base URL, key, model — defaults point at `api.openai.com` with
`gpt-4o-mini`). Reached **only** when the local tiers come up empty *and*
`cloud_ready()` holds:

```
cloud_ready = network_mode != "lan_only"  AND  cloud_enabled
              AND cloud_api_key set       AND  cloud_model set
```

Incognito sets `network_mode = "lan_only"`; quiet hours produce the same
state on schedule (`incognito_now()`); and every actual cloud answer
increments the persistent `cloud_calls` counter and writes a `cloud-egress`
activity line. The verification questions Veritas asks
(`verify.py: verify_claim`) ride this same path — local model first, cloud
only under the same gate, never while incognito.

## What can and cannot leave

Can leave (cloud on, and only then): the text of a hard, non-personal ask
that no local tier could answer; a Veritas verification question; a vision
explain when configured to escalate. Cannot leave, in any configuration:
your files and index, the people registry, the user-model profile, faces or
embeddings (there is no cloud face path at all), messages and mail, backups,
the pairing token. The server enforces the boundary at one choke point —
`Brain.ask`'s cloud branch — not by convention.

## Embeddings and semantic search

Semantic search is deliberately modest: local embeddings via Ollama's
`nomic-embed-text`, cosine scoring, keyword fallback, and an explicit panel
toggle. Turning it on re-embeds at reindex time; nothing is embedded in the
cloud. (The orchestrator's own memory vault separately uses an embedding
provider seam — a mock offline, OpenAI only when a key is present — for
recall over saved moments.)

## Schedulers and mirrors

Three daemon loops: the brief scheduler (fires once daily at the configured
hour, stores `last_brief` for `GET /dreamlayer/brief/latest`), the
calendar/contacts/reminders sync loop (15 minutes, plus an immediate pull
when a sync toggle turns on), and the folder watcher. The Brain also mirrors
two things it never authors: the Oracle's user-model profile (pushed by the
hub, capped and stored as `profile.json`) and the Saga ledger it advances on
ecosystem events.

## Wire reference

The full endpoint table — auth, bodies, responses — is in
[the API reference](reference/endpoints.md). The integration map with the
seams marked lives in `docs/INTEGRATION.md`.
