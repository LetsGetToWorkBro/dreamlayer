---
id: 0001
title: Nothing on the device ever expires — the retention lifecycle has no live caller
status: confirmed-deferred
date: 2026-07-27
area: orchestrator/retention
---

## Claim

Raised in the full-stack audit (wave 1, carried through waves 2 and 3 without
being overturned): `RetentionSweep` — the nightly pass that purges the hot ring
past its window and sweeps the warm store — never runs in a shipped build. If
true, no memory on the device is ever aged out by policy, and the retention
settings in the panel describe a lifecycle that does not exist.

## Verdict

Confirmed, and over-determined: the chain is broken in **three independent
places**, any one of which alone would be enough.

## Evidence

**1. `RetentionSweep` has exactly one construction site, and it is inside
`maybe_dream_tonight`.**

```
$ grep -rn "RetentionSweep(" src/dreamlayer --include=*.py | grep -v "/tests/"
src/dreamlayer/orchestrator/ops_dream_rem.py:68:            sweep = RetentionSweep(
```

**2. `maybe_dream_tonight` has no production caller.** Every reference outside
its own definition is a test or a docstring mention:

```
$ grep -rn "maybe_dream_tonight" src/dreamlayer --include=*.py
orchestrator/ops_dream_rem.py:45:    def maybe_dream_tonight(self, charging: bool):   # the definition
orchestrator/ops_ember.py:173:  """...runs inside maybe_dream_tonight, before   # a docstring
tests/test_ember_ops.py                                                # test
tests/test_stasis_ops.py                                               # test
tests/test_integration_dream_suite.py                                  # test
```

**3. Even if it were called, it returns before reaching the sweep.**
`ops_dream_rem.py:51` bails when `nightwatch` is `None`, and `nightwatch` is
always `None` because `vault_dir` is read off `Config` with a defaulting
`getattr` and `Config` has no such field:

```
$ sed -n '629,639p' src/dreamlayer/orchestrator/orchestrator.py
        vault_dir = getattr(cfg, "vault_dir", None)
        ...
        self.nightwatch = NightWatch(vault_dir) if vault_dir else None

$ grep -n "_dir" src/dreamlayer/config.py
(no output — Config declares no directory fields at all)
```

`getattr(cfg, "vault_dir", None)` is the tell. A plain attribute access would
have raised on the first run and this would have been found years ago; the
default silently produced `None` forever.

## What would overturn this

Any of:

```
grep -rn "maybe_dream_tonight" src/dreamlayer --include=*.py | grep -v "/tests/"
```
returning a call site rather than only the definition and a docstring; **or**
`vault_dir` appearing as a real field on `Config`; **or** a second
`RetentionSweep(` construction outside `ops_dream_rem.py`.

Fixing any one of the three is not enough — the entry stays valid until all
three legs are repaired, because each independently blocks the sweep.

## Consequences

- Treat any statement that DreamLayer ages out memory on a schedule as **not
  currently true**. Check the product copy and the panel's retention settings
  against this before shipping either.
- `RetentionPolicy`'s `retention_hot_hours` / `retention_warm_days` config reads
  are likewise inert. They are also `getattr` defaults
  (`ops_dream_rem.py:66-67`), so setting them changes nothing today.
- A fix has to wire `vault_dir` into `Config` **and** give
  `maybe_dream_tonight` a real scheduler, not just one or the other. Doing half
  of it will look like progress and change no behaviour.
- The privacy story is unaffected in the other direction: explicit deletion
  (`purge_all`, "Erase all memories") does work and was hardened separately in
  PR #530. This entry is about *automatic expiry*, not about erase.
