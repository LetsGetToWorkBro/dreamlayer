# Inner Weather — you are also a place with a climate

The room's weather paints the rim (mic → palette). Your own weather churns
the core: InnerWeather (dream_mode/inner_weather.py) fuses IMU restlessness
(angular velocity 0.45, micro head-motion 0.25) with your own speech cadence
(rate/hesitation/pause deviation, 0.30) into one state scalar [0..1],
double-EMA smoothed. The slow trend is the storm front: a sustained climb
past the warn threshold fires one early `{t:"event", name:"inner_storm"}` —
the display gets restless minutes before you'd have named the feeling — with
front semantics (saturation never re-warns; a second warning needs calm, the
cooldown, and a genuinely new climb).

Rendering rides the existing geometry type on a dedicated channel:
`{t:"geometry", mode:"churn", intensity:state}` — the renderer stores churn
separately so it never clobbers the IMU's transient rotate/scatter gestures,
and applies it as random-walk agitation to the core particles (still clipped
to r ≤ 96; the rim stays the room's). Interference is emergent: calm wearer
in a loud room = still center, storming rim; agitated wearer in a library =
churning core under a settled sky. Hysteresis-gated (±0.05): a steady mood
costs no radio, an empty context costs none at all. The Privacy Veil
silences the estimator completely.

Tests: `src/dreamlayer/tests/test_inner_weather.py` (14, incl. the renderer
channel isolation under lupa).
