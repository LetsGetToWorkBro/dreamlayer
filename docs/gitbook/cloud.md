# DreamLayer Cloud

DreamLayer is free, local, and open — and there is now a specified hosted
tier, **DreamLayer Cloud**, for the three things a local-first product
genuinely cannot do alone: managed AI without bringing your own key,
encrypted sync and backup across devices, and a hosted relay so the mesh
and the phone reach home from anywhere. The full spec is `docs/CLOUD.md`;
this chapter is what it means and — in this book's tradition — exactly what
is implemented versus specified.

## The two invariants (enforced in code, not promised in copy)

1. **Plans only ever add.** Entitlements are union-only: the `free` plan is
   the baseline everything ships with, and `cloud` adds
   `{cloud_ai, cloud_sync, cloud_relay}` on top. A plan structurally cannot
   remove a capability, and an unknown plan degrades to free — both proven
   by tests.
2. **The cloud that can't read your life.** Sync is ciphertext-only (the
   Brain encrypts before upload and strips secrets first; without a crypto
   library it *refuses* rather than falling back to plaintext), the relay is
   blind (it forwards the mesh's already-HMAC-signed packets), and managed
   AI answers only explicit queries — riding the same `cloud_calls` egress
   ledger as any other provider. Accounts store an email, a plan, and usage
   counters. Nothing else.

## The plans, as specified

| Plan | Price | What it adds |
|---|---|---|
| Free | $0 forever | everything in this book — bring your own key or run Ollama |
| DreamLayer Cloud | $7.99/mo or $79/yr | managed AI, encrypted sync + backup, hosted mesh relay, richer briefs |
| Cloud Pro | $19.99/mo | 10x AI budget, multi-Brain, 5-seat family, publisher perks |

Over-budget managed AI degrades gracefully to your own key or local model —
never a lockout. The marketplace's specified creator split is 85/15.

## Implemented today versus specified

**Live in the product now:**

- The plan machinery (`PLAN_CAPS`, `plan_summary`, `plan` in
  `GET /dreamlayer/config`), rendered as the panel's **Plan** card —
  "Free - local & open" — with a working **Notify me** waitlist button.
- The `dreamlayer` provider preset in the multi-provider picker (OpenAI
  wire format pointed at `api.dreamlayer.app`).
- Plugin manifests may declare the three cloud entitlements
  (`cloud_ai/cloud_sync/cloud_relay`) — a "paid-tier plugin" simply loads on
  a cloud-plan Brain and skips, by name, on free. No gate changes needed.
- The waitlist route in the reference social API and the Cloudflare Worker.

**Merged client seams, waiting on the service:**

- `cloud_sync.py` — the encrypted-blob producer/opener (Fernet, scrypt key,
  secrets stripped before encryption; requires the `privacy` extra).
- `CloudRelayTransport` — a drop-in mesh transport that buffers locally
  through outages ("late, never lost") with zero change to the mesh crypto.

**Specified only (no server code in this repo):** accounts and magic-link
auth, Stripe billing, the managed-AI proxy, R2-backed sync storage, relay
rooms, and marketplace payments — phases P1 through P4 in `docs/CLOUD.md`,
all designed to run as the same single Worker at `api.dreamlayer.app`.

## The honest summary

Today, nothing about DreamLayer requires an account, and no paid feature
exists to buy. What exists is the *shape* of the business, built the same
way as the product: the privacy contract enforced structurally, the free
tier defined as everything, and the paid tier defined as additions a
local-first product cannot self-host — with every client seam already
merged and tested against the day the service turns on.
