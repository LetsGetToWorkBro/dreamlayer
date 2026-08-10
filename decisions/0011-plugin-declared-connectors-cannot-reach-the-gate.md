---
id: 0011
title: The four plugin-declared connectors egress from inside a sandboxed plugin, which has no Brain to ask for consent
status: confirmed-deferred
date: 2026-08-10
area: plugins/openlibrary, plugins/currency, plugins/vinyl_oracle, plugins/pokemon_price
---

## Claim

Four of the eight connectors issue #611 lists — `plugins/openlibrary.py`
(openlibrary.org), `plugins/currency.py` (api.frankfurter.app),
`plugins/vinyl_oracle.py` (api.discogs.com) and `plugins/pokemon_price.py`
(api.pokemontcg.io) — reach a pinned public host and appear on no list, so
`/dreamlayer/status` under-reports what the device did.

At full strength, and unlike `decisions/0010`, this is NOT "nothing calls them".
A wearer who installs any of these from the in-app plugin store gets a provider
that talks to a third party, and the consent panel says nothing about it.

## Verdict

Confirmed and deferred: the claim is true, and the fix is not a `Sink` plus a
`check` — the egress happens inside a plugin, and a plugin is deliberately
handed no Brain to ask.

## Evidence

**1. Nothing constructs these connectors outside their own module and the
tests. Every remaining reference is prose.**

```
$ grep -rn "openlibrary\|vinyl_oracle\|pokemon_price\|plugins.currency\|plugins import currency" src/dreamlayer --include=*.py | grep -v "/tests/" | grep -vE "^src/dreamlayer/plugins/(openlibrary|vinyl_oracle|pokemon_price|currency)\.py:"
src/dreamlayer/object_lens/vision_recognizer.py:143:    so bound them here (mirrors the openlibrary rating-clamp posture)."""
src/dreamlayer/plugins/openfoodfacts.py:177:    pins — matching the openlibrary sibling."""
src/dreamlayer/plugins/dictionaryapi.py:3:Mirrors `plugins/openlibrary.py` structure/error-handling/declaration style: a
src/dreamlayer/plugins/dictionaryapi.py:46:# same way `openlibrary._MAX_RESPONSE_BYTES` is.
src/dreamlayer/plugins/dictionaryapi.py:145:    Hardened egress, identical to the openlibrary/openfoodfacts siblings: the
src/dreamlayer/plugins/dictionaryapi.py:151:    ONE retry rather than openlibrary's two, and no retry at all on a 4xx: the
src/dreamlayer/plugins/_egress.py:4:Every shipped connector (openlibrary, openfoodfacts, currency, vinyl_oracle)
src/dreamlayer/plugins/_egress.py:7:can't reintroduce them by copy-paste (audit 2026-07-17 found openlibrary hardened
```

**2. Their real entry point is a plugin `register(ctx)`, reached only through
`PluginStore.load_installed`** — i.e. only after the wearer installs the plugin:

```
$ grep -rn "add_shop_provider\|add_panel_provider\|register(" src/dreamlayer/plugins/openlibrary.py src/dreamlayer/plugins/currency.py src/dreamlayer/plugins/vinyl_oracle.py src/dreamlayer/plugins/pokemon_price.py
src/dreamlayer/plugins/openlibrary.py:158:    def register(self, ctx):
src/dreamlayer/plugins/openlibrary.py:160:        ctx.add_shop_provider(ol_shop_fn(self._fetch or _default_fetch, ttl=ttl))
src/dreamlayer/plugins/pokemon_price.py:390:    def register(self, ctx):
src/dreamlayer/plugins/currency.py:102:    def register(self, ctx):
src/dreamlayer/plugins/vinyl_oracle.py:214:    def register(self, ctx):
```

(The listing is filtered to the `register` seam; the same grep also matches
docstring lines in `openlibrary.py:16` and `:147` and the class docstrings at
`currency.py:88`, `vinyl_oracle.py:199`, `pokemon_price.py:374`.)

**3. The `ctx` a plugin receives carries no Brain.** `WorldLensHost.plugin_context`
passes `brain=self._router` — a `_BrainVisionRouter`, which exposes
`has_vision()` and `explain()` and nothing else:

```
$ grep -n "brain=self._router" src/dreamlayer/ai_brain/server/world_lens.py
375:            glance_arbiter=self.glance_arbiter, brain=self._router,
```

`consent(brain)` needs `incognito_now()`, `config` and `save()`; the router has
none of them, and third-party plugins run in a sandboxed subprocess where a
Brain handle could not be passed even if one were wanted. Gating "at the call
site" for these four means gating inside the connector module — which is
precisely the shape #611 says to avoid, and which `dictionaryapi.py` (the one
already done) deliberately does not do.

**4. Plugin egress already has a gate, and it is a different one.** The world
lens strips the `network` capability whenever capture is not allowed, so a
veiled Brain hands installed plugins no egress at all:

```
$ grep -n 'caps.discard("network")' src/dreamlayer/ai_brain/server/world_lens.py
366:                caps.discard("network")
368:            caps.discard("network")            # unreadable posture → no egress
```

So the behaviour is right and the legibility is missing — #611's own framing,
with a different seam to fix it at.

## What would overturn this

Either half:

* **A Brain-side construction appears.** Re-run check 1; a hit under
  `src/dreamlayer/ai_brain/` that constructs `ol_shop_fn`, `CurrencyProvider`,
  `VinylOracleProvider` or `PokemonPriceProvider` makes that call site gateable
  exactly like the Open Food Facts barcode lookup, and it should be gated in the
  same commit.
* **`PluginContext` gains a consent seam.** If `ctx` ever carries something a
  plugin can ask — a `ctx.egress(name)` the host answers from the gate, or a
  host-side count around `add_shop_provider` — these four stop needing a Brain
  and become ordinary registrations. `grep -n "capabilities=" src/dreamlayer/ai_brain/server/world_lens.py`
  and the `PluginContext` definition are where that would show up.

## Consequences

Do not add `openlibrary`, `currency`, `vinyl_oracle` or `pokemon_price` to
`SINKS` until one of those two lands. A sink with no reachable `check` is a row
that reads "allowed, never sent" no matter what an installed plugin does — worse
than absence, because the panel is asserting something.

The plugin-egress surface is worth one entry on the panel eventually, but it is
one entry about *plugins*, answered by the host, not four entries about four
connectors the Brain never constructs. That is a design decision for the plugin
host, not a mechanical continuation of this issue.
