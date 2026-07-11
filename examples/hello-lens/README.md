# Hello, Lens — write your first DreamLayer plugin in ten minutes

This folder is a **complete, store-valid plugin**: ~25 lines of Python, a
manifest, done. It registers one custom HUD card type and draws it on the
glass. Every big lens in DreamLayer — TasteLens, the Beacon, Face Synth — is
this same pattern with more ideas.

It is also **tested in CI** (`test_hello_lens_example.py` runs this exact
folder through the real store validation gate), so this tutorial can't rot.

## 1 · What a plugin is

A plugin is a `register(ctx)` function plus a factory that wraps it:

```python
from dreamlayer.plugins import make_plugin

def draw_hello_card(draw, card):            # fn(draw, card): paint the 256px glass
    draw.text((128, 118), card.get("text", "hello, world"),
              fill=(44, 199, 154, 255), anchor="mm")

def register(ctx):
    ctx.add_card_renderer("HelloCard", draw_hello_card)

def make():                                  # the manifest's entry point
    return make_plugin("hello-lens", register, requires=("cards",))
```

`ctx` is the narrow doorway (`plugins/base.py`) — a plugin can extend the
registries and read veil/ring state, and nothing else. `requires` names the
capabilities you need; the host grants them or skips your plugin cleanly.

| Capability | Lets you |
|---|---|
| `cards` | register custom HUD card renderers |
| `object_lens` / `glance` | add rows when the wearer looks at things / bid for the glance |
| `perception` | add a perception provider |
| `ring` | read veil / day-ring state |
| `mesh` | emit/receive tiny GhostMode circle packets |
| `shop` | be a TasteLens price/review source |
| `vision` / `network` / `midi` / `fs` | vision model, network egress, MIDI out, file reads |
| `cloud_ai` / `cloud_sync` / `cloud_relay` | DreamLayer Cloud entitlements — declaring one makes yours a cloud-plan plugin |

(The full set lives in `plugins.package.KNOWN_CAPABILITIES`.)

## 2 · Run it locally

```bash
pip install -e "host-python[dev]"
cd host-python && python -m pytest -q -k hello_lens     # the gate, on this folder
```

Or check and preview it with the CLI (from this folder):

```bash
dreamlayer plugins validate .    # runs the full store gate
dreamlayer plugins preview .     # renders your card through the real 256px glass
```

## 3 · Package it

A store package is `manifest.json` + your module, bound by a checksum. The CLI
computes it and writes the shippable package for you — no manual hashing:

```bash
dreamlayer plugins pack .        # -> a store-ready package JSON
```

Every install runs the full gate (`plugins/validate.py`): manifest shape,
checksum integrity, a static scan proving the code touches nothing beyond its
declared capabilities, and a smoke load. No undeclared reach, ever.

New to the CLI? `dreamlayer plugins new my-lens` scaffolds a fresh plugin, and
[`docs/SDK.md`](../../docs/SDK.md) is the full quickstart.

## 4 · Ship it

- Open a PR adding your plugin to `registry/` (see
  [`docs/MARKETPLACE.md`](../../docs/MARKETPLACE.md)), or
- share the package JSON directly — anyone can sideload it from the Brain
  panel's Plugins page, through the same gate.

Copy this folder, rename everything, and go build the lens you wish existed.
