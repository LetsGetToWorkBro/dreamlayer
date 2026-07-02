# Halo Cinema v1 — Risks & Self-Critique

Arguing against the implementation before it ships. Three most likely
real-hardware failures, an emulator test that would have caught each, a
device fallback for each — and one aesthetic call that needs the
founder's eye.

## 1. Palette-slot contention between host frames and on-device animation

**Failure mode.** Both sides now write `assign_color_ycbcr` on the
dynamic bank: the host streams palette-weather frames at 2 Hz
(slots 1–4) while the device animates ghost fades, prism fringes and the
fx pulse (slots 3–6) at up to 20 fps. The slot map keeps them disjoint
*by mode* (drift slots are prism fringes only during card crossfades,
which can't happen in dream mode) — but the transition *between* modes is
the hole: a `dream_exit` arriving mid-crossfade, or a palette frame that
was already in the BLE queue when the card UI resumed, will repaint a
fringe slot mid-signature. On glass this looks like a one-frame color
glitch exactly during the most visible moment (a card transition).

**Emulator test that would catch it.** Extend `EmulatorBridge` to keep a
16-entry virtual palette and replay a recorded frame log: script
`dream_enter → palette×N → dream_exit → show_card → show_card`
(crossfade) with adversarial interleaving, and assert that no slot
receives writes from both "owners" within one 50ms window. This is pure
bookkeeping and would have flagged the transition hole immediately.

**Device fallback.** On `dream_exit`, the Lua side calls
`palette.restore_all()` before the card UI resumes (cheap, already
implemented for individual signatures), and `host_comm_dream` drops any
`palette`/`line_field` frame that arrives while `dream_active` is false
— making stale queued frames harmless.

## 2. BLE stalls starving the 2 Hz dream tick (sprite head-of-line blocking)

**Failure mode.** A SynesthesiaCard v2 tick sends a card (~300 B), a
~4 KB gesture sprite (17+ MTU chunks with ACK flow control), *and* the
regular palette + line_field frames. On a congested link the sprite
transfer can take >500 ms, head-of-line blocking the next palette tick —
the ambient weather visibly freezes, which reads as a crash in an
"always alive" mode. The emulator can't see this because its
`send_raw` is instantaneous.

**Emulator test that would catch it.** Give `EmulatorBridge.send_raw` a
simulated per-byte latency budget (240 B per 30 ms connection event) and
assert that across a scripted 10 s dream session no gap between
consecutive `palette` frames exceeds 750 ms. The test would fail today
whenever a sprite lands.

**Device fallback.** Priority queue in the bridge: palette/line_field
frames preempt sprite chunks (sprites are already tolerant of arriving a
scene late); drop — never queue — a palette frame if a newer one exists.
The Lua renderer already interpolates between palette targets, so a
skipped frame degrades to a slower fade, not a freeze.

## 3. Per-character Ghost Wake and dither cost at 20 fps on the Lua VM

**Failure mode.** Ghost Wake draws each character with two `perlin1d`
calls and a `frame.display.text` per glyph; a 22-char anchor is ~22 text
calls per frame on top of the 12-vector field and 24 particles. The
emulator's Lua runs on a desktop CPU; the device VM is an order of
magnitude slower and `frame.display.text` has per-call BLE/driver
overhead. Worst case the dream frame drops under 10 fps and the
"condensation" reads as stutter — worse than no animation.

**Emulator test that would catch it.** Instruction-budget test via lupa:
run one full dream frame + Ghost Wake tick under `debug.sethook` counting
VM instructions, and fail above a budget calibrated once against real
hardware (e.g. 50k instructions/frame). Catches regressions without
needing the device in CI.

**Device fallback.** Ghost Wake already degrades cleanly: cap jittered
rendering to the first 320 ms (after settle it's one text call per line),
and under measured frame-time pressure drop to the `reduce_motion`
variant automatically — the information (the echo text) is preserved by
contract §1.4.

## The aesthetic call I'm not confident about

**The Confidence Halo on recall cards.** Radius *and* sweep both encode
confidence (24–64 px, 0–360°), drawn under the card content once per
3.2 s orbit. My worry: on the real additive display, a moving 1 px arc
*behind* text may read as flicker near the fovea rather than as a calm
orbit — and at conf ≈ 0.5 the half-halo can look like a rendering bug
("why is the ring broken?") instead of an honest half-confidence signal.
The alternative is anchoring the halo to the rim (fixed r=104, sweep-only
encoding), which is calmer but weakens the "size = certainty" pre-reading.
I shipped the spec'd version; this is the one signature I'd want the
founder to wear on glass before it's locked. Related smaller taste
question: `confidence_high = 0xAA00FF` (violet) predates this pass and
reads off-family next to the teal system — flagged during the vision
review (`HALO_CINEMA_V1_REVIEW.md`, object_recall) but deliberately not
changed unilaterally since it recolors every high-confidence artifact.
