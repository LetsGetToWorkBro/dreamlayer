# Confluence — two wearers, one entangled sky

When two DreamLayer wearers bond, their palette weathers entangle: each
display renders the blend of both nervous systems' weather. Converge and the
shared sky settles into one coherent front (palettes blended 50/50, no seam —
the absence is the message); drift and the sky splits — your weather keeps
your half, theirs renders on their half as a ready RGB, and a visible seam
stands between the fronts, widening with divergence. Togetherness =
1 − |your inner state − theirs|, EMA-smoothed, hysteresis-banded so the sky
never flaps. Nothing is said, nothing is measured out loud.

**The bond** (bond.py): explicit, mutual, revocable. Propose → a short human
code passes between the two of you → accept → confirm; both sides derive the
same HMAC key from (bond_id, code). Only WeatherPackets ever cross — a state
scalar, four palette slots, a sequence number; forged/replayed/stranger
traffic drops silently; your Veil silences your side completely; a quiet
peer fades to solo after 12 s; dissolve is unilateral; bonds expire in 8 h.

**Over the same bond:**
- **TinCan** (tincan.py) — silent gesture pings: taps play as light pulses at
  the partner's bearing. ≤5 pulses, one ping per 4 s, veil-gated.
- **Crossing** (crossing.py) — shared future ghosts where both rhythms
  already meet. Only salted place-hashes cross (salt = bond key, unlinkable
  across bonds); each side intersects locally; the shared ghost renders
  through Premonition's kind-6 path on both horizons.
- **Duet Rehearsal** (duet.py) — two performers, one figment: both wearers'
  beats land in one trace, either corrects any beat, both keep separately
  signed copies with independent revocation.
- **Weather Gift** (gift.py) — hand a WeatherLedger moment across: their sky
  plays your morning for 30 s, verbatim palette history.

Device: CONFLUENCE + TINCAN BLE types (lockstep with entangle.py/tincan.py);
dream_renderer draws the peer half-band + seam ticks and the ping pulse
train. Demo: `python scripts/run_demo_confluence.py` — the full dinner arc.
Tests: `src/dreamlayer/tests/test_confluence.py` (33).
