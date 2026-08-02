# Example figments

Proof-carrying state machines for the glasses, scored by the compiler-referee
(`host-python/src/dreamlayer/reality_compiler/v2/golf.py`): an entry is only
eligible if it passes every budget, and its `golf_score` is expressiveness per
1000 canonical bytes — most machine, fewest bytes. Verify any entry with:

```
dreamlayer golf verify examples/figments/<name>.json --json
```

| Figment | Machine | golf_score | bytes |
|---|---|---|---|
| `reflex-ladder.json` | Reaction ladder: a random 1–3s arm (`duration_range`) with false-start detection, a 2s `countup` GO window with a closing pulse, hit/miss/streak counters, a guarded timeout branch that ends the ladder after 8 rounds, and ledger emits (`hit`/`miss`/`rd`…) — 21 event types, 8 counters, 2 pulses in 4.6 KB. | 20.1 | 4627 |
| `sous-sear.json` | Two-scene sear-then-rest kitchen timer with a countdown tick and a final-seconds pulse. | 15.06 | 797 |
| `kiln-darkroom.json` | Four-scene kiln firing schedule with a temperature counter. | 10.39 | 1732 |

`reflex-ladder` is the Figment Golf entry for issue #402; its eligibility and
score floor are pinned in CI by
`host-python/src/dreamlayer/tests/test_golf_example_figment.py`, so the claimed
score cannot silently rot.
