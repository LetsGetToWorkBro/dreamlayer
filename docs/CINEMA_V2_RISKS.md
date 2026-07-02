# Cinema v2 — Risks & Self-Critique

Arguing against Meridian before it ships. The three most likely
real-hardware failures with the emulator test that would catch each and
the device fallback for each; the harness fidelity gaps, named; and the
aesthetic calls that need the founder's eye on real glass.

## 1. Ghost-tier legibility on the real additive display

**Failure mode.** The whole horizon lives at Ghost/Air tier by design —
1px `border_subtle` track, 3–9px ticks in dim teal. The raster harness
renders sRGB on black; the real microOLED is additive through a lens in
uncontrolled ambient light. If the dim tier lands below perceptual
threshold outdoors, Meridian's resting state degrades to "a breathing
notch and two amber dots" — still honest, but the day disappears and
with it the thesis.

**Emulator test that would catch it.** None — this is exactly the class
of failure no software test can see, which is why it is risk #1. The
closest proxy: a luminance-histogram assertion on the goldens (min
contrast ratio between mark tiers and background under a modeled
transfer curve), calibrated once against the real panel. The
calibration constant does not exist yet; the assertion lands with the
first device session.

**Device fallback.** Every mark color is a palette token and every
length a `MER_*` constant — a "daylight" token table (one file,
`palette.lua`) can raise the whole ghost tier without touching logic.
The notch and promise amber (full-tier tokens) survive worst-case, so
the instrument's two most safety-relevant readings (system alive,
something owed) never degrade first.

## 2. Horizon frame starvation during sprite/dream congestion

**Failure mode.** v1's risk register documented sprite head-of-line
blocking starving the 2Hz palette tick. Meridian adds a third ambient
stream (~600B per 5s). Under a congested link with a Synesthesia sprite
mid-transfer, horizon frames queue behind ~4KB of chunks; the day goes
stale exactly when the display is busiest, and the wearer sees a rich
dream over a wrongly-dim rim.

**Emulator test that would catch it.** The same simulated-latency
`send_raw` harness v1 proposed and never built (240B per 30ms connection
event): script a dream session with one sprite + palette ticks + horizon
cadence and assert no horizon gap exceeds 2 × `HORIZON_CADENCE_S`.
Deliberately not built in this PR — it belongs with the BLE priority
queue work, and building the assertion without the queue just documents
a known failure.

**Device fallback.** Shipped: the staleness rule is the graceful path
(marks drop one tier at 30s — visibly stale, never wrong), full-state
frames mean one delivery fully heals, and the seq guard makes reordering
harmless. The failure degrades to "the rim is conservative for a few
seconds," not to a lie.

## 3. The focus ring and the track are 8px apart

**Failure mode.** The hold ring (r=92) and the rim track (r=100) are
both thin arcs. On glass, optical bloom at eyewear focus depth could
merge them into one smeared ring, costing both readings at once — the
card's confidence and the day's reference line.

**Emulator test that would catch it.** A bloom-kernel pass over the
goldens (2px Gaussian, the classic cheap model of panel bloom) asserting
the two arcs remain separable maxima along a radial slice. Cheap to
build; deferred until one real-glass photo calibrates the kernel —
an uncalibrated blur test proves nothing either way.

**Device fallback.** `SIG_FOCUS_RING_R` is one constant; dropping it to
88 or 84 is a no-logic change, and the layering rule (content < ring <
horizon) holds down to r=80 for every shipped card layout.

## Known harness fidelity gaps (stated, bounded)

- **Base-hex conflation:** the raster resolves any draw whose color
  equals a dynamic slot's base hex to the slot's *live* color. Affects
  exactly one committed golden family (dream particles, drawn in the
  static `accent_memory` token, show storm-shifted). Direction of error
  is overstated drama — the safe direction. On-device behavior differs
  only when a slot is chroma-shifted *and* a static-token element shares
  its base hex; the audit found one such pair (particles/energy).
- **Font weight:** PIL's 13px face is heavier than the device glyphs.
  Conservative: text that survives the harness survives the panel.
- **No additive blending:** the harness paints opaque; the panel adds
  light. Overlaps read slightly brighter on device — accounted for by
  the layering rule keeping information-bearing strokes non-overlapping.

## The aesthetic calls that need the founder's eye

1. **The seam.** Empty bottom arc as deliberate negative space — on the
   phone mirror it reads as design; on glass it might read as a dead
   zone. Pre-planned cheap response if it fails the wear test: 1px
   boundary ticks at the caps (see `CINEMA_V2_ATTACKS.md`, horizon
   misread #4).
2. **The dial period.** 12 hours was chosen so "this morning" is
   readable at lunch. A 6h dial doubles angular resolution (busy days
   read better) at the cost of the morning falling off by mid-afternoon.
   The constant is `MER_DEG_PER_HOUR`; the wear test decides.
3. **Recession speed.** 160ms was tuned in stills; on glass, content
   flying toward the rim in peripheral vision might read as "something
   escaped" rather than "filed." If so, `SIG_RECEDE_MS` up to ~240 and
   the head fades rather than flies. One constant, one function.
4. **The retired violet.** `confidence_high` is now `0xB8FFE9`. This
   recolors every high-confidence artifact — deliberate, argued in the
   golden review, and trivially reversible if the founder disagrees
   (one token in three files, and the goldens regenerate in one
   command).
