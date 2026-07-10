# The DreamLayer SDK

Everything you need to build, test, and ship a plugin — one import surface
(`dreamlayer.sdk`) and one command (`dreamlayer plugins`).

A plugin extends the layer without touching core: a new **card** on the HUD, a
**row** on the look-at-a-thing panel, a **lens** the glance can route to, a
**price/review connector** for TasteLens, or an on-glass **perceptor**. Every
plugin passes the same safety gate — integrity check, capability scan, smoke
test — before it runs on anyone's glasses.

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

## Capabilities

Declare in `requires` only what you use. The host grants a capability if it can,
skips your plugin (never crashes) if it can't, and the gate **refuses any
undeclared reach** — a plugin that imports `socket` or writes files without
declaring `network`/`fs` fails validation. Known capabilities: `cards`,
`object_lens`, `glance`, `shop`, `perception`, `vision`, `ring`, `mesh`, `midi`,
`network`, `fs`.

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
- `dreamlayer plugins --help` — every command and flag.
