# Meridian Solid — every settled frame worth a screenshot

## The claim

Lumen made the light move; Solid makes the still frame rich. The founder
test for this pass was blunt: "from my end the screenshots don't look
that much different." All of Lumen's quality is temporal — springs,
flowing palette light, parallax — and the settled poses were
deliberately kept near-identical. Solid is the static half: real
typographic hierarchy, translucent material, gradient light, and
recomposed hero cards, all within the same call budget and the same
information-bearing discipline. A regression to the austere look now
breaks CI (the richness floors below).

## The three levers (all verified in code before design)

1. **Real font sizes.** `frame.display.set_font(fid, sz, sc)` existed in
   the adapter the whole time and was wired nowhere — every string on
   the glasses rendered at one size while the Python mirror pretended
   there were five. `typography.DEVICE_FONT` is now THE hardware seam
   (one table to recalibrate on glass); `primitives.set_font_size` is
   cached per size and pcall-latched — firmware without set_font
   degrades the whole feature to single-size text by flipping one
   boolean. `fit_size(text, width, ladder)` drops long hero strings to
   xl/lg instead of clipping the circular panel. The old `AVG_W` table
   equated font px with glyph advance (~2× too wide);
   `test_typography_metrics.py` pins the corrected advances to the
   reference face within ±2px.
2. **Cheap translucency.** Row-gap scanline fills: one `line` call per
   ROW. A r=62 glass disc at 3px gap = 41 calls; per-pixel dithering
   would be thousands and stays banned for areas. This is not the
   rejected set_pixel/moiré item from lumen.md: cost is per-row, and it
   is static, not temporal.
3. **Free static gradients.** Strokes whose segment color walks a token
   ramp — identical call count to a plain stroke.

## Materials API (`display/materials.lua`, twins in `hud/renderer.py`)

| Function | Cost | Notes |
|---|---|---|
| `glass_disc(cx,cy,r,color,gap)` | ⌊2r/gap⌋ lines (r62/g3 = 41) | circular clip, 2px inset, default `PANE` |
| `glass_capsule(x,y,w,h,color,gap)` | ≈h/gap lines | rounded-end inset |
| `grad_line(...,ramp)` | #ramp lines | |
| `grad_arc(...,ramp,steps)` | steps lines | == plain arc |
| `grad_bezier(...,ramp,steps)` | steps lines | continuous — the ramp replaces the 7/12 dash fake-alpha |
| `bloom_ring(cx,cy,r,color)` | 2 circles | dim twin at r+2, border at r+5 |

Ramps: `RAMP_MEMORY`, `RAMP_MEMORY_LIVE` (band bases first — the Lumen
conduct wave still flows on the bright half), `RAMP_SUCCESS`. New tokens
(`palette.lua`/`themes.py`): `accent_memory_static 0x2CC79B` (the fx
slot's base is `accent_memory` — static ramps must never use it, or the
geometry would follow live slot luma; same for `text_ghost`), plus
success/attention/amber dim twins. The alias-guard test asserts no new
hex equals any reserved dynamic base and no ramp contains one.

Rules: panes only in surface-luma colors (additive display — richer,
not brighter); panes and fills draw only when `exit_t == 0` (bounds the
crossfade worst frame and makes recession read as "the light files
first"); text never in pane color; privacy-class cards get no pane.

## The recompositions

- **ObjectRecall v3 — a spatial scene.** The place is a translucent
  field; the object is a layered diamond jewel with orbit arcs and
  bloom; the wearer is a dot at the bottom; a continuous gradient trace
  (dim at you, bright at the jewel) connects the two. Place name in hero
  type. The card *shows* where the thing is instead of listing rows.
- **SavedMemory v2 — a jewel.** Giant double-struck check inside
  concentric gradient rings over a soft pane; SAVED in hero type. The
  Lumen spring draw-on, chime, and burst contracts are untouched.
- **TruthLens — the verdict weighs what it claims.** Hero-class verdict
  in a glass capsule with a rounded outline; the thread gains *recency*:
  only the newest revealed stage is bright, older testimony cools to its
  dim twin — temporal order becomes a visible bit, direction hue is
  preserved.
- **PersonContext — a centerpiece.** Avatar ring with bloom under an
  enlarged crown over a pane; name in hero/xl; gradient separator; the
  one-why-line spec and chord arpeggio kept.
- **Material pass on the rest**: the live chain link glows from within
  (capsule fill) with gradient connectors; ReadyCard's inner ring is a
  gradient stroke; drift/scrub/deviation/proactive/loading information
  dots get bloom halos. The Horizon is identity and stays untouched
  except one bloom dot at the heartbeat tip.

## Budgets (measured by test_draw_budget.py, not estimated)

Worst composited frames — idle aurora, ObjectRecall/SavedMemory/
PersonContext holds, testimony all-9-stages, the ObjectRecall→Saved
crossfade, prism at max intensity — all measured ≤ `DRAW_CALLS_MAX =
420` (unchanged from Lumen). Font switches ≤ 32/tick (`font_calls`,
counted separately from draw calls, like palette writes).

## Richness floors (test_meridian_solid.py)

Regenerated goldens/samples must exceed the pre-Solid lit-pixel
baselines by ≥1.25×: `focus/hold_conf090` 3487→>4358,
`testimony/elevated_mixed` 1317→>1646, samples `object_recall`
3261→>4076, `saved_memory` 1436→>1795, `person_context` 1750→>2187.
"The screenshots don't look different" is now a CI failure.

## reduce_motion contracts

The settled composite is not pixel-identical across the flag — the
notch heartbeat freezes and reduce deliberately draws a static origin
tick in place of the travel motion. The two honest assertions, both
tested per recomposed card: under reduce_motion NOTHING moves (settled
frames at different times are pixel-identical), and the Solid materials
survive it (panes/gradients/blooms are static richness, not motion —
the reduce frame keeps ≥80% of the full frame's light).

## Device-day risks

1. **DEVICE_FONT calibration** — fid/sz/sc are one table; if firmware's
   set_font maps differently only the table changes; if it's absent the
   pcall latch reverts to single-size text with no other code path.
2. **PANE luma vs daylight** — `surface 0x0E1416` may be sub-visible
   outdoors on the additive panel; it is one token, tunable on glass
   (the same class as the aurora amplitude risk in lumen.md).
3. **Draw-color→slot resolution** — Solid leans on the same convention
   dream weather has always used; the band/twin hexes are single-LSB
   adjustable if real firmware matches static palette entries first.

## Revision log

- 2026-07-03 — Initial Solid pass (typography, materials, five
  recompositions, material pass, richness/stillness contracts).
- 2026-07-03 — O3 conversation cards (FactCheck / AnswerAhead /
  OracleReply / Hark) brought onto the device: renderer.lua draw fns with
  the material bed (glass pane, gradient separators, bloomed status cue),
  hero-class wrapped type, dim-twin secondary; Lumen spring-in + a
  reduce-gated idle breathe on the Listen!/verdict ring. Routed through
  cards.lua constructors, state_machine, the URGENT/CONTEXT queue, and
  diagnostics. test_o3_cards_device.py drives them through the raster
  harness (budget, richness, reduce-motion stillness, the breathe). These
  four were Python-only before; new HUD cards are device-Lua-first from
  here.
- 2026-07-03 — O3 cards standards pass (review of #86): verdict/tone
  mapping moved into renderer.lua `card_tone`/`FACT_COLOR` — the BLE
  path never runs the cards.lua constructors, so constructor-set colors
  were lost and every wire-delivered FactCheck cue rendered ghost-gray
  (now pinned by BLE-path tone tests that build payloads with the HOST
  constructors); `text_ghost_static 0x58686D` for drawn ghost accents
  (the unverified cue was on the ghost_text slot base and ramped with
  landing luma); breathe/pulse timings and block line pitch moved to
  their owners (animations.lua / typography.BLOCK_H); mirror parity for
  the unverified hue; the four settled holds joined the deterministic
  golden contract; AnswerAhead's cue dot nudged clear of its eyebrow.
- 2026-07-05 — World lenses standards pass (review of #106/#108/#116):
  Scholar / GlanceChoice / Taste shipped as Python-mirror-only — on the
  BLE path `composite()` found no draw fn and rendered NOTHING (the
  black-disc failure class the O3 pass already closed once; the
  device-Lua-first policy above was violated twice in two waves). Now on
  the device: `draw_scholar` / `draw_taste` share a World-lens bed (pane,
  bloomed cue, gradient separator, hero type, dim-twin rows, honest
  ghost "connect a Brain" state); `draw_glance_choice` is a
  circular-native radial chooser — up to three option nodes on an upper
  arc that spring in staggered, labels inside the ring (the docstring
  promised "around the ring"; the mirror had drawn a text line). Routed
  through cards.lua pass-through constructors, state_machine, the URGENT
  queue, DISMISS_MS, and diagnostics; `GLANCE_NODE_R`/`_STAGGER_MS` in
  animations.lua (+ motion_math parity). The mirror `_scholar` catch-all
  split into three parity renderers (dead `RAMP if not x else RAMP`
  conditional removed; `TEXT_GHOST_STATIC` for the ghost state).
  **The enforcement, not just the doc:** `test_world_cards_device.py`
  drives all three through the raster harness AND builds payloads with
  the HOST constructors to assert content reaches pixels — the exact
  test class that would have caught the black frame at commit time. Four
  settled holds joined the deterministic golden contract. (Separate
  finding, out of this scope: Message #41, Here/Upcoming #45, Dossier/
  SpokenCaption #53, MorningBrief #61, Listening #62 are also
  device-Lua-less — long-standing, pre-overhaul; flagged for a later
  pass.)
- 2026-07-06 — The missing frames + the structural safety net. The
  audit behind the World-lens note turned out to understate it: **22**
  glass-bound card types had no device draw fn and rendered a black
  frame on the real BLE path (`composite()`'s `if not fn then return
  end`). Seven were product-designed HUD cards — Message, Upcoming,
  Here, PersonDossier, SpokenCaption, MorningBrief, Listening — each now
  has a bespoke Solid renderer (`draw_message`/`draw_upcoming`/…) on the
  shared World-lens bed; ListeningCard gets a Lumen wake-ring breathe
  (distinct from the capture waveform); UpcomingCard warms to amber
  inside 5 min; Message/Here/Upcoming finally surface the `headline`
  hero field the mirror `_generic_rows` had been dropping. Wired through
  cards.lua / state_machine / DISMISS_MS / CARD_PRIORITY / diagnostics /
  motion_math parity, with bespoke mirror methods for all seven.
  **The systemic fix:** `composite()` no longer returns on an unmapped
  type — it falls back to `draw_layout_card` when the card carries a
  `layout`, else a minimal titled Solid card. And `draw_layout_card`
  itself now draws the glass bed + gradient separator (privacy-class
  cards, which carry a shield/lock glyph, stay pane-free per the Solid
  rule). Net effect: every current and future unmapped card renders
  something legible, and the whole layout-driven family — the four
  existing cards plus the safety-net-routed lens tail — is lifted to
  Solid standard in one change. `test_missing_cards_device.py` covers
  the seven (budget / richness / stillness / listening breathe), the
  BLE-path host-payload-reaches-pixels class, and two safety-net tests
  (an unknown type is never black; a layout-carrying unknown uses the
  layout renderer). Seven settled holds joined the deterministic golden
  contract. Full suite 1701 passing.
  **Remaining lens tail (covered by the safety net, bespoke deferred):**
  Waypath, SocialLens, Provenance, Consistency, Answer, ObjectPanel,
  Quest/QuestReward, Reaction, IntroOffer/IntroKept, LucidRecall each
  carry a `layout` and now render on the Solid layout bed via the safety
  net — legible and material, not black. Genuine heroes worth a bespoke
  pass later: Waypath (a direction dial + distance), SocialLens (a
  person centerpiece), Quest/Reward (an XP/rank moment). BeaconCard /
  FaceSynthCard / WidgetCard were not confirmed bridged to glass (no
  send_card site found) — likely phone/panel surfaces; the safety net
  catches them regardless if they ever are sent.
