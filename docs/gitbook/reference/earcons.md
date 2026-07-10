# Reference — earcons and haptics

DreamLayer's sound design is small on purpose: five earcon identities, each
with two rotating variants so repetition never grates, plus two haptic
patterns. The map lives host-side in `host-python/src/dreamlayer/hud/audio.py`;
the actual audio files ship in the phone app (`phone-app/assets/sounds/`),
and the phone's sound service applies the same never-repeat-back-to-back
rotation.

## The earcon map

| Earcon id | Means | Variant files | Fired by |
|---|---|---|---|
| `wake` | the Juno woke / greeting | `hey1`, `hey2` | ListeningCard (any wake source) |
| `hark` | "Listen!" | `listen1`, `listen2` | normal harks; self-contradiction and unverified fact-checks |
| `hark_urgent` | "Watch out!" | `watchout1`, `watchout2` | urgent watch-out harks; disputed fact-checks |
| `look` | "look at this" | `look1`, `look2` | person dossier surfacing |
| `chime` | neutral confirmation | `sfx10`, `sfx13` | verified (supported) fact-checks |

Deliberate silence: **AnswerAheadCard carries no earcon** — the copilot must
never interrupt the conversation it is helping with.

Resolution: variants resolve from `<dir>/sounds/<name>.{wav,mp3,m4a,aac,ogg}`;
a missing family falls back to a built-in tone; `watchout` falls back to
`listen` when absent.

## Haptics

Two patterns ride card payloads as string ids:

| Pattern | Feel | Used by |
|---|---|---|
| `tick` | one light tap | wake, normal harks, answer-ahead, supported/unverified fact-checks |
| `double` | two taps | urgent harks, disputed and self-contradiction fact-checks |

The phone's own haptic service adds light / medium / success / warn taps to
its UI interactions.

## Visual acoustics on the device

**Seam:** the glasses' speaker and actuator play the earcons and haptics on
real hardware. The device Lua already draws a matched visual for each sonic
moment (`display/transitions.lua`):

| Visual | Shape | Paired with |
|---|---|---|
| `chime` | a success ring expanding 8 to 28 px over 220 ms | the save moment |
| `chord` | a three-arc arpeggio, 40 ms steps | a person with an avatar |
| `rumble` | a 100 ms full-field palette dim | the instant before the privacy slam |
| `ripple` | a 400 ms expanding ring | testimony entry |

## Wake feedback is per-channel

The three wake feedback channels — the visual ring, the earcon, the haptic —
are independently toggleable (`set_wake_feedback`, or the phone's "Show it's
listening with" group), so the glasses can wake silently, invisibly, or both.

## The phone haptic vocabulary

The glasses have no actuator, so the phone is the haptic body — one
data-driven map (`phone-app/src/services/haptics.ts`, rules pinned by
tests). Grammar: weight × pattern × repetition; every pattern ≤ 400 ms;
L0 ambient never buzzes; lens signatures never reuse system patterns.

| Signal | Pattern | Means |
|---|---|---|
| `confirm` | 1× light | every tap (the universal touch primitive) |
| `action` | 1× medium | weightier actions: pair, send, confirm |
| `success` / `warn` | system notification | pair landed / parse failed |
| `notice` (L1) | 1× light | a message card, a brief ready |
| `attention` (L2) | 2× medium, 120 ms apart | a commitment drifting, someone you owe in view |
| `interrupt` (L3) | heavy + error | "Listen!" — the only signal a caller may re-fire |
| `veil_on` / `veil_off` | descending / ascending 3-beat ramp | going dark / eyes open — unique and directional |
| `commitment_crack` | 2× heavy, slow | something broke |
| `commitment_bloom` | 3× light ascending | something healed |
| `truth_flag` | sharp – pause – sharp | Veritas flagged a claim (see leakage below) |
| `figment_deployed` | medium + success | a rehearsed behavior went live |
| `answer_ahead` | *silence* | by design — the copilot never announces itself |
| TinCan | the sender's actual tap rhythm, replayed | the message *is* the pattern |

## Leakage classification (bone conduction is quiet in noise, audible in silence)

Every sonic/haptic moment carries a social-leakage class, because a private
cue that a bystander can hear is not private:

- **silent** — haptic only, safe anywhere: `truth_flag`, `answer_ahead`
  (nothing at all), Veritas verdicts. These must NEVER gain an earcon.
- **discreet** — soft earcon acceptable in company: `confirm`, `notice`,
  wake tick, save chime.
- **loud-ok** — the wearer wants to be interrupted and doesn't mind who
  knows: `interrupt` harks, timers ending, the privacy slam.

The rule: anything that *judges another person* (Truth, Veritas,
Discernment) is silent-class, always.
