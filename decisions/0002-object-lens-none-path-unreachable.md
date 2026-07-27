---
id: 0002
title: "`default_classifier()` cannot return `None` in production"
status: refuted
date: 2026-07-27
area: object_lens/classify_backends
---

## Claim

Raised in the full-stack audit (wave 1): the object lens can fall back to a
caller-supplied mock classifier, so a build with no vision dependencies could
serve mock object labels as if they were real recognition — an honesty failure
in the lens that names what the wearer is looking at.

## Verdict

Refuted. The `None` return that would let a mock take over is unreachable: it
requires an argument no production caller passes.

## Evidence

`default_classifier` returns `None` only on the explicit opt-out branch:

```
$ sed -n '382,405p' src/dreamlayer/object_lens/classify_backends.py
def default_classifier(labels=None, heuristic_fallback: bool = True):
    ...
    return HeuristicVisionClassifier() if heuristic_fallback else None
```

The parameter defaults to `True`, and no non-test code ever sets it. The only
three hits in the package are the signature, the docstring, and the return
expression — all in the defining file:

```
$ grep -rn "heuristic_fallback" src/dreamlayer --include=*.py | grep -v "/tests/"
object_lens/classify_backends.py:383:                       heuristic_fallback: bool = True):
object_lens/classify_backends.py:387:    recognition happens even with no ML deps. Pass ``heuristic_fallback=False`` to
object_lens/classify_backends.py:405:    return HeuristicVisionClassifier() if heuristic_fallback else None
```

With no ML dependency installed, the ladder therefore ends at
`HeuristicVisionClassifier` — which reads real pixels. It is a weak backend, but
it is not a mock, and it is not dishonest about what it is.

## What would overturn this

```
grep -rn "heuristic_fallback=False" src/dreamlayer --include=*.py | grep -v "/tests/"
```

returning a hit. That is the single condition. The `heuristic_fallback=False`
path exists deliberately so a caller's own mock stays authoritative in tests —
if it ever gains a production caller, this refutation is void and the original
finding becomes live.

## Consequences

- The finding should not be re-raised against `default_classifier` itself.
- The adjacent, *separate* concern is real and out of scope here:
  `HeuristicVisionClassifier` has its own accuracy problems (it was measured
  calling a night street a 'screen' at 80% confidence). That is a quality issue
  in a real backend, not a mock leaking into production, and it needs its own
  entry if it is ever closed without a fix.
