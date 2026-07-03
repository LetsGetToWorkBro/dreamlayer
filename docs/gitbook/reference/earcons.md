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
| `wake` | the Oracle woke / greeting | `hey1`, `hey2` | ListeningCard (any wake source) |
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
