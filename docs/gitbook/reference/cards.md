# Reference — the card catalog

Every card constructor in `host-python/src/dreamlayer/hud/cards.py`, plus
the cards other modules construct. "Renderer" says where it draws today:
**device** (`halo-lua/display/renderer.lua`, 33 bespoke types plus a never-black layout/titled fallback), **dream** (the
device's dream path), **mirror** (the Python mirror / phone only), or
**payload** (no glass renderer yet). Dismiss is milliseconds (0 = sticky).
Full visual treatment per card: [the gallery](../hud-cards.md).

| Card | Emitted by | Renderer | Dismiss | Sound / touch |
|---|---|---|---|---|
| ReadyCard | boot, resume, connect | device | — | — |
| SavedMemoryCard | scene/conversation kept, nod-to-save | device | 1200 | chime visual, burst |
| QueryListeningCard | single click / ask | device | on result | live amp waveform |
| ListeningCard | Oracle wake (any source) | device | 0 | earcon `wake`, haptic tick |
| LoadingCard | a tier thinking | device | on result | — |
| OracleReplyCard | Oracle answer/action | device | 6000 | — |
| ObjectRecallCard | object recall | device | 3500 | conduct flair |
| CommitmentRecallCard | commitment recall / capture | device | 4000 | — |
| CommitmentDriftCard | `tick_drift` slippage | device | 4500 | — |
| ProactiveMemoryCard | arriving at a memory place | device | 3500 | — |
| PersonContextCard | person cue (anticipation) | device | 3500 | chord arpeggio |
| PersonDossierCard | greet / look at a known person | device | 5000 | earcon `look` |
| SpokenCaptionCard | each caption line | device | rolling | — |
| LiveCaptionCard | Puente / Rosetta translation | device | rolling | — |
| MorningBriefCard | wake with a brief waiting | device | 8000 | — |
| FactCheckCard | Veritas verdict | device | 7000 | chime / hark / hark_urgent by verdict; double haptic + flash on flags |
| AnswerAheadCard | copilot pre-answer | device | 8000 | **silent**; tick haptic |
| HarkCard | attention policy | device | 6500 (9000 urgent) | `hark` / `hark_urgent`; tick / double; flash urgent |
| TruthLensCard (testimony/gauge) | delivery read | device | — | — |
| DeviationAlertCard | tell_check contradiction | device | 5000 | — |
| TimeScrubNodeCard | rewind scrub | device | 0 | — |
| PrivacyVeilCard | the veil lands | device | 0 | rumble + slam |
| ForgetLastCard | "forget that" | device | 0 | slam class |
| PrivateZoneCard | entering a private zone | device | 0 | slam class |
| ConsentRequiredCard | a source needs consent | device | 0 | slam class |
| ErrorCard | failures worth surfacing | device | 4000 | — |
| LowConfidenceCard | recall below threshold | device | 3000 | — |
| WorldAnchorCard | Ghost Layer echo | dream | 8000 | — |
| SynesthesiaCard (v1/v2) | Dream Mode sense read | dream | 4000 | — |
| PaletteShiftCard | mood tint | consumed as a palette command | 0 | — |
| UpcomingCard | event cue ("leave in 8 min") | device (warms to amber inside 5 min) | 6000 | — |
| HereCard | place cue ("your bike is here") | device | 5000 | — |
| MessageCard | message pop-up | device | 6000 | — |

From other modules:

| Card | Module | Purpose |
|---|---|---|
| ScholarCard | `hud/cards.py: scholar` | answer / form help / plain words (device; dismiss 9000) — [chapter](../world-lenses.md) |
| GlanceChoiceCard | `hud/cards.py: glance_choice` | the arbiter's one-tap chooser, up to 3 options (device, circular-native; dismiss 6000) |
| TasteCard | `hud/cards.py: taste` | the shelf/menu pick with reasons; vetoed items flagged, never dropped (device; dismiss 9000) |
| BeaconCard | `confluence/beacon.py` | your GhostMode circle by bearing and band ("Maya - close, ahead-left") |
| ReactionCard / FillerCard / AirDrumCard / FaceSynthCard | registry plugins | plugin-registered renderers via `add_card_renderer` |
| QuestCard / QuestRewardCard | `orchestrator/quest.py` | quests and QUEST COMPLETE / LEVEL UP / RANK UP rewards |
| SocialLensCard | `social_lens/` | identity match result |
| IntroKeptCard | `social_lens/introduction.py` | a self-introduction, kept automatically |
| IntroOfferCard | `social_lens/introduction.py` | the consent-flow name offer (auto_keep=False) |
| ConsistencyCard | Candor | self-consistency flags |
| Provenance / Waypath panels | their lenses | belief origins; bearing to your things |
| AnswerCard | inline in `ask_brain` | brain answers with tier attribution |

Notes for implementers: cards are plain dicts — the BLE path delivers them
straight to the device dispatch table, which is why verdict tone for the
conversation cards is resolved in the renderer (`card_tone` / `FACT_COLOR`)
rather than trusted from the constructor. The sample payloads used for every
image in this book live in `cards.py: ALL_SAMPLES` (31 keys), and
`hud/golden_images.py` renders any of them with
`generate_golden(card_key, golden_dir)`.
