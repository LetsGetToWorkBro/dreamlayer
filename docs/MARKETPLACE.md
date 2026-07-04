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
    "api": "1", "checksum": "sha256:…" }    # of plugin.py — integrity
plugin.py                                    # exposes register(ctx)
```

It plugs into the extension points we already have (`docs/PLATFORM.md`): object
providers, glance candidates, brain/perception tiers, card renderers. Nothing
more — the `PluginContext` is the whole surface a plugin can touch.

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

### The honest limit

In-process Python **cannot be fully sandboxed** — a determined author can hide
intent from a static scan. This gate is real defence-in-depth for a **curated,
reviewed** registry (integrity + declared capabilities + screen + smoke test),
not a jail for hostile code. The hardening path, in order:

- **Curated registry** — every plugin lands by reviewed PR + CI gate (below).
- **Signatures** — authors sign packages; clients verify a trusted key
  (`manifest.signature`, reserved and wired through, verification next).
- **Real isolation** — run untrusted plugins in a subprocess or a wasm/
  RestrictedPython sandbox with a capability-mediated bridge. This is the only
  way to safely run *unreviewed* third-party code, and it's the big next step.

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
`https://dreamlayer-registry-api.nameless-forest-17dc.workers.dev` (KV-backed),
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
