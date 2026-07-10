# The DreamLayer SDK

Everything you need to build, test, and ship a plugin — one import surface
(`dreamlayer.sdk`) and one command (`dreamlayer plugins`).

A plugin extends the layer without touching core: a new **card** on the HUD, a
**row** on the look-at-a-thing panel, a **lens** the glance can route to, a
**price/review connector** for TasteLens, or an on-glass **perceptor**. Every
plugin passes the same safety gate — integrity check, capability scan, smoke
test — before it runs on anyone's glasses.

> **Two ways to build.** A **plugin** is *code* (this guide). A **figment** is
> *data* — a signed, budget-proven scene machine you can author with **no code
> at all**: in the phone's rehearsal flow, in the browser builder
> (`landing/lens-builder.html`), or as JSON checked by `dreamlayer figment` /
> `golf`. Same platform, same proofs; jump to [Figments](#figments--behaviors-as-data-no-code)
> if you don't want to write Python.

> **Stability contract.** Import only from `dreamlayer.sdk`. Everything under it
> (`dreamlayer.orchestrator.*`, `dreamlayer.object_lens.*`, …) is internal and
> will move. The SDK surface is versioned (`dreamlayer.sdk.__version__`) and
> changes only when an author would notice.

## Install

```bash
pip install -e host-python            # the base install ships the SDK + the CLI
dreamlayer --version                  # dreamlayer sdk 1.0.0
```

## Your first plugin in five minutes

```bash
dreamlayer plugins new hello-world    # scaffold a working starter
cd hello-world
dreamlayer plugins validate .         # integrity + capability scan + smoke test
pytest                                # the same gate, as a test
```

The scaffold is a complete, passing **API v2** plugin — a HUD card plus one
persisted setting. Edit two files:

- **`plugin.py`** — your code. It imports from `dreamlayer.sdk`, defines a
  `register(ctx)` (plus optional `start`/`stop`/`tick`/`on_event`), and exposes
  a `plugin()` entry factory.
- **`plugin.json`** — the manifest: `name`, `version`, `requires` (the
  capabilities you use), and the store copy (`description`, `forwho`, `long`,
  `screenshot`).

Then package and ship:

```bash
dreamlayer plugins pack .                              # -> hello-world-0.1.0.json
dreamlayer plugins install . --brain http://localhost:8765   # sideload to a Brain
```

`install` sends the package to a paired Brain, which **re-runs the gate** and
returns its verdict — the phone and Mac panel do exactly the same thing. Set
`DREAMLAYER_BRAIN` / `DREAMLAYER_TOKEN` to skip the flags.

## The surface

```python
from dreamlayer.sdk import make_plugin

def register(ctx):
    ctx.add_card_renderer("HelloCard", draw_hello)   # a HUD card

def plugin():
    return make_plugin("hello-world", register, requires=("cards",))
```

| You're building | Import / call | Declare |
|---|---|---|
| A HUD card | `ctx.add_card_renderer(type, fn)` — `fn(draw, card)` paints a 256×256 additive display | `cards` |
| A look-at-a-thing row | subclass `PanelProvider` (`matches`/`build` → `PanelRow` from an `ObjectSighting`) | `object_lens` |
| A new lens for the glance | subclass `LensCandidate` (`bid(reading, ctx)` → `LensBid` from a `GlanceReading`) | `glance` |
| A TasteLens connector | `ctx.add_shop_provider(fn)` — `fn(label, attrs) -> {rating?, price?}` | `shop` |
| An on-glass perceptor | object with `listen`/`perceive` → `AudioPercept`; `ctx.add_perceptor(...)` | `perception` |

**API v2** adds an optional lifecycle — `start(ctx)`, `stop()`, `tick(now)`,
`on_event(kind, payload)` — plus veil-gated events (`ctx.subscribe(kind, fn)`)
and per-plugin persisted settings (`ctx.settings`). Capture a name-bound
settings handle in `register()` (`self._settings = ctx.settings`) so host-invoked
setters persist to *your* bucket even outside a lifecycle callback.

**Typed** — the SDK ships `py.typed`, so your editor and `mypy`/`pyright` see
its types. Annotate against the structural `PluginContextProtocol` and type your
manifest with `ManifestDict`:

```python
from dreamlayer.sdk import PluginContextProtocol

def register(ctx: PluginContextProtocol) -> None:
    ctx.add_card_renderer("HelloCard", draw_hello)   # autocompleted
```

## Compatibility (`min_sdk`)

Declare the lowest SDK your plugin needs in the manifest; a host running an older
SDK refuses it *at the gate* with a clear message instead of failing at runtime:

```json
{ "name": "hello", "version": "0.1.0", "entry": "plugin:plugin",
  "min_sdk": "1.0.0" }
```

`dreamlayer plugins new` fills in the current `min_sdk` for you.

## See it on-glass: `plugins preview`

Because DreamLayer runs the exact device render path in software, you can see —
and snapshot-test — **precisely what your card looks like on the glasses**, with
no hardware:

```bash
dreamlayer plugins preview .                      # → <name>-preview.png (256×256, the device output)
dreamlayer plugins preview . --shot               # a 640×340 store banner
dreamlayer plugins preview . --card '{"type":"HelloCard","text":"hi"}'
```

The same thing programmatically, for **visual-regression tests** — the render is
deterministic, so assert against a committed golden:

```python
from dreamlayer.sdk import render_card
img = render_card(my_plugin, {"type": "HelloCard", "text": "hi"})   # a PIL image
assert img.tobytes() == golden.tobytes()          # pixel-exact regression
```

Set a `preview_card` in `plugin.json` to give `preview`/the store a representative
sample. Provider-only plugins (no card) report that there's nothing to preview.

## Iterate fast: `plugins dev`

```bash
dreamlayer plugins dev .                       # re-run the gate on every save
dreamlayer plugins dev . --brain http://localhost:8765   # + hot-reload to a Brain
```

It watches `plugin.py`/`plugin.json` and re-validates (and reinstalls, with
`--brain`) each time you save — an instant inner loop. `--once` runs a single
pass (handy in CI).

## See the glass, no hardware: Glass Desk

```bash
python -m dreamlayer.simulator --watch my-plugin/          # re-render on every save
python -m dreamlayer.simulator --watch my-plugin/ --once   # one frame (CI)
```

The zero-hardware devkit: it re-renders your card through the **real 256×256
device renderer** — the exact pixels the glasses draw, with the 112px safe-radius
circle overlaid — every time you save, to `my-plugin/.glass/glass.png` (or
`--out`). No flashing, no glasses; the render is deterministic, so the same PNG
doubles as a visual-regression golden.

## Two ways a host finds a plugin

- **The registry** (this repo's `registry/`) — the curated, reviewed store the
  clients read. This is how end users install.
- **Entry points** — a `pip`/`uv`-installed plugin package advertises itself so a
  host discovers it locally, great for development and private plugins:

  ```toml
  # in your plugin's pyproject.toml
  [project.entry-points."dreamlayer.plugins"]
  my-plugin = "my_pkg.plugin:plugin"
  ```

  `dreamlayer plugins list --entry-points` shows what's discoverable. Discovery
  answers *where a plugin loads from*; the **manifest still governs *what it may
  do*** — the capability gate runs either way.

## Capabilities

Declare in `requires` only what you use. The host grants a capability if it can,
skips your plugin (never crashes) if it can't, and the gate **refuses any
undeclared reach** — a plugin that imports `socket` or writes files without
declaring `network`/`fs` fails validation. Known capabilities: `cards`,
`object_lens`, `glance`, `shop`, `perception`, `vision`, `ring`, `mesh`, `midi`,
`network`, `fs`.

## Trust, signing & isolation

- **Signing** — an author signature (Ed25519) covers the code hash **and the
  security-relevant manifest fields** (`name`, `version`, `entry`, `api`,
  `min_sdk`, `requires`), so an attacker can't take a signed package and quietly
  widen its capabilities or redirect its entry point. Store-detail copy stays
  free to edit without re-signing. Unsigned packages remain installable under the
  curated-registry trust model (surfaced with a warning).
- **Transparency log** — the host keeps a per-plugin record of what each plugin
  was *granted* and what it actually *did* with it — host events routed to it and
  calls into an isolated plugin's providers — surfaced in `health_snapshot()`
  under `plugins`. Honest scope: an in-process plugin's raw network/file access
  isn't intercepted (the host isn't in that path); run untrusted plugins in the
  isolation tier and their activity shows up. So it's complete for isolated +
  mediated surfaces, and honest about the in-process gap.
- **Isolation tiers** — reviewed first-party plugins run in-process. *Untrusted*
  plugins run in a capability-mediated subprocess jail; where `bwrap`/`nsjail`
  are present, that child is additionally wrapped in an **OS sandbox** — no
  `network` capability means no network namespace, the filesystem is read-only
  except a private scratch, PID/IPC unshared. Control with `DL_SANDBOX`
  (`auto` | `bwrap` | `nsjail` | `none`); it degrades cleanly to a plain
  subprocess where the tools aren't usable. A **WASM tier** (`plugins/wasm_host.py`)
  is wired as the strongest jail — the same sandbox child under `wasmtime`, where
  a denied capability is simply a WASI grant the host never provides (no `fs` →
  no `--dir`; no `network` → no socket inheritance). It activates when an
  operator sets `DL_WASM_RUNTIME` (wasmtime) + `DL_WASM_GUEST` (a `python.wasm`
  with dreamlayer bundled); otherwise the store falls back to the subprocess
  tier. The capability→grant mapping and tier selection are tested; end-to-end
  execution is gated on that operator-provided runtime.

## Figments — behaviors as data (no code)

A **figment** is a behavior expressed as *data*: scenes, timed/event
transitions, pulses, bounded counters — signed and **statically proven safe
before it ever runs**. No Python, no build step. This is what makes a behavior
marketplace possible: the installer re-checks the proof; it doesn't trust the
author.

Three ways to author one, easiest first:

- **The browser builder** — `landing/lens-builder.html`. Pick a recipe (interval
  timer, checklist ritual, countdown, box-breathing), customize it, watch it run
  on a live ring preview, read the safety card, then **Deploy to your Brain** or
  download the JSON. Zero install, zero code.
- **The phone** — rehearse it by performing it (tap, speak the beats, keep), in
  the app's rehearsal flow.
- **JSON + the CLI** — hand-write or generate the figment and check it:

```bash
dreamlayer figment safety my-lens.json      # the proof: what this behavior CANNOT do
dreamlayer golf verify my-lens.json          # score expressiveness per byte
```

`figment safety` prints the machine-verified upper bound — "cannot pulse faster
than 2 Hz, cannot outlive 40 minutes, cannot swallow your kill switch" — plus,
for a **shared** figment, a **voice** disclosure: whether its text imitates
system/power/security chrome (the "BATTERY CRITICAL — REMOVE GLASSES" attack).
*The sandbox proves physics; provenance proves voice.* Worked examples live in
[`examples/figments/`](../examples/figments/) (`sous-sear.json`,
`kiln-darkroom.json`).

## Publishing

Open a pull request that adds your packaged `.json` under `registry/packages/`
and an entry in `registry/index.json`. CI runs the gate; a maintainer reviews
the code. Free plugins stay free to publish and install; a paid tier
(85% creator / 15% platform) is reserved — see
[`MARKETPLACE.md`](MARKETPLACE.md).

## Reference

- [`MARKETPLACE.md`](MARKETPLACE.md) — the registry, the gate, the social layer,
  and the pricing model.
- [`PLATFORM.md`](PLATFORM.md) — where the Plugin API sits among the five
  platform pillars.
- `dreamlayer --help` — the full surface: `plugins` (`new`/`validate`/`pack`/
  `install`/`list`/`info`/`preview`/`dev`), `figment safety`, `golf verify`,
  `packs validate`, `bench perception`, `memories` (`path`/`browse`/`export`/
  `import`/`burn`).
- **Themes** — the in-eye design language is data too: a theme table restyles
  the palette, type scale, and motion (`halo-lua/display/theme.lua`, refs in
  `display/themes/`), validated against the skin budget.
- **Physical events** — any sensor can transition a figment via
  `POST /dreamlayer/event/ble/<n>`; see [`examples/esp32/`](../examples/esp32/).
- [`adr/0001-plugin-extension-model.md`](adr/0001-plugin-extension-model.md) —
  why the extension model is `register(ctx)` + capabilities, not pluggy.
  `dreamlayer plugins info` (and `sdk.contributions()`) shows what a plugin adds.
