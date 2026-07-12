# The DreamLayer plugin marketplace

A place to find, rate, and install what the community builds on DreamLayer —
CurseForge for the layer. Browse from the website, the phone app, or the Mac
panel; install with a tap; remove just as easily; and never run a plugin that
hasn't passed the gate.

This document is the design and the phased plan. The **core** (package format,
validation gate, store client) is built and tested (`plugins/package.py`,
`validate.py`, `store.py`; `tests/test_plugin_store.py`). The **surfaces** (web
store, phone screen, Mac tab) and the **hosted social layer** come next.

---

## The shape of a plugin

A published plugin is a **manifest + one code module** (`plugins/package.py`):

```
manifest.json
  { "name": "face-synth", "version": "0.1.0",
    "entry": "plugin:face_synth_plugin",   # module:factory
    "author": "…", "requires": ["midi"],   # capabilities it asks for
    "api": "1", "checksum": "sha256:…",     # of plugin.py — integrity
    # -- store detail (optional; your page, not ours) --
    "description": "one line, shown on the card",
    "screenshot": "https://…/shot.png",     # a preview image (URL or data-URI)
    "forwho": "who it's for, in one sentence",
    "long": ["paragraph 1 — how it helps you", "paragraph 2 — …"] }
plugin.py                                    # exposes register(ctx)
```

It plugs into the extension points we already have (`docs/PLATFORM.md`): object
providers, glance candidates, brain/perception tiers, card renderers. Nothing
more — the `PluginContext` is the whole surface a plugin can touch.

**Your detail page travels with the plugin.** `description`, `screenshot`,
`forwho`, and `long` live in the manifest, so the same copy renders everywhere —
the website store, the phone app, and the Mac panel all read these fields and
show *your* page when someone taps the plugin. They're the only manifest fields
that don't feed the checksum (which covers `plugin.py` only), so you can revise
your write-up or swap the screenshot without re-signing the code. Keep the shot
light — host it (≤~640×340 works well) or inline a small `data:` URI.

---

## The gate — "runs without errors, won't infect your device"

Every plugin passes through `plugins/validate.py` before it is installed **and
again before it is loaded**. Four lines of defence, cheapest first:

1. **Manifest** — name/version/entry/api well-formed; capabilities are from the
   known set (no undeclared reach).
2. **Integrity** — `sha256(plugin.py)` matches the manifest checksum, and the
   registry's advertised checksum matches what was fetched. What you validated
   is what you run; tampering in transit or at rest is caught.
3. **Static scan** — the source is parsed to an AST and screened for dangerous
   operations — `subprocess`, `eval`/`exec`, raw `socket`, file writes,
   `ctypes`, dynamic import. Each is allowed **only** if the manifest declared
   the matching capability (`network`, `fs`, `subprocess`). No code runs.
4. **Smoke load** — the module is imported in a fresh namespace and its factory
   registered against a **mock** context. If it throws, or reaches for an
   extension point it didn't declare, it fails here — not on your glasses.

On install the user sees exactly what a plugin asked for ("wants: **midi**") and
grants it; a device that can't grant a capability refuses the plugin outright.

### The honest limit — and the jail that answers it

In-process Python **cannot be fully sandboxed** — a determined author can hide
intent from a static scan. The static gate is real defence-in-depth for a
**curated, reviewed** registry (integrity + declared capabilities + screen +
smoke test), not a jail for hostile code. The hardening path, now built:

- **Curated registry** — every plugin lands by reviewed PR + CI gate (below).
- **Signatures** — authors sign packages (Ed25519); clients verify against a
  trusted-key registry (`manifest.signature` + `pubkey`, `plugins/validate.py`
  defence 2b). Unsigned is installable-with-warning under the curated model; a
  *bad* signature is a hard refusal.
- **Real isolation (built)** — an *unreviewed / unsigned* plugin can be run in a
  capability-mediated **subprocess jail** (`plugins/isolation.py` +
  `sandbox_child.py`): the plugin's code executes in a child process, and the
  host holds only thin RPC proxies. What crosses the boundary is deliberately
  tiny — object-provider `matches`/`build` and shop-provider calls, pure
  request→data, each under the glance-panel deadline. The child never receives
  the wearer's camera frame, never touches the display, the mesh, the
  filesystem, or the host's network. Side-effecting extension points (card
  renderers, glance candidates, perceptors, brain tiers) **cannot** be proxied
  and are *rejected* for isolated loading — that refusal is the guarantee, not a
  gap. A hung child is killed at the deadline; a crashed child is recorded to
  the health ledger, never fatal. Route through it with
  `PluginStore.load_installed(orchestrator, isolate="untrusted")`: signed/
  trusted packages still load in-process; everything else goes to the jail.
- **Runtime-enforced capabilities (built)** — for a plugin shipped as a compiled
  **WASM component**, `plugins/wasm_component_host.py` runs it *in-process* under
  wasmtime with **zero ambient authority**: the guest can call only the host
  functions its declared capabilities link. A denied capability is a host
  function that is simply never provided, so a module that imports it **cannot
  instantiate** — the host pre-scans the module's imports and refuses, with a
  precise "imports X but did not declare requires:[cap]" error, before anything
  runs. This closes manifest-vs-reality drift at the runtime layer (the
  Extism / Wasmtime-Component-Model design): a forged plugin can't invoke a
  power it never declared, because the power isn't in its address space. Complements
  the subprocess jail (which confines from the outside); this enforces from the
  inside. Available when `wasmtime` is installed (`platform` extra).

### API v2 — what a plugin may do

A plugin declaring `"api": "2"` gets, in addition to `register(ctx)`:

- **Lifecycle** — optional `start(ctx)` / `stop()` / `tick(now)` /
  `on_event(kind, payload)`; each call isolated and health-recorded. `tick`
  formalises the ambient-reactor pattern.
- **Events** — `ctx.subscribe(kind, fn)` over a **veil-gated** bus
  (`card_shown`, `glance`, `place`, `dream_enter`, `dream_exit`, `veil`,
  `mesh`). While the Privacy Veil is down, only `veil` events flow. Each kind
  requires the matching capability to subscribe.
- **Settings** — `ctx.settings`, a per-plugin persisted dict.

v1 plugins keep loading unchanged, but the **entire first-party catalogue is
now v2**, so every surface is dogfooded: `filler` (persisted lifetime tally +
tunable threshold), `reactions` (`on_event("mesh", …)`), `currency-converter`
(a persisted **home currency**), `face-synth` (a persisted **scale**),
`air-drums` (a persisted **sensitivity** that scales hit velocity), and
`open-food-facts` (a persisted cache **TTL**). Each setting is written to the
plugin's own bucket via a name-bound `ctx.settings` handle captured at
`register()`, so a host-invoked setter persists correctly even outside a
lifecycle callback.

### Official publisher and the pricing seam

First-party plugins are published as the **DreamLayer team**: every manifest and
index entry carries `"author": "DreamLayer Team"` and `"official": true`, and the
clients render a **✓ Official** badge (phone list + detail, Mac panel). Today the
official catalogue rides the same curated-registry trust as everything else;
*cryptographic* signing under a `DreamLayer Team` key is an owner action (see
`registry/keys.json` — generate the keypair off-repo, register only the public
key, never commit the private one).

Every manifest and index entry also declares an `"api"` version and a
`"pricing"` object. **Everything ships `{"model": "free"}` today** — the field is
a reserved, forward-compatible seam for the Phase-3 paid marketplace below. No
payment code runs against it yet; a missing `pricing` reads as free.

> **Scan caveat for first-party bundles.** The six shipped packages are thin
> re-export shims (`from dreamlayer.plugins.currency import currency_plugin`), so
> the static scan sees the shim, not the `urllib`/`socket` code in the imported
> module — their declared capabilities rest on review, not the scan. This is
> fine *because* they're first-party and reviewed; third-party packages ship
> their real source inline, which the scan does see.

---

## The registry — phased

**Phase 1 (now): git-backed, validated.** The registry is `registry/index.json`
in this repo — one file the website, phone, and Mac panel all read. A plugin is
contributed by **pull request**; CI runs the gate on it before it can merge, so
nothing lands that doesn't pass. This is the Homebrew-taps model: trustworthy
because everything is reviewed and checksummed, and it needs **no backend**.

**Phase 2 (built): the hosted social layer.** The CurseForge numbers — download
counts, star ratings, comments — as a small shared service. Delivered as:

- a **tested reference implementation + contract** in
  `plugins/social.py` (`SocialStore` + pure `route()`), so the behaviour is
  pinned and a self-hoster has something to run;
- a deployable **Cloudflare Worker** over KV in `registry-api/` (mirrors the
  contract exactly) — `npx wrangler deploy`;
- **client wiring**: the website (`landing/plugins.html`) and phone
  (`usePluginStore.ts`) read live stats and offer one-tap rating when a
  `SOCIAL_API` base is set, and **fall back to the static `registry/index.json`**
  when it isn't or is unreachable.

**Phase 3 (spec'd): payments.** Paid plugins/lenses with an **85/15**
creator/DreamLayer split (Stripe fees inside our 15; free plugins stay free
to publish). Purchases produce signed install grants verified by the same
validation gate. Sequenced as phase P4 of the hosted tier — full design in
[`CLOUD.md`](CLOUD.md).

### Compromise-resilient trust — TUF / Uptane (built: `plugins/registry_trust.py`)

Whole-package Ed25519 signing proves *"signed by a key."* It has no answer to the
attacks that actually take down plugin stores: a **stolen signing key**, a
**rollback** to an old vulnerable version, a **freeze** pinning clients to stale
listings, or **mix-and-match** of metadata. `registry_trust.py` implements the
TUF (CNCF-graduated) model natively over the existing Ed25519 signer, with the
**Uptane** two-repository specialization for our topology:

- **Role separation with k-of-n thresholds** — a `root` trust anchor delegates
  to `targets` / `snapshot` / `timestamp` roles; one stolen key below threshold
  cannot forge, and root is rotatable (a new root must be signed by the old
  root's threshold).
- **`snapshot`** binds the exact current targets version+hash → kills
  mix-and-match; **`timestamp`** is short-lived with an `expires` → kills freeze
  (the client detects staleness).
- **Uptane Director/Image split** — the offline-signed **Image repo** (`targets`)
  is the catalog of blessed `{name/version → hash}`; the internet-facing
  **Director** (our Cloudflare Worker, the most-compromisable component) only
  *selects which* blessed target a client installs. A fully-owned Director can
  misdirect among approved plugins but **cannot introduce a new malicious one** —
  a selection naming a target the Image repo never signed is refused.

`TrustClient` pins a root and verifies the whole chain (threshold → freshness →
version monotonicity → hash binding) before any install. The attack suite —
key-compromise, rollback, freeze, mix-and-match, root rotation, and the Director
guarantee — is pinned in `test_registry_trust.py`.

The contract:

```
GET  /api/plugins                 → index + live stats
GET  /api/plugins/<name>          → stats + comments
POST /api/plugins/<name>/rate     {stars, user} → stats   (one vote/user)
POST /api/plugins/<name>/comment  {text, user}  → comment
POST /api/plugins/<name>/download                → {downloads}
```

The plugins themselves stay git-backed and validated — the social service only
serves numbers, so a compromise there can't ship code. Hardening (auth on
ratings, rate limits, moderation) is noted in `registry-api/README.md`.

**Deployed.** The Worker is live at
`https://api.dreamlayer.app` (KV-backed),
and the web + phone clients point at it. Because the registry repo is private,
the *catalogue* lives with the clients (a bundled snapshot, overlaid by the git
index when it's public) and the API supplies only the numbers — `GET
/api/plugins` returns stats for every plugin it has seen activity on, and the
client **merges by name**. So a brand-new plugin shows immediately (from the
client's catalogue) and picks up its numbers once someone rates or installs it.

---

## The client — `PluginStore`

On-device, gated by the validator:

- `search(query)` / `top(by="downloads"|"rating")` over the index.
- `install(name)` — fetch → validate → write, and **refuses** (installs
  nothing) if the gate fails.
- `install_package(pkg)` — sideload a package you already hold, same gate.
- `remove(name)` — delete the installed package.
- `load_installed(orchestrator)` — re-validate and load every installed plugin
  into a running host via `orchestrator.load_plugins`.

Downloading is a seam (`fetch_fn`), so it tests fully offline; the real one
pulls the package from the entry's `url`.

---

## The three surfaces (next)

All read the same index; all install through the same gate.

- **Website** — a browsable store: featured, top-rated, most-downloaded, search,
  a plugin page with the manifest, permissions, ratings, and comments, and a
  "Build a plugin" guide. Static against `registry/index.json` today.
- **Phone app** — a **Plugins** screen: browse, install/remove, a permissions
  prompt on install, and "manage installed."
- **Mac Brain panel** — a **Plugins** tab in the existing control panel, where
  power users sideload and manage the plugins their Brain runs.

---

## Contributing a plugin (phase 1)

1. Write `plugin.py` exposing a `register(ctx)` factory.
2. `PluginPackage.build(...)` stamps the checksum; drop the manifest + source
   under `registry/packages/<name>-<version>.json` and add an entry to
   `registry/index.json`.
3. Open a PR. CI runs `validate()` on it. A maintainer reviews the code (the
   human half of "won't infect devices"). On merge, it's in the store.
