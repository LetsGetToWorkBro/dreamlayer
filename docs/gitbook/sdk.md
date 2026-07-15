# The SDK — plugins with code

The other half of building on DreamLayer: a stable, typed Python authoring
surface, a CLI that carries a plugin from scaffold to store, and an
isolation ladder underneath it. The quickstart lives in `docs/SDK.md`;
this chapter is the map.

## One import, one contract

```python
from dreamlayer import sdk
```

`dreamlayer.sdk` is the **only** supported import surface — everything
below it (`dreamlayer.orchestrator.*`, `object_lens.*`, ...) is internal
and may move. It is versioned (`dreamlayer sdk 1.0.0`), ships a PEP 561
`py.typed` marker, and exports typed contracts (`PluginContextProtocol`,
`SettingsProtocol`, `ManifestDict`) so `mypy` and `pyright` check plugin
code out of the box. A design record (`docs/adr/0001`) fixes the
extension model: `register(ctx)` plus explicit capabilities, deliberately
*not* a hook-discovery framework — on a permission-sensitive platform,
grants you can read beat hooks you have to hunt for.

## The CLI — scaffold to store

```bash
dreamlayer plugins new my-lens        # API v2 scaffold: plugin.py, plugin.json, test, README
dreamlayer plugins validate my-lens   # the same five-defence gate the Brain runs
dreamlayer plugins preview my-lens    # renders your card through the REAL device renderer
dreamlayer plugins dev my-lens --brain http://mac:7777   # watch, re-validate, reinstall on save
dreamlayer plugins pack my-lens       # a store-ready package
dreamlayer plugins install / info / list
```

Sibling commands: `dreamlayer figment safety` (the proof-carrying card),
`dreamlayer golf verify` (the byte-score referee), `dreamlayer packs
validate` (the earcon/haptic sensory gate), `dreamlayer bench perception`
(the 350ms Club), and the memories trinity below. Stdlib-only — argparse
and urllib, no dependencies.

`preview` matters more than it looks: it renders through
`hud.renderer.CardRenderer`, so the PNG you check into your repo is a
device-accurate golden, and `--shot` composes the 640x340 store banner
from it.

## Glass Desk — the zero-hardware devkit

```bash
python -m dreamlayer.simulator --watch my-lens/
```

Watches `plugin.py` / `plugin.json` and re-renders your card through the
real 256x256 device renderer on every save, overlaying the 112 px
safe-radius ring, into `my-lens/.glass/glass.png` — keep it open in any
image viewer and you have a live glass on your desk. `--once` renders a
single frame for CI.

## Plugin API v2

A v2 plugin can, beyond registering providers:

- **Live:** optional `start(ctx)` / `stop()` / `tick(now)` lifecycle,
  isolated per plugin — one throwing plugin never takes the loop down,
  and `reload()` hot-swaps a plugin in place.
- **Listen:** `subscribe` to a fixed event vocabulary — `card_shown`,
  `glance`, `place`, `dream_enter`/`dream_exit`, `veil`, `mesh` — each
  gated by the matching capability, and **while the Veil is down only the
  `veil` event is delivered.** One bad subscriber never breaks a publish.
- **Remember:** `ctx.settings` — per-plugin persisted settings,
  name-scoped in the memory store.
- **Declare compatibility:** `min_sdk` in the manifest; the gate refuses
  a plugin that needs a newer SDK than the host provides, by name.

## Signing and the gate

Packages carry **manifest-bound Ed25519 signatures**: the signed payload
covers the code hash *plus* every security-relevant manifest field (name,
version, entry, api, min_sdk, requires) — so a signature pins what the
plugin *is allowed to do*, not just its bytes — while store copy stays
outside it (editing a description never re-signs code). A bad signature
is a hard install error; an unsigned package installs under
curated-registry trust with a warning; trusted publisher keys live in
`registry/keys.json` (empty today — generating the team key is an owner
action, so the six official plugins currently ship unsigned).

The gate itself is now five defences: manifest shape, SDK compatibility,
checksum integrity, authenticity, and the AST scan (which follows import
aliases and rebinds) — plus a smoke load that is **opt-in author tooling
only**: the install path validates without ever executing plugin code. One
sharpening worth knowing: `subprocess`, `ctypes`, and `os.system` map to
a capability that **cannot be declared at all** — they are forbidden
outright, not merely withheld.

## The isolation ladder

Where a plugin runs depends on what it earned:

1. **In-process** — signed/trusted plugins (fastest, least isolated).
2. **Subprocess jail** — the untrusted default: the plugin lives in a
   child process; only pure-data calls (`matches`/`build`, shop lookups)
   cross a JSON-lines RPC, each under the glance-panel deadline; frames,
   display, mesh, filesystem, and network never cross. A dead or hung
   child is killed and recorded.
3. **OS sandbox** — when bubblewrap or nsjail is present, the child also
   loses the network namespace (unless `network` was granted), gets a
   read-only rootfs and unshared PID/IPC (`DL_SANDBOX=auto|bwrap|nsjail|none`).
4. **WASM** — the strongest jail, seam-complete and **off by default**:
   the same host drives a wasmtime/WASI runtime, with capabilities mapped
   to WASI grants (`fs` → a single preopened dir, `network` → inherit).
   It activates only when the operator sets `DL_WASM_RUNTIME` and
   `DL_WASM_GUEST`; until then the store falls back to the subprocess
   jail.

And a ledger watches all of it: the **capability-transparency log**
records, per plugin, what was granted and what was actually used (events
delivered, RPC calls made), surfaced in the health snapshot. Its honesty
is stated in the module itself: in-process plugins' raw network/file
access is not intercepted — the log is complete only for the isolated and
mediated surfaces.

## Figments have a contract too

Plugins are not the only third-party surface with declared powers — the
figment grammar grew its own, deliberately tiny pair:

- **Named slots.** Beyond the default `{slot}`, a lens can address up to
  **eight named channels** — `{slot:translation}`, `{slot:langs}` — each
  still one 24-character line, still host-fed (a slot fill is a `text`
  event, so it adds zero autonomous budget). The grammar is identical in
  all **four** interpreters — the Python stage, the device Lua, the
  browser `figment.js`, and the Rust `reality-core` (the embedded
  native/WASM core) — and parity-tested across them, down to one
  canonical text-length unit (UTF-8 bytes, truncated on a codepoint
  boundary, sized to the core's fixed 24-byte slot buffers).
- **The emit-capability registry** (`reality_compiler/v2/capabilities.py`).
  Three emit tags are host powers with plain-language summaries: `ask`,
  `translate` (passive — the Brain fills a slot; the lens emits nothing),
  and `look`. A lens must declare what it invokes in `meta.requires`,
  which rides the signed canonical bytes — the figment twin of a plugin
  manifest's `requires`. The verifier enforces declared-covers-emitted
  before signing; the Brain re-checks at runtime and refuses an
  undeclared power by name. Unregistered tags remain free local signals.
  The safety card and every store listing surface the declared powers as
  an "asks your Brain to" list.

## The output-shape rule (ADR 0002)

A second design record fixes *what shape new output ships in*:

| The behavior is... | Ship it as | Why |
|---|---|---|
| a self-contained on-glass machine that owns the screen — text, state, host-fed slots, no novel geometry | **a figment** | zero renderer twin to maintain; budget-proven; signed; parity for free |
| a transient overlay with custom geometry over whatever holds focus (the veil slam, a hark, the truth gauge) | **a card** | needs a bespoke draw and must not seize the stage |
| a host power a lens invokes, not a screen | **an emit capability** | the reaction is host-side; the screen is whatever lens declared it |

The headline: *new world-facing text output is a figment by default; a
card is now the exception*, justified by custom geometry plus overlay
semantics. Rosetta Live was the migration pilot
([World lenses](world-lenses.md#rosetta-live--the-ear-offline)), the
how-to lives in `docs/rc_v2/figment_migration.md` (step five is "retire
the twin"), and the ADR names the next text-shaped candidates: the live
caption, upcoming, here, and morning-brief cards. A test pins the
decision — the docs' existence included.

## Your memory is a file

The data-trinity commands treat your memory store as what it is — one
SQLite file you own:

```bash
dreamlayer memories path      # where it lives (~/.dreamlayer/dreamlayer.db)
dreamlayer memories browse    # read-only Datasette UI over it (veil-gated: "Lower the veil first.")
dreamlayer memories export ~/backup.db
dreamlayer memories import ~/backup.db   # refuses to clobber without --force
dreamlayer memories burn --yes           # gone means gone
```

The same browse/export surfaces appear in the Mac panel
([the Brain app](brain-app.md)) so none of this needs a terminal.

## Where the pieces live

| Piece | Path |
|---|---|
| SDK surface | `host-python/src/dreamlayer/sdk/` |
| CLI | `host-python/src/dreamlayer/cli.py` (`dreamlayer = dreamlayer.cli:main`) |
| API v2 + events + settings | `plugins/base.py`, `plugins/events.py` |
| Packaging, signing, gate | `plugins/package.py`, `plugins/validate.py` |
| Isolation ladder | `plugins/isolation.py`, `os_sandbox.py`, `wasm_host.py`, `sandbox_child.py` |
| Capability-transparency log | `orchestrator/capability_log.py` |
| Glass Desk | `simulator/glass_desk.py` |
| The ADR | `docs/adr/0001-plugin-extension-model.md` |
