---
id: 0003
title: Presidio tags `"mug"` as a PERSON, and we ship it
status: accepted-risk
date: 2026-07-27
area: object_lens/person_guard
---

## Claim

Found while giving the `real-models` CI job a Presidio it could actually run
(issue #528): `person_guard.label_is_a_person("mug")` returns `True` against the
real analyzer. The stranger-defence text layer therefore defers on an ordinary
object label, and the object lens declines to name a mug.

## Verdict

True, reproducible, and accepted. It is a utility cost, not a privacy failure,
and every fix we found for it cost more recall than it bought precision.

## Evidence

`en_core_web_sm` scores `"mug"` as PERSON at 0.85 — above the 0.6 floor — and it
does so in every sentence frame we tried:

```
$ python -c "from dreamlayer import nlp_setup; e = nlp_setup.analyzer_engine();
  print(e.analyze(text='mug', language='en', entities=['PERSON']))"
[type: PERSON, start: 0, end: 3, score: 0.85]
```

`Mug` is a real surname, so this is the model behaving as designed rather than
misfiring. Measured across 85 object labels and 3 sentence frames, the false
positives were:

| frame | false positives |
|-------|-----------------|
| bare label | `mouse`, `mug`, `napkin`, `coffee mug` |
| `"This is X."` | `mug` |
| `"I met X."` (shipped) | `mug`, `coffee mug` |

No frame eliminates `mug`.

## Why it is accepted

The two failure directions are not symmetric, and the module says so: the layer
"can only ADD a deferral, never remove one."

* **False positive** (`mug` → defer): the wearer looks at a mug and the lens
  declines to name it. Annoying. No information leaves, nobody is identified.
* **False negative** (a real name → no defer): a stranger could be named. That
  is the failure this layer exists to prevent.

Buying precision here costs recall, and recall is the axis that matters. The
shipped frame was chosen because it improved *both* (18/35 → 27/35 names caught,
4 → 2 false positives) — not because we traded one for the other.

## What would overturn this

```
cd host-python && python -m pytest -m real_model \
  src/dreamlayer/tests/test_pii_presidio_real.py::test_mug_is_the_known_false_positive
```

That test asserts `label_is_a_person("mug") is True`. When a future spaCy model
or frame fixes the tagging, **the test fails** — and the correct response is to
delete both the test and this entry, not to re-pin the old behaviour. Its
docstring says so.

## Consequences

- Do not raise this again as a bug without new information; raise it as a
  *model-quality* item if the false-positive set grows beyond a handful.
- Do not "fix" it by adding a shape or common-noun precondition to the text
  layer. That layer exists precisely to catch what the deterministic shape rules
  in `recognizer._names_a_person` already miss; gating it on a shape rule
  collapses it into the thing it supplements.
- If the false-positive list ever grows enough to be a real nuisance, the
  cheaper lever is a small allow-list of confirmed object nouns checked before
  the analyzer — bounded and auditable — not a threshold change, which trades
  away recall globally.
