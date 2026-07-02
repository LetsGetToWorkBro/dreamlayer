# REM — the glasses literally dream

At night, on the charger, DreamLayer runs a sleep cycle (`dreamlayer.rem`):
the day's events replay *recombined* — anchors from different hours collide
and the DreamPoet weaves each pair into one phrase whose every content word
traces to a real memory ("the gym remembers level"). The dreaming is
functional: each appearance in a dream is a vote to remember (+0.10, capped
±0.5); undreamed events at or below the day's median salience are let go
(−0.20). Deltas land in the RetrievalBias store (`rem_bias.json`), which
retrieval ranking and the Horizon composer both read — dreamed memories wake
up one luma tier brighter, and dreamed promises survive the 48-mark cap
preferentially.

Deterministic under the night's seed; fully offline; private/veiled events
are excluded at the door (never dreamed, scored, or rendered). Morning reel:
`render_reel()` exports one 256px frame per dream — sources at their true
hours, traces converging on the phrase — plus a consolidation report.

Demo: `python scripts/run_rem_cycle.py` → `out/rem/`.
Tests: `src/dreamlayer/tests/test_rem.py` (18).
