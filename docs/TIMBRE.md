# Timbre — see who's speaking before you turn around

Every contact has a visual timbre: a 12-point waveform derived one-way from
their prosody baseline (the per-contact voice statistics the Truth Lens
narrative store already learns — pitch, jitter, shimmer, cadence seed three
harmonics; sampled, quantized 1..15). The same person always draws the same
shape; different voices draw visibly different shapes; the shape cannot be
inverted back to a voice.

In Dream Mode, when a known voice enters the room, TimbreReactor sends
`{t:"timbre", known:1, side_dd, points}` and the shape glows at the rim on
the side the sound came from (teal, 2.5 s TTL). Strangers render as gray
static — random noise derived from nothing about them: presence without
identity, honoring the no-stranger-ID contract. Rate-limited to one frame
per 2 s per speaker; fully silenced by the Privacy Veil.

Lockstep: `TIMBRE` in message_types.lua ↔ `MSG_TIMBRE` in timbre_reactor.py.
Tests: `src/dreamlayer/tests/test_timbre.py` (16, incl. the Lua renderer).
