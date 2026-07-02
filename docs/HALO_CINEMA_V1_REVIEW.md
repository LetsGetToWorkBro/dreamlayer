# Halo Cinema v1 — Golden Image Vision Review

Render → inspect → critique → patch loop over the golden images in
`assets/hud/samples/`. Each card below went through **at least three
passes**: the renderer output was regenerated and visually re-inspected
after every patch, and the loop stopped only when no legitimate critique
against the Phase 1 spec (`docs/HALO_CINEMA_V1.md`) remained. All fixes
were mirrored into the Lua renderer so the golden and the device agree.

## Systemic finding (pass 3 → pass 4, affects every card)

Inspecting `commitment_recall.png` showed the third chain link as a
**solid opaque pill** hiding the due-date text, and `loading.png`'s
"ghost" rings rendering at full white. Root cause: `CardRenderer` drew
onto an **RGBA** canvas — Pillow's `"RGBA"` draw mode only alpha-*blends*
on RGB images; on an RGBA base the ink alpha is stored in the alpha
channel and was then discarded by `putalpha(mask)`. **Every `alpha=`
value in the Python renderer had been rendering fully opaque.** Fix:
render on an RGB canvas and convert to RGBA only for the final circular
mask. This single fix restored the intended material tiers (ghost tracks,
dim echoes, subtle blooms) across the entire card library. It is exactly
the class of "material honesty" defect the Air/Ghost/Solid system exists
to catch.

## truth_gauge.png (TruthLensCard, new)

- **Pass 1:** The nine rings at r=20..52 ran straight through the verdict
  word — "ELEVATED" was illegible, which fails the spec's "center of card
  holds the fused verdict" and HUD principle 2 (glanceable in under 2s).
  *Patch:* rings moved outward to r=34..66 (same 4px pitch), leaving a
  clear core; confidence dot moved inside the core.
- **Pass 2:** Legible, but ring strokes still clipped the first and last
  glyphs where the text width exceeded the clear core. *Patch:* black
  backing capsule sized to the verdict text, mirrored on-device with a
  filled `frame.display.rect`.
- **Pass 3:** After the systemic alpha fix, the ghost ring tracks
  (border_subtle @ 44) read as faint orbits — the deceptive-coral fills
  and the single truthful-green face ring are readable pre-consciously,
  which is the design intent. No remaining critique. The insufficient
  narrative ring correctly shows as an empty track: absence of evidence
  is displayed, never hidden.

## person_context_v2.png (PersonContextCard v2, new)

- **Pass 1:** The 12-segment polar ring's bottom segments struck straight
  through the why-line, and the two-line why paragraph collided with the
  detail row. *Patch:* bottom three segments skipped (crown reads as a
  halo over the name), spacing retuned.
- **Pass 2:** The why-line still wrapped to two lines — the spec says
  *one line* of "why this person matters right now". *Patch:* single-line
  "sm" why with ellipsis at 34 chars; headline and met-date demoted to
  ghost-tier rows beneath it.
- **Pass 3:** After the alpha fix the dim crown segments and chord
  arpeggio around the avatar zone sit correctly behind the name.
  Hierarchy is now name → why → context → recency → confidence dot, top
  to bottom. No remaining critique.

## world_anchor.png (WorldAnchorCard)

- **Pass 1:** The detail row at y=230 escaped the circular safe chord —
  at that height the display is only ~46px wide per side and
  "Kitchen • 09:42" clipped at the glass edge. The Lua renderer was worse
  (y=242 is *outside* the 112px safe radius entirely). *Patch:* rows moved
  to 192/208/222 and the summary cap tightened from 32 to 22 chars, in
  both renderers; `layout.assert_safe` added for debug builds.
- **Pass 2:** Truncation dropped text without an ellipsis ("counte").
  *Patch:* proper ellipsizing in the Python mirror (Lua already had it).
- **Pass 3:** Ghost-tier echo sits fully inside the safe area at honest
  ghost luma. No remaining critique.

## synesthesia_v2.png (SynesthesiaCard v2, new)

- **Pass 1:** Composition read correctly on first render: phrase top-half,
  hairline seam, 3-shape gesture bottom-half in the dominant color with
  dim echoes. Critique: the triangle at size 16 was near-subliminal.
  Verified against spec: shape sizes come from the VLM/hash spec
  (8-56 px), so a small accent shape is legitimate variance, not a
  renderer defect. Left as-is.
- **Pass 2:** Checked the preview-vs-device contract: the golden composes
  the gesture in-card while the device streams it as a TxSprite anchored
  at (64,128) — the y×0.75 compression in the golden keeps shapes inside
  the circle where the sprite's lower rows would be clipped by the glass.
  Documented here as an accepted, deliberate divergence (the phone
  CardPreview matches the golden).
- **Pass 3:** Post-alpha-fix re-inspection; dim echoes now genuinely dim.
  No remaining critique.

## object_recall.png (hero card, existing)

- **Pass 1:** The confidence jewel (6px diamond + 10px bloom + r=12
  orbits) swallowed the bezier trace apex — the jewel is meant to sit *on*
  the memory trace, not obliterate it. *Patch:* 4px diamond, tighter
  bloom, r=10 orbits at lower alpha, both renderers.
- **Pass 2:** Bloom still heavy because alpha was rendering opaque
  (systemic finding). After the RGB-canvas fix the bloom is a true 25-alpha
  halo. The dashed trace now shows its intended head-to-tail alpha ramp.
- **Pass 3:** The hero "Kitchen table" ghost-glow double-image is now a
  subtle 40-alpha echo rather than a hard offset copy. No remaining
  critique — though `confidence_high = 0xAA00FF` (violet) reads
  off-palette next to the teal family; flagged in
  `HALO_CINEMA_V1_RISKS.md` as a founder-taste question, not changed
  unilaterally.

## commitment_recall.png / loading.png / ready.png / privacy_veil.png (existing)

- **Pass 1 (commitment):** third chain link rendered as a solid green pill
  with the due text invisible inside it (green-on-green). This was the
  smoking gun for the systemic alpha finding above.
- **Pass 2:** after the fix: the active link shows an 18-alpha wash with
  legible due text; loading's ghost rings and spinner echo trail fall off
  correctly; ready's three arcs now have the specified 68/34/17 depth
  falloff; privacy's breach rings are faint and the shield glyph is the
  single solid focal point (sub-bass analog reads as intended).
- **Pass 3:** re-inspected all four post-fix; no remaining critiques.

## Coverage note

All 24 samples in `ALL_SAMPLES` were regenerated and inspected; the cards
not listed above (saved_memory, query_listening, proactive_memory,
commitment_drift, time_scrub_node, deviation_alert, forget_last,
private_zone, consent_required, live_caption, low_confidence, error,
person_context v1, synesthesia v1, palette_shift) passed inspection after
the systemic alpha fix with no card-specific patches. The goldens are now
committed (previously gitignored) so CI can pixel-diff against them via
`python -m dreamlayer.hud.golden_images --suite --dir assets/hud/samples`.
