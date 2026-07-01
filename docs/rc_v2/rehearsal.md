# Rehearsal — Deep Dive (Phase 3 survivor)

> You don't describe the behavior — you perform it once, and the glasses
> learn the choreography.

---

## 1. Full paradigm description

Rehearsal reframes "programming the glasses" as **performing one round of the
behavior in sketch time**. The core loop:

1. **Open the stage.** Long-press + "rehearse" (or the phone's Rehearse
   button). The HUD clears to an empty stage with a faint `REHEARSING`
   eyebrow. Everything the user now does is a *beat* in a trace.
2. **Perform beats.** The user acts the behavior out as if it already
   existed. Three beat channels:
   - **Taps** — the physical button/IMU taps mark where triggers live.
   - **Speech** — durations and labels are *spoken instead of lived*:
     "rolling — three minutes" advances the rehearsal clock 180 s in one
     beat (time-folding). Words like "pulse", "warn me", "count this",
     "again", "until I double-tap", "done" are *marks*.
   - **Dwell** — short real pauses (< 5 s) are kept as literal beats
     (e.g., a 3-second flash is just… three seconds of dwell).
3. **The compiler infers.** The beat trace is generalized into a **Figment**
   — a finite scene-machine (scenes, timed exits, event exits, bounded
   counters, pulse specs). Inference, not transcription: two taps followed by
   a folded duration is recognized as *trigger → timed scene*; "again" closes
   a cycle; "count this" binds a counter to a tap.
4. **Run-through.** The instant the user says "done", the HUD plays the whole
   behavior back **time-folded** (a 3-minute round replays in ~6 s, long
   stretches elided with a `⋯ 2:40 ⋯` fold indicator). What you authored is
   what you watch, in the exact display it will live on.
5. **Correct by re-performing.** If a beat came out wrong, the user says
   "no — the ending again", the stage reopens *at that beat*, and they
   re-perform only it. Nobody edits text. Nobody sees a syntax.
6. **Keep.** "Keep it" signs the Figment with the phone's session key, stores
   it in the local vault, and hot-swaps it onto Halo. It's now in the
   **Repertoire** (phone library) with a human name.

Composition without a composition feature: rehearse *while a figment is
armed* and the new beats layer onto it ("and when the coach sends a cue,
show it big, then go back") — the compiler merges the traces into one
machine. Two behaviors combine the same way one is authored: by performing.

Pattern memory: every run of a figment appends to its performance history.
The Tuesday-class user is offered their round timer *armed* when Tuesday
18:00 + gym place match — the Echo concept, demoted from paradigm to feature,
which is where it wants to be.

## 2. The complete surface

### 2.1 Voice grammar (offline, closed vocabulary)

The rehearsal vocabulary is a **closed, offline grammar** — 30-odd words,
matchable by the on-phone recognizer with no network:

```
duration   := NUMBER ("minute"|"minutes"|"min"|"second"|"seconds"|"sec") 
             | spelled number ("one".."ten") + unit
label      := leading words before a duration ("rolling — three minutes")
mark       := "pulse" | "flash" | "warn me" | "quietly" | "big" | "count this"
             | "show" <short text>
loop       := "again" | "it repeats" | "keeps going"
until      := "until I" ("double-tap"|"tap"|"hold")
control    := "rehearse" | "done" | "keep it" | "no — <beat> again" | "forget it"
```

Anything outside the grammar during rehearsal is kept as *label text*
(subtitles, reminders), never as commands — there is no way to speak your way
into an unsafe machine.

### 2.2 Gesture set

| Gesture            | In rehearsal means            | In playback means      |
|--------------------|-------------------------------|------------------------|
| single tap         | a beat (trigger / count)      | pause run-through      |
| double tap         | a *strong* beat (start/stop)  | replay from start      |
| long press         | open/close the stage          | discard                |
| nod                | accept ("keep it")            | accept                 |
| head-roll (option) | wind a duration without speech| —                      |

### 2.3 HUD screens (ASCII, 256×256 circular)

Stage (recording):
```
        .-----------------.
      /     REHEARSING      \
     |                       |
     |      ●  beat 3        |
     |   "rolling — 3:00"    |
     |                       |
     |   tap · speak · done  |
      \                     /
        '-----------------'
```

Run-through (time-folded playback):
```
        .-----------------.
      /      RUN-THROUGH     \
     |        ROLLING         |
     |         2:47           |
     |      ⋯ folding ⋯       |
     |   ▂▂▂▂▂▂▂▂▂▂▂▂▂●▂▂    |
      \    nod to keep       /
        '-----------------'
```

Teachable failure:
```
        .-----------------.
      /     CAN'T DO THAT    \
     |   your 3rd beat asks   |
     |   the screen to change |
     |   30×/sec — Halo can   |
     |   breathe 2×/sec.      |
     |   try "pulse" instead  |
      \   tap: re-do beat 3  /
        '-----------------'
```

### 2.4 Phone screens

`phone-app/app/rehearsal.tsx` — two panes:
- **Score** — the current/last rehearsal as a horizontal beat timeline
  (taps ●, folded time ⋯3:00⋯, marks ◆), with the inferred reading written
  underneath each beat in plain words. Tap a beat to re-perform it.
- **Repertoire** — the vault: each figment as a card (name, trigger, length,
  signed dot, ACTIVE/revoked), with Arm / Revoke / Export actions.

## 3. Safety model

The safety story is **the user never authors code — the user authors a
performance, and performances compile to data**:

1. **Total by construction.** A Figment has no expressions, no loops, no
   recursion — only scenes with timed/event exits and saturating bounded
   counters. The only cycles possible are scene cycles, and the verifier
   rejects any cycle that doesn't consume time or an external event, so
   zero-time livelock is unrepresentable.
2. **Static budget proof.** `verify()` computes worst-case display writes/sec,
   BLE emits/sec (via minimum-time-around-cycle analysis), scene/counter/text
   bounds, and palette-token whitelisting **before signing**. No proof, no
   signature, no deploy.
3. **Fixed stage runtime.** Halo runs one reviewed Lua interpreter
   (`figment_stage.lua`) with whitelisted effects (display text/clear/show,
   rate-limited BLE emit). User data can't name a function, an `os` call, or
   a filesystem path because the vocabulary doesn't contain them.
4. **Dynamic clamps (defense in depth).** The stage re-enforces the same
   budgets at runtime — ops-per-tick counter, emit token bucket, text
   truncation — so even a forged blob that bypassed the host can't flood or
   lock the display.
5. **Signed, revocable, hot-swappable.** HMAC-SHA256 over canonical JSON with
   a per-install session key; the vault holds a revocation list the deployer
   consults; `figment_swap` replaces the active table between ticks — no
   reboot, no residue.

## 4. Teachability model

Failures are **shown as beats, not reported as errors**. Every rejection maps
to (a) which beat, (b) what the compiler understood, (c) which physical limit
it hit, (d) a suggested re-performance — rendered in rehearsal vocabulary
("beat 3", "pulse", "fold"), never compiler vocabulary. Because the unit of
authorship is a beat, the unit of correction is a beat: the stage reopens at
the offending beat and the user re-performs it. Ambiguity is handled the same
way — the run-through *is* the disambiguation (you watch the compiler's
reading; if it's wrong you re-perform, and the correction is itself a beat).

## 5. Runtime model

```
 PHONE (host-python, offline-complete)          HALO (Lua 5.3)
 ┌───────────────────────────────┐              ┌──────────────────────────┐
 │ rehearsal.py    beat trace    │              │ figment_stage.lua        │
 │ choreographer.py trace→Figment│   BLE JSON   │  fixed interpreter       │
 │ budgets.py     static proof   │  figment_put │  dynamic clamps          │
 │ signer.py      HMAC session   │ figment_swap │  scene machine tick      │
 │ vault.py       local store    │figment_revoke│  emits ← token bucket    │
 │ playback.py    folded preview │ ───────────► │                          │
 │ transport.py   envelopes      │ ◄─────────── │ figment_ack / event      │
 └───────────────────────────────┘              └──────────────────────────┘
```

- Everything left of the BLE line runs on the phone with **no network**; a
  cloud LLM can *optionally* pre-label noisy speech, but the closed grammar
  is the contract.
- The Figment travels as chunked JSON (existing 4-byte-framed envelope
  protocol), verified by hash on device, activated by `figment_swap` between
  ticks.
- Figment `emit` ops surface to the host as `figment_event` envelopes (points
  logging, etc.), rate-limited on both sides.

## 6. Backward-compat story

v1's 15 intents are **lifted, not emulated**: `compat.lift(intent)` maps every
`BehaviorIntent` dataclass to a Figment that preserves its semantics (same
durations, triggers, labels, colors). The v1 pipeline — `IntentParser`,
`CodeGenerator`, templates, tests — is untouched and still passes; v2 also
accepts v1's plain-English strings (`compile_text`) by reusing the v1 parser
and lifting the result, so the old surface keeps working during deprecation.
Five v1 intents (`overtime_timer`, `next_class`, `text_subtitles`,
`gesture_repeater`, `speaker_indicator`) had **no registered template in v1**
and could never actually compile; the lift covers all 15, so v2 is a strict
superset of what v1 shipped *and* what v1 promised.

## 7. End-to-end trace: "3-minute rolls timer, 10-second pulse"

| t (s) | user                              | system                                                       |
|------:|-----------------------------------|--------------------------------------------------------------|
|   0   | long-press, "rehearse"            | stage opens, trace starts                                     |
|   2   | double-tap                        | beat 1: strong tap → trigger hypothesis (double_click)        |
|   4   | "rolling — three minutes"         | beat 2: label ROLLING + fold 180 s → timed scene, countdown   |
|   8   | "last ten seconds, pulse"         | beat 3: pulse mark → pulse spec (final 10 s, coral, 2 Hz)     |
|  11   | "then it starts again"            | beat 4: loop mark → cycle to armed state                      |
|  13   | "done"                            | choreographer infers 3-scene Figment; verifier proves budgets |
|  14   | watches run-through               | folded playback: ARMED → ROLLING 3:00→0:00 (folded) → pulse → loop, ~6 s |
|  20   | nod ("keep it")                   | HMAC-signed, vaulted as "Rolling rounds", `figment_put` + `figment_swap` to Halo |
|  21   | double-taps at the gym            | stage ticks: `ROLLING 2:59…`, coral breathe at 0:10, re-arms  |

Twenty seconds from empty stage to deployed behavior; zero syntax seen.

## 8. The one test that proves the paradigm

**The blind-handoff test.** Give a user who has never seen DreamLayer one
sentence — "show the glasses one round of what you want" — and no other
instruction. They must reach a deployed, correct 3-minute pulse timer in
under 60 seconds, and the verifier must show the deployed Figment's
worst-case budgets under limits. (Automated form:
`test_rc2_e2e.py::test_blind_handoff_rehearsal` scripts exactly the beat
trace above through the public API and asserts deployment, playback frames,
budget proof, and signature in one pass.) If the paradigm needs a manual, it
failed; if the machine can exceed a budget, it failed. Both are asserted.
