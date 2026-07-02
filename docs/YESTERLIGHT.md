# Yesterlight — walk through the past, in place

Roll your head deliberately back (held ≥1.5 s past the enter threshold) and
the Horizon dials back in time at this place: the palette weather replays the
room's *actual recorded ambience* (WeatherLedger snapshots the exact colors
MicReactor shipped, ≤1 per 5 s, keyed by place signature), a detached still
notch in the paused hue marks the visited hour on the same dial law the day's
marks use (30°/h, elder door at +58°), and any memory anchor living within
±10 min of that hour glows at its mark via the provenance highlight. Deeper
tilt scrubs further back (240 min/rad, capped at the dial's 5 h); returning
your head, changing place, or 120 s releases the present with a single
`{t:"yesterlight", active:0}`.

Privacy: the ledger honors the Veil — nothing records while paused; replay of
lawfully recorded weather stays available. New BLE type `yesterlight`
(message_types.lua ↔ dream_mode/yesterlight.py, lockstep).

Tests: `src/dreamlayer/tests/test_yesterlight.py` (19, incl. the Lua plotter).
