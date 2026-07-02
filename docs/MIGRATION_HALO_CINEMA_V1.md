# Migration — Halo Cinema v1

One-page changelog of every removed and added public symbol. Ships as one
atomic PR; nothing here requires data migration. Renderer public API
(`bind` / `show_card` / `dismiss` / `tick`) is unchanged.

## Removed

| Symbol | Where | Replacement |
|---|---|---|
| `palette.ghost_white` (`0x08FFFFFF` pseudo-ARGB) | `halo-lua/display/palette.lua` | ghost tier: `palette.reserve_dynamic("ghost_text", …)` + `materials.draw_ghost_text` |
| ENTER uniform scale (0.94→1) behavior | `display/renderer.lua` | Iris Bloom (S1); `A.ENTER_SCALE_FROM/TO` remain as deprecated constants |
| EXIT text shrink-to-zero | `display/renderer.lua` | `transitions.exit_contract` (text cuts at t=0.4) |
| DeviationAlert arc-step fake alpha ripple | `display/renderer.lua` | fx-slot luma dim ripple |
| `MicReactor` band→color mapping (`_BASS_BANDS` … `_AIR_BANDS`, single-tick colors) | `app/dream/mic_reactor.py` | two-band palette weather (`_LOW_BANDS`/`_HIGH_BANDS`, sky/energy axes) — wire format unchanged |
| stale test API `ActionUnits`/`ProsodyFeatures`/`LinguisticFeatures` (import-crashed) | `tests/test_truth_lens_narrative.py` | rewritten against shipped `AUFrame`/`ProsodyFrame`/`LinguisticFrame` |

## Added — Lua (halo-lua/)

| Symbol | Where |
|---|---|
| `easing.out_expo`, `easing.in_out_cubic`, `easing.out_back`, `easing.perlin1d` | `lib/easing.lua` |
| `A.SIG_*` timing constants (iris/ghostwake/prism/halo/ripple/comet/chime/chord/rumble), `A.DISMISS_MS.TruthLensCard` | `display/animations.lua` |
| `palette.reserve_dynamic`, `.dynamic_slot`, `.dynamic_color`, `.shift_dynamic`, `.set_dynamic_y`, `.restore`, `.restore_all`, `.reserved_names`, `.hex_to_ycbcr` | `display/palette.lua` |
| `materials.AIR/GHOST/SOLID`, `.init`, `.draw_ghost_text`, `.dither_fill`, `.DITHER_25/50`, `.tier_of` | `display/materials.lua` (new file) |
| `transitions.*` — six signatures + acoustics + `exit_contract`, `set_reduce_motion`, `enter_duration`, `comet_entry_angle` | `display/transitions.lua` (new file) |
| `TruthLensCard` draw (9-ring gauge), `SIGNATURES` routing table | `display/renderer.lua` |
| PersonContextCard v2 fields: `why`, `has_avatar` | `display/renderer.lua` |
| `dream_renderer.on_line_field`, `.draw_synesthesia_v2`; Ghost-Wake world anchors | `display/dream_renderer.lua` |
| `layout.assert_safe`, `layout.SAFE_INSET_RADIUS`, `layout.DEBUG` | `display/layout.lua` |
| `MT.PALETTE/GEOMETRY/LINE_FIELD/SPRITE/SPRITE_AVATAR/DREAM_ENTER/DREAM_EXIT` | `ble/message_types.lua` |
| `line_field` + `sprite_avatar` dispatch; sprite `x`/`y` anchoring | `ble/host_comm_dream.lua` |

## Added — Python (host-python/)

| Symbol | Where |
|---|---|
| `BridgeBase.send_raw` (abstract), `RAW_FRAME_TYPES`, `PAUSE_ALLOWED_RAW` | `bridge/base.py` |
| `EmulatorBridge.send_raw`, `.raw_frames`, `.dream_active` | `bridge/emulator_bridge.py` |
| `RealBridge.send_raw` (public, pause-gated) | `bridge/real_bridge.py` |
| `PlaceReactor` (`app/dream/place_reactor.py`, exported from `app.dream`) | new file |
| `ImuReactor.line_field` | `app/dream/imu_reactor.py` |
| `SceneDescriber.last_sprite`, `GesturalSprite`, `sprite_from_phrase` | `app/dream/scene_describer.py` |
| `render_gesture`, `GESTURE_SIZE`; `SpriteBridge.queue_image(x, y, msg_type)` | `app/dream/sprite_bridge.py` |
| `TruthLensResult.gauge_stages`, `.to_gauge_card`, `GAUGE_STAGES`; prosody/linguistic baseline means in `ContactBaseline.update` | `truth_lens/schema.py` |
| `TruthLensRenderer.render(origin=…)` → TruthLensCard gauge | `truth_lens/renderer.py` |
| `AvatarCache`, `why_this_person`, `build_person_context_card`, `AVATAR_SIZE`, `WHY_WINDOW_DAYS` | `social_lens/renderer.py` |
| `cards.truth_gauge_card`, `cards.synesthesia_card_v2` (+ `truth_gauge`, `person_context_v2`, `synesthesia_v2` samples) | `hud/cards.py` |
| `CardRenderer._truth_gauge/_world_anchor/_synesthesia`; RGB-canvas alpha fix | `hud/renderer.py` |
| `themes.DYNAMIC_SLOTS` | `hud/themes.py` |

## Added — phone-app/

| Symbol | Where |
|---|---|
| `signatures`, `SignatureName` | `src/ui/theme/motion.ts` |
| `haloPalette`, `HaloColorToken` | `src/ui/theme/colors.ts` |
| `CardPreview`, `HaloCard` | `src/ui/components/CardPreview.tsx` (new) |
| `DreamCanvas`, `DreamTick` | `src/ui/components/DreamCanvas.tsx` (new) |
| dependency `react-native-svg` | `package.json` (PROPOSED_DEPENDENCY, see design doc) |

## Behavior changes to be aware of

- `TruthLensRenderer.render` now returns a `TruthLensCard` gauge payload;
  the flat `TruthLensCard` is still available via `TruthLensResult.to_hud_card()`.
- `MicReactor` still emits `{t:"palette", colors:[4], duration_ms:2000}`;
  only the color *model* changed. `drift_b` (slot 4) may be overridden by
  `PlaceReactor` while a place bias is ramping.
- `RealBridge`/`EmulatorBridge` now gate raw frames while privacy-paused
  (only `dream_enter`/`dream_exit` pass).
- Golden PNGs under `assets/hud/samples/` are now committed (previously
  gitignored) and CI can diff against them.
- `LinguisticFrame.deception_score` weighting corrected (calm speech no
  longer scores 0.43); downstream fusion thresholds unchanged.
- Pillow `CardRenderer` now genuinely alpha-blends (RGB canvas); any
  screenshots captured before this PR will differ from new renders.
