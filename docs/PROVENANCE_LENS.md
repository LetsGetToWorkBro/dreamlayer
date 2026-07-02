# Provenance Lens — where did that belief come from?

`orchestrator/provenance.py`

Truth Lens judges whether **other people** are credible. Candor keeps **your
own** story consistent. The Provenance Lens is the third of that family and
the strangest: point it at something you believe or are about to repeat, and
it traces the belief back through your own memory to its origin.

> "You believe the deadline is Friday because **Maya** told you, **3 weeks
> ago**, corroborated by Sam — but the standup time is **contested**: Priya
> said 10, Deshawn said 11."

It answers three questions no other instrument does:

- **who** put this belief in your head (`meta.person`)
- **when** it entered (memory timestamp → "3 weeks ago")
- **how well it stands up** — its *standing*

## Standing

| standing | meaning |
|---|---|
| **firsthand** | you were there for it (`via` = saw/said/observed/did) |
| **corroborated** | ≥2 independent attributions agree |
| **unverified** | a single piece of hearsay, uncorroborated |
| **contested** | something else you recorded contradicts it (via Candor) |
| **unknown** | no source in your memory at all |

Independence is counted by distinct people, or distinct source+day when
anonymous. A memory that *clashes* with the claim (Candor's pairwise
`contradicts`) is never counted as support — it becomes the contradiction.

It never asserts truth — only genealogy and standing, so you can *weigh* a
belief instead of just holding it. Deterministic and offline over the memory
ring; private memories (`meta.private`) are never traced, and the
orchestrator (`trace_provenance`) gates the lens behind the Privacy Veil.

## Try it

```
python scripts/run_demo_provenance.py
```

## Tests

`test_provenance.py` — age humanising, origin/attribution, unverified vs
corroborated vs firsthand, earliest-support-is-origin, contested (with the
clashing memory excluded from support), the unknown and private guards, and
orchestrator wiring (veil-gated, cards).
