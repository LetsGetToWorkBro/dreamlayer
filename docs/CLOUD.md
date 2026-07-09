# DreamLayer Cloud — the hosted tier

The business and architecture spec for DreamLayer's revenue engine. Written to
be executed: every attach point below names the real seam in this repo, and
every phase ends in something shippable.

## 1 · Thesis

Sell **continuity, convenience, and reach** — never the core.

The code is Apache-2.0 and the local app is complete: that is the moat, not a
leak. What an open local-first product *can* charge for is exactly what can't
be self-hosted for free in practice: someone reliably running the servers,
paying for the inference, holding the encrypted copy, and relaying packets
across the internet at 3am. That's DreamLayer Cloud.

Two invariants, both already enforced in code:

- **Union-only.** `PLAN_CAPS` in `ai_brain/server/server.py` can only *add*
  capabilities on top of the always-free base set — structurally, a plan can
  never remove one. Free never gets worse. (This is also the anti-enshittification
  guarantee an open-source community will hold us to.)
- **The cloud that can't read your life.** Sync is ciphertext, the relay is
  blind, managed AI carries only explicit queries. Detailed contract in §4 —
  it is the differentiator against every big-tech glasses cloud, and it is
  auditable because the client code is public.

## 2 · Products & pricing

| Tier | Price | What it adds |
|---|---|---|
| **Free** | $0, forever | Everything local. BYO AI key or Ollama. Self-host relay/registry if you like. |
| **DreamLayer Cloud** | **$7.99/mo · $79/yr** | **Managed AI** (no key to wire, metered), **encrypted sync + off-site backup** across devices, **hosted mesh relay** (GhostMode weather, tin-can pings, the Beacon — beyond Bluetooth range), push morning briefs. |
| **Cloud Pro** | **$19.99/mo** | 10× AI budget, multi-Brain (home + studio), 5-seat family circle, publisher perks: plugin signing, publisher account, store analytics. |
| **Marketplace** | **85/15** creator/DreamLayer | On paid plugins/lenses, once payments ship (Phase P4). Stripe fees come out of our 15. Free plugins stay free to publish. |

Pricing rationale: Halo owners already spent hundreds on hardware —
price-tolerant early adopters. $7.99 sits below ChatGPT Plus (which it partly
substitutes for glasses use) and above throwaway-utility pricing, signaling a
serious service. Annual at ~2 months free drives the cash-flow that matters
at small scale. The 85/15 marketplace split deliberately undercuts the
platform-standard 70/30: creators are the growth engine, not the margin.

**Where each capability is *worth paying for*** (the honest pitch, per line of
the panel's Plan card):
- *Managed AI* — onboarding's biggest cliff today is "get an API key." Cloud
  deletes the cliff. Cost-controlled by budget, not by feature removal.
- *Encrypted sync* — a memory layer that can be lost with a laptop isn't a
  memory layer. Off-site, ciphertext, passphrase only the user holds.
- *Relay* — GhostMode/Beacon are the product's most shareable moments and
  they currently end at Bluetooth range. The relay makes "find my people"
  work across a festival, a city, a country.

## 3 · Unit economics

**Managed AI (the only real COGS):** budget-metered at mini/haiku-class
pricing (order of $0.15–0.60 per 1M input tokens, $0.60–2.40 per 1M output).
A typical glance-ask is ~1k in / 300 out. Plan budgets:

| Plan | Monthly AI budget | Est. COGS ceiling | Gross margin at price |
|---|---|---|---|
| Cloud | ~2,000 standard asks | ≈ $1.00–1.50 | **~75–85%** |
| Cloud Pro | ~20,000 asks | ≈ $8–12 | ~40–60% |

Over-budget behavior is **graceful degrade, never lockout**: the Brain falls
back to the user's own key (if wired) or local/keyword tier — the same
fallback ladder the free product runs. Union-only applies to metering too.

**Everything else is ~free at this scale:** Cloudflare Workers paid plan
($5/mo flat) + KV/Durable Objects/R2 measured in cents per user for relay
packets (tiny signed dicts), sync blobs (a few MB of ciphertext), and
waitlist/account rows. Stripe: 2.9% + 30¢.

**Break-even reality check:** fixed costs ≈ $10–20/mo (CF + domain) — ~3
subscribers. At 1,000 Cloud subscribers: ≈ $8k MRR, ≈ $6.5k gross profit.
The marketplace rake starts negligible and compounds with the ecosystem.

## 4 · The privacy contract under cloud

Auditable in this repo (that's the point of being open):

1. **Sync is ciphertext-only.** `ai_brain/server/cloud_sync.py`:
   `prepare_sync_blob()` strips `SECRET_FIELDS` (pairing token, cloud API key
   — each device keeps its own) and encrypts client-side (Fernet; scrypt-derived
   key from a passphrase only the user holds). No `cryptography` installed →
   it **refuses**; plaintext sync is not a fallback that exists.
2. **The relay is blind.** `confluence/relay_transport.py` carries the mesh's
   already-HMAC'd wire dicts; the server can't read, forge, or join a circle
   (all verification is client-side in `MeshManager.receive`). Rooms are
   derived from the group code client-side; the group key never leaves.
3. **Managed AI carries explicit queries only.** Same path as every provider:
   `Brain._ask_cloud()` — gated by consent + incognito, every call logged in
   the `cloud_calls` egress ledger the panel shows. Server-side: zero
   retention, no training on user content, ever. The Veil silences it like
   everything else.
4. **Accounts know almost nothing:** email, plan, usage counters. Memories,
   people, places live in the blobs the server cannot open.

## 5 · Architecture — Cloudflare-first

One Worker domain, `api.dreamlayer.app` (already live for plugin-store
social), grows these routes:

| Route | Backing | Phase |
|---|---|---|
| `POST/GET /api/waitlist` | KV (`waitlist:cloud`) | **P0 — in this repo now** |
| `POST /api/account` (magic-link), `GET /api/account/me` | KV + signed session tokens | P1 |
| `POST /api/billing/checkout`, `POST /api/billing/webhook` | Stripe Checkout + webhooks → plan flag on account | P1 |
| `POST /v1/chat/completions` | managed-AI proxy: verify account token → check budget (Durable Object counter) → forward to upstream provider(s) → meter | P1 |
| `PUT/GET /api/sync/:device` | R2 ciphertext blobs + version stamp | P2 |
| `POST /api/relay/:room/send`, `GET /api/relay/:room/recv` | Durable Object per room (poll v1 → WebSocket v2) | P3 |
| marketplace payments (paid plugin entitlements) | Stripe + signed install grants | P4 |

**Client attach points (all wired in this repo):**
- Managed AI → `PROVIDER_PRESETS["dreamlayer"]` (`ai_brain/server/backends.py`)
  — OpenAI-compatible wire, base `https://api.dreamlayer.app`; the "API key"
  slot carries the account token. Panel provider picker includes it.
- Entitlements → `PLAN_CAPS["cloud"] = {cloud_ai, cloud_sync, cloud_relay}` +
  `Brain.plan_summary()` (`server.py`); `BrainConfig.plan` flips via the
  existing `/dreamlayer/config` path when billing webhooks say so.
- Sync → `cloud_sync.prepare_sync_blob()/open_sync_blob()` around the
  existing `export_backup()/import_backup()` pair.
- Relay → `CloudRelayTransport` (`confluence/relay_transport.py`), a drop-in
  `MeshTransport`; the Brain-reach relay reuses the phone's existing
  `relayUrl` fallback client (`useBrainStore.brainFetch`).
- Waitlist → panel's Notify-me button (live), Worker route (deploys with the
  next `wrangler deploy`), tested reference in `plugins/social.py`.

## 6 · Conversion funnel — nudge only at real moments

The free product is whole, so conversion rides *moments of genuine need*,
never crippled features:

1. **The key cliff** — user opens cloud-AI settings, has no key →
   "Skip the key — DreamLayer Cloud handles it." (Panel, P1.)
2. **The second device** — pairing a second phone/Mac → "Want your memory to
   follow you? Encrypted sync." (P2.)
3. **Out of range** — Beacon/GhostMode loses BLE contact → "Keep the circle
   alive anywhere — private relay." (Glasses/phone prompt, P3.)
4. **The backup click** — panel backup download → "Keep an off-site encrypted
   copy, automatically." (P2.)

No countdown timers, no feature keys held hostage, no dark patterns — the
repo is public and the community would (rightly) torch us.

## 7 · Phases

- **P0 (this PR):** waitlist live end-to-end (panel button → Worker KV);
  entitlement seams filled; provider preset; relay-transport + sync-blob
  client halves, tested. *Owner action: `wrangler deploy`.*
- **P1 — first dollars:** accounts (magic link) + Stripe + managed-AI proxy
  with per-plan budgets. Flip `plan="cloud"` from the billing webhook.
  Panel "coming soon" → real checkout link.
- **P2 — sync/backup:** R2 blob store; scheduled encrypted uploads from the
  Brain; restore-on-new-device flow.
- **P3 — relay:** Durable Object rooms; `CloudRelayTransport` goes live for
  mesh + Beacon; phone `relayUrl` gets a hosted default for Brain reach.
- **P4 — marketplace payments:** paid plugins, 85/15, signed install grants;
  publisher accounts fold into Cloud Pro.

Each phase is independently shippable and each widens the funnel the previous
one opened: waitlist → subscribers → synced households → connected circles →
a paid creator ecosystem.

## 8 · Risks & honest counters

- **"Nobody pays when the code is free."** They pay Supabase, Ghost(Pro),
  Bitwarden, Proton — for hosting, reliability, and blame-absorption, not
  code. Same sale here, plus inference costs we genuinely absorb.
- **Managed-AI margin risk.** Budgets are hard-capped per plan and degrade
  gracefully; upstream model prices only fall.
- **A closed fork hosts a competitor.** Possible under Apache-2.0 (accepted
  trade-off, documented in OPEN_SOURCE.md); they don't get the trademark,
  the store, the registry, the community, or the App Store listing.
- **Solo-operator load.** Everything rides Cloudflare's managed primitives +
  Stripe — no servers to babysit; the local-first design means a Cloud outage
  degrades to... the free product, which works.
