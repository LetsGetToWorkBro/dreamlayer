---
id: 0010
title: The weather and skywatch connectors have no shipped Brain caller, so a consent sink for them could never fire
status: refuted
date: 2026-08-10
area: plugins/open_meteo, plugins/skywatch_adsb
---

## Claim

Issue #611 lists eight keyless connectors that reach a pinned public host and
appear on no list, and asks that each be registered as a `Sink` in
`ai_brain/server/consent_gate.py` with a `consent(brain).check(key)` at its call
site. Two of them are `plugins/open_meteo.py` (api.open-meteo.com) and
`plugins/skywatch_adsb.py` (api.adsb.lol). Stated at full strength: the wearer's
device can talk to two more third parties than `/dreamlayer/status` admits, and
`anything_left()` answers `False` while it does.

The issue also names its own doubt — *"I did not chase these to a conclusion.
If the only caller is Orchestrator-only, then gating there gates something no
wearer reaches"* — which is what this entry settles.

## Verdict

Refuted for the shipped Brain: both connectors are called only from an
`Orchestrator` mixin, no shipped Brain builds an `Orchestrator`, and the consent
gate is a Brain-side registry an `Orchestrator` has nothing to register with —
so a sink for either could never fire, and would make the wearer-facing list
longer without making it truer.

## Evidence

**1. Each connector has exactly one caller outside its own module and the
tests, and both are the same Orchestrator mixin.**

```
$ grep -rn "open_meteo\|skywatch_adsb" src/dreamlayer --include=*.py | grep -v "/tests/" | grep -v "^src/dreamlayer/plugins/open_meteo.py\|^src/dreamlayer/plugins/skywatch_adsb.py"
src/dreamlayer/orchestrator/ops_world_lenses.py:662:        from ..plugins.open_meteo import current_weather, say_weather
src/dreamlayer/orchestrator/ops_world_lenses.py:675:        from ..plugins.skywatch_adsb import overhead, say_plane
```

**2. `Orchestrator` is constructed in three places outside the tests, and none
of them is the Brain.** `main.py` and both `simulator/` sites build it against
an `EmulatorBridge` — the pre-hardware glasses emulator, not the Mac-mini Brain
a phone talks to:

```
$ grep -rn "Orchestrator(" src/dreamlayer --include=*.py | grep -v "/tests/"
src/dreamlayer/main.py:3:def build(db_path=":memory:"): return Orchestrator(EmulatorBridge(), db_path=db_path)
src/dreamlayer/simulator/scenarios.py:15:    return Orchestrator(EmulatorBridge(), db_path=":memory:")
src/dreamlayer/simulator/core.py:66:        self.orc = Orchestrator(self.bridge)
src/dreamlayer/orchestrator/orchestrator.py:90:class Orchestrator(
```

This is `decisions/0001`'s finding at a different layer, and
`tests/test_attention_gate.py:5` already states it in as many words: *"the
shipped Brain never builds an `Orchestrator`"*.

**3. There is nothing on the Orchestrator side to ask.** Every entry point of
the gate takes a Brain — `consent(brain)` caches on `brain._egress_consent`,
`allowed()` reads `brain.incognito_now()` and `brain.config`, `grant()` calls
`brain.save()`. An `Orchestrator` has none of those, so "gate it at the
Orchestrator call site" is not a smaller version of this change; it is a
different mechanism, and it does not exist yet.

## What would overturn this

A production construction of `Orchestrator` from Brain-side code, or a Brain
route that reaches `ops_world_lenses`. Re-run check 2 above, scoped to the
Brain:

```
$ grep -rn "Orchestrator(" src/dreamlayer/ai_brain --include=*.py | grep -v "/tests/"
```

One hit there and both connectors become wearer-reachable, at which point they
each need a `Sink` and a `check`/`note` pair at `ops_world_lenses.py:662` and
`:675`. The same follows if either lens ever gains a Brain host beside
`world_lens.py` — grep for `current_weather(` / `overhead(` outside
`orchestrator/`.

## Consequences

Do not register `open_meteo` or `skywatch_adsb` in `SINKS` while this holds. A
sink that can never fire reports `sent: 0` forever, which reads to a wearer as
"this device has never talked to api.adsb.lol" — true today, true for the wrong
reason, and it would go on reading that way after somebody wired a caller.

The honest moment for it is the one that makes the family reachable at all: if
the Orchestrator world lenses are ever hosted Brain-side (the shape
`world_lens.py` already is for the Object Lens), gate them as they are wired, in
the same commit.
