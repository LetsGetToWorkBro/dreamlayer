---
id: 0006
title: causal_fusion inferred nothing causally and returned None either way — dropped
status: accepted-risk
date: 2026-08-01
area: truth_lens/causal_fusion.py
---

## Claim

Raised in the capability-reachability pass: `truth_lens/causal_fusion.py` was
declared as an optional capability ("Causal inference over credibility
channels", extras group `causal`, dependency `dowhy`), sat in `_NOT_WIRED` as
dormant, and was listed in `HANDOFF.md` as one of eighteen adapters awaiting a
Brain-side wire.

Stated in its strongest form: *it is a built adapter, one call away from
working, and wiring it would give the Truth Lens a causal second opinion on
credibility instead of the fixed-weight fusion it uses today.*

## Verdict

It would not. `assess()` could never return a number on real inputs, and the
number it returned on any input owed nothing to `dowhy`. Dropped rather than
wired.

## Evidence

The whole body, as it stood:

```python
if not _HAS_DOWHY:
    return None
signals = [s for s in (getattr(au, "score", None),
                       getattr(prosody, "stress", None),
                       getattr(linguistic, "confidence", None)) if s is not None]
if not signals:
    return None
agree = 1.0 - (max(signals) - min(signals))
return max(0.0, min(1.0, agree))
```

Three separate findings, any one of which is disqualifying:

**1. `dowhy` is imported and never called.** The only use is the flag:

```
$ grep -n "dowhy" host-python/src/dreamlayer/truth_lens/causal_fusion.py
14:    import dowhy  # type: ignore  # noqa: F401
```

`scripts/capability_dependency.py` filed it under PROBE ONLY for exactly this
reason — one of ten, so removing it does not make that checker vacuous.

**2. The three attributes it reads do not exist.** The credibility channels are
`AUChannel` / `ProsodyChannel` / `LinguisticChannel` in `truth_lens/schema.py`;
none of them defines `score`, `stress` or `confidence`. Every `getattr` returns
its `None` default, `signals` is empty, and the function returns `None` — on
every call, with or without the dependency installed.

**3. What it would compute is not causal.** `1.0 - (max - min)` is an agreement
spread between three correlated numbers. That is the correlation-only reasoning
the module's own docstring said it existed to replace, with a causal-inference
library named in the metadata as though it produced it.

The declared gain — "baseline fuses credibility channels with fixed weights;
this infers causally" — was therefore false in both halves.

## What would overturn this

Someone implementing a real causal read: a DAG over the channels, an estimand,
and an actual `dowhy` call whose result changes the verdict. That is writing the
feature, not restoring the file — and it should be raised as new work with its
own evidence, not as a revert.

Cheap check that the file is genuinely gone rather than merely unreferenced:

```
$ grep -rn "causal_fusion" --include=*.py host-python/src scripts | grep -v decisions
host-python/src/dreamlayer/tests/test_integration_seams_pr2.py:17: (docstring)
scripts/capability_dependency.py:401: (docstring)
```

## Consequences

* The `causal` extras group is removed; `dowhy` was its only member, and the
  `profile-mac` / `profile-cloud` profiles no longer name it. Nothing else in
  the tree imports it.
* `HANDOFF.md`'s dormant list drops from eighteen to seventeen, and says why —
  **dropping a seam is a third valid answer**, alongside "wire it" and "move it
  to `_BY_DESIGN`". It is the right answer when the adapter would be worse than
  the fallback it shadows, which is the case whenever an adapter can only ever
  return its own null.
* `test_integration_seams_pr2.py` keeps a renamed test with the reasoning in its
  docstring, so the deletion is discoverable from the place that used to assert
  the old behaviour.
* The floor principle this repo already holds — *an optional dependency must
  never return less than its own fallback* — has a corollary this entry is the
  first instance of: an adapter that can only ever return its own null is not a
  dormant capability, it is a claim. Prefer deleting it to carrying it.
